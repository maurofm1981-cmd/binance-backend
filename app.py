import os
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pandas as pd
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)


# -----------------------------
# Configuración de rutas
# -----------------------------
DATA_DIR = os.environ.get("AUDITORIA_DATA_DIR", os.path.join(os.getcwd(), "data"))
MUESTRAS_FILE = os.path.join(DATA_DIR, "1MUESTRAS", "BaseMuestras.xlsx")
DESVIOS_FILE = os.path.join(DATA_DIR, "2DESVIOS", "BaseDesvios.xlsx")
REPUESTOS_FILE = os.path.join(DATA_DIR, "3REPUESTOS", "BaseRepuestos.xlsx")
BI_DIR = os.path.join(DATA_DIR, "4BIMENSUAL")

CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "300"))


# -----------------------------
# Helpers de normalización
# -----------------------------
MONTH_MAP = {
    "ENE": 1,
    "FEB": 2,
    "MAR": 3,
    "ABR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AGO": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DIC": 12,
}


MUESTRAS_COL_ALIASES = {
    "STRO": ["STRO", "SINIESTRO", "NRO SINIESTRO", "NRO_SINIESTRO", "NUMERO SINIESTRO"],
    "PERITO": ["PERITO", "NOMBRE PERITO", "PERITO NOMBRE"],
    "SUCURSAL": ["SUCURSAL", "AGENCIA", "SEDE"],
    "MES": ["MES", "PERIODO", "FECHA", "MES AUDITORIA"],
}

DESVIOS_COL_ALIASES = {
    "STRO": ["STRO", "SINIESTRO", "NRO SINIESTRO"],
    "PERITO": ["PERITO", "NOMBRE PERITO"],
    "SUCURSAL": ["SUCURSAL", "AGENCIA", "SEDE"],
    "MES": ["MES", "PERIODO", "FECHA", "MES AUDITORIA"],
    "CODIGOS_DE_DESVIOS_A": ["CODIGOS DE DESVIOS A", "CODIGO DESVIO A", "CODIGO A"],
    "CODIGOS_DE_DESVIOS_B": ["CODIGOS DE DESVIOS B", "CODIGO DESVIO B", "CODIGO B"],
    "CODIGOS_DE_DESVIOS_C": ["CODIGOS DE DESVIOS C", "CODIGO DESVIO C", "CODIGO C"],
    "TOTAL_DESVIO": ["TOTAL DESVIO", "MONTO DESVIO", "DESVIO TOTAL"],
    "AUDITOR_CORRIGIO_DESVIO": ["AUDITOR CORRIGIO DESVIO", "AUDITOR CONFIRMA", "ESTADO DESVIO"],
    "MONTO_CONFIRMADO": ["MONTO CONFIRMADO", "TOTAL CONFIRMADO", "MONTO CONFIRMA"],
}

REPUESTOS_COL_ALIASES = {
    "STRO": ["STRO", "SINIESTRO", "NRO SINIESTRO"],
    "PERITO": ["PERITO", "NOMBRE PERITO"],
    "SUCURSAL": ["SUCURSAL", "AGENCIA", "SEDE"],
    "MES": ["MES", "PERIODO", "FECHA", "MES AUDITORIA"],
    "REPUESTO": ["REPUESTO", "DESCRIPCION REPUESTO", "PIEZA"],
    "CANTIDAD": ["CANTIDAD", "CANT", "QTY"],
    "MONTO": ["MONTO", "IMPORTE", "COSTO"],
}


@dataclass
class CacheContainer:
    generated_at: float
    payload: dict


_DATA_CACHE: Optional[CacheContainer] = None


def strip_accents(value: str) -> str:
    if value is None:
        return ""
    return "".join(
        c for c in unicodedata.normalize("NFKD", str(value)) if not unicodedata.combining(c)
    )


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_column_name(col: str) -> str:
    col = strip_accents(col)
    col = normalize_spaces(col)
    col = col.replace("\n", " ").replace("\t", " ")
    return col.upper()


def canonical_name(raw_name: str) -> str:
    txt = normalize_spaces(strip_accents(raw_name).upper())
    if not txt:
        return ""
    tokens = [tok for tok in re.split(r"[^A-Z0-9]+", txt) if tok]
    tokens = sorted(tokens)
    return " ".join(tokens)


def clean_stro(value) -> str:
    if pd.isna(value):
        return ""
    txt = normalize_spaces(str(value))
    if txt.endswith(".0"):
        txt = txt[:-2]
    txt = re.sub(r"\.0$", "", txt)
    return txt


def parse_any_month(value) -> Optional[pd.Timestamp]:
    if pd.isna(value):
        return None

    if isinstance(value, pd.Timestamp):
        return pd.Timestamp(year=value.year, month=value.month, day=1)

    txt = normalize_spaces(str(value)).upper()
    txt = strip_accents(txt)

    # ENE-24 / ENE 2024
    m = re.match(r"^([A-Z]{3})[-\s_/]*(\d{2,4})$", txt)
    if m and m.group(1) in MONTH_MAP:
        month = MONTH_MAP[m.group(1)]
        year = int(m.group(2))
        if year < 100:
            year += 2000
        return pd.Timestamp(year=year, month=month, day=1)

    # 2024-01 o 202401
    m2 = re.match(r"^(\d{4})[-_/]?(\d{1,2})$", txt)
    if m2:
        year = int(m2.group(1))
        month = int(m2.group(2))
        if 1 <= month <= 12:
            return pd.Timestamp(year=year, month=month, day=1)

    # Parse genérico
    try:
        dt = pd.to_datetime(value, errors="coerce")
        if pd.isna(dt):
            return None
        return pd.Timestamp(year=dt.year, month=dt.month, day=1)
    except Exception:
        return None


def month_key(ts: Optional[pd.Timestamp]) -> str:
    if ts is None or pd.isna(ts):
        return ""
    return ts.strftime("%Y-%m")


def quarter_key(ts: Optional[pd.Timestamp]) -> str:
    if ts is None or pd.isna(ts):
        return ""
    q = ((ts.month - 1) // 3) + 1
    return f"{ts.year}-Q{q}"


def coalesce_columns(df: pd.DataFrame, aliases: Dict[str, List[str]]) -> pd.DataFrame:
    df = df.copy()
    df.columns = [normalize_column_name(c) for c in df.columns]

    for canonical, options in aliases.items():
        normalized_options = [normalize_column_name(o) for o in options]
        if canonical in df.columns:
            continue
        found = next((opt for opt in normalized_options if opt in df.columns), None)
        if found:
            df.rename(columns={found: canonical}, inplace=True)
        else:
            df[canonical] = pd.NA
    return df


def safe_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0)


def safe_read_excel(path: str, **kwargs) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        return pd.read_excel(path, **kwargs)
    except Exception:
        return pd.DataFrame()


def preprocess_common(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["STRO"] = df["STRO"].apply(clean_stro)
    df["PERITO"] = df["PERITO"].fillna("").astype(str).apply(normalize_spaces)
    df["SUCURSAL"] = df["SUCURSAL"].fillna("").astype(str).apply(normalize_spaces)
    df["PERITO_NORM"] = df["PERITO"].apply(canonical_name)
    df["SUCURSAL_NORM"] = df["SUCURSAL"].apply(lambda x: normalize_spaces(strip_accents(x).upper()))
    df["MES_TS"] = df["MES"].apply(parse_any_month)
    df["MES_KEY"] = df["MES_TS"].apply(month_key)
    df["TRIMESTRE"] = df["MES_TS"].apply(quarter_key)
    return df


def load_bi_files() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not os.path.isdir(BI_DIR):
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    peritos_frames = []
    sucursales_frames = []
    mano_obra_frames = []

    for fname in sorted(os.listdir(BI_DIR)):
        if not re.match(r"^BI\d{6}\.xlsx$", fname.upper()):
            continue

        full_path = os.path.join(BI_DIR, fname)
        m = re.match(r"^BI(\d{4})(\d{2})\.xlsx$", fname.upper())
        if not m:
            continue

        y, mo = int(m.group(1)), int(m.group(2))
        mes_ts = pd.Timestamp(year=y, month=mo, day=1)
        mes_key = month_key(mes_ts)

        xls = pd.ExcelFile(full_path)
        sheet_map = {normalize_column_name(s): s for s in xls.sheet_names}

        if "PERITOS" in sheet_map:
            p = pd.read_excel(full_path, sheet_name=sheet_map["PERITOS"])
            p.columns = [normalize_column_name(c) for c in p.columns]
            p["MES_KEY"] = mes_key
            peritos_frames.append(p)

        if "SUCURSALES" in sheet_map:
            s = pd.read_excel(full_path, sheet_name=sheet_map["SUCURSALES"])
            s.columns = [normalize_column_name(c) for c in s.columns]
            s["MES_KEY"] = mes_key
            sucursales_frames.append(s)

        if "MANO_OBRA" in sheet_map:
            mo_df = pd.read_excel(full_path, sheet_name=sheet_map["MANO_OBRA"])
            mo_df.columns = [normalize_column_name(c) for c in mo_df.columns]
            mo_df["MES_KEY"] = mes_key
            mano_obra_frames.append(mo_df)

    peritos_df = pd.concat(peritos_frames, ignore_index=True) if peritos_frames else pd.DataFrame()
    suc_df = pd.concat(sucursales_frames, ignore_index=True) if sucursales_frames else pd.DataFrame()
    mo_df = pd.concat(mano_obra_frames, ignore_index=True) if mano_obra_frames else pd.DataFrame()

    return peritos_df, suc_df, mo_df


def normalize_bi(peritos_df: pd.DataFrame, suc_df: pd.DataFrame, mo_df: pd.DataFrame):
    if peritos_df.empty:
        peritos_df = pd.DataFrame(columns=[
            "MES_KEY",
            "DNI",
            "PERITO_BI",
            "PERITO_NORM",
            "CANT_PERITACIONES",
            "DIAS_PROMEDIO",
            "PIEZAS_PROMEDIO",
            "COSTO_TOTAL_XPERICIA",
        ])
    else:
        cols = {c: c for c in peritos_df.columns}
        peritos_df = peritos_df.rename(columns={
            next((c for c in cols if "DNI" in c and "PERITO" in c), "DNI - PERITO"): "DNI_PERITO",
            next((c for c in cols if "CANT" in c and "PERIT" in c), "CANT. PERITACIONES"): "CANT_PERITACIONES",
            next((c for c in cols if "CIERRE" in c and "PROM" in c), "CIERRE_IP_PROM_DIAS"): "DIAS_PROMEDIO",
            next((c for c in cols if "PIEZAS" in c), "PIEZAS XPERICIA"): "PIEZAS_PROMEDIO",
            next((c for c in cols if "COSTO" in c and "TOTAL" in c), "COSTO TOTAL XPERICIA"): "COSTO_TOTAL_XPERICIA",
        })

        split_cols = peritos_df["DNI_PERITO"].fillna("").astype(str).str.split("-", n=1, expand=True)
        peritos_df["DNI"] = split_cols[0].str.replace(r"\D", "", regex=True)
        peritos_df["PERITO_BI"] = split_cols[1].fillna("").apply(normalize_spaces)
        peritos_df["PERITO_NORM"] = peritos_df["PERITO_BI"].apply(canonical_name)
        peritos_df["CANT_PERITACIONES"] = safe_numeric(peritos_df.get("CANT_PERITACIONES", 0))
        peritos_df["DIAS_PROMEDIO"] = safe_numeric(peritos_df.get("DIAS_PROMEDIO", 0))
        peritos_df["PIEZAS_PROMEDIO"] = safe_numeric(peritos_df.get("PIEZAS_PROMEDIO", 0))
        peritos_df["COSTO_TOTAL_XPERICIA"] = safe_numeric(peritos_df.get("COSTO_TOTAL_XPERICIA", 0))

    if suc_df.empty:
        suc_df = pd.DataFrame(columns=["MES_KEY", "SUCURSAL_NORM", "COSTO_MO_SUCURSAL"])
    else:
        suc_df = suc_df.rename(columns={
            next((c for c in suc_df.columns if "SUCURSAL" in c), "SUCURSAL"): "SUCURSAL",
            next((c for c in suc_df.columns if "COSTO" in c and "MO" in c), "COSTO MO XSINIESTRO"): "COSTO_MO_SUCURSAL",
        })
        suc_df["SUCURSAL"] = suc_df["SUCURSAL"].fillna("").astype(str).apply(normalize_spaces)
        suc_df["SUCURSAL_NORM"] = suc_df["SUCURSAL"].apply(lambda x: normalize_spaces(strip_accents(x).upper()))
        suc_df["COSTO_MO_SUCURSAL"] = safe_numeric(suc_df.get("COSTO_MO_SUCURSAL", 0))

    if mo_df.empty:
        mo_df = pd.DataFrame(columns=["MES_KEY", "PERITO_NORM", "COSTO_MO_PERITO"])
    else:
        mo_df = mo_df.rename(columns={
            next((c for c in mo_df.columns if c == "PERITO" or "PERITO" in c), "PERITO"): "PERITO",
            next((c for c in mo_df.columns if "COSTO" in c and "MO" in c), "COSTO MO XSINIESTRO"): "COSTO_MO_PERITO",
        })
        mo_df["PERITO"] = mo_df["PERITO"].fillna("").astype(str).apply(normalize_spaces)
        mo_df["PERITO_NORM"] = mo_df["PERITO"].apply(canonical_name)
        mo_df["COSTO_MO_PERITO"] = safe_numeric(mo_df.get("COSTO_MO_PERITO", 0))

    return peritos_df, suc_df, mo_df


def compute_risk(row: pd.Series) -> Tuple[int, str]:
    score = 0
    td = row.get("TASA_DESVIO", 0)
    if td > 50:
        score += 40
    elif td > 20:
        score += 20

    if row.get("VARIACION_VS_SUCURSAL", 0) > 0:
        score += 30

    if row.get("DIAS_PROMEDIO", 0) > 10:
        score += 20

    if row.get("PIEZAS_PROMEDIO", 0) > 7:
        score += 10

    if score > 70:
        nivel = "CRITICO"
    elif score > 50:
        nivel = "ALTO"
    elif score > 30:
        nivel = "MEDIO"
    else:
        nivel = "BAJO"
    return score, nivel


def build_dataset() -> dict:
    # 1) Leer fuentes principales
    muestras = safe_read_excel(MUESTRAS_FILE)
    desvios = safe_read_excel(DESVIOS_FILE)
    repuestos = safe_read_excel(REPUESTOS_FILE)

    # 2) Homogeneizar columnas + defaults
    muestras = coalesce_columns(muestras, MUESTRAS_COL_ALIASES)
    desvios = coalesce_columns(desvios, DESVIOS_COL_ALIASES)
    repuestos = coalesce_columns(repuestos, REPUESTOS_COL_ALIASES)

    # 3) Normalización común
    muestras = preprocess_common(muestras)
    desvios = preprocess_common(desvios)
    repuestos = preprocess_common(repuestos)

    # 4) Reglas de negocio de desvíos
    desvios["CODIGOS_DE_DESVIOS_A"] = desvios["CODIGOS_DE_DESVIOS_A"].fillna("").astype(str).apply(normalize_spaces)
    desvios["TOTAL_DESVIO"] = safe_numeric(desvios.get("TOTAL_DESVIO", 0))
    desvios["MONTO_CONFIRMADO"] = safe_numeric(desvios.get("MONTO_CONFIRMADO", 0))

    audit_conf = desvios["AUDITOR_CORRIGIO_DESVIO"].fillna("").astype(str).str.upper()
    audit_conf = audit_conf.apply(strip_accents)

    desvios["TIENE_DESVIO"] = desvios["CODIGOS_DE_DESVIOS_A"].astype(str).str.strip() != ""
    desvios["DESVIO_CONFIRMADO"] = audit_conf.str.contains("CONFIRMA|\bSI\b", regex=True)

    # Asegurar que solo cuente desvíos según regla (si vino basura)
    desvios_validos = desvios[desvios["TIENE_DESVIO"]].copy()

    # 5) BI
    bi_peritos, bi_sucursales, bi_mo = load_bi_files()
    bi_peritos, bi_sucursales, bi_mo = normalize_bi(bi_peritos, bi_sucursales, bi_mo)

    # 6) Agregados por perito/sucursal/mes
    grp_keys = ["PERITO_NORM", "SUCURSAL_NORM", "MES_KEY"]

    muestras_agg = (
        muestras.groupby(grp_keys, dropna=False)
        .agg(
            PERITO=("PERITO", "first"),
            SUCURSAL=("SUCURSAL", "first"),
            CASOS_AUDITADOS=("STRO", "nunique"),
        )
        .reset_index()
    )

    desvios_agg = (
        desvios_validos.groupby(grp_keys, dropna=False)
        .agg(
            DESVIOS_DETECTADOS=("STRO", "nunique"),
            DESVIOS_CONFIRMADOS=("DESVIO_CONFIRMADO", "sum"),
            MONTO_TOTAL_DESVIADO=("TOTAL_DESVIO", "sum"),
            MONTO_TOTAL_CONFIRMADO=("MONTO_CONFIRMADO", "sum"),
        )
        .reset_index()
    )

    monthly = pd.merge(muestras_agg, desvios_agg, on=grp_keys, how="left")

    for col in [
        "DESVIOS_DETECTADOS",
        "DESVIOS_CONFIRMADOS",
        "MONTO_TOTAL_DESVIADO",
        "MONTO_TOTAL_CONFIRMADO",
    ]:
        monthly[col] = safe_numeric(monthly.get(col, 0))

    # Join BI por perito + mes
    bi_peritos_small = bi_peritos[[
        "MES_KEY",
        "PERITO_NORM",
        "CANT_PERITACIONES",
        "DIAS_PROMEDIO",
        "PIEZAS_PROMEDIO",
        "COSTO_TOTAL_XPERICIA",
    ]].copy()

    monthly = monthly.merge(bi_peritos_small, on=["MES_KEY", "PERITO_NORM"], how="left")

    bi_mo_small = bi_mo[["MES_KEY", "PERITO_NORM", "COSTO_MO_PERITO"]].copy()
    monthly = monthly.merge(bi_mo_small, on=["MES_KEY", "PERITO_NORM"], how="left")

    bi_suc_small = bi_sucursales[["MES_KEY", "SUCURSAL_NORM", "COSTO_MO_SUCURSAL"]].copy()
    monthly = monthly.merge(bi_suc_small, on=["MES_KEY", "SUCURSAL_NORM"], how="left")

    for col in [
        "CANT_PERITACIONES",
        "DIAS_PROMEDIO",
        "PIEZAS_PROMEDIO",
        "COSTO_TOTAL_XPERICIA",
        "COSTO_MO_PERITO",
        "COSTO_MO_SUCURSAL",
    ]:
        monthly[col] = safe_numeric(monthly.get(col, 0))

    monthly["TASA_CONFIRMACION"] = monthly.apply(
        lambda r: (r["DESVIOS_CONFIRMADOS"] / r["DESVIOS_DETECTADOS"] * 100)
        if r["DESVIOS_DETECTADOS"]
        else 0,
        axis=1,
    )
    monthly["TASA_DESVIO"] = monthly.apply(
        lambda r: (r["DESVIOS_DETECTADOS"] / r["CASOS_AUDITADOS"] * 100)
        if r["CASOS_AUDITADOS"]
        else 0,
        axis=1,
    )

    monthly["VARIACION_VS_SUCURSAL"] = monthly.apply(
        lambda r: ((r["COSTO_MO_PERITO"] - r["COSTO_MO_SUCURSAL"]) / r["COSTO_MO_SUCURSAL"] * 100)
        if r["COSTO_MO_SUCURSAL"]
        else 0,
        axis=1,
    )

    risk = monthly.apply(compute_risk, axis=1)
    monthly["SCORE_RIESGO"] = [r[0] for r in risk]
    monthly["NIVEL_RIESGO"] = [r[1] for r in risk]

    monthly["MES_TS"] = pd.to_datetime(monthly["MES_KEY"] + "-01", errors="coerce")
    monthly["TRIMESTRE"] = monthly["MES_TS"].apply(quarter_key)

    # Trimestral
    trimestral = (
        monthly.groupby(["PERITO_NORM", "SUCURSAL_NORM", "PERITO", "SUCURSAL", "TRIMESTRE"], dropna=False)
        .agg(
            CANT_PERITACIONES=("CANT_PERITACIONES", "sum"),
            CASOS_AUDITADOS=("CASOS_AUDITADOS", "sum"),
            DESVIOS_DETECTADOS=("DESVIOS_DETECTADOS", "sum"),
            DESVIOS_CONFIRMADOS=("DESVIOS_CONFIRMADOS", "sum"),
            DIAS_PROMEDIO=("DIAS_PROMEDIO", "mean"),
            PIEZAS_PROMEDIO=("PIEZAS_PROMEDIO", "mean"),
            COSTO_MO_PERITO=("COSTO_MO_PERITO", "mean"),
            COSTO_MO_SUCURSAL=("COSTO_MO_SUCURSAL", "mean"),
            MONTO_TOTAL_DESVIADO=("MONTO_TOTAL_DESVIADO", "sum"),
            MONTO_TOTAL_CONFIRMADO=("MONTO_TOTAL_CONFIRMADO", "sum"),
            SCORE_RIESGO=("SCORE_RIESGO", "mean"),
        )
        .reset_index()
    )

    trimestral["TASA_CONFIRMACION"] = trimestral.apply(
        lambda r: (r["DESVIOS_CONFIRMADOS"] / r["DESVIOS_DETECTADOS"] * 100)
        if r["DESVIOS_DETECTADOS"]
        else 0,
        axis=1,
    )
    trimestral["TASA_DESVIO"] = trimestral.apply(
        lambda r: (r["DESVIOS_DETECTADOS"] / r["CASOS_AUDITADOS"] * 100)
        if r["CASOS_AUDITADOS"]
        else 0,
        axis=1,
    )
    trimestral["VARIACION_VS_SUCURSAL"] = trimestral.apply(
        lambda r: ((r["COSTO_MO_PERITO"] - r["COSTO_MO_SUCURSAL"]) / r["COSTO_MO_SUCURSAL"] * 100)
        if r["COSTO_MO_SUCURSAL"]
        else 0,
        axis=1,
    )

    tri_risk = trimestral.apply(compute_risk, axis=1)
    trimestral["SCORE_RIESGO"] = [r[0] for r in tri_risk]
    trimestral["NIVEL_RIESGO"] = [r[1] for r in tri_risk]

    # Repuestos detalle por STRO
    repuestos["CANTIDAD"] = safe_numeric(repuestos.get("CANTIDAD", 0))
    repuestos["MONTO"] = safe_numeric(repuestos.get("MONTO", 0))

    repuestos_detail = repuestos[[
        "STRO",
        "MES_KEY",
        "PERITO",
        "SUCURSAL",
        "REPUESTO",
        "CANTIDAD",
        "MONTO",
    ]].copy()

    # KPIs globales
    total_casos = int(muestras["STRO"].nunique()) if not muestras.empty else 0
    total_desvios = int(desvios_validos["STRO"].nunique()) if not desvios_validos.empty else 0
    total_confirmados = int(desvios_validos[desvios_validos["DESVIO_CONFIRMADO"]]["STRO"].nunique()) if not desvios_validos.empty else 0
    tasa_desvio = (total_desvios / total_casos * 100) if total_casos else 0
    monto_total_desviado = float(desvios_validos["TOTAL_DESVIO"].sum()) if not desvios_validos.empty else 0.0
    monto_total_confirmado = float(desvios_validos["MONTO_CONFIRMADO"].sum()) if not desvios_validos.empty else 0.0

    payload = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "kpis": {
            "total_casos_auditados": total_casos,
            "total_desvios_detectados": total_desvios,
            "total_desvios_confirmados": total_confirmados,
            "tasa_desvio": round(tasa_desvio, 2),
            "monto_total_desviado": round(monto_total_desviado, 2),
            "monto_total_confirmado": round(monto_total_confirmado, 2),
        },
        "filters": {
            "meses": sorted([m for m in monthly["MES_KEY"].dropna().unique().tolist() if m]),
            "sucursales": sorted([s for s in monthly["SUCURSAL"].dropna().unique().tolist() if s]),
            "peritos": sorted([p for p in monthly["PERITO"].dropna().unique().tolist() if p]),
        },
        "monthly": monthly.to_dict(orient="records"),
        "quarterly": trimestral.to_dict(orient="records"),
        "repuestos": repuestos_detail.to_dict(orient="records"),
    }

    return payload


def get_data(force_refresh: bool = False) -> dict:
    global _DATA_CACHE
    now = time.time()

    if not force_refresh and _DATA_CACHE and now - _DATA_CACHE.generated_at < CACHE_TTL_SECONDS:
        return _DATA_CACHE.payload

    payload = build_dataset()
    _DATA_CACHE = CacheContainer(generated_at=now, payload=payload)
    return payload


def apply_filters(payload: dict, params: dict) -> dict:
    desde = params.get("desde", "")
    hasta = params.get("hasta", "")
    sucursal = params.get("sucursal", "")
    perito = params.get("perito", "")
    estado = params.get("estado", "")  # detectado|confirmado

    monthly = pd.DataFrame(payload["monthly"])
    quarterly = pd.DataFrame(payload["quarterly"])
    repuestos = pd.DataFrame(payload["repuestos"])

    if not monthly.empty:
        if desde:
            monthly = monthly[monthly["MES_KEY"] >= desde]
        if hasta:
            monthly = monthly[monthly["MES_KEY"] <= hasta]
        if sucursal:
            monthly = monthly[monthly["SUCURSAL"] == sucursal]
        if perito:
            monthly = monthly[monthly["PERITO"] == perito]

        if estado == "confirmado":
            monthly = monthly[monthly["DESVIOS_CONFIRMADOS"] > 0]
        elif estado == "detectado":
            monthly = monthly[monthly["DESVIOS_DETECTADOS"] > 0]

    if not quarterly.empty:
        if sucursal:
            quarterly = quarterly[quarterly["SUCURSAL"] == sucursal]
        if perito:
            quarterly = quarterly[quarterly["PERITO"] == perito]

    if not repuestos.empty:
        if desde:
            repuestos = repuestos[repuestos["MES_KEY"] >= desde]
        if hasta:
            repuestos = repuestos[repuestos["MES_KEY"] <= hasta]
        if sucursal:
            repuestos = repuestos[repuestos["SUCURSAL"] == sucursal]
        if perito:
            repuestos = repuestos[repuestos["PERITO"] == perito]

    kpis = {
        "total_casos_auditados": int(monthly["CASOS_AUDITADOS"].sum()) if not monthly.empty else 0,
        "total_desvios_detectados": int(monthly["DESVIOS_DETECTADOS"].sum()) if not monthly.empty else 0,
        "total_desvios_confirmados": int(monthly["DESVIOS_CONFIRMADOS"].sum()) if not monthly.empty else 0,
        "tasa_desvio": 0,
        "monto_total_desviado": float(monthly["MONTO_TOTAL_DESVIADO"].sum()) if not monthly.empty else 0.0,
        "monto_total_confirmado": float(monthly["MONTO_TOTAL_CONFIRMADO"].sum()) if not monthly.empty else 0.0,
    }
    if kpis["total_casos_auditados"]:
        kpis["tasa_desvio"] = round(kpis["total_desvios_detectados"] / kpis["total_casos_auditados"] * 100, 2)

    return {
        "generated_at": payload["generated_at"],
        "kpis": kpis,
        "monthly": monthly.to_dict(orient="records"),
        "quarterly": quarterly.to_dict(orient="records"),
        "repuestos": repuestos.to_dict(orient="records"),
        "filters": payload["filters"],
    }


@app.route("/")
def index():
    payload = get_data(force_refresh=False)
    return render_template("index.html", initial_data=payload)


@app.route("/api/data")
def api_data():
    refresh = request.args.get("refresh", "false").lower() == "true"
    payload = get_data(force_refresh=refresh)
    filtered = apply_filters(payload, request.args)
    return jsonify(filtered)


@app.route("/api/stats")
def api_stats():
    payload = get_data(force_refresh=False)
    filtered = apply_filters(payload, request.args)
    return jsonify({"generated_at": filtered["generated_at"], "kpis": filtered["kpis"]})


@app.route("/api/repuestos")
def api_repuestos():
    payload = get_data(force_refresh=False)
    filtered = apply_filters(payload, request.args)
    return jsonify({"generated_at": filtered["generated_at"], "repuestos": filtered["repuestos"]})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
