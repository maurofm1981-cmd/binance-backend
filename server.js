const express = require('express');
const axios = require('axios');
const cors = require('cors');
require('dotenv').config();

const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json());

// Cache de trades
let tradesCache = [];
let lastUpdate = 0;
const CACHE_DURATION = 10000; // 10 segundos

app.get('/api/trades', async (req, res) => {
    try {
        // Si el cache es reciente, usar cached
        if (tradesCache.length > 0 && Date.now() - lastUpdate < CACHE_DURATION) {
            return res.json({
                success: true,
                trades: tradesCache,
                stats: {
                    totalTrades: tradesCache.length,
                    totalVolume: tradesCache.reduce((sum, t) => sum + parseFloat(t.volume || 0), 0).toFixed(2)
                },
                source: 'cached'
            });
        }

        // Obtener datos REALES de Binance
        const response = await axios.get('https://api.binance.com/api/v3/trades', {
            params: {
                symbol: 'BTCUSDT',
                limit: 10
            },
            timeout: 5000
        });

        tradesCache = response.data.map((trade, index) => ({
            type: 'p2p',
            icon: '₿',
            title: `Trade BTC/USDT #${trade.id}`,
            amount: `${parseFloat(trade.qty).toFixed(4)} BTC`,
            detail: `Precio: $${parseFloat(trade.price).toFixed(2)}`,
            time: new Date(trade.time).toLocaleString('es-AR'),
            timestamp: trade.time,
            volume: trade.qty * trade.price
        }));

        lastUpdate = Date.now();

        res.json({
            success: true,
            trades: tradesCache,
            stats: {
                totalTrades: tradesCache.length,
                totalVolume: tradesCache.reduce((sum, t) => sum + parseFloat(t.volume), 0).toFixed(2)
            },
            source: 'binance_live'
        });

    } catch (error) {
        console.error('Error:', error.message);
        
        // Fallback si Binance falla
        res.json({
            success: true,
            trades: tradesCache.length > 0 ? tradesCache : [
                { type: 'p2p', icon: '₿', title: 'Trade BTC/USDT', amount: '0.0042 BTC', detail: 'Precio: $42,500', time: 'hace 2 min', volume: 178500 }
            ],
            stats: {
                totalTrades: tradesCache.length || 1,
                totalVolume: tradesCache.reduce((sum, t) => sum + parseFloat(t.volume || 0), 0).toFixed(2) || '178500'
            },
            source: 'fallback'
        });
    }
});

app.get('/health', (req, res) => {
    res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

app.listen(PORT, () => {
    console.log(`🚀 Backend corriendo en puerto ${PORT}`);
});
