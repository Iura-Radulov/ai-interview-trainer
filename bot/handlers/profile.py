"""Handler for the /profile command."""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ai.scoring import format_profile_message
from db.database import get_user_stats

logger = logging.getLogger(__name__)

FRONTEND_URL = "https://techinterviewai.com"


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

    # Build context-aware manage button
    plan_name = stats.get("plan_name", "Free")
    payment_type = stats.get("payment_type")
    buttons = []

    if payment_type == "card":
        buttons.append(
            InlineKeyboardButton(
                "💳 Manage Subscription",
                url=f"{FRONTEND_URL}/dashboard/profile",
            )
        )
    elif payment_type == "stars":
        buttons.append(
            InlineKeyboardButton(
                "⭐ Renew Stars",
                callback_data="stars_pro",
            )
        )
    else:
        buttons.append(
            InlineKeyboardButton(
                "🚀 Upgrade Plan",
                url=f"{FRONTEND_URL}/tariffs",
            )
        )

    reply_markup = InlineKeyboardMarkup([buttons])

    await update.message.reply_text(
        format_profile_message(stats),
        parse_mode="Markdown",
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )
