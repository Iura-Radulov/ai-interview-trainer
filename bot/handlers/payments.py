"""Handler for Telegram Stars payments — invoice, pre_checkout, successful_payment."""
import json
import logging

from telegram import LabeledPrice, Update
from telegram.ext import ContextTypes

from db.database import activate_subscription, get_tariff_plans

logger = logging.getLogger(__name__)

# Map payload strings to tariff_plan_id
PLAN_PAYLOADS = {
    "pro_1month": 2,
    "premium_1month": 3,
}


async def send_stars_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a Telegram Stars invoice for the selected plan."""
    user = update.effective_user
    if not user:
        return

    # Determine the message target (command vs callback)
    msg = update.message or (update.callback_query and update.callback_query.message)
    if not msg:
        return

    # Get plan key from args
    plan_key = None
    if context.args:
        plan_key = context.args[0].lower()
    elif update.callback_query and update.callback_query.data:
        plan_key = update.callback_query.data.removeprefix("stars_")

    if plan_key not in ("pro", "premium"):
        await msg.reply_text("Available plans: pro, premium")
        return

    plans = await get_tariff_plans()
    plan = next((p for p in plans if p["name"].lower() == plan_key), None)
    if not plan or not plan.get("star_price"):
        await msg.reply_text("This plan is not available for Stars payment.")
        return

    star_price = plan["star_price"]
    plan_name = plan["name"]
    payload = f"{plan_key}_1month"

    title = f"AI Interview {plan_name}"
    description = (
        f"{plan_name} plan — {star_price} Stars\n"
        f"30 days of unlimited interviews.\n"
        f"Renew manually before expiry."
    )

    try:
        await msg.reply_invoice(
            title=title,
            description=description,
            payload=payload,
            provider_token="",  # required for XTR
            currency="XTR",
            prices=[LabeledPrice(plan_name, star_price)],
            start_parameter="pay",
        )
    except Exception as exc:
        logger.error("Failed to send Stars invoice: %s", exc)
        await msg.reply_text("❌ Failed to create invoice. Please try again later.")


async def stars_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Buy with Stars' button callback — send invoice."""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()

    plan_key = query.data.removeprefix("stars_")
    if plan_key not in ("pro", "premium"):
        await query.edit_message_text("Unknown plan.")
        return

    context.args = [plan_key]
    await send_stars_invoice(update, context)


async def pre_checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirm the pre-checkout query — always ok for Stars payments."""
    query = update.pre_checkout_query
    if not query:
        return
    payload = query.invoice_payload
    if payload not in PLAN_PAYLOADS:
        await query.answer(ok=False, error_message="Invalid plan. Please try again.")
        return
    await query.answer(ok=True)


async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Activate subscription after successful Stars payment."""
    user = update.effective_user
    if not user:
        return

    payment = update.message.successful_payment
    if not payment:
        return

    payload = payment.invoice_payload
    tariff_plan_id = PLAN_PAYLOADS.get(payload)

    if not tariff_plan_id:
        await update.message.reply_text("❌ Payment received but plan not recognized. Contact support.")
        return

    await activate_subscription(
        telegram_id=user.id,
        tariff_plan_id=tariff_plan_id,
        payment_type="stars",
    )

    plan_names = {2: "Pro", 3: "Premium"}
    plan_name = plan_names.get(tariff_plan_id, "Unknown")

    await update.message.reply_text(
        f"✅ *{plan_name} activated\\!*\n\n"
        f"Your subscription is active for 30 days\\.\n"
        f"Use /interview to start practising\\!\n"
        f"Check your plan with /profile\\.",
        parse_mode="MarkdownV2",
    )
