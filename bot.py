from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler,
    ContextTypes, filters
)

import sqlite3
from datetime import datetime, date, timedelta

# =========================
# CONFIG
# =========================

TOKEN = "8384208978:AAG5AgV2RpCIckco7xfq3Wg2xO0BEqsVxPs"
ADMIN_ID = 123456789  # <-- твой ID

# =========================
# DB
# =========================

conn = sqlite3.connect("schedule.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS shifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    point TEXT,
    date TEXT,
    time_start TEXT,
    time_end TEXT,
    status TEXT DEFAULT 'approved'
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    status TEXT DEFAULT 'pending'
)
""")

conn.commit()

# =========================
# POINTS
# =========================

points = ["Меганом", "Ашан", "Карла Маркса", "Центрум", "Жигулина Роща"]

DATE, TIME = range(2)

# =========================
# HELPERS
# =========================

def register_user(user):
    cursor.execute("""
        INSERT OR IGNORE INTO users (user_id, username, status)
        VALUES (?, ?, 'pending')
    """, (user.id, user.username))
    conn.commit()


def is_allowed(user_id):
    cursor.execute("SELECT status FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    return row and row[0] == "approved"


def parse_time(t):
    return datetime.strptime(t, "%H:%M")


def is_overlap(a1, a2, b1, b2):
    return a1 < b2 and a2 > b1


def user_conflict(uid, date_, start, end):
    cursor.execute(
        "SELECT time_start, time_end FROM shifts WHERE user_id=? AND date=?",
        (uid, date_)
    )
    rows = cursor.fetchall()

    for r in rows:
        if is_overlap(start, end, parse_time(r[0]), parse_time(r[1])):
            return True
    return False


def save_shift(uid, username, point, date_, start, end):
    cursor.execute("""
        INSERT INTO shifts (user_id, username, point, date, time_start, time_end, status)
        VALUES (?, ?, ?, ?, ?, ?, 'approved')
    """, (uid, username, point, date_, start, end))
    conn.commit()

# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.message.from_user
    register_user(user)

    if not is_allowed(user.id):
        await update.message.reply_text("⛔ Доступ не открыт")
        return

    keyboard = [
        [InlineKeyboardButton("📍 Записаться", callback_data="book")],
        [InlineKeyboardButton("📅 Мои смены", callback_data="my")],
        [InlineKeyboardButton("❌ Отменить смену", callback_data="cancel")],
    ]

    await update.message.reply_text(
        "👋 Главное меню:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# =========================
# MENU
# =========================

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id

    # BOOK
    if q.data == "book":
        kb = [
            [InlineKeyboardButton(p, callback_data=f"point_{p}")]
            for p in points
        ]

        await q.edit_message_text(
            "📍 Выбери точку:",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    # MY
    elif q.data == "my":
        cursor.execute("""
            SELECT point, date, time_start, time_end
            FROM shifts WHERE user_id=?
        """, (uid,))
        rows = cursor.fetchall()

        if not rows:
            await q.edit_message_text("📭 Нет смен")
            return

        text = "📅 Твои смены:\n\n"
        for r in rows:
            text += f"{r[0]} | {r[1]} | {r[2]}-{r[3]}\n"

        await q.edit_message_text(text)

    # CANCEL LIST
    elif q.data == "cancel":
        cursor.execute("""
            SELECT id, point, date FROM shifts WHERE user_id=?
        """, (uid,))
        rows = cursor.fetchall()

        kb = [
            [InlineKeyboardButton(f"{r[1]} {r[2]}", callback_data=f"del_{r[0]}")]
            for r in rows
        ]

        await q.edit_message_text(
            "❌ Выбери смену:",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    # DELETE
    elif q.data.startswith("del_"):
        sid = q.data.split("_")[1]
        cursor.execute("DELETE FROM shifts WHERE id=?", (sid,))
        conn.commit()

        await q.edit_message_text("🗑 удалено")

# =========================
# POINT
# =========================

async def point(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    context.user_data["point"] = q.data.replace("point_", "")

    await q.edit_message_text("📅 Введи дату (YYYY-MM-DD):")
    return DATE

# =========================
# DATE
# =========================

async def date_h(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["date"] = update.message.text
    await update.message.reply_text("⏰ Время (10:00-13:00):")
    return TIME

# =========================
# TIME
# =========================

async def time_h(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    try:
        start_s, end_s = text.split("-")

        start = parse_time(start_s)
        end = parse_time(end_s)

        if start < parse_time("10:00") or end > parse_time("21:00"):
            await update.message.reply_text("❌ 10–21")
            return ConversationHandler.END

        if (end - start).seconds / 3600 < 3:
            await update.message.reply_text("❌ минимум 3 часа")
            return ConversationHandler.END

        uid = update.message.from_user.id
        username = update.message.from_user.username

        if user_conflict(uid, context.user_data["date"], start, end):
            await update.message.reply_text("❌ конфликт смен")
            return ConversationHandler.END

        save_shift(
            uid,
            username,
            context.user_data["point"],
            context.user_data["date"],
            start_s,
            end_s
        )

        await update.message.reply_text("✅ записано")

    except:
        await update.message.reply_text("❌ формат 10:00-13:00")

    return ConversationHandler.END

# =========================
# ADMIN USERS
# =========================

async def users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return

    cursor.execute("SELECT user_id, username, status FROM users")
    rows = cursor.fetchall()

    kb = []

    for uid, username, status in rows:
        name = f"@{username}" if username else str(uid)

        kb.append([
            InlineKeyboardButton(f"{name} ({status})", callback_data="noop")
        ])
        kb.append([
            InlineKeyboardButton("✅", callback_data=f"approve_{uid}"),
            InlineKeyboardButton("⛔", callback_data=f"block_{uid}")
        ])

    await update.message.reply_text(
        "👥 USERS",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# =========================
# CALLBACK
# =========================

async def cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    data = q.data

    if data.startswith("point_"):
        return await point(update, context)

    if data == "noop":
        return

    if data.startswith("approve_"):
        uid = data.split("_")[1]
        cursor.execute("UPDATE users SET status='approved' WHERE user_id=?", (uid,))
        conn.commit()
        await q.edit_message_text("✅ approved")
        return

    if data.startswith("block_"):
        uid = data.split("_")[1]
        cursor.execute("UPDATE users SET status='blocked' WHERE user_id=?", (uid,))
        conn.commit()
        await q.edit_message_text("⛔ blocked")
        return

# =========================
# BOT
# =========================

app = Application.builder().token(TOKEN).build()

conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(cb)],
    states={
        DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, date_h)],
        TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, time_h)],
    },
    fallbacks=[]
)

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("users", users))

app.add_handler(conv)
app.add_handler(CallbackQueryHandler(menu))
app.add_handler(CallbackQueryHandler(cb))

print("BOT STARTED")
app.run_polling()
