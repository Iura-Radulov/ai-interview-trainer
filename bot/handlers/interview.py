"""Full interview ConversationHandler: role → level → 5 questions → summary."""
import logging

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
from ai import interviewer as ai
from ai.scoring import format_evaluation_message, format_summary_message
from bot.keyboards import level_keyboard, role_keyboard
from bot.states import InterviewState
from db.database import (
    check_subscription_limit,
    complete_session,
    count_month_sessions,
    create_session,
    get_or_create_user,
    get_session_answers,
    save_answer,
)

logger = logging.getLogger(__name__)

SELECTING_ROLE = InterviewState.SELECTING_ROLE
SELECTING_LEVEL = InterviewState.SELECTING_LEVEL
IN_INTERVIEW = InterviewState.IN_INTERVIEW


# ── entry point ───────────────────────────────────────────────────────────────

async def start_interview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Begin the interview flow: register user and enforce monthly rate limit."""
    user = update.effective_user
    if user is None:
        return ConversationHandler.END

    db_user = await get_or_create_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )

    # Check monthly subscription limit
    if not await check_subscription_limit(user.id):
        await update.message.reply_text(
            f"⚠️ You've reached the monthly limit of "
            f"*{config.MAX_FREE_INTERVIEWS_PER_MONTH} interviews*\\.\n\n"
            "Upgrade your plan with /plan to get unlimited access\\! 🚀\n"
            "Review your progress with /profile\\.",
            parse_mode="MarkdownV2",
        )
        return ConversationHandler.END

    month_count = await count_month_sessions(db_user.id)
    remaining = max(0, config.MAX_FREE_INTERVIEWS_PER_MONTH - month_count)

    context.user_data.clear()
    context.user_data["db_user_id"] = db_user.id

    await update.message.reply_text(
        f"🎯 *Start New Interview*\n\n"
        f"Interviews this month: *{month_count}* "
        f"({remaining} remaining)\\.\n\n"
        "Select your role:",
        parse_mode="MarkdownV2",
        reply_markup=role_keyboard(),
    )
    return SELECTING_ROLE


# ── state: SELECTING_ROLE ─────────────────────────────────────────────────────

async def select_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the chosen role and ask for experience level."""
    query = update.callback_query
    await query.answer()

    role = query.data.removeprefix("role_") if query.data else ""
    if role not in config.ROLES:
        await query.edit_message_text(
            "Invalid role — please pick again\\.", parse_mode="MarkdownV2",
            reply_markup=role_keyboard(),
        )
        return SELECTING_ROLE

    context.user_data["role"] = role
    emoji = config.ROLE_EMOJIS.get(role, "")

    await query.edit_message_text(
        f"*Role:* {emoji} {role}\n\nNow choose your experience level:",
        parse_mode="Markdown",
        reply_markup=level_keyboard(),
    )
    return SELECTING_LEVEL


# ── state: SELECTING_LEVEL ────────────────────────────────────────────────────

async def select_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Create the DB session, generate question 1, and move into IN_INTERVIEW."""
    query = update.callback_query
    await query.answer()

    level = query.data.removeprefix("level_") if query.data else ""
    if level not in config.EXPERIENCE_LEVELS:
        await query.edit_message_text(
            "Invalid level — please pick again\\.", parse_mode="MarkdownV2",
            reply_markup=level_keyboard(),
        )
        return SELECTING_LEVEL

    role: str = context.user_data["role"]
    db_user_id: int = context.user_data["db_user_id"]

    context.user_data["level"] = level
    context.user_data["question_number"] = 0
    context.user_data["previous_questions"] = []

    session_id = await create_session(db_user_id, role, level)
    context.user_data["session_id"] = session_id

    role_emoji = config.ROLE_EMOJIS.get(role, "")
    level_emoji = config.LEVEL_EMOJIS.get(level, "")

    await query.edit_message_text(
        f"🚀 *Interview Starting\\!*\n\n"
        f"Role: {role_emoji} *{role}*\n"
        f"Level: {level_emoji} *{level}*\n"
        f"Questions: *{config.QUESTIONS_PER_SESSION}*\n\n"
        "Generating your first question…",
        parse_mode="MarkdownV2",
    )

    question = await ai.generate_question(role, level, 1, [])
    context.user_data["current_question"] = question
    context.user_data["question_number"] = 1
    context.user_data["previous_questions"] = [question["question"]]

    await query.message.reply_text(
        _question_text(question, 1, config.QUESTIONS_PER_SESSION),
        parse_mode="Markdown",
    )
    return IN_INTERVIEW


# ── state: IN_INTERVIEW ───────────────────────────────────────────────────────

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Evaluate the user's answer, persist it, then ask the next question or end."""
    user_answer: str = update.message.text
    role: str = context.user_data.get("role", "")
    level: str = context.user_data.get("level", "")
    question: dict = context.user_data.get("current_question", {})
    question_number: int = context.user_data.get("question_number", 1)
    session_id: int = context.user_data.get("session_id", 0)

    if not (role and level and question and session_id):
        await update.message.reply_text(
            "Session error — please start a new interview with /interview\\.",
            parse_mode="MarkdownV2",
        )
        return ConversationHandler.END

    thinking = await update.message.reply_text("🤔 Evaluating your answer…")

    evaluation = await ai.evaluate_answer(
        role=role,
        level=level,
        question=question["question"],
        answer=user_answer,
    )

    await save_answer(
        session_id=session_id,
        question_number=question_number,
        question_text=question["question"],
        user_answer=user_answer,
        score=evaluation["score"],
        feedback=evaluation["feedback"],
        strengths=evaluation["strengths"],
        improvements=evaluation["improvements"],
        tip=evaluation["tip"],
        category=question.get("category", "Technical"),
    )

    try:
        await thinking.delete()
    except Exception:
        pass

    await update.message.reply_text(
        format_evaluation_message(
            question_number=question_number,
            total_questions=config.QUESTIONS_PER_SESSION,
            score=evaluation["score"],
            feedback=evaluation["feedback"],
            strengths=evaluation["strengths"],
            improvements=evaluation["improvements"],
            tip=evaluation["tip"],
        ),
        parse_mode="Markdown",
    )

    if question_number >= config.QUESTIONS_PER_SESSION:
        return await _finish_interview(update, context, session_id, role, level)

    # Generate next question
    previous_questions: list[str] = context.user_data.get("previous_questions", [])
    next_num = question_number + 1
    next_q = await ai.generate_question(role, level, next_num, previous_questions)

    context.user_data["current_question"] = next_q
    context.user_data["question_number"] = next_num
    context.user_data["previous_questions"] = previous_questions + [next_q["question"]]

    await update.message.reply_text(
        _question_text(next_q, next_num, config.QUESTIONS_PER_SESSION),
        parse_mode="Markdown",
    )
    return IN_INTERVIEW


# ── helpers ───────────────────────────────────────────────────────────────────

def _question_text(question: dict, number: int, total: int) -> str:
    """Format a question for display."""
    category = question.get("category", "Technical")
    difficulty = question.get("difficulty", "Medium")
    return (
        f"📝 *Question {number}/{total}*  [{category}]  •  {difficulty}\n\n"
        f"{question['question']}"
    )


async def _finish_interview(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session_id: int,
    role: str,
    level: str,
) -> int:
    """Compute score, generate summary, persist completion, end conversation."""
    thinking = await update.message.reply_text("📊 Generating your session summary…")

    answers = await get_session_answers(session_id)
    avg_score = sum(a["score"] for a in answers) / len(answers) if answers else 0.0

    summary = await ai.generate_summary(role, level, answers, avg_score)
    await complete_session(session_id, avg_score)

    try:
        await thinking.delete()
    except Exception:
        pass

    await update.message.reply_text(
        format_summary_message(
            role=role,
            level=level,
            avg_score=avg_score,
            answers=answers,
            overall_assessment=summary["overall_assessment"],
            key_strengths=summary["key_strengths"],
            key_improvements=summary["key_improvements"],
            topics_to_study=summary["topics_to_study"],
            overall_rating=summary["overall_rating"],
        ),
        parse_mode="Markdown",
    )

    context.user_data.clear()
    return ConversationHandler.END


async def cancel_interview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel an in-progress interview."""
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Interview cancelled\\. Use /interview to start a new one\\.",
        parse_mode="MarkdownV2",
    )
    return ConversationHandler.END


# ── builder ───────────────────────────────────────────────────────────────────

def build_interview_handler() -> ConversationHandler:
    """Return a fully configured ConversationHandler for the interview flow."""
    return ConversationHandler(
        entry_points=[CommandHandler("interview", start_interview)],
        states={
            SELECTING_ROLE: [
                CallbackQueryHandler(select_role, pattern=r"^role_"),
            ],
            SELECTING_LEVEL: [
                CallbackQueryHandler(select_level, pattern=r"^level_"),
            ],
            IN_INTERVIEW: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_answer),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_interview),
        ],
        conversation_timeout=config.SESSION_TIMEOUT_MINUTES * 60,
        allow_reentry=True,
    )
