const express = require('express');
const axios = require('axios');
const cors = require('cors');

const app = express();
app.use(cors());

let priceHistory = [];
let initialPrice = 93500; // Fallback
let lastRefreshTime = Date.now();

// AL INICIAR - Fetch UNA sola vez
async function initializePrice() {
    try {
        console.log('🔄 Obteniendo precio inicial de Binance...');
        const response = await axios.get(
            'https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT',
            { timeout: 5000 }
        );
        initialPrice = parseFloat(response.data.price);
        console.log(`✅ Precio inicial: $${initialPrice}`);
    } catch (error) {
        console.log(`⚠️ No se pudo obtener precio, usando fallback: $${initialPrice}`);
    }

    // Inicializar histórico
    priceHistory = [initialPrice];
}

// Llamar al iniciar
initializePrice();

// Generar nuevo precio cada minuto
function generateRealisticPrice() {
    const now = Date.now();
    const secondsSinceRefresh = (now - lastRefreshTime) / 1000;

    if (secondsSinceRefresh > 60) {
        const lastPrice = priceHistory[priceHistory.length - 1];
        const newPrice = lastPrice + Math.floor(Math.random() * 500 - 250);
        priceHistory.push(newPrice);

        if (priceHistory.length > 30) {
            priceHistory.shift();
        }

        lastRefreshTime = now;
        console.log(`💰 Nuevo precio generado: $${newPrice}`);
    }

    return priceHistory[priceHistory.length - 1];
}

function generateTrades() {
    const trades = [];

    for (let i = 0; i < 12; i++) {
        const priceIndex = Math.max(0, priceHistory.length - 1 - i);
        const price = priceHistory[priceIndex];
        const qty = (0.08 + Math.random() * 0.35).toFixed(4);
        const time = new Date(Date.now() - i * 5 * 60000);

        trades.push({
            type: 'p2p',
            icon: '₿',
            title: 'BTC/USDT Trade',
            amount: qty + ' BTC',
            detail: '$' + price.toLocaleString(),
            time: time.toLocaleTimeString('es-AR'),
            volume: (qty * price).toFixed(0)
        });
    }

    return trades;
}

app.get('/api/trades', (req, res) => {
    try {
        const currentPrice = generateRealisticPrice();
        const trades = generateTrades();
        const totalVolume = trades.reduce((sum, t) => sum + parseFloat(t.volume), 0);

        res.json({
            success: true,
            trades: trades,
            stats: {
                totalTrades: trades.length,
                totalVolume: totalVolume.toFixed(0),
                currentPrice: currentPrice
            }
        });
    } catch (error) {
        console.error('Error:', error);
        res.status(500).json({ success: false, error: error.message });
    }
});

app.listen(process.env.PORT || 3000, () => {
    console.log('✅ Backend iniciado - Precios actualizados cada minuto');
});
