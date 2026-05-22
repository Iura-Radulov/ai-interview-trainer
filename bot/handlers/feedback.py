"""Handlers for the /feedback conversation."""
import logging

from telegram import Update
from telegram.ext import (
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from db.database import save_feedback

logger = logging.getLogger(__name__)

WAITING_FOR_FEEDBACK = 10  # state within this handler only


async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt the user to type their feedback."""
    await update.message.reply_text(
        "💬 *Send Feedback*\n\n"
        "Type your feedback, suggestion, or bug report below\\.\n"
        "Use /cancel to abort\\.",
        parse_mode="MarkdownV2",
    )
    return WAITING_FOR_FEEDBACK


async def receive_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save feedback to DB and forward to the admin group."""
    user = update.effective_user
    text = update.message.text or ""

    # Save to DB
    await save_feedback(
        telegram_id=user.id if user else 0,
        username=f"@{user.username}" if (user and user.username) else None,
        message=text,
    )

    # Forward to admin group if configured
    if config.FEEDBACK_CHAT_ID:
        try:
            sender = f"@{user.username}" if (user and user.username) else f"ID {user.id}"
            await context.bot.send_message(
                chat_id=config.FEEDBACK_CHAT_ID,
                text=(
                    f"📬 New Feedback\n"
                    f"From: {sender}\n\n"
                    f"{text}"
                ),
            )
        except Exception as exc:
            logger.warning("Failed to forward feedback to chat %s: %s", config.FEEDBACK_CHAT_ID, exc)

    await update.message.reply_text(
        "✅ *Thank you for your feedback\\!*\n\n"
        "Your message has been recorded and will help us improve the bot\\.\n"
        "Use /interview to keep practising\\!",
        parse_mode="MarkdownV2",
    )
    return ConversationHandler.END


async def cancel_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel feedback submission."""
    await update.message.reply_text(
        "Feedback cancelled\\. Use /help to see available commands\\.",
        parse_mode="MarkdownV2",
    )
    return ConversationHandler.END


def build_feedback_handler() -> ConversationHandler:
    """Return a configured ConversationHandler for /feedback."""
    return ConversationHandler(
        entry_points=[CommandHandler("feedback", feedback_command)],
        states={
            WAITING_FOR_FEEDBACK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_feedback),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_feedback)],
    )
