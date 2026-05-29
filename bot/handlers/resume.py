"""Resume upload and analysis ConversationHandler."""
import logging
import os
import tempfile

import fitz  # PyMuPDF
from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from ai import resume_analyzer
from ai import interviewer as ai
from bot.keyboards import _resume_level_keyboard, _resume_role_keyboard, resume_confirm_keyboard
from bot.states import InterviewState, ResumeState
from db.database import check_subscription_limit, create_session, get_or_create_user

logger = logging.getLogger(__name__)

WAITING_PDF = ResumeState.WAITING_PDF
CONFIRMING = ResumeState.CONFIRMING
IN_INTERVIEW = InterviewState.IN_INTERVIEW


def _analysis_text(role: str, level: str, analysis: dict) -> str:
    """Format resume analysis summary for display."""
    tech = ", ".join(analysis.get("tech_stack", [])[:6]) or "—"
    years = analysis.get("years_experience")
    years_text = f"{years} year{'s' if years != 1 else ''}" if years else "—"
    confidence = analysis.get("confidence", 0.0)
    emoji = config.ROLE_EMOJIS.get(role, "")
    level_emoji = config.LEVEL_EMOJIS.get(level, "")
    return (
        f"📋 *Resume Analysis*\n\n"
        f"Position: {emoji} *{role}*\n"
        f"Level: {level_emoji} *{level}*\n"
        f"Stack: {tech}\n"
        f"Experience: {years_text}\n"
        f"Confidence: {int(confidence * 100)}%\n\n"
        "Would you like to start an interview tailored to this profile?"
    )


def _question_text(question: dict, number: int, total: int) -> str:
    """Format a question for display."""
    category = question.get("category", "Technical")
    difficulty = question.get("difficulty", "Medium")
    return (
        f"📝 *Question {number}/{total}*  [{category}]  •  {difficulty}\n\n"
        f"{question['question']}"
    )


async def resume_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for /resume command and Upload Resume button callback."""
    user = update.effective_user
    if user is None:
        return ConversationHandler.END

    db_user = await get_or_create_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )

    if not await check_subscription_limit(user.id):
        msg = (
            f"⚠️ You've reached the monthly limit of "
            f"*{config.MAX_FREE_INTERVIEWS_PER_MONTH} interviews*.\n\n"
            "Upgrade your plan with /plan to get unlimited access! 🚀"
        )
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text(msg, parse_mode="Markdown")
        return ConversationHandler.END

    context.user_data.clear()
    context.user_data["db_user_id"] = db_user.id

    text = "📄 Send me your resume as a PDF file."
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text)
    else:
        await update.message.reply_text(text)

    return WAITING_PDF


async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Download PDF, extract text, call analyze_resume, and show results."""
    doc_obj = update.message.document
    if not doc_obj or doc_obj.mime_type != "application/pdf":
        await update.message.reply_text(
            "⚠️ Please send a PDF file. Other formats are not supported."
        )
        return WAITING_PDF

    thinking = await update.message.reply_text("⏳ Analyzing your resume…")

    tmp_path = os.path.join(
        tempfile.gettempdir(), f"resume_{update.effective_user.id}.pdf"
    )
    try:
        tg_file = await doc_obj.get_file()
        await tg_file.download_to_drive(tmp_path)

        pdf_doc = fitz.open(tmp_path)
        text = "\n".join(page.get_text() for page in pdf_doc)
        pdf_doc.close()
        text = text[:10_000]

        if not text.strip():
            await thinking.edit_text(
                "❌ Could not extract text from this PDF. "
                "Please make sure the PDF is not scanned/image-only."
            )
            return WAITING_PDF

        analysis = await resume_analyzer.analyze_resume(text)
        context.user_data["resume_analysis"] = analysis

        role = analysis.get("suggested_role") or config.ROLES[0]
        level = analysis.get("suggested_level") or config.EXPERIENCE_LEVELS[0]
        context.user_data["role"] = role
        context.user_data["level"] = level

        try:
            await thinking.delete()
        except Exception:
            pass

        await update.message.reply_text(
            _analysis_text(role, level, analysis),
            parse_mode="Markdown",
            reply_markup=resume_confirm_keyboard(),
        )
        return CONFIRMING

    except Exception as exc:
        logger.error("handle_pdf failed: %s", exc)
        try:
            await thinking.edit_text("❌ Failed to process the PDF. Please try again.")
        except Exception:
            pass
        return WAITING_PDF
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


async def confirm_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User confirmed role/level — create DB session and generate first question."""
    query = update.callback_query
    await query.answer()

    role: str = context.user_data.get("role", config.ROLES[0])
    level: str = context.user_data.get("level", config.EXPERIENCE_LEVELS[0])
    db_user_id: int = context.user_data["db_user_id"]

    role_emoji = config.ROLE_EMOJIS.get(role, "")
    level_emoji = config.LEVEL_EMOJIS.get(level, "")

    await query.edit_message_text(
        f"🚀 *Interview Starting!*\n\n"
        f"Role: {role_emoji} *{role}*\n"
        f"Level: {level_emoji} *{level}*\n"
        f"Questions: *{config.QUESTIONS_PER_SESSION}*\n\n"
        "Generating your first question…",
        parse_mode="Markdown",
    )

    session_id = await create_session(db_user_id, role, level)
    context.user_data["session_id"] = session_id
    context.user_data["question_number"] = 0
    context.user_data["previous_questions"] = []

    question = await ai.generate_question(role, level, 1, [])
    context.user_data["current_question"] = question
    context.user_data["question_number"] = 1
    context.user_data["previous_questions"] = [question["question"]]

    await query.message.reply_text(
        _question_text(question, 1, config.QUESTIONS_PER_SESSION),
        parse_mode="Markdown",
    )
    return IN_INTERVIEW


async def edit_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show role selection keyboard for editing the suggested role."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Select your role:",
        reply_markup=_resume_role_keyboard(),
    )
    return CONFIRMING


async def select_edit_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the user-selected role and show level selection."""
    query = update.callback_query
    await query.answer()

    role = query.data.removeprefix("resume_role_") if query.data else ""
    if role not in config.ROLES:
        await query.edit_message_text("Invalid role — please pick again.", reply_markup=_resume_role_keyboard())
        return CONFIRMING

    context.user_data["role"] = role
    emoji = config.ROLE_EMOJIS.get(role, "")
    await query.edit_message_text(
        f"Role: {emoji} *{role}*\n\nNow select your experience level:",
        parse_mode="Markdown",
        reply_markup=_resume_level_keyboard(),
    )
    return CONFIRMING


async def select_edit_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the user-selected level and show updated analysis summary."""
    query = update.callback_query
    await query.answer()

    level = query.data.removeprefix("resume_level_") if query.data else ""
    if level not in config.EXPERIENCE_LEVELS:
        await query.edit_message_text("Invalid level — please pick again.", reply_markup=_resume_level_keyboard())
        return CONFIRMING

    context.user_data["level"] = level
    role: str = context.user_data.get("role", config.ROLES[0])
    analysis: dict = context.user_data.get("resume_analysis", {})

    await query.edit_message_text(
        _analysis_text(role, level, analysis),
        parse_mode="Markdown",
        reply_markup=resume_confirm_keyboard(),
    )
    return CONFIRMING


async def cancel_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the resume flow via inline button."""
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("❌ Resume upload cancelled. Use /resume to try again.")
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the resume flow via /cancel command."""
    context.user_data.clear()
    await update.message.reply_text("❌ Resume upload cancelled. Use /resume to try again.")
    return ConversationHandler.END


def build_resume_handler() -> ConversationHandler:
    """Return a fully configured ConversationHandler for the resume upload flow."""
    from bot.handlers.interview import handle_answer

    return ConversationHandler(
        entry_points=[
            CommandHandler("resume", resume_start),
            CallbackQueryHandler(resume_start, pattern=r"^upload_resume$"),
        ],
        states={
            WAITING_PDF: [
                MessageHandler(filters.Document.ALL, handle_pdf),
            ],
            CONFIRMING: [
                CallbackQueryHandler(confirm_resume, pattern=r"^resume_start$"),
                CallbackQueryHandler(edit_role, pattern=r"^resume_edit$"),
                CallbackQueryHandler(select_edit_role, pattern=r"^resume_role_"),
                CallbackQueryHandler(select_edit_level, pattern=r"^resume_level_"),
                CallbackQueryHandler(cancel_resume, pattern=r"^resume_cancel$"),
            ],
            IN_INTERVIEW: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_answer),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
        ],
        conversation_timeout=config.SESSION_TIMEOUT_MINUTES * 60,
        allow_reentry=True,
    )
