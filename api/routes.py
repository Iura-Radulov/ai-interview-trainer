"""All API route handlers for the Mini App backend."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

import config
from ai.interviewer import evaluate_answer, generate_question, generate_summary
from api.auth import validate_init_data
from db.database import (
    async_session,
    check_subscription_limit,
    complete_session,
    create_session,
    get_or_create_user,
    get_session_answers,
    get_user_stats,
)
from db.models import Session, User

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Pydantic request models ───────────────────────────────────────────────────


class AuthRequest(BaseModel):
    init_data: str


class StartInterviewRequest(BaseModel):
    role: str
    level: str


class AnswerRequest(BaseModel):
    session_id: int
    question_text: str  # The question that was asked — needed for stateless evaluation
    answer: str


# ── Auth dependency ───────────────────────────────────────────────────────────


async def get_current_user(
    x_telegram_init_data: Optional[str] = Header(None),
    x_user_id: Optional[int] = Header(None),
) -> dict:
    """Validate X-Telegram-Init-Data header and ensure user exists in DB.

    Falls back to X-User-ID header (from landing site auth) if no init data.
    Falls back to a guest user if neither is provided (MVP mode).
    """
    if x_telegram_init_data:
        user_data = validate_init_data(x_telegram_init_data)
        if user_data:
            telegram_id = user_data.get("id")
            if telegram_id:
                try:
                    await get_or_create_user(
                        telegram_id=telegram_id,
                        username=user_data.get("username"),
                        first_name=user_data.get("first_name"),
                    )
                except Exception as exc:
                    logger.error("get_or_create_user failed: %s", exc)
                return user_data

    # Fallback: X-User-ID from landing auth
    if x_user_id and x_user_id > 0:
        return {"id": x_user_id, "username": None, "first_name": "Web User"}

    return {"id": 0, "username": None, "first_name": "Guest"}


# ── Helper ────────────────────────────────────────────────────────────────────


async def _get_db_user_id(telegram_id: int) -> int:
    """Return the internal DB user.id for a given Telegram user ID."""
    async with async_session() as sess:
        result = await sess.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        db_user = result.scalar_one_or_none()
    if db_user is None:
        # Auto-create guest user or new Telegram user
        from db.database import get_or_create_user as _create_user
        db_user = await _create_user(
            telegram_id=telegram_id,
            username=f"user_{telegram_id}",
            first_name="Guest" if telegram_id == 0 else None,
        )
    return db_user.id


async def _get_owned_session(session_id: int, db_user_id: int) -> Session:
    """Fetch a session and verify it belongs to the given user."""
    async with async_session() as sess:
        result = await sess.execute(
            select(Session).where(Session.id == session_id)
        )
        session = result.scalar_one_or_none()

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != db_user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    return session


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/roles")
async def get_roles() -> dict:
    """Return available roles and experience levels."""
    return {
        "roles": config.ROLES,
        "levels": config.EXPERIENCE_LEVELS,
    }


@router.post("/auth")
async def auth(request: AuthRequest) -> dict:
    """Validate Telegram init data and create user in DB if not exists."""
    user_data = validate_init_data(request.init_data)
    if not user_data:
        return {"ok": False, "error": "Invalid authentication"}

    telegram_id = user_data.get("id")
    if not telegram_id:
        return {"ok": False, "error": "Invalid authentication"}

    try:
        await get_or_create_user(
            telegram_id=telegram_id,
            username=user_data.get("username"),
            first_name=user_data.get("first_name"),
        )
        return {
            "ok": True,
            "user": {
                "id": telegram_id,
                "username": user_data.get("username"),
                "first_name": user_data.get("first_name"),
            },
        }
    except Exception as exc:
        logger.error("auth endpoint error: %s", exc)
        return {"ok": False, "error": "Database error"}


@router.post("/interview/start")
async def start_interview(
    request: StartInterviewRequest,
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Start a new interview session and return the first question."""
    try:
        telegram_id = user_data["id"]
        db_user_id = await _get_db_user_id(telegram_id)

        # Check subscription / daily limit
        can_proceed = await check_subscription_limit(telegram_id)
        if not can_proceed:
            raise HTTPException(
                status_code=429,
                detail="Monthly interview limit reached. Upgrade to Pro for unlimited access.",
            )

        session_id = await create_session(db_user_id, request.role, request.level)

        question = await generate_question(
            role=request.role,
            level=request.level,
            question_number=1,
            previous_questions=[],
        )

        return {
            "session_id": session_id,
            "question": question,
            "question_number": 1,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("start_interview error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to start interview")


@router.post("/interview/answer")
async def submit_answer(
    request: AnswerRequest,
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Evaluate an answer, save it, then return the next question or final summary."""
    try:
        telegram_id = user_data["id"]
        db_user_id = await _get_db_user_id(telegram_id)
        session = await _get_owned_session(request.session_id, db_user_id)

        if session.completed:
            raise HTTPException(status_code=400, detail="Session already completed")

        existing_answers = await get_session_answers(request.session_id)
        question_number = len(existing_answers) + 1

        evaluation = await evaluate_answer(
            role=session.role,
            level=session.experience_level,
            question=request.question_text,
            answer=request.answer,
        )

        # Persist the evaluated answer
        from db.database import save_answer  # local import avoids any circular issues
        await save_answer(
            session_id=request.session_id,
            question_number=question_number,
            question_text=request.question_text,
            user_answer=request.answer,
            score=evaluation["score"],
            feedback=evaluation["feedback"],
            strengths=evaluation["strengths"],
            improvements=evaluation["improvements"],
            tip=evaluation["tip"],
            category="Technical",
        )

        if question_number < config.QUESTIONS_PER_SESSION:
            all_answers = await get_session_answers(request.session_id)
            previous_questions = [a["question_text"] for a in all_answers]

            next_question = await generate_question(
                role=session.role,
                level=session.experience_level,
                question_number=question_number + 1,
                previous_questions=previous_questions,
            )

            return {
                "done": False,
                "evaluation": evaluation,
                "next_question": next_question,
                "question_number": question_number + 1,
            }
        else:
            all_answers = await get_session_answers(request.session_id)
            avg_score = sum(a["score"] for a in all_answers) / len(all_answers)

            await complete_session(request.session_id, avg_score)

            summary = await generate_summary(
                role=session.role,
                level=session.experience_level,
                answers=all_answers,
                avg_score=avg_score,
            )

            return {
                "done": True,
                "evaluation": evaluation,
                "summary": summary,
            }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("submit_answer error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to process answer")


@router.get("/interview/{session_id}")
async def get_session_detail(
    session_id: int,
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Return full session details with answers and summary (if completed)."""
    try:
        telegram_id = user_data["id"]
        db_user_id = await _get_db_user_id(telegram_id)
        session = await _get_owned_session(session_id, db_user_id)

        answers = await get_session_answers(session_id)

        session_dict = {
            "id": session.id,
            "role": session.role,
            "experience_level": session.experience_level,
            "started_at": session.started_at.isoformat(),
            "completed": session.completed,
            "total_score": session.total_score,
            "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        }

        summary = None
        if session.completed and answers:
            avg_score = sum(a["score"] for a in answers) / len(answers)
            summary = await generate_summary(
                role=session.role,
                level=session.experience_level,
                answers=answers,
                avg_score=avg_score,
            )

        return {
            "session": session_dict,
            "answers": answers,
            "summary": summary,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_session_detail error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to get session")


@router.get("/interview/{session_id}/next-question")
async def get_next_question(
    session_id: int,
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Return the next question for an incomplete session."""
    try:
        telegram_id = user_data["id"]
        db_user_id = await _get_db_user_id(telegram_id)

        # Check subscription limit before resuming
        if not await check_subscription_limit(telegram_id):
            raise HTTPException(
                status_code=429,
                detail="Monthly interview limit reached. Upgrade to Pro for unlimited access.",
            )

        session = await _get_owned_session(session_id, db_user_id)

        if session.completed:
            raise HTTPException(status_code=400, detail="Session already completed")

        existing_answers = await get_session_answers(session_id)
        next_num = len(existing_answers) + 1

        question = await generate_question(
            role=session.role,
            level=session.experience_level,
            question_number=next_num,
            previous_questions=[a["question_text"] for a in existing_answers],
        )

        return {
            "question": question,
            "question_number": next_num,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_next_question error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to generate next question")


@router.get("/profile")
async def get_profile(user_data: dict = Depends(get_current_user)) -> dict:
    """Return the authenticated user's interview statistics."""
    try:
        telegram_id = user_data["id"]
        stats = await get_user_stats(telegram_id)

        if not stats:
            return {
                "total_sessions": 0,
                "avg_score": 0.0,
                "recent_sessions": [],
            }

        return {
            "total_sessions": stats["total_sessions"],
            "avg_score": round(stats["avg_score"], 1),
            "recent_sessions": stats["recent_sessions"],
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_profile error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to get profile")
