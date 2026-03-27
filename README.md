Pro Trading Engine
==================

[![License](https://img.shields.io/github/license/yourusername/trading-engine.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)]()
[![FastAPI](https://img.shields.io/badge/FastAPI-ready-green.svg)]()

A real-time multi-asset trading engine built with FastAPI.  
It simulates a simplified electronic exchange with an order book, matching engine, automated trading bots, and a live browser-based interface.

The system supports multiple assets, different order types, and a dynamic price engine influenced by volatility, trend signals, and order book pressure.

Performance and simplicity are the primary focus. The engine is designed to demonstrate how trading systems work internally, including order matching, price formation, and liquidity simulation.

---

### What does this project provide?

* Real-time trading engine with WebSocket updates  
* Multi-asset support (BTC, ETH, AAPL, DOGE)  
* Order types:
  * Limit orders  
  * Market orders  
  * Stop orders with expiry  
* Matching engine with price-time priority  
* Dynamic price simulation (trend, volatility, order book imbalance)  
* Automated trading bots (trend-following and mean reversion)  
* Portfolio tracking (cash, position, PnL)  
* Interactive charts using Chart.js  
* Order book heatmap visualization  
* Market phase control (continuous / closed)  

---

### How do I run the trading engine?

1. Clone the repository

```bash
git clone https://github.com/yourusername/trading-engine.git
cd trading-engine
