"""Handler for the /profile command."""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from ai.scoring import format_profile_message
from db.database import get_user_stats

logger = logging.getLogger(__name__)


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetch and display the user's interview statistics."""
    user = update.effective_user
    if user is None:
        return

    stats = await get_user_stats(user.id)
    if not stats:
        await update.message.reply_text(
            "No profile found\\. Use /start to register first\\.",
            parse_mode="MarkdownV2",
        )
        return

    await update.message.reply_text(
        format_profile_message(stats), parse_mode="Markdown"
    )
