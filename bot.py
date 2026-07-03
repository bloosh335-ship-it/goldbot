import os
import csv
import asyncio
from datetime import datetime

import ta
from tvDatafeed import TvDatafeed, Interval
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("T8651321542:AAGzndLVsrFimOmVoAYEMshXlOMgBPgrlxMOKEN")
CHAT_ID = os.getenv("7994882819")

tv = TvDatafeed()
HISTORY_FILE = "signals_history.csv"
last_alerts = {}

MARKETS = [
    {"name": "🥇 GOLD", "symbol": "XAUUSD", "exchange": "OANDA"},
    {"name": "₿ BITCOIN", "symbol": "BTCUSDT", "exchange": "BINANCE"},
]


def get_data(symbol, exchange, interval, bars=300):
    data = tv.get_hist(
        symbol=symbol,
        exchange=exchange,
        interval=interval,
        n_bars=bars
    )
    if data is None or data.empty:
        raise Exception(f"ما وصلت بيانات {symbol} من TradingView")
    return data


def candle_signal(data):
    o1, c1 = data["open"].iloc[-2], data["close"].iloc[-2]
    o2, c2 = data["open"].iloc[-1], data["close"].iloc[-1]
    h, l = data["high"].iloc[-1], data["low"].iloc[-1]

    body = abs(c2 - o2)
    rng = h - l

    if rng > 0 and body < rng * 0.2:
        return "Doji ⚪", "neutral"

    if c2 > o2:
        return "Bullish Candle 🟢", "buy"

    if c2 < o2:
        return "Bearish Candle 🔴", "sell"

    return "لا يوجد نموذج قوي", "neutral"


def analyze_market(market, interval):
    data = get_data(market["symbol"], market["exchange"], interval)

    close = data["close"]
    high = data["high"]
    low = data["low"]

    price = float(close.iloc[-1])

    ema20 = ta.trend.ema_indicator(close, window=20).iloc[-1]
    ema50 = ta.trend.ema_indicator(close, window=50).iloc[-1]
    ema200 = ta.trend.ema_indicator(close, window=200).iloc[-1]

    rsi = ta.momentum.rsi(close, window=14).iloc[-1]

    macd = ta.trend.macd(close).iloc[-1]
    macd_signal = ta.trend.macd_signal(close).iloc[-1]

    atr = ta.volatility.average_true_range(high, low, close, window=14).iloc[-1]

    support = float(low.tail(30).min())
    resistance = float(high.tail(30).max())

    pattern, candle_dir = candle_signal(data)

    buy_score = 0
    sell_score = 0

    if price > ema20:
        buy_score += 1
    else:
        sell_score += 1

    if ema20 > ema50:
        buy_score += 1
    else:
        sell_score += 1

    if price > ema200:
        buy_score += 1
    else:
        sell_score += 1

    if rsi > 55:
        buy_score += 1
    elif rsi < 45:
        sell_score += 1

    if macd > macd_signal:
        buy_score += 1
    else:
        sell_score += 1

    if candle_dir == "buy":
        buy_score += 1
    elif candle_dir == "sell":
        sell_score += 1

    if buy_score > sell_score:
        signal = "buy"
        side = "شراء 🟢"
        entry = price
        sl = price - atr
        tp1 = price + atr
        tp2 = price + atr * 2
    elif sell_score > buy_score:
        signal = "sell"
        side = "بيع 🔴"
        entry = price
        sl = price + atr
        tp1 = price - atr
        tp2 = price - atr * 2
    else:
        signal = "neutral"
        side = "انتظار ⚪"
        entry = price
        sl = None
        tp1 = None
        tp2 = None

    return {
        "market": market["name"],
        "symbol": market["symbol"],
        "price": price,
        "signal": signal,
        "side": side,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,
        "rsi": rsi,
        "macd": macd,
        "macd_signal": macd_signal,
        "atr": atr,
        "support": support,
        "resistance": resistance,
        "pattern": pattern,
        "buy_score": buy_score,
        "sell_score": sell_score,
    }


def save_signal(result):
    file_exists = os.path.isfile(HISTORY_FILE)

    with open(HISTORY_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        if not file_exists:
            writer.writerow([
                "time", "market", "symbol", "signal", "price",
                "entry", "sl", "tp1", "tp2"
            ])

        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            result["market"],
            result["symbol"],
            result["signal"],
            result["price"],
            result["entry"],
            result["sl"],
            result["tp1"],
            result["tp2"],
        ])


def format_message(result):
    if result["signal"] == "neutral":
        trade_part = "⚪ لا توجد إشارة قوية الآن"
    else:
        trade_part = f"""
📍 الدخول: {result['entry']:.2f}
🛑 وقف الخسارة: {result['sl']:.2f}
🎯 الهدف الأول: {result['tp1']:.2f}
🎯 الهدف الثاني: {result['tp2']:.2f}
"""

    return f"""
🚨 إشارة جديدة

📊 MB Gold Trader Pro Level 9

{result['market']} - {result['symbol']}
النوع: {result['side']}
السعر: {result['price']:.2f}

{trade_part}

⏱️ الاتجاه:
Buy Score: {result['buy_score']}
Sell Score: {result['sell_score']}

📈 EMA20: {result['ema20']:.2f}
📈 EMA50: {result['ema50']:.2f}
📈 EMA200: {result['ema200']:.2f}
📊 RSI: {result['rsi']:.1f}

📉 MACD: {result['macd']:.2f}
📉 MACD Signal: {result['macd_signal']:.2f}

🧱 الدعم: {result['support']:.2f}
🚧 المقاومة: {result['resistance']:.2f}
📏 ATR: {result['atr']:.2f}

🕯️ النموذج: {result['pattern']}

⚠️ تحليل آلي تجريبي وليس توصية مالية.
"""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 MB Gold Trader Pro Level 9 شغال\n🥇 Gold + ₿ Bitcoin")


async def check_markets(context: ContextTypes.DEFAULT_TYPE):
    global last_alerts

    for market in MARKETS:
        try:
            result = analyze_market(market, Interval.in_15_minute)
            key = result["symbol"]

            if result["signal"] != "neutral":
                alert_key = f"{result['signal']}_{round(result['price'], 1)}"

                if last_alerts.get(key) != alert_key:
                    msg = format_message(result)
                    await context.bot.send_message(chat_id=CHAT_ID, text=msg)
                    save_signal(result)
                    last_alerts[key] = alert_key

        except Exception as e:
            print(f"Auto check error {market['symbol']}:", e)


def main():
    if not TOKEN:
        raise Exception("TOKEN غير موجود في Environment")

    if not CHAT_ID:
        raise Exception("CHAT_ID غير موجود في Environment")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.job_queue.run_repeating(
        check_markets,
        interval=300,
        first=10
    )

    print("🤖 MB Gold Trader Pro Level 9 is running...")
    app.run_polling()


if __name__ == "__main__":
    main()