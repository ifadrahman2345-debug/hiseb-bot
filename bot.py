import os
import sqlite3
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = "9136596869:AAG3r3l0HQNcY2VvOxVmsXGhguUqWgD1NlU"
BOT_NAME = "HISEB"
DB_PATH = "hiseb.db"

KEYBOARD = ReplyKeyboardMarkup(
    [
        ["📥 আয় লিখি", "🏦 জমা লিখি", "💸 খরচ লিখি"],
        ["📅 ৭ দিনের হিসাব", "🗓️ ১ মাসের হিসাব", "📆 ১ বছরের হিসাব"],
        ["💰 মোট জমা"],
    ],
    resize_keyboard=True,
)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            entry_type TEXT NOT NULL, -- 'income', 'deposit', 'expense'
            amount REAL NOT NULL,
            note TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def add_entry(user_id: int, entry_type: str, amount: float, note: str = ""):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute(
        "INSERT INTO entries (user_id, entry_type, amount, note, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, entry_type, amount, note, now_str),
    )
    # খরচ করলে জমার ব্যালেন্স থেকে সমন্বয়ের জন্য নেগেটিভ ডিপোজিট এন্ট্রি রাখা যায়,
    # অথবা সরাসরি মোট জমা থেকে খরচ বাদ দিয়ে দেখানো যায়।
    conn.commit()
    conn.close()


def get_total_deposit(user_id: int) -> float:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM entries WHERE user_id = ? AND entry_type = 'deposit'",
        (user_id,),
    )
    total_dep = cur.fetchone()[0] or 0.0

    cur.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM entries WHERE user_id = ? AND entry_type = 'expense'",
        (user_id,),
    )
    total_exp = cur.fetchone()[0] or 0.0
    conn.close()
    # জমা টাকা থেকে খরচ বাদ দিলে অবশিষ্ট/সমন্বিত জমা
    return total_dep - total_exp


def get_period_summary(user_id: int, days: int):
    since_dt = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT entry_type, COALESCE(SUM(amount), 0)
        FROM entries
        WHERE user_id = ? AND created_at >= ?
        GROUP BY entry_type
        """,
        (user_id, since_dt),
    )
    rows = dict(cur.fetchall())
    conn.close()

    income = rows.get("income", 0.0)
    raw_deposit = rows.get("deposit", 0.0)
    expense = rows.get("expense", 0.0)
    net_deposit_after_expense = raw_deposit - expense
    return income, raw_deposit, expense, net_deposit_after_expense


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("pending_type", None)
    await update.message.reply_text(
        f"স্বাগতম! আমি **{BOT_NAME}** — তোমার ডেইলি, মান্থলি ও ইয়ারলি হিসাব রাখার বট।\n\n"
        "নিচের বাটন থেকে যেকোনো একটি বেছে নাও:",
        reply_markup=KEYBOARD,
        parse_mode="Markdown",
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    user_id = update.effective_user.id

    # বাটন হ্যান্ডলারসমূহ
    if text == "📥 আয় লিখি":
        context.user_data["pending_type"] = "income"
        await update.message.reply_text("আজকের আয়ের পরিমাণ লেখো (যেমন: `500` বা `500 নাস্তা/কাজ`):", parse_mode="Markdown")
        return

    if text == "🏦 জমা লিখি":
        context.user_data["pending_type"] = "deposit"
        await update.message.reply_text("কত টাকা জমা করলে তা লেখো (যেমন: `300` বা `300 বিকাশ/ব্যাংক`):", parse_mode="Markdown")
        return

    if text == "💸 খরচ লিখি":
        context.user_data["pending_type"] = "expense"
        await update.message.reply_text("কত টাকা খরচ করলে তা লেখো (যেমন: `120` বা `120 দুপুরের খাবার`):", parse_mode="Markdown")
        return

    if text == "📅 ৭ দিনের হিসাব":
        context.user_data.pop("pending_type", None)
        inc, dep, exp, net_dep = get_period_summary(user_id, 7)
        await update.message.reply_text(
            f"📅 **{BOT_NAME} — গত ৭ দিনের হিসাব**\n"
            f"━━━━━━━━━━━━━━\n"
            f"📥 মোট আয়: `{inc:.2f}` টাকা\n"
            f"🏦 মোট জমা: `{dep:.2f}` টাকা\n"
            f"💸 মোট খরচ: `{exp:.2f}` টাকা\n"
            f"📊 জমা থেকে খরচ বাদ দিলে: `{net_dep:.2f}` টাকা",
            parse_mode="Markdown",
        )
        return

    if text == "🗓️ ১ মাসের হিসাব":
        context.user_data.pop("pending_type", None)
        inc, dep, exp, net_dep = get_period_summary(user_id, 30)
        await update.message.reply_text(
            f"🗓️ **{BOT_NAME} — গত ১ মাসের (৩০ দিন) হিসাব**\n"
            f"━━━━━━━━━━━━━━\n"
            f"📥 মোট আয়: `{inc:.2f}` টাকা\n"
            f"🏦 মোট জমা: `{dep:.2f}` টাকা\n"
            f"💸 মোট খরচ: `{exp:.2f}` টাকা\n"
            f"📊 জমা থেকে খরচ বাদ দিলে: `{net_dep:.2f}` টাকা",
            parse_mode="Markdown",
        )
        return

    if text == "📆 ১ বছরের হিসাব":
        context.user_data.pop("pending_type", None)
        inc, dep, exp, net_dep = get_period_summary(user_id, 365)
        await update.message.reply_text(
            f"📆 **{BOT_NAME} — গত ১ বছরের (৩৬৫ দিন) হিসাব**\n"
            f"━━━━━━━━━━━━━━\n"
            f"📥 মোট আয়: `{inc:.2f}` টাকা\n"
            f"🏦 মোট জমা: `{dep:.2f}` টাকা\n"
            f"💸 মোট খরচ: `{exp:.2f}` টাকা\n"
            f"📊 জমা থেকে খরচ বাদ দিলে: `{net_dep:.2f}` টাকা",
            parse_mode="Markdown",
        )
        return

    if text == "💰 মোট জমা":
        context.user_data.pop("pending_type", None)
        current_deposit = get_total_deposit(user_id)
        await update.message.reply_text(
            f"💰 **{BOT_NAME} — বর্তমান সমন্বিত জমা**\n"
            f"খরচ সমন্বয়ের পর অবশিষ্ট জমা: `{current_deposit:.2f}` টাকা",
            parse_mode="Markdown",
        )
        return

    # সংখ্যা ও নোট এন্ট্রি প্রসেসিং
    pending_type = context.user_data.get("pending_type")
    if pending_type:
        parts = text.split(maxsplit=1)
        try:
            amount = float(parts[0])
            if amount <= 0:
                raise ValueError()
        except ValueError:
            await update.message.reply_text("সঠিক টাকার পরিমাণ সংখ্যায় লেখো (যেমন: `250` অথবা `250 বাজার`)।", parse_mode="Markdown")
            return

        note = parts[1] if len(parts) > 1 else ""
        add_entry(user_id, pending_type, amount, note)
        context.user_data.pop("pending_type", None)

        label_map = {
            "income": "📥 আয়",
            "deposit": "🏦 জমা",
            "expense": "💸 খরচ",
        }
        current_deposit = get_total_deposit(user_id)
        note_text = f" ({note})" if note else ""

        await update.message.reply_text(
            f"✅ {label_map[pending_type]} যুক্ত হয়েছে: `{amount:.2f}` টাকা{note_text}\n"
            f"💰 বর্তমান সমন্বিত জমা: `{current_deposit:.2f}` টাকা",
            reply_markup=KEYBOARD,
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text("হিসাব লিখতে বা দেখতে নিচের বাটনগুলো ব্যবহার করো।", reply_markup=KEYBOARD)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        return


def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


if __name__ == "__main__":
    init_db()
    threading.Thread(target=start_health_server, daemon=True).start()
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .pool_timeout(30.0)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print(f"{BOT_NAME} is running...")
    app.run_polling(timeout=30, drop_pending_updates=True)
    
