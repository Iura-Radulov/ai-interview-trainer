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
    """Log the feedback and thank the user."""
    user = update.effective_user
    text = update.message.text
    logger.info(
        "Feedback from user %s (%s): %s",
        user.id if user else "?",
        f"@{user.username}" if (user and user.username) else "no username",
        text,
    )
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
