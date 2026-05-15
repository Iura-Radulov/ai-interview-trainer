"""Handlers for /start, /help and role-selection callback from /start."""
import logging

from telegram import Update
from telegram.ext import ContextTypes

import config
from bot.keyboards import start_role_keyboard
from db.database import get_or_create_user, update_user_role

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Register the user and show a role-selection welcome message."""
    user = update.effective_user
    if user is None:
        return

    await get_or_create_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )

    text = (
        f"👋 Welcome to *AI Interview Trainer*, {user.first_name or 'there'}\\!\n\n"
        "I'm your personal AI interview coach\\. Practice for:\n"
        "🎨 *Frontend* — React, Next\\.js, TypeScript\n"
        "⚙️ *Backend* — APIs, databases, system design\n"
        "🔄 *Fullstack* — end\\-to\\-end development\n"
        "🤖 *ML* — machine learning, deep learning\n\n"
        "Select your primary role to get started:"
    )

    await update.message.reply_text(
        text, parse_mode="MarkdownV2", reply_markup=start_role_keyboard()
    )


async def set_role_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Persist the role chosen from /start and confirm to the user."""
    query = update.callback_query
    await query.answer()

    if not query.data:
        return

    role = query.data.removeprefix("set_role_")
    if role not in config.ROLES:
        await query.edit_message_text("Unknown role — please use /start again.")
        return

    user = update.effective_user
    if user is None:
        return

    await update_user_role(user.id, role)
    emoji = config.ROLE_EMOJIS.get(role, "")

    text = (
        f"✅ Role set to *{emoji} {role}*\\!\n\n"
        "Here's what you can do:\n"
        "📝 /interview — start an interview session\n"
        "👤 /profile — view your stats\n"
        "💬 /feedback — send feedback\n"
        "❓ /help — show help\n\n"
        "Ready to practise? Hit /interview 🚀"
    )
    await query.edit_message_text(text, parse_mode="MarkdownV2")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display usage instructions."""
    text = (
        "*AI Interview Trainer — Help*\n\n"
        "*Commands:*\n"
        "/start — register and set your preferred role\n"
        "/interview — start a new interview session\n"
        "/profile — view your stats and history\n"
        "/feedback — send feedback to the developers\n"
        "/help — show this message\n\n"
        "*How it works:*\n"
        "1\\. Choose your role and experience level\n"
        "2\\. Answer 5 AI\\-generated interview questions\n"
        "3\\. Receive per\\-answer feedback scored 1–10\n"
        "4\\. Get a full session summary with study tips\n\n"
        f"*Daily limit:* {config.MAX_FREE_INTERVIEWS_PER_DAY} interviews per day\n\n"
        "💡 Answer as you would in a real interview — the more detail, the better the feedback\\!"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")
