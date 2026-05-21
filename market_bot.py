import yfinance as yf
import requests
import ta
from datetime import datetime

BOT_TOKEN = "BURAYA_BOT_TOKEN"
CHAT_ID = "BURAYA_CHAT_ID"

ticker = "ISCTR.IS"

df = yf.download(
    ticker,
    period="2d",
    interval="15m"
)

df["Close"] = df["Close"].squeeze()
df["Volume"] = df["Volume"].squeeze()

df["EMA20"] = ta.trend.EMAIndicator(
    close=df["Close"],
    window=20
).ema_indicator()

df["RSI"] = ta.momentum.RSIIndicator(
    close=df["Close"],
    window=14
).rsi()

last = df.iloc[-1]
prev = df.iloc[-2]

price = round(last["Close"], 2)

change = round(
    ((last["Close"] - prev["Close"]) / prev["Close"]) * 100,
    2
)

rsi = round(last["RSI"], 2)
ema = round(last["EMA20"], 2)

signal = "HOLD"
emoji = "🟡"

if price > ema and rsi > 55:
    signal = "BUY"
    emoji = "🟢"

elif price < ema and rsi < 45:
    signal = "SELL"
    emoji = "🔴"

message = f"""
{emoji} ISCTR SIGNAL

⏰ {datetime.now().strftime('%H:%M')}

💰 Price: {price}
📈 Change: %{change}

📊 RSI: {rsi}
📉 EMA20: {ema}

Signal: {signal}
"""

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

requests.post(
    url,
    data={
        "chat_id": CHAT_ID,
        "text": message
    }
)

print(message)
