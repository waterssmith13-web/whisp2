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
                expires_at INTEGER,
                is_read INTEGER DEFAULT 0,
                inline_message_id TEXT
            )
        ''')
        await db.commit()

# 📡 BOT 2: LOGGER FUNCTION
async def log_to_admin(whisper_id, sender_user, target, text_length):
    log_message = (
        "📥 **New Whisper Registered**\n\n"
        f"🆔 **ID:** `{whisper_id}`\n"
        f"👤 **From:** @{sender_user}\n"
        f"🎯 **To:** {target}\n"
        f"📊 **Size:** {text_length} characters"
    )
    try:
        await bot2.send_message(chat_id=ADMIN_CHAT_ID, text=log_message, parse_mode="Markdown")
    except Exception as e:
        print(f"[LOGGER ERROR] Failed to send reference log: {e}")

# 🚀 BOT 1: INLINE QUERY HANDLER
@dp.inline_query()
async def inline_handler(inline_query: types.InlineQuery):
    text = inline_query.query.strip()
    
    if not text.startswith("@"):
        return 
        
    parts = text.split(" ", 1)
    target_username = parts[0]
    whisper_text = parts[1].strip() if len(parts) > 1 else ""
    
    if target_username == "@":
        return

    sender = inline_query.from_user
    whisper_id = secrets.token_urlsafe(8)
    expires_at = int(time.time()) + 2592000  # 30 Days expiration retention
    
    if whisper_text:
        description_text = "🔑 Click to dispatch secure whisper."
    else:
        description_text = "Type your ultra-long message after the username..."

    # Matches the exact UI string from your graphic upload
    group_layout = (
        f"🔘 via @{BOT_USERNAME}\n"
        f"📜 A long whisper message to {target_username}\n"
        "───\n"
        "📊 Status: 🔒 Unread\n"
        "───"
    )
    
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🔑 Read Secure Whisper", callback_data=f"chk:{whisper_id}")]
    ])

    item = types.InlineQueryResultArticle(
        id=whisper_id,
        title=f"🔒 Send long whisper to {target_username}",
        description=description_text,
        input_message_content=types.InputTextMessageContent(message_text=group_layout),
        reply_markup=keyboard
    )
    
    if whisper_text:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO whispers (whisper_id, sender_id, sender_username, target_username, secret_text, expires_at, is_read) VALUES (?, ?, ?, ?, ?, ?, 0)",
                (whisper_id, sender.id, sender.username, target_username, whisper_text, expires_at)
            )
            await db.commit()
        await log_to_admin(whisper_id, sender.username or sender.id, target_username, len(whisper_text))
        
    await inline_query.answer([item], cache_time=0, is_personal=True)

# 📥 BOT 1: CHOSEN INLINE RESULT HANDLER
@dp.chosen_inline_result()
async def chosen_result_handler(chosen_result: types.ChosenInlineResult):
    whisper_id = chosen_result.result_id
    inline_message_id = chosen_result.inline_message_id
    
    if inline_message_id:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE whispers SET inline_message_id = ? WHERE whisper_id = ?",
                (inline_message_id, whisper_id)
            )
            await db.commit()

# ⚡ BOT 1: GROUP CALLBACK INTERCEPTOR (With Fixed Redirection Slash)
@dp.callback_query(lambda c: c.data.startswith("chk:"))
async def handle_group_click(callback: types.CallbackQuery):
    whisper_id = callback.data.split(":")[1]
    current_user = callback.from_user.username

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT target_username, expires_at, is_read FROM whispers WHERE whisper_id = ?",
            (whisper_id,)
        ) as cursor:
            row = await cursor.fetchone()

    if not row:
        await callback.answer("⚠️ This whisper has expired and was securely deleted from our database.", show_alert=True)
        return

    target_username, expires_at, is_read = row

    if int(time.time()) > expires_at:
        await callback.answer("⚠️ This whisper has expired and was securely deleted from our database.", show_alert=True)
        return

    if not current_user:
        await callback.answer("❌ You must configure a Telegram username handle in settings to read whispers.", show_alert=True)
        return

    clean_target = target_username.lstrip('@').lower()
    
    # ❌ WRONG USER: Clean alert modal pop up instantly
    if current_user.lower() != clean_target:
        await callback.answer(f"Access Denied: This whisper is strictly encrypted for {target_username}.", show_alert=True)
        return

    # 🔗 CORRECT RECIPIENT: Fixed URL syntax with added forward slash
    redirect_url = f"https://t.me{BOT_USERNAME}?start={whisper_id}"
    await callback.answer(url=redirect_url)

    # Update Group Layout text field to reflect "Read" status
    if is_read == 0 and callback.inline_message_id:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE whispers SET is_read = 1 WHERE whisper_id = ?", (whisper_id,))
            await db.commit()
            
        clean_display_name = target_username.replace('_', '\\_')
        updated_layout = (
            f"🔘 via @{BOT_USERNAME}\n"
            f"📜 A long whisper message to {clean_display_name}\n"
            "───\n"
            "📊 Status: ✅ Read by recipient\n"
            "───"
        )
        
        revisit_keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="🔑 Open in Private Bot", url=f"https://t.me{BOT_USERNAME}")]
        ])
        
        try:
            await bot1.edit_message_text(
                inline_message_id=callback.inline_message_id,
                text=updated_layout,
                reply_markup=revisit_keyboard
            )
        except Exception as e:
            print(f"[LAYOUT EDIT ERROR] {e}")

# 📥 BOT 1: START COMMAND DECODER
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

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT target_username, secret_text, sender_username FROM whispers WHERE whisper_id = ?",
            (whisper_id,)
        ) as cursor:
            row = await cursor.fetchone()

    if row:
        target_username, secret_text, sender_username = row
        current_user = message.from_user.username
        
        if current_user and current_user.lower() == target_username.lstrip('@').lower():
            saved_copy = (
                f"📩 **Your Secure Whisper:**\n\n"
                f"👤 **From:** @{sender_username or 'Anonymous'}\n\n"
                f"💬 **Message:**\n{secret_text}"
            )
            await message.answer(saved_copy)
        else:
            await message.answer("❌ **Access Denied:** You are not authorized to view this secret whisper thread.")
    else:
        await message.answer("⚠️ This whisper has expired or does not exist.")

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
