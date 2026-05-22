"""Handler for the /plan command — show pricing and subscription buttons."""
import json
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from db.database import get_tariff_plans

logger = logging.getLogger(__name__)

FRONTEND_URL = "https://techinterviewai.com"


def _parse_features(features_raw: str | None) -> list[str]:
    """Parse features JSON or comma-separated string."""
    if not features_raw:
        return []
    try:
        parsed = json.loads(features_raw)
        if isinstance(parsed, list):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return [f.strip() for f in features_raw.split(",") if f.strip()]


async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show pricing plans with subscription buttons."""
    user = update.effective_user
    if user is None:
        return

    plans = await get_tariff_plans()
    if not plans:
        await update.message.reply_text("❌ Plans not available. Please try again later.")
        return

    parts = ["💰 *AI Interview Trainer — Plans*\n"]

    for p in plans:
        name = p["name"]
        price = p["price"]
        limit = p["max_per_month"]
        star_price = p.get("star_price", 0)
        features = _parse_features(p["features"])

        if price == 0:
            price_str = "Free"
            limit_str = f"{limit}/month" if limit < 999999 else "♾️ Unlimited"
        elif limit >= 999999:
            price_str = f"${price:.2f}/month"
            limit_str = "♾️ Unlimited"
        else:
            price_str = f"${price:.2f}/month"
            limit_str = f"{limit}/month"

        # Emoji per plan
        emoji_map = {"Free": "🆓", "Pro": "⭐", "Premium": "💎", "Enterprise": "💎"}
        emoji = emoji_map.get(name, "📋")

        parts.append(f"{emoji} *{name}* — {price_str}")
        parts.append(f"   {limit_str}")
        if star_price:
            parts.append(f"   ⭐ {star_price} Stars/month")

        if features:
            for feat in features:
                parts.append(f"   ✅ {feat}")
        parts.append("")

    parts.append("👇 Select a plan to subscribe:")

    # Build subscription buttons
    buttons = []
    for p in plans:
        if p["price"] > 0 and p["stripe_price_id"]:
            name = p["name"]
            emoji_map = {"Pro": "⭐", "Premium": "💎", "Enterprise": "💎"}
            btn_emoji = emoji_map.get(name, "💳")
            url = f"{FRONTEND_URL}/tariffs"
            buttons.append(
                InlineKeyboardButton(
                    f"{btn_emoji} Subscribe {name} — ${p['price']:.2f}/month",
                    url=url,
                )
            )
        # Stars button for paid plans
        star_price = p.get("star_price", 0)
        if star_price:
            name = p["name"].lower()
            buttons.append(
                InlineKeyboardButton(
                    f"⭐ Buy {p['name']} with Stars — {star_price}⭐",
                    callback_data=f"stars_{name}",
                )
            )

    buttons.append(
        InlineKeyboardButton("❓ Need help?", url=f"{FRONTEND_URL}/about")
    )

    reply_markup = InlineKeyboardMarkup([[b] for b in buttons])

    await update.message.reply_text(
        "\n".join(parts),
        parse_mode="Markdown",
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )
