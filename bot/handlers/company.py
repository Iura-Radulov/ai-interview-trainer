"""ConversationHandler for company-based interviews."""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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
from bot.states import CompanyState
from db.database import (
    check_subscription_limit,
    complete_session,
    count_month_sessions,
    create_session,
    create_user_company,
    delete_user_company,
    get_or_create_user,
    get_session_answers,
    get_user_companies,
    get_user_plan_name,
    save_answer,
)

logger = logging.getLogger(__name__)

# ── states ──────────────────────────────────────────────────────────────────
SHOWING = CompanyState.SHOWING_COMPANIES
ADD_NAME = CompanyState.ADDING_NAME
ADD_URL = CompanyState.ADDING_URL
ADD_POS = CompanyState.ADDING_POSITION
SEL_ROLE = CompanyState.SELECTING_ROLE
SEL_LEVEL = CompanyState.SELECTING_LEVEL
IN_INTERVIEW = CompanyState.IN_INTERVIEW


# ── helpers ─────────────────────────────────────────────────────────────────


def _companies_keyboard(companies: list[dict]) -> InlineKeyboardMarkup:
    """Build an inline keyboard listing user companies + action buttons."""
    buttons = []
    for c in companies:
        name = c["company_name"]
        if c.get("position"):
            name += f" ({c['position']})"
        buttons.append([
            InlineKeyboardButton(f"🏢 {name}", callback_data=f"ci_select_{c['id']}"),
        ])
    buttons.append([InlineKeyboardButton("➕ Add Company", callback_data="ci_add")])
    if companies:
        buttons.append([InlineKeyboardButton("❌ Delete a Company", callback_data="ci_delete")])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="ci_cancel")])
    return InlineKeyboardMarkup(buttons)


def _company_list_for_delete(companies: list[dict]) -> InlineKeyboardMarkup:
    """Build a keyboard for selecting which company to delete."""
    buttons = []
    for c in companies:
        name = c["company_name"]
        if c.get("position"):
            name += f" ({c['position']})"
        buttons.append([
            InlineKeyboardButton(f"🗑 {name}", callback_data=f"ci_del_{c['id']}"),
        ])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="ci_back_to_list")])
    return InlineKeyboardMarkup(buttons)


def _roles_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(f"{config.ROLE_EMOJIS.get(r, '')} {r}", callback_data=f"ci_role_{r}")
        for r in config.ROLES
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


def _levels_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(f"{config.LEVEL_EMOJIS.get(lvl, '')} {lvl}", callback_data=f"ci_level_{lvl}")
        for lvl in config.EXPERIENCE_LEVELS
    ]
    return InlineKeyboardMarkup([buttons])


def _question_text(question: dict, number: int, total: int) -> str:
    category = question.get("category", "Technical")
    difficulty = question.get("difficulty", "Medium")
    return (
        f"📝 *Question {number}/{total}*  [{category}]  •  {difficulty}\n\n"
        f"{question['question']}"
    )


# ── entry ───────────────────────────────────────────────────────────────────


async def company_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point: check premium, show company list or upgrade prompt."""
    user = update.effective_user
    if user is None:
        return ConversationHandler.END

    db_user = await get_or_create_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )
    context.user_data.clear()
    context.user_data["db_user_id"] = db_user.id

    # Check premium
    plan = await get_user_plan_name(user.id)
    if plan != "Premium":
        text = (
            "⭐ *Company Interview Prep* is a *Premium* feature.\n\n"
            "Upgrade to Premium to:\n"
            "• Add any company and vacancy URL\n"
            "• Get AI questions tailored to that specific role\n"
            "• Practice with company culture context\n\n"
            "Use /plan to see available plans."
        )
        if update.message:
            await update.message.reply_text(text, parse_mode="Markdown")
        elif update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(text, parse_mode="Markdown")
        return ConversationHandler.END

    # Check subscription limit
    if not await check_subscription_limit(user.id):
        await update.message.reply_text(
            "⚠️ You've reached your monthly interview limit.\n"
            "Upgrade your plan with /plan to get unlimited access!",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    month_count = await count_month_sessions(db_user.id)
    remaining = max(0, config.MAX_FREE_INTERVIEWS_PER_MONTH - month_count)

    companies = await get_user_companies(user.id)
    context.user_data["companies"] = companies

    text = (
        f"🏢 *Company Link Interview*\n\n"
        f"Select a company to start an interview tailored to that role.\n"
        f"Interviews this month: {month_count} ({remaining} remaining)."
    )

    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=_companies_keyboard(companies))
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=_companies_keyboard(companies))

    return SHOWING


# ── state: SHOWING_COMPANIES ────────────────────────────────────────────────


async def handle_company_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle company selection, add, delete, or back from company list."""
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    if data == "ci_add":
        await query.edit_message_text(
            "📝 Enter the *company name* (e.g. Stripe, Uber, Spotify):",
            parse_mode="Markdown",
        )
        return ADD_NAME

    if data == "ci_delete":
        companies: list[dict] = context.user_data.get("companies", [])
        if not companies:
            await query.edit_message_text(
                "No companies to delete.",
                reply_markup=_companies_keyboard(companies),
            )
            return SHOWING
        await query.edit_message_text(
            "Select a company to delete:",
            reply_markup=_company_list_for_delete(companies),
        )
        return SHOWING

    if data == "ci_back_to_list":
        companies: list[dict] = context.user_data.get("companies", [])
        await query.edit_message_text(
            "🏢 *Company Link Interview*\n\nSelect a company:",
            parse_mode="Markdown",
            reply_markup=_companies_keyboard(companies),
        )
        return SHOWING

    if data == "ci_cancel":
        await query.edit_message_text("❌ Cancelled. Use /company to try again.")
        context.user_data.clear()
        return ConversationHandler.END

    if data.startswith("ci_del_"):
        company_id = int(data.removeprefix("ci_del_"))
        user = update.effective_user
        if user:
            await delete_user_company(company_id, user.id)
            companies = await get_user_companies(user.id)
            context.user_data["companies"] = companies
            await query.edit_message_text(
                "✅ Company deleted.",
                reply_markup=_companies_keyboard(companies),
            )
        return SHOWING

    if data.startswith("ci_select_"):
        company_id = int(data.removeprefix("ci_select_"))
        companies: list[dict] = context.user_data.get("companies", [])
        selected = next((c for c in companies if c["id"] == company_id), None)
        if not selected:
            await query.edit_message_text("Company not found. Please try again.")
            return SHOWING

        context.user_data["selected_company"] = selected

        text = (
            f"🏢 *{selected['company_name']}*"
        )
        if selected.get("position"):
            text += f"\n📋 Position: {selected['position']}"
        if selected.get("vacancy_url"):
            text += f"\n🔗 {selected['vacancy_url']}"

        text += "\n\nNow select your role:"
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=_roles_keyboard())
        return SEL_ROLE

    return SHOWING


# ── state: ADDING_NAME ──────────────────────────────────────────────────────


async def handle_add_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive company name, ask for vacancy URL."""
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Please enter a company name.")
        return ADD_NAME

    context.user_data["new_company_name"] = name
    await update.message.reply_text(
        "🔗 Now enter the *vacancy URL* (optional, send /skip to skip):",
        parse_mode="Markdown",
    )
    return ADD_URL


# ── state: ADDING_URL ──────────────────────────────────────────────────────


async def handle_add_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive vacancy URL, ask for position."""
    text = update.message.text.strip()
    if text.lower() == "/skip":
        context.user_data["new_company_url"] = ""
    else:
        context.user_data["new_company_url"] = text

    await update.message.reply_text(
        "📋 Enter the *target position* (optional, send /skip to skip):\n"
        "e.g. *Senior Frontend Engineer*",
        parse_mode="Markdown",
    )
    return ADD_POS


# ── state: ADDING_POSITION ─────────────────────────────────────────────────


async def handle_add_position(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive position, create company, AI analyze, show result."""
    text = update.message.text.strip()
    if text.lower() == "/skip":
        context.user_data["new_company_position"] = ""
    else:
        context.user_data["new_company_position"] = text

    user = update.effective_user
    if user is None:
        return ConversationHandler.END

    name = context.user_data["new_company_name"]
    url = context.user_data.get("new_company_url", "")
    position = context.user_data.get("new_company_position", "")

    thinking = await update.message.reply_text("⏳ Adding company...")

    try:
        company = await create_user_company(
            telegram_id=user.id,
            company_name=name,
            vacancy_url=url,
            position=position,
        )

        # Refresh companies
        companies = await get_user_companies(user.id)
        context.user_data["companies"] = companies
        context.user_data["selected_company"] = company

        await thinking.delete()

        text = f"✅ *{name}* added successfully!"
        if position:
            text += f"\n📋 Position: {position}"
        if url:
            text += f"\n🔗 {url}"

        text += "\n\nNow select your role to start an interview:"
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=_roles_keyboard())
        return SEL_ROLE

    except Exception as exc:
        logger.error("Failed to create company: %s", exc)
        await thinking.edit_text("❌ Failed to add company. Please try again.")
        companies = context.user_data.get("companies", [])
        await update.message.reply_text(
            "🏢 Select a company:",
            reply_markup=_companies_keyboard(companies),
        )
        return SHOWING


# ── state: SELECTING_ROLE ──────────────────────────────────────────────────


async def handle_select_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store role and ask for experience level."""
    query = update.callback_query
    await query.answer()

    role = query.data.removeprefix("ci_role_") if query.data else ""
    if role not in config.ROLES:
        await query.edit_message_text(
            "Invalid role — please pick again.",
            reply_markup=_roles_keyboard(),
        )
        return SEL_ROLE

    context.user_data["ci_role"] = role
    emoji = config.ROLE_EMOJIS.get(role, "")
    await query.edit_message_text(
        f"🎯 Role: {emoji} *{role}*\n\nNow choose your experience level:",
        parse_mode="Markdown",
        reply_markup=_levels_keyboard(),
    )
    return SEL_LEVEL


# ── state: SELECTING_LEVEL ────────────────────────────────────────────────


async def handle_select_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Create session with company context and generate first question."""
    query = update.callback_query
    await query.answer()

    level = query.data.removeprefix("ci_level_") if query.data else ""
    if level not in config.EXPERIENCE_LEVELS:
        await query.edit_message_text(
            "Invalid level — please pick again.",
            reply_markup=_levels_keyboard(),
        )
        return SEL_LEVEL

    role: str = context.user_data["ci_role"]
    db_user_id: int = context.user_data["db_user_id"]
    company: dict = context.user_data.get("selected_company", {})
    company_name = company.get("company_name", "")
    company_context = company.get("ai_context", "")

    context.user_data["ci_level"] = level
    context.user_data["ci_question_number"] = 0
    context.user_data["ci_previous_questions"] = []

    session_id = await create_session(
        db_user_id, role, level,
        company_id=str(company.get("id", "")),
    )
    context.user_data["ci_session_id"] = session_id

    role_emoji = config.ROLE_EMOJIS.get(role, "")
    level_emoji = config.LEVEL_EMOJIS.get(level, "")

    await query.edit_message_text(
        f"🚀 *Interview Starting\!*\n\n"
        f"Company: 🏢 *{company_name}*\n"
        f"Role: {role_emoji} *{role}*\n"
        f"Level: {level_emoji} *{level}*\n"
        f"Questions: *{config.QUESTIONS_PER_SESSION}*\n\n"
        "Generating your first question…",
        parse_mode="MarkdownV2",
    )

    # Build company context prompt
    company_prompt_parts = []
    if company_name:
        company_prompt_parts.append(f"You are interviewing for *{company_name}*.")
    if company.get("position"):
        company_prompt_parts.append(f"Target position: {company['position']}.")
    if company.get("vacancy_url"):
        company_prompt_parts.append(f"Vacancy URL: {company['vacancy_url']}.")
    if company_context:
        company_prompt_parts.append(company_context)

    company_prompt = "\n".join(company_prompt_parts)

    question = await ai.generate_question(
        role, level, 1, [],
        company_context=company_prompt,
    )
    context.user_data["ci_current_question"] = question
    context.user_data["ci_question_number"] = 1
    context.user_data["ci_previous_questions"] = [question["question"]]

    await query.message.reply_text(
        _question_text(question, 1, config.QUESTIONS_PER_SESSION),
        parse_mode="Markdown",
    )
    context.user_data["ci_question_sent_at"] = __import__("time").time()
    return IN_INTERVIEW


# ── state: IN_INTERVIEW ────────────────────────────────────────────────────


async def handle_ci_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Evaluate answer, persist, ask next question or finish."""
    user_answer: str = update.message.text
    role: str = context.user_data.get("ci_role", "")
    level: str = context.user_data.get("ci_level", "")
    question: dict = context.user_data.get("ci_current_question", {})
    question_number: int = context.user_data.get("ci_question_number", 1)
    session_id: int = context.user_data.get("ci_session_id", 0)

    if not (role and level and question and session_id):
        await update.message.reply_text(
            "Session error — please start again with /company.",
        )
        return ConversationHandler.END

    sent_at = context.user_data.get("ci_question_sent_at")
    time_taken = int(__import__("time").time() - sent_at) if sent_at else None

    thinking = await update.message.reply_text("🤔 Evaluating your answer…")

    evaluation = await ai.evaluate_answer(
        role=role,
        level=level,
        question=question["question"],
        answer=user_answer,
        time_taken_seconds=time_taken,
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
        return await _finish_ci(update, context, session_id, role, level)

    previous_questions: list[str] = context.user_data.get("ci_previous_questions", [])
    next_num = question_number + 1
    next_q = await ai.generate_question(role, level, next_num, previous_questions)

    context.user_data["ci_current_question"] = next_q
    context.user_data["ci_question_number"] = next_num
    context.user_data["ci_previous_questions"] = previous_questions + [next_q["question"]]

    await update.message.reply_text(
        _question_text(next_q, next_num, config.QUESTIONS_PER_SESSION),
        parse_mode="Markdown",
    )
    context.user_data["ci_question_sent_at"] = __import__("time").time()
    return IN_INTERVIEW


async def _finish_ci(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session_id: int,
    role: str,
    level: str,
) -> int:
    """Compute score, generate summary, persist, end conversation."""
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


async def cancel_ci(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the company interview flow."""
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Cancelled. Use /company to start again.",
    )
    return ConversationHandler.END


# ── builder ────────────────────────────────────────────────────────────────


def build_company_handler() -> ConversationHandler:
    """Return a fully configured ConversationHandler for the company interview flow."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("company", company_start),
            CallbackQueryHandler(company_start, pattern=r"^company_start$"),
        ],
        states={
            SHOWING: [
                CallbackQueryHandler(handle_company_selection, pattern=r"^ci_"),
            ],
            ADD_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_name),
                CommandHandler("cancel", cancel_ci),
            ],
            ADD_URL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_url),
                CommandHandler("skip", handle_add_url),
                CommandHandler("cancel", cancel_ci),
            ],
            ADD_POS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_position),
                CommandHandler("skip", handle_add_position),
                CommandHandler("cancel", cancel_ci),
            ],
            SEL_ROLE: [
                CallbackQueryHandler(handle_select_role, pattern=r"^ci_role_"),
            ],
            SEL_LEVEL: [
                CallbackQueryHandler(handle_select_level, pattern=r"^ci_level_"),
            ],
            IN_INTERVIEW: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ci_answer),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_ci),
        ],
        conversation_timeout=config.SESSION_TIMEOUT_MINUTES * 60,
        allow_reentry=True,
    )
