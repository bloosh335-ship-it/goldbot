from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from tvDatafeed import TvDatafeed, Interval
from datetime import datetime
import ta, csv, os

TOKEN = "8651321542:AAGzndLVsrFimOmVoAYEMshXlOMgBPgrlxM"
CHAT_ID = "7994882819"

tv = TvDatafeed()
last_alert = None
HISTORY_FILE = "signals_history.csv"


def get_data(interval, bars=300):
    data = tv.get_hist("XAUUSD", "OANDA", interval=interval, n_bars=bars)
    if data is None or data.empty:
        raise Exception("ما وصلت بيانات TradingView")
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
def analyze_tf(interval):
    data = get_data(interval)
    close, high, low = data["close"], data["high"], data["low"]

    price = float(close.iloc[-1])
    ema20 = float(close.ewm(span=20).mean().iloc[-1])
    ema50 = float(close.ewm(span=50).mean().iloc[-1])
    ema200 = float(close.ewm(span=200).mean().iloc[-1])
    rsi = float(ta.momentum.RSIIndicator(close).rsi().iloc[-1])

    macd_i = ta.trend.MACD(close)
    macd = float(macd_i.macd().iloc[-1])
    macd_signal = float(macd_i.macd_signal().iloc[-1])
    atr = float(ta.volatility.AverageTrueRange(high, low, close).average_true_range().iloc[-1])

    buy = sell = 0
    reasons = []

    if price > ema20:
        buy += 15; reasons.append("✅ السعر فوق EMA20")
    else:
        sell += 15; reasons.append("✅ السعر تحت EMA20")

    if ema20 > ema50:
        buy += 15; reasons.append("✅ EMA20 فوق EMA50")
    else:
        sell += 15; reasons.append("✅ EMA20 تحت EMA50")

    if ema50 > ema200:
        buy += 20; reasons.append("✅ EMA50 فوق EMA200")
    else:
        sell += 20; reasons.append("✅ EMA50 تحت EMA200")

    if rsi > 55:
        buy += 15; reasons.append("✅ RSI يدعم الصعود")
    elif rsi < 45:
        sell += 15; reasons.append("✅ RSI يدعم الهبوط")
    else:
        reasons.append("⚪ RSI محايد")

    if macd > macd_signal:
        buy += 15; reasons.append("✅ MACD إيجابي")
    else:
        sell += 15; reasons.append("✅ MACD سلبي")

    candle, cdir = candle_signal(data)
    if cdir == "buy":
        buy += 20; reasons.append(f"🕯️ {candle}")
    elif cdir == "sell":
        sell += 20; reasons.append(f"🕯️ {candle}")
    else:
        reasons.append(f"🕯️ {candle}")

    trend = "صاعد 🟢" if buy > sell else "هابط 🔴" if sell > buy else "غير واضح ⚪"

    return {
        "price": price, "ema20": ema20, "ema50": ema50, "ema200": ema200,
        "rsi": rsi, "macd": macd, "macd_signal": macd_signal,
        "atr": atr, "support": float(low.tail(30).min()),
        "resistance": float(high.tail(30).max()),
        "buy": buy, "sell": sell, "trend": trend, "reasons": reasons,
        "candle": candle
    }


def save_signal(signal, strength, entry, sl, tp1, tp2):
    exists = os.path.exists(HISTORY_FILE)
    with open(HISTORY_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow(["time", "signal", "strength", "entry", "sl", "tp1", "tp2"])
        writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M"), signal, strength, entry, sl, tp1, tp2])


def analyze_gold(mode="scalp", force=None):
    m5 = analyze_tf(Interval.in_5_minute)
    m15 = analyze_tf(Interval.in_15_minute)
    h1 = analyze_tf(Interval.in_1_hour)

    price, atr = m15["price"], m15["atr"]
    buy_score, sell_score = m15["buy"], m15["sell"]
    reasons = m15["reasons"]

    if h1["trend"] == "صاعد 🟢":
        buy_score += 25; reasons.append("✅ H1 صاعد")
    elif h1["trend"] == "هابط 🔴":
        sell_score += 25; reasons.append("✅ H1 هابط")

    if m5["trend"] == "صاعد 🟢":
        buy_score += 10; reasons.append("✅ M5 صاعد")
    elif m5["trend"] == "هابط 🔴":
        sell_score += 10; reasons.append("✅ M5 هابط")

    atr_mult = 1.5 if mode == "swing" else 1
    tp_mult = 3 if mode == "swing" else 2
    min_score = 75 if mode == "scalp" else 85

    if force == "buy":
        buy_score += 15
    if force == "sell":
        sell_score += 15

    if buy_score > sell_score and buy_score >= min_score:
        signal, trend, strength = "شراء 🟢", "صاعد 🟢", buy_score
        entry = price; sl = price - atr * atr_mult; tp1 = price + atr; tp2 = price + atr * tp_mult
    elif sell_score > buy_score and sell_score >= min_score:
        signal, trend, strength = "بيع 🔴", "هابط 🔴", sell_score
        entry = price; sl = price + atr * atr_mult; tp1 = price - atr; tp2 = price - atr * tp_mult
    else:
        signal, trend, strength = "انتظار ⏳", "غير واضح ⚪", max(buy_score, sell_score)
        entry = sl = tp1 = tp2 = None

    text = f"""📊 MB Gold Trader Pro Level 8

⚙️ النوع: {mode}
💰 السعر: {price:.2f}

⏱️ H1: {h1["trend"]}
⏱️ M15: {m15["trend"]}
⏱️ M5: {m5["trend"]}

📈 EMA20: {m15["ema20"]:.2f}
📉 EMA50: {m15["ema50"]:.2f}
📊 EMA200: {m15["ema200"]:.2f}
📊 RSI: {m15["rsi"]:.1f}

📉 MACD: {m15["macd"]:.2f}
📈 MACD Signal: {m15["macd_signal"]:.2f}

🧱 الدعم: {m15["support"]:.2f}
🚧 المقاومة: {m15["resistance"]:.2f}
📏 ATR: {atr:.2f}

📢 الإشارة: {signal}
🔥 القوة: {strength}%

🧠 الأسباب:
{chr(10).join(reasons)}
"""

    if entry is not None:
        risk = abs(entry - sl)
        reward = abs(tp2 - entry)
        rr = reward / risk if risk else 0
        text += f"""

📍 الدخول: {entry:.2f}
🛑 وقف الخسارة: {sl:.2f}
🎯 الهدف الأول: {tp1:.2f}
🎯 الهدف الثاني: {tp2:.2f}
📊 R:R = 1:{rr:.1f}
"""

    text += "\n⚠️ تحليل آلي تجريبي وليس توصية مالية."
    return signal, strength, entry, sl, tp1, tp2, text


async def send_analysis(update, mode="scalp", force=None):
    try:
        *_, text = analyze_gold(mode, force)
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"❌ صار خطأ:\n{e}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 MB Gold Trader Pro Level 8 شغال\nاكتب /help")


async def help_cmd(update, context):
    await update.message.reply_text(
        "📊 الأوامر:\n\n"
        "/gold تحليل كامل\n/scalp سكالب\n/swing سوينغ\n/signal أفضل إشارة\n"
        "/buy فحص شراء\n/sell فحص بيع\n/trend الترند\n/price السعر\n/levels دعم ومقاومة\n"
        "/pattern شموع\n/sniper أقوى فرصة\n/history السجل\n/status الحالة\n/id آيديك"
    )


async def gold(update, context): await send_analysis(update, "scalp")
async def scalp(update, context): await send_analysis(update, "scalp")
async def swing(update, context): await send_analysis(update, "swing")
async def buy(update, context): await send_analysis(update, "scalp", "buy")
async def sell(update, context): await send_analysis(update, "scalp", "sell")
async def signal(update, context): await send_analysis(update, "scalp")
async def sniper(update, context): await send_analysis(update, "swing")


async def trend(update, context):
    h1 = analyze_tf(Interval.in_1_hour)
    m15 = analyze_tf(Interval.in_15_minute)
    m5 = analyze_tf(Interval.in_5_minute)
    await update.message.reply_text(f"📈 الترند:\nH1: {h1['trend']}\nM15: {m15['trend']}\nM5: {m5['trend']}")


async def price(update, context):
    m15 = analyze_tf(Interval.in_15_minute)
    await update.message.reply_text(f"💰 سعر الذهب الحالي: {m15['price']:.2f}")


async def levels(update, context):
    m15 = analyze_tf(Interval.in_15_minute)
    await update.message.reply_text(f"🧱 الدعم: {m15['support']:.2f}\n🚧 المقاومة: {m15['resistance']:.2f}")


async def pattern(update, context):
    m15 = analyze_tf(Interval.in_15_minute)
    await update.message.reply_text(f"🕯️ نموذج الشمعة الحالي:\n{m15['candle']}")


async def history(update, context):
    if not os.path.exists(HISTORY_FILE):
        await update.message.reply_text("مافي سجل إشارات للحين.")
        return
    with open(HISTORY_FILE, "r") as f:
        rows = list(csv.reader(f))[-10:]
    text = "📋 آخر الإشارات:\n\n" + "\n".join([" | ".join(r[:4]) for r in rows])
    await update.message.reply_text(text)


async def status(update, context):
    await update.message.reply_text("✅ البوت شغال ويراقب الذهب كل دقيقة.")


async def get_id(update, context):
    await update.message.reply_text(f"🆔 آيديك:\n{update.effective_chat.id}")


async def auto_check(context):
    global last_alert
    try:
        signal, strength, entry, sl, tp1, tp2, text = analyze_gold("scalp")
        alert_key = f"{signal}_{round(entry or 0, 2)}"
        if signal != "انتظار ⏳" and strength >= 85 and alert_key != last_alert:
            last_alert = alert_key
            save_signal(signal, strength, entry, sl, tp1, tp2)
            await context.bot.send_message(chat_id=CHAT_ID, text="🚨 إشارة قوية جديدة\n\n" + text)
    except Exception as e:
        print("Auto check error:", e)


app = Application.builder().token(TOKEN).build()

for cmd, func in [
    ("start", start), ("help", help_cmd), ("gold", gold), ("scalp", scalp),
    ("swing", swing), ("signal", signal), ("buy", buy), ("sell", sell),
    ("sniper", sniper), ("trend", trend), ("price", price), ("levels", levels),
    ("pattern", pattern), ("history", history), ("status", status), ("id", get_id)
]:
    app.add_handler(CommandHandler(cmd, func))

app.job_queue.run_repeating(auto_check, interval=60, first=10)

print("🤖 MB Gold Trader Pro Level 8 is running...")
app.run_polling()