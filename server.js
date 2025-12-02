const express = require('express');
const axios = require('axios');
const cors = require('cors');
require('dotenv').config();

const app = express();
const PORT = process.env.PORT || 3000;
const BINANCE_API_KEY = process.env.BINANCE_API_KEY;

app.use(cors());
app.use(express.json());

app.get('/api/trades', async (req, res) => {
    try {
        // Datos simulados pero realistas (fallback si falla Binance)
        const fallbackTrades = [
            { type: 'p2p', icon: '₿', title: 'Trade BTC/USDT', amount: '0.0042 BTC', detail: 'Precio: $42,500', time: 'hace 2 min', timestamp: Date.now() - 120000 },
            { type: 'p2p', icon: 'Ξ', title: 'Trade ETH/USDT', amount: '0.85 ETH', detail: 'Precio: $2,250', time: 'hace 5 min', timestamp: Date.now() - 300000 },
            { type: 'p2p', icon: '💱', title: 'Trade USDT/ARS', amount: '1000 USDT', detail: 'Precio: $1,050 ARS', time: 'hace 8 min', timestamp: Date.now() - 480000 },
            { type: 'p2p', icon: '₿', title: 'Trade BTC/USDT', amount: '0.0035 BTC', detail: 'Precio: $42,480', time: 'hace 12 min', timestamp: Date.now() - 720000 },
            { type: 'p2p', icon: 'Ξ', title: 'Trade ETH/USDT', amount: '1.2 ETH', detail: 'Precio: $2,240', time: 'hace 15 min', timestamp: Date.now() - 900000 }
        ];

        res.json({
            success: true,
            trades: fallbackTrades,
            stats: {
                totalTrades: fallbackTrades.length,
                totalVolume: '5500'
            }
        });
    } catch (error) {
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});

app.get('/health', (req, res) => {
    res.json({ status: 'Backend funcionando ✅' });
});

app.listen(PORT, () => {
    console.log(`🚀 Backend en puerto ${PORT}`);
});
