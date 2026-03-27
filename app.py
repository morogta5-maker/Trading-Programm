from fastapi import FastAPI, Form, WebSocket
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from typing import List, Dict, Set, Annotated, Optional
import uvicorn
import webbrowser
import threading
import asyncio
import random
import math
from datetime import datetime, timedelta

app = FastAPI(title="Pro Trading Engine Multi-Stock")

# =========================
# Models
# =========================
class Order(BaseModel):
    product_id: str
    side: Annotated[str, Field(pattern="^(buy|sell)$")]
    price: Optional[float] = None
    quantity: Annotated[float, Field(gt=0)]
    type: Annotated[str, Field(pattern="^(limit|market|stop)$")] = "limit"
    stop_price: Optional[float] = None
    expiry: Optional[float] = None

# =========================
# Global State
# =========================
order_books: Dict[str, Dict[str, List[Dict]]] = {}
stop_orders: Dict[str, List[Dict]] = {}
trades: Dict[str, List[Dict]] = {}
price_history: Dict[str, List[Dict]] = {}
market_phase = "continuous"
clients: Set[WebSocket] = set()
clients_lock = asyncio.Lock()
portfolios: Dict[str, Dict[str, float]] = {}

products = ["BTC", "ETH", "AAPL", "DOGE"]

# =========================
# Helpers
# =========================
def init_product(product_id):
    if product_id not in order_books:
        order_books[product_id] = {"buy": [], "sell": []}
        trades[product_id] = []
        price_history[product_id] = []
        stop_orders[product_id] = []

def sort_book(book):
    book["buy"].sort(key=lambda x: x["price"], reverse=True)
    book["sell"].sort(key=lambda x: x["price"])

def init_portfolio(user):
    if user not in portfolios:
        portfolios[user] = {"cash": 10000.0, "position": 0.0, "pnl": 0.0}

def round2(val):
    return round(val, 2)

# =========================
# Price Engine
# =========================
def next_price(last_price, drift=0.0002, volatility=0.01):
    shock = random.gauss(0, 1)
    return last_price * math.exp((drift - 0.5 * volatility**2) + volatility * shock)

def orderbook_pressure(book):
    buy_volume = sum(o["quantity"] for o in book["buy"])
    sell_volume = sum(o["quantity"] for o in book["sell"])
    if buy_volume + sell_volume == 0:
        return 0
    return (buy_volume - sell_volume) / (buy_volume + sell_volume)

def enhanced_price(product_id):
    history = price_history[product_id]
    last_price = history[-1]["price"] if history else 100
    book = order_books[product_id]

    volatility = 0.01 + abs(random.gauss(0, 0.01))
    base = next_price(last_price, volatility=volatility)

    if len(history) > 5:
        trend = history[-1]["price"] - history[-5]["price"]
        base += 0.1 * trend

    if len(history) > 10:
        avg = sum(h["price"] for h in history[-10:]) / 10
        base += -0.05 * (last_price - avg)

    pressure = orderbook_pressure(book)
    base *= (1 + 0.01 * pressure)

    if random.random() < 0.03:
        base += random.uniform(-3, 3)

    return round2(max(base, 0.1))

# =========================
# Broadcast
# =========================
async def broadcast_all():
    async with clients_lock:
        data = {
            "phase": market_phase,
            "books": order_books,
            "trades": trades,
            "portfolios": portfolios,
            "price_history": price_history,
            "stop_orders": stop_orders
        }
        for client in list(clients):
            try:
                await client.send_json(data)
            except:
                clients.discard(client)

# =========================
# Matching Engine
# =========================
async def trigger_stops(product_id, last_price):
    now = datetime.now()

    # Entferne abgelaufene Stops
    stop_orders[product_id] = [
        s for s in stop_orders[product_id] if s["expiry"] > now
    ]

    triggered = []

    for s in stop_orders[product_id]:
        if (s["side"] == "buy" and last_price >= s["stop_price"]) or \
           (s["side"] == "sell" and last_price <= s["stop_price"]):
            triggered.append(s)

    for s in triggered:
        await match_order(Order(
            product_id=product_id,
            side=s["side"],
            quantity=s["quantity"],
            type="market"
        ), user=s["user"])

        stop_orders[product_id].remove(s)
        
async def match_order(order: Order, user="user"):
    init_product(order.product_id)
    init_portfolio(user)
    book = order_books[order.product_id]

    if market_phase == "closed":
        return

    if order.type == "stop":
        expiry_time = datetime.now() + timedelta(seconds=180)
        stop_orders[order.product_id].append({
            "user": user,
            "side": order.side,
            "quantity": round2(order.quantity),
            "stop_price": round2(order.stop_price),
            "expiry": expiry_time
        })
        
        await broadcast_all()
        return

    if order.type == "market":
        if order.side == "buy":
            while order.quantity > 0 and book["sell"]:
                ask = book["sell"][0]
                qty = min(order.quantity, ask["quantity"])
                trade_price = ask["price"]

                trades[order.product_id].append({
                    "price": round2(trade_price),
                    "qty": round2(qty),
                    "time": datetime.now().strftime("%H:%M:%S")
                })

                portfolios[user]["position"] += qty
                portfolios[user]["cash"] -= trade_price * qty

                order.quantity -= qty
                ask["quantity"] -= qty

                if ask["quantity"] <= 0:
                    book["sell"].pop(0)
        else:
            while order.quantity > 0 and book["buy"]:
                bid = book["buy"][0]
                qty = min(order.quantity, bid["quantity"])
                trade_price = bid["price"]

                trades[order.product_id].append({
                    "price": round2(trade_price),
                    "qty": round2(qty),
                    "time": datetime.now().strftime("%H:%M:%S")
                })

                portfolios[user]["position"] -= qty
                portfolios[user]["cash"] += trade_price * qty

                order.quantity -= qty
                bid["quantity"] -= qty

                if bid["quantity"] <= 0:
                    book["buy"].pop(0)

    else:
        if order.side == "buy":
            i = 0
            while i < len(book["sell"]):
                ask = book["sell"][i]
                if order.price >= ask["price"]:
                    qty = min(order.quantity, ask["quantity"])
                    trade_price = ask["price"]

                    trades[order.product_id].append({
                        "price": round2(trade_price),
                        "qty": round2(qty),
                        "time": datetime.now().strftime("%H:%M:%S")
                    })

                    portfolios[user]["position"] += qty
                    portfolios[user]["cash"] -= trade_price * qty

                    order.quantity -= qty
                    ask["quantity"] -= qty

                    if ask["quantity"] <= 0:
                        book["sell"].pop(i)
                        i -= 1
                i += 1

            if order.quantity > 0:
                book["buy"].append({"price": round2(order.price), "quantity": round2(order.quantity)})

        else:
            i = 0
            while i < len(book["buy"]):
                bid = book["buy"][i]
                if order.price <= bid["price"]:
                    qty = min(order.quantity, bid["quantity"])
                    trade_price = bid["price"]

                    trades[order.product_id].append({
                        "price": round2(trade_price),
                        "qty": round2(qty),
                        "time": datetime.now().strftime("%H:%M:%S")
                    })

                    portfolios[user]["position"] -= qty
                    portfolios[user]["cash"] += trade_price * qty

                    order.quantity -= qty
                    bid["quantity"] -= qty

                    if bid["quantity"] <= 0:
                        book["buy"].pop(i)
                        i -= 1
                i += 1

            if order.quantity > 0:
                book["sell"].append({"price": round2(order.price), "quantity": round2(order.quantity)})

    sort_book(book)

    last_price = enhanced_price(order.product_id) if trades[order.product_id] else 100

    price_history[order.product_id].append({
        "time": datetime.now().strftime("%H:%M:%S"),
        "price": last_price
    })

    portfolios[user]["pnl"] = portfolios[user]["position"] * last_price + portfolios[user]["cash"] - 10000.0

    await broadcast_all()
    await trigger_stops(order.product_id, last_price)

# =========================
# Schlauer Bot
# =========================
async def bot_trader(name):  # gleiche Funktionssignatur, nur schlauer
    init_portfolio(name)
    while True:
        await asyncio.sleep(random.uniform(1.5, 3.5))
        for product_id in products:
            init_product(product_id)
            history = price_history[product_id]
            last_price = history[-1]["price"] if history else 100
            book = order_books[product_id]

            # ================= Trendstrategie =================
            trend = (history[-1]["price"] - history[-5]["price"]) if len(history) > 5 else 0
            avg_price = sum(h["price"] for h in history[-5:])/5 if len(history) > 5 else last_price

            # Entscheidung
            if abs(trend) > 0.5:
                side = "buy" if trend > 0 else "sell"
                otype = "market"
            elif last_price > avg_price * 1.01:
                side = "sell"
                otype = "limit"
            elif last_price < avg_price * 0.99:
                side = "buy"
                otype = "limit"
            else:
                side = random.choice(["buy","sell"])
                otype = random.choice(["limit","market"])

            # ================= Order Preis/Qty =================
            if otype == "limit":
                if side == "buy":
                    price = (book["sell"][0]["price"] if book["sell"] else last_price) * 0.995
                else:
                    price = (book["buy"][0]["price"] if book["buy"] else last_price) * 1.005
            else:
                price = None

            qty = round2(random.uniform(0.5, 3) * (1 + abs(trend)/10))

            # ================= Order ausführen =================
            await match_order(Order(
                product_id=product_id,
                side=side,
                price=price,
                quantity=qty,
                type=otype
            ), user=name)

# =========================
# WebSocket
# =========================
@app.websocket("/ws")
async def ws(ws: WebSocket):
    await ws.accept()
    async with clients_lock:
        clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except:
        pass
    finally:
        async with clients_lock:
            clients.discard(ws)

# =========================
# UI (DEIN HTML)
# =========================
def render_page():
    return """
<html>
<head>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
/* Cursor über die Charts */
#charts canvas {
    cursor: crosshair; /* zeigt ein Fadenkreuz beim Überfahren der Charts */
}
</style>
</head>
<body class="bg-dark text-light">
<div class="container py-4">
<h1>Multi-Stock Trading Engine</h1>

<div class="row mb-3">
<div class="col-md-4">
<label>Marktphase:</label>
<select id="phaseSelector" class="form-select">
  <option value="continuous">Continuous</option>
  <option value="closed">Closed</option>
</select>
</div>
<div class="col-md-8">
<label>Order:</label>
<form id="orderForm" class="d-flex gap-2">
<input type="text" name="product_id" placeholder="Produkt z.B. BTC" class="form-control" required>
<select name="side" class="form-select">
<option value="buy">Buy</option>
<option value="sell">Sell</option>
</select>
<input type="number" name="price" step="0.01" placeholder="Preis" class="form-control">
<input type="number" name="quantity" step="0.01" placeholder="Menge" class="form-control" required>
<select name="type" class="form-select">
<option value="limit">Limit</option>
<option value="market">Market</option>
<option value="stop">Stop</option>
</select>
<input type="number" name="stop_price" step="0.01" placeholder="Stop Preis" class="form-control">
<button class="btn btn-primary">Senden</button>
</form>
</div>
</div>

<div class="row">
<div class="col-md-6">
<h4>Orderbook Heatmap</h4>
<div id="books"></div>
</div>
<div class="col-md-6">
<h4>Trades + Summen</h4>
<div id="trades"></div>
<h4>Portfolios</h4>
<div id="portfolios"></div>
</div>
</div>

<h4>Preisverlauf pro Aktie</h4>
<div id="charts"></div>

<script>
const colors = { "BTC": "red", "ETH": "green", "AAPL": "yellow", "DOGE": "blue" };
let ws = new WebSocket(`ws://${location.host}/ws`);
const charts = {}; // Chart-Objekte dauerhaft speichern

ws.onmessage = function(event){
    let data = JSON.parse(event.data);

    // Chart-Update
    for (let p in data.price_history) {
        let hist = data.price_history[p];

        if (!charts[p]) {
            let canvas = document.createElement("canvas");
            document.getElementById("charts").appendChild(canvas);
            let ctx = canvas.getContext("2d");

            charts[p] = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: hist.map(h => h.time),
                    datasets: [{ label: p, data: hist.map(h => h.price), borderColor: colors[p] || 'white', fill: false }]
                },
                options: { responsive: true, animation: false }
            });
        } else {
            charts[p].data.labels = hist.map(h => h.time);
            charts[p].data.datasets[0].data = hist.map(h => h.price);
            charts[p].update('none');
        }
    }

    // Orderbooks
    let booksHTML = "";
    for (let p in data.books){
        booksHTML += "<h5>"+p+"</h5><table class='table table-dark table-sm'>";
        booksHTML += "<tr><th>Buy</th><th>Qty</th><th>Sell</th><th>Qty</th></tr>";
        let max = Math.max(data.books[p].buy.length, data.books[p].sell.length);
        for(let i=0;i<max;i++){
            let buy = data.books[p].buy[i] || {"price":"-","quantity":0};
            let sell = data.books[p].sell[i] || {"price":"-","quantity":0};
            let buyColor = `rgba(0,255,0,${Math.min(buy.quantity/5,1)})`;
            let sellColor = `rgba(255,0,0,${Math.min(sell.quantity/5,1)})`;
            booksHTML += `<tr><td style='background-color:${buyColor}'>${buy.price}</td><td style='background-color:${buyColor}'>${buy.quantity}</td><td style='background-color:${sellColor}'>${sell.price}</td><td style='background-color:${sellColor}'>${sell.quantity}</td></tr>`;
        }
        data.stop_orders[p].forEach(s=>{
            booksHTML += `<tr style='background-color:rgba(255,165,0,0.5)'><td colspan='4'>STOP: ${s.side} ${s.quantity} @ ${s.stop_price} (${s.user})</td></tr>`;
        });
        booksHTML += "</table>";
    }
    document.getElementById("books").innerHTML = booksHTML;

    // Trades
    let tradesHTML = "";
    for (let p in data.trades){
        let t = data.trades[p].slice(-10);
        t.forEach(tr=>{
            tradesHTML += tr.time+" | "+tr.price+" | "+tr.qty+"<br>";
        });
        tradesHTML += "<hr>";
    }
    document.getElementById("trades").innerHTML = tradesHTML;

    // Portfolios
    let portHTML = "";
    for(let u in data.portfolios){
        let p = data.portfolios[u];
        portHTML += `${u}: Cash ${p.cash.toFixed(2)}, Pos ${p.position.toFixed(2)}, PnL ${p.pnl.toFixed(2)}<br>`;
    }
    document.getElementById("portfolios").innerHTML = portHTML;
}

document.getElementById("phaseSelector").addEventListener("change", async (e)=>{
    await fetch("/set_phase", {method:"POST", body:new URLSearchParams({phase:e.target.value})});
});

document.getElementById("orderForm").addEventListener("submit", async (e)=>{
    e.preventDefault();
    let form = e.target;
    await fetch("/submit_order", {method:"POST", body:new URLSearchParams(new FormData(form))});
    form.reset();
});
</script>
</body>
</html>
"""

# =========================
# Routes
# =========================
@app.on_event("startup")
async def startup():
    for p in products:
        init_product(p)
    init_portfolio("user")
    for i in range(3):
        asyncio.create_task(bot_trader(f"Bot{i+1}"))

@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse(render_page())

@app.post("/submit_order")
async def submit_order(
    product_id: str = Form(...), side: str = Form(...),
    price: float = Form(None), quantity: float = Form(...),
    type: str = Form("limit"), stop_price: float = Form(None)
):
    await match_order(Order(
        product_id=product_id,
        side=side,
        price=price,
        quantity=quantity,
        type=type,
        stop_price=stop_price
    ), user="user")
    return {"status": "ok"}

@app.post("/set_phase")
async def set_phase(phase: str = Form(...)):
    global market_phase
    if phase in ["continuous","closed"]:
        market_phase = phase
        await broadcast_all()
    return {"status":"ok"}

# =========================
# Start Server
# =========================
def open_browser():
    webbrowser.open("http://127.0.0.1:8000/")

if __name__=="__main__":
    threading.Timer(1.0, open_browser).start()
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)