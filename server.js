const express = require('express');
const axios = require('axios');
const cors = require('cors');
require('dotenv').config();

const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json());

let tradesCache = [];
let lastUpdate = 0;
const CACHE_DURATION = 12000;
let isUpdating = false;

app.get('/api/trades', async (req, res) => {
    const now = Date.now();

    if (tradesCache.length > 8 && now - lastUpdate < CACHE_DURATION) {
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

    if (isUpdating) {
        return res.json({
            success: true,
            trades: tradesCache.length > 0 ? tradesCache : [],
            stats: {
                totalTrades: tradesCache.length,
                totalVolume: tradesCache.reduce((sum, t) => sum + parseFloat(t.volume || 0), 0).toFixed(2)
            },
            source: 'updating'
        });
    }

    isUpdating = true;

    try {
        const response = await axios.get('https://api.binance.com/api/v3/trades', {
            params: {
                symbol: 'BTCUSDT',
                limit: 20
            },
            timeout: 5000
        });

        const newTrades = response.data.map((trade) => ({
            type: 'p2p',
            icon: '₿',
            title: 'BTC/USDT',
            amount: parseFloat(trade.qty).toFixed(4) + ' BTC',
            detail: '$' + parseFloat(trade.price).toFixed(2),
            time: new Date(trade.time).toLocaleTimeString('es-AR'),
            timestamp: trade.time,
            volume: trade.qty * trade.price
        })).reverse();

        tradesCache = newTrades;
        lastUpdate = Date.now();
        isUpdating = false;

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
        isUpdating = false;

        if (tradesCache.length > 0) {
            return res.json({
                success: true,
                trades: tradesCache,
                stats: {
                    totalTrades: tradesCache.length,
                    totalVolume: tradesCache.reduce((sum, t) => sum + parseFloat(t.volume), 0).toFixed(2)
                },
                source: 'cached_error'
            });
        }

        res.json({
            success: true,
            trades: [{
                type: 'p2p',
                icon: '₿',
                title: 'BTC/USDT',
                amount: '0.0042 BTC',
                detail: '$42,500',
                time: new Date().toLocaleTimeString('es-AR'),
                volume: 178500
            }],
            stats: {
                totalTrades: 1,
                totalVolume: '178500'
            },
            source: 'fallback'
        });
    }
});

app.get('/health', (req, res) => {
    res.json({
        status: 'ok',
        timestamp: new Date().toISOString(),
        cacheSize: tradesCache.length,
        isUpdating: isUpdating
    });
});

app.listen(PORT, () => {
    console.log('Backend en puerto ' + PORT);
});
