const express = require('express');
const axios = require('axios');
const cors = require('cors');

const app = express();
app.use(cors());
app.use(express.json());

let tradesCache = [];
let lastUpdate = 0;
const CACHE_DURATION = 25000;

app.get('/api/trades', async (req, res) => {
    const now = Date.now();

    if (tradesCache.length > 3 && now - lastUpdate < CACHE_DURATION) {
        return res.json({
            success: true,
            trades: tradesCache,
            stats: { 
                totalTrades: tradesCache.length, 
                totalVolume: tradesCache.reduce((s,t)=>s+parseFloat(t.volume),0).toFixed(0) 
            }
        });
    }

    try {
        const response = await axios.get('https://api.coingecko.com/api/v3/coins/bitcoin/market_chart', {
            params: { 
                vs_currency: 'usd', 
                days: 1, 
                interval: 'minutely' 
            },
            timeout: 8000
        });

        const prices = response.data.prices.slice(-15);

        tradesCache = prices.map((p, i) => {
            const time = new Date(p[0]);
            const qty = (Math.random() * 0.5 + 0.05).toFixed(4);
            const price = p[1].toFixed(0);
            const volume = (qty * price).toFixed(0);
            
            return {
                type: 'p2p',
                icon: '₿',
                title: 'BTC/USDT',
                amount: qty + ' BTC',
                detail: '$' + price,
                time: time.toLocaleTimeString('es-AR'),
                volume: volume
            };
        }).reverse();

        lastUpdate = now;

        res.json({
            success: true,
            trades: tradesCache,
            stats: { 
                totalTrades: tradesCache.length, 
                totalVolume: tradesCache.reduce((s,t)=>s+parseFloat(t.volume),0).toFixed(0) 
            }
        });

    } catch (error) {
        console.log('Error CoinGecko:', error.message);
        
        res.json({
            success: true,
            trades: tradesCache.length > 0 ? tradesCache : [
                { type:'p2p', icon:'₿', title:'BTC/USDT', amount:'0.15 BTC', detail:'$93,500', time:new Date().toLocaleTimeString('es-AR'), volume:'14025' }
            ],
            stats: { 
                totalTrades: tradesCache.length || 1, 
                totalVolume: tradesCache.reduce((s,t)=>s+parseFloat(t.volume),0) || '14025' 
            }
        });
    }
});

app.get('/health', (req, res) => res.json({ status: 'ok' }));

app.listen(process.env.PORT || 3000, () => {
    console.log('✅ Servidor corriendo - Usando CoinGecko API');
});
