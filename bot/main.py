"""Entry point for the AI Interview Trainer Telegram bot."""
import logging
import sys

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler

import config
from bot.handlers.feedback import build_feedback_handler
from bot.handlers.interview import build_interview_handler
from bot.handlers.profile import profile_command
from bot.handlers.start import help_command, set_role_callback, start_command
from db.database import init_db

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
)
logger = logging.getLogger(__name__)

# Sentinel used by the import-smoke-test: python -c "from bot.main import *; print(OK)"
OK = "OK"


async def _post_init(application: Application) -> None:
    """Run once after the Application is built — initialise the database."""
    await init_db()
    logger.info("AI Interview Trainer bot is ready.")


def create_application() -> Application:
    """Build and configure the Telegram Application with all handlers."""
    if not config.BOT_TOKEN:
        raise ValueError("BOT_TOKEN is not set. Check your .env file.")

    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(_post_init)
        .build()
    )

    # ── basic commands ────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("profile", profile_command))

    # ── /start role-selection callback ────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(set_role_callback, pattern=r"^set_role_"))

    # ── conversation handlers ─────────────────────────────────────────────────
    app.add_handler(build_interview_handler())
    app.add_handler(build_feedback_handler())

    return app


def main() -> None:
    """Validate config then start long-polling."""
    missing = [k for k in ("BOT_TOKEN", "OPENAI_API_KEY") if not getattr(config, k)]
    if missing:
        logger.error("Missing required environment variables: %s", ", ".join(missing))
        sys.exit(1)

    app = create_application()
    logger.info("Starting bot (polling)…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
