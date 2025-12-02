const express = require('express');
const axios = require('axios');
const cors = require('cors');
require('dotenv').config();

const app = express();
const PORT = process.env.PORT || 3000;
const BINANCE_API_KEY = process.env.BINANCE_API_KEY;

app.use(cors());
app.use(express.json());

const TRADING_PAIRS = [
    { symbol: 'BTCUSDT', display: 'BTC/USDT', icon: '₿' },
    { symbol: 'ETHUSDT', display: 'ETH/USDT', icon: 'Ξ' },
    { symbol: 'USDTARS', display: 'USDT/ARS', icon: '💱' }
];

app.get('/api/trades', async (req, res) => {
    try {
        let allTrades = [];

        for (const pair of TRADING_PAIRS) {
            try {
                const response = await axios.get(
                    `https://api.binance.com/api/v3/trades?symbol=${pair.symbol}&limit=5`,
                    {
                        headers: {
                            'X-MBX-APIKEY': BINANCE_API_KEY
                        }
                    }
                );

                const trades = response.data;

                trades.forEach(trade => {
                    const tradeTime = new Date(trade.time);
                    const now = new Date();
                    const diffMinutes = Math.floor((now - tradeTime) / 60000);

                    const timeStr = diffMinutes === 0 ? 'hace unos segundos' :
                        diffMinutes === 1 ? 'hace 1 min' :
                        `hace ${diffMinutes} min`;

                    allTrades.push({
                        type: 'p2p',
                        icon: pair.icon,
                        title: `Trade ${pair.display}`,
                        amount: `${parseFloat(trade.qty).toFixed(4)} ${pair.display.split('/')[0]}`,
                        detail: `Precio: $${parseFloat(trade.price).toFixed(2)}`,
                        time: timeStr,
                        timestamp: trade.time
                    });
                });
            } catch (error) {
                console.error(`Error fetching ${pair.symbol}:`, error.message);
            }
        }

        allTrades.sort((a, b) => b.timestamp - a.timestamp);
        allTrades = allTrades.slice(0, 15);

        const tradeCount = allTrades.length;
        const volumeTotal = allTrades.reduce((sum, trade) => {
            const qty = parseFloat(trade.amount.split(' ')[0]);
            return sum + qty;
        }, 0);

        res.json({
            success: true,
            trades: allTrades,
            stats: {
                totalTrades: tradeCount,
                totalVolume: volumeTotal.toFixed(2)
            }
        });
    } catch (error) {
        console.error('Error:', error);
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
