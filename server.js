const express = require('express');
const axios = require('axios');
const cors = require('cors');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json());

let tradesCache = [];
let lastUpdate = 0;
const CACHE_DURATION = 20000;

app.get('/api/trades', async (req, res) => {
    const now = Date.now();

    if (tradesCache.length > 5 && now - lastUpdate < CACHE_DURATION) {
        return res.json({
            success: true,
            trades: tradesCache,
            stats: { totalTrades: tradesCache.length, totalVolume: tradesCache.reduce((s,t)=>s+t.volume,0).toFixed(0) }
        });
    }

    try {
        const response = await axios.get('https://api2.binance.com/api/v3/trades', {
            params: { symbol: 'BTCUSDT', limit: 20 },
            timeout: 10000,
            headers: { 'Accept': 'application/json' }
        });

        tradesCache = response.data.map(t => ({
            type: 'p2p',
            icon: '₿',
            title: 'BTC/USDT Trade',
            amount: parseFloat(t.qty).toFixed(4) + ' BTC',
            detail: '$' + parseFloat(t.price).toFixed(0),
            time: new Date(t.time).toLocaleTimeString('es-AR'),
            volume: t.qty * t.price
        }));
        
        lastUpdate = now;

        res.json({
            success: true,
            trades: tradesCache,
            stats: { totalTrades: tradesCache.length, totalVolume: tradesCache.reduce((s,t)=>s+t.volume,0).toFixed(0) }
        });

    } catch (error) {
        console.log('Binance error:', error.message);
        res.json({
            success: true,
            trades: tradesCache.length > 0 ? tradesCache : [
                { type:'p2p', icon:'₿', title:'BTC/USDT', amount:'0.25 BTC', detail:'$21,500', time:new Date().toLocaleTimeString(), volume:5375 }
            ],
            stats: { totalTrades: tradesCache.length || 1, totalVolume: tradesCache.reduce((s,t)=>s+t.volume,0) || '5375' }
        });
    }
});

app.get('/health', (req,res) => res.json({ok:true}));

app.listen(PORT, () => console.log(`Server on ${PORT}`));
