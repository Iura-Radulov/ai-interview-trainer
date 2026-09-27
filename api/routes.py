"""All API route handlers for the Mini App backend."""
import hashlib
import json
import logging
from datetime import datetime
from typing import Optional

import os
import tempfile

import fitz
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select, text

import config
from ai.interviewer import (
    evaluate_answer,
    evaluate_sd_step,
    generate_question,
    generate_sd_step,
    generate_sd_summary,
    generate_summary,
    _SD_STEP_NAMES,
)
from ai.resume_deep_analyzer import analyze_resume_deep
from api.auth import validate_init_data
from db.database import (
    async_session,
    check_subscription_limit,
    complete_session,
    create_session,
    get_or_create_user,
    get_session_answers,
    get_user_plan_name,
    get_user_stats,
)
from db.models import Session, User

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Helper: resolve model by plan ──────────────────────────────────────────────

def _resolve_model(plan_name: str) -> str:
    """Return 'gpt-5.4' for Premium users, otherwise the default model."""
    return config.OPENAI_MODEL_PREMIUM if plan_name == "Premium" else config.OPENAI_MODEL


# ── Pydantic request models ───────────────────────────────────────────────────


class GapAnalysisRequest(BaseModel):
    target_role: str
    target_level: str
    resume_id: Optional[int] = None  # If not provided, uses latest resume
    skills: Optional[str] = None
    company_id: Optional[str] = None
    user_company_id: Optional[int] = None
    language: str = "en"


class AuthRequest(BaseModel):
    init_data: str


class StartInterviewRequest(BaseModel):
    role: str
    level: str
    skills: Optional[str] = None
    company_id: Optional[str] = None
    user_company_id: Optional[int] = None
    mode: str = "technical"  # "technical" or "behavioral"
    resume_id: Optional[int] = None  # For CV-aware interviews


class AnswerRequest(BaseModel):
    session_id: int
    question_text: str  # The question that was asked — needed for stateless evaluation
    answer: str
    time_taken_seconds: Optional[int] = None
    resume_id: Optional[int] = None  # For CV-aware evaluation


class GeneratePlanRequest(BaseModel):
    """Request to generate a study plan based on past interviews."""
    mode: Optional[str] = None  # 'technical' | 'behavioral' | None = both
    date_from: Optional[str] = None  # ISO date string (inclusive)
    date_to: Optional[str] = None  # ISO date string (inclusive)
    duration_days: int = 7  # 3, 5, 7, 14, 30
    language: str = "en"


class UpdatePlanStatusRequest(BaseModel):
    status: str  # 'active' | 'paused' | 'completed'


class MarkDayRequest(BaseModel):
    day_id: int


# ── Auth dependency ───────────────────────────────────────────────────────────

SESSION_COOKIE = "session"


def _verify_session_cookie(token: str) -> Optional[int]:
    """Verify an HS256 session JWT issued by the landing; return its telegram_id.

    Written against the stdlib so the API needs no JWT dependency. Returns None
    for anything that is not a valid, unexpired token signed with JWT_SECRET.
    """
    try:
        import base64
        import hmac
        import json as _json
        import time as _time

        secret = config.JWT_SECRET
        if not secret:
            logger.error("JWT_SECRET is not set — cannot verify session cookies")
            return None

        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, payload_b64, sig_b64 = parts

        def _b64(s: str) -> bytes:
            return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

        expected = hmac.new(
            secret.encode(), f"{header_b64}.{payload_b64}".encode(), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected, _b64(sig_b64)):
            return None

        payload = _json.loads(_b64(payload_b64))
        exp = payload.get("exp")
        if exp is not None and int(exp) < int(_time.time()):
            return None

        telegram_id = payload.get("telegramId")
        return int(telegram_id) if telegram_id else None
    except Exception as exc:
        logger.warning("session cookie verification failed: %s", exc)
        return None


async def get_current_user(
    request: Request,
    x_telegram_init_data: Optional[str] = Header(None),
) -> dict:
    """Resolve the current user, or raise 401.

    Accepts, in order:
      1. Telegram initData (Mini App) — HMAC-verified with the bot token.
      2. The landing's signed session cookie — HMAC-verified with JWT_SECRET.

    There is deliberately NO guest fallback and NO trust in a caller-supplied id
    header: either the identity is cryptographically proven, or the request is
    rejected. A `Depends()` that never returns 401 is not authentication.
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

    token = request.cookies.get(SESSION_COOKIE)
    if token:
        telegram_id = _verify_session_cookie(token)
        if telegram_id:
            try:
                await get_or_create_user(
                    telegram_id=telegram_id, username=None, first_name=None
                )
            except Exception as exc:
                logger.error("get_or_create_user failed: %s", exc)
            return {"id": telegram_id, "username": None, "first_name": "Web User"}

    raise HTTPException(status_code=401, detail="Not authenticated")


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
async def get_roles(user_data: dict = Depends(get_current_user)) -> dict:
    """Return available interview roles and experience levels from DB."""
    from db.database import get_interview_roles

    telegram_id = user_data.get("id", 0)
    roles = await get_interview_roles(telegram_id if telegram_id > 0 else None)
    return {
        "roles": roles,
        "levels": config.EXPERIENCE_LEVELS,
    }


@router.get("/companies")
async def get_companies(user_data: dict = Depends(get_current_user)) -> dict:
    """Return available company sets filtered by subscription plan."""
    from db.database import get_companies as _get_companies

    telegram_id = user_data.get("id", 0)
    companies = await _get_companies(telegram_id if telegram_id > 0 else None)
    return {"companies": companies}


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


@router.post("/auth/create-token")
async def create_auth_token_endpoint(
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Generate a one-time auth token for seamless web login."""
    telegram_id = user_data.get("id")
    if not telegram_id or telegram_id == 0:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        from db.database import create_auth_token as _create_token
        token = await _create_token(telegram_id)
        return {"ok": True, "token": token}
    except Exception as exc:
        logger.error("create_auth_token error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create token")


# ── CV Gap Analysis ──────────────────────────────────────────────────────


@router.post("/interview/gap-analysis")
async def get_gap_analysis(
    request: GapAnalysisRequest,
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Analyze gap between user's CV/resume and target position before interview."""
    from ai.gap_analyzer import analyze_gap as _analyze_gap

    telegram_id = user_data.get("id", 0)
    if not telegram_id or telegram_id == 0:
        raise HTTPException(status_code=401, detail="Not authenticated")
    db_user_id = await _get_db_user_id(telegram_id)

    async with async_session() as sess:
        if request.resume_id:
            result = await sess.execute(
                text(
                    "SELECT id, user_id, role, experience_level, analysis_result FROM user_resumes "
                    "WHERE id = :rid AND user_id = :uid"
                ),
                {"rid": request.resume_id, "uid": db_user_id},
            )
        else:
            # Use the latest resume for this user
            result = await sess.execute(
                text(
                    "SELECT id, user_id, role, experience_level, analysis_result FROM user_resumes "
                    "WHERE user_id = :uid ORDER BY id DESC LIMIT 1"
                ),
                {"uid": db_user_id},
            )
        row = result.one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail="Resume not found. Upload your CV first.")

    role_from_db = row[2] or ""
    level_from_db = row[3] or ""
    analysis_raw = row[4] or "{}"

    # Parse analysis JSON (deep analysis: strengths, missing_keywords, etc.)
    try:
        import json as _json
        deep_analysis = _json.loads(analysis_raw) if isinstance(analysis_raw, str) else analysis_raw
    except Exception:
        deep_analysis = {}

    # Get company context if provided
    company_context = ""
    if request.company_id:
        from api.companies import get_company_context
        company_context = get_company_context(request.company_id)
    elif request.user_company_id:
        async with async_session() as sess:
            result = await sess.execute(
                text(
                    "SELECT ai_context FROM user_companies "
                    "WHERE id = :ucid AND user_id = (SELECT id FROM users WHERE telegram_id = :tid)"
                ),
                {"ucid": request.user_company_id, "tid": telegram_id},
            )
            row_ctx = result.one_or_none()
            if row_ctx:
                company_context = row_ctx[0] or ""

    plan_name = await get_user_plan_name(telegram_id)
    model = _resolve_model(plan_name)

    tech_stack_raw = deep_analysis.get("missing_keywords", [])
    strengths_raw = deep_analysis.get("strengths", [])

    gap = await _analyze_gap(
        target_role=request.target_role,
        target_level=request.target_level,
        cv_role=role_from_db,
        cv_level=level_from_db,
        tech_stack=tech_stack_raw,
        years_experience=None,
        key_skills=strengths_raw,
        cv_confidence=0.7,
        company_context=company_context,
        skills=request.skills or "",
        language=request.language,
        model=model,
    )
    return gap


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

        effective_mode = "system_design" if request.role == "System Design" else request.mode
        session_id = await create_session(db_user_id, request.role, request.level, request.company_id, effective_mode)

        # Fetch user's language preference and plan
        from db.database import get_user_settings
        settings = await get_user_settings(telegram_id)
        language = settings.get("language", "en")
        plan_name = await get_user_plan_name(telegram_id)
        model = _resolve_model(plan_name)

        # Get company context if specified
        company_context = ""
        if request.company_id:
            from api.companies import get_company_context
            company_context = get_company_context(request.company_id)
        elif request.user_company_id:
            # Look up user's custom company
            from db.database import async_session
            async with async_session() as sess:
                result = await sess.execute(
                    text(
                        "SELECT company_name, position, ai_context FROM user_companies "
                        "WHERE id = :ucid AND user_id = (SELECT id FROM users WHERE telegram_id = :tid)"
                    ),
                    {"ucid": request.user_company_id, "tid": telegram_id},
                )
                row = result.one_or_none()
            if row:
                company_context = row[2] or ""  # ai_context

        question = await generate_question(
            role=request.role,
            level=request.level,
            question_number=1,
            previous_questions=[],
            language=language,
            company_context=company_context,
            mode=effective_mode,
            skills=request.skills or "",
            model=model,
        )

        logger.info("start_interview uid=%s plan=%s model=%s q=%s",
                     telegram_id, plan_name, model,
                     str(question.get("question", ""))[:100] if question.get("question") else "EMPTY!")

        return {
            "session_id": session_id,
            "question": question,
            "question_number": 1,
            "mode": effective_mode,
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

        from db.database import get_user_settings
        settings = await get_user_settings(telegram_id)
        language = settings.get("language", "en")
        plan_name = await get_user_plan_name(telegram_id)
        model = _resolve_model(plan_name)

        # Build resume_context for CV-aware evaluation
        resume_context = ""
        if request.resume_id:
            try:
                import json as _json
                async with async_session() as _sess:
                    _result = await _sess.execute(
                        text("SELECT role, experience_level, analysis_result FROM user_resumes WHERE id = :rid AND user_id = :uid"),
                        {"rid": request.resume_id, "uid": db_user_id},
                    )
                    _row = _result.one_or_none()
                if _row:
                    _parts = []
                    if _row[0]:
                        _parts.append(f"CV detected role: {_row[0]}")
                    if _row[1]:
                        _parts.append(f"CV detected level: {_row[1]}")
                    if _row[2]:
                        try:
                            _deep = _json.loads(_row[2]) if isinstance(_row[2], str) else _row[2]
                            # Simple analyzer keys (from /resume/upload)
                            if _deep.get("tech_stack"):
                                _parts.append(f"Known technologies: {', '.join(_deep['tech_stack'][:8])}")
                            if _deep.get("key_skills"):
                                _parts.append(f"Key skills: {', '.join(_deep['key_skills'][:8])}")
                            if _deep.get("years_experience"):
                                _parts.append(f"Years of experience: {_deep['years_experience']}")
                            # Deep analyzer keys (from /user-resumes/upload)
                            if _deep.get("missing_keywords"):
                                _parts.append(f"Known technologies: {', '.join(_deep['missing_keywords'][:8])}")
                            if _deep.get("strengths"):
                                _parts.append(f"Key skills: {', '.join(_deep['strengths'][:8])}")
                        except Exception:
                            pass
                    resume_context = "\n".join(_parts)
            except Exception as _exc:
                logger.warning("Failed to build resume_context: %s", _exc)

        evaluation = await evaluate_answer(
            role=session.role,
            level=session.experience_level,
            question=request.question_text,
            answer=request.answer,
            language=language,
            time_taken_seconds=request.time_taken_seconds,
            mode=getattr(session, 'mode', 'technical'),
            model=model,
            resume_context=resume_context,
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
            category=evaluation.get("category", "Technical"),
        )

        if question_number < config.QUESTIONS_PER_SESSION:
            all_answers = await get_session_answers(request.session_id)
            previous_questions = [a["question_text"] for a in all_answers]

            # Get company context for next questions
            company_context = ""
            company_id = getattr(session, 'company_id', None)
            if company_id:
                from api.companies import get_company_context
                company_context = get_company_context(company_id)

            next_question = await generate_question(
                role=session.role,
                level=session.experience_level,
                question_number=question_number + 1,
                previous_questions=previous_questions,
                language=language,
                company_context=company_context,
                mode=getattr(session, 'mode', 'technical'),
                model=model,
            )

            return {
                "done": False,
                "evaluation": evaluation,
                "next_question": next_question,
                "question_number": question_number + 1,
                "mode": getattr(session, 'mode', 'technical'),
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
                language=language,
                mode=getattr(session, 'mode', 'technical'),
                model=model,
                resume_context=resume_context,
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


@router.post("/interview/voice-answer")
async def voice_answer(
    file: UploadFile = File(...),
    session_id: int = Form(...),
    question_text: str = Form(...),
    time_taken_seconds: Optional[int] = Form(None),
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Accept a voice answer, transcribe via Whisper, evaluate via AI, return result.

    Only available for Pro+ plans.
    Accepts multipart: file (audio) + session_id (int) + question_text (str).
    """
    try:
        telegram_id = user_data["id"]
        db_user_id = await _get_db_user_id(telegram_id)
        session = await _get_owned_session(session_id, db_user_id)

        if session.completed:
            raise HTTPException(status_code=400, detail="Session already completed")

        # ── Pro+ check ───────────────────────────────────────────────────────────
        plan = await get_user_plan_name(telegram_id)
        if plan not in ("Pro", "Premium"):
            raise HTTPException(
                status_code=403,
                detail="Voice answers are available on Pro and Premium plans only.",
            )

        # ── Read audio file ──────────────────────────────────────────────────────
        if not file.filename:
            raise HTTPException(status_code=400, detail="No audio file provided")
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Empty audio file")
        if len(contents) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Audio file too large (max 10MB)")

        # Determine extension
        ext = ".webm"
        if file.filename:
            _, ext = os.path.splitext(file.filename)
            if not ext:
                ext = ".webm"

        # ── Transcribe via Whisper ───────────────────────────────────────────────
        from ai.voice import transcribe_audio as whisper_transcribe

        transcribed = await whisper_transcribe(contents, suffix=ext)
        if not transcribed:
            raise HTTPException(status_code=422, detail="Could not transcribe audio. Try speaking clearly.")

        # ── Evaluate via AI ──────────────────────────────────────────────────────
        from db.database import get_user_settings
        settings = await get_user_settings(telegram_id)
        language = settings.get("language", "en")

        evaluation = await evaluate_answer(
            role=session.role,
            level=session.experience_level,
            question=question_text,
            answer=transcribed,
            language=language,
            time_taken_seconds=time_taken_seconds,
            mode=getattr(session, 'mode', 'technical'),
            resume_context="",
        )

        # ── Persist answer ───────────────────────────────────────────────────────
        from db.database import save_answer

        existing_answers = await get_session_answers(session_id)
        question_number = len(existing_answers) + 1

        await save_answer(
            session_id=session_id,
            question_number=question_number,
            question_text=question_text,
            user_answer=transcribed,
            score=evaluation["score"],
            feedback=evaluation["feedback"],
            strengths=evaluation["strengths"],
            improvements=evaluation["improvements"],
            tip=evaluation["tip"],
            category=evaluation.get("category", "Technical"),
        )

        # ── Next question or summary ─────────────────────────────────────────────
        plan_name = await get_user_plan_name(telegram_id)
        model = _resolve_model(plan_name)

        if question_number < config.QUESTIONS_PER_SESSION:
            all_answers = await get_session_answers(session_id)
            previous_questions = [a["question_text"] for a in all_answers]

            company_context = ""
            company_id = getattr(session, 'company_id', None)
            if company_id:
                from api.companies import get_company_context
                company_context = get_company_context(company_id)

            next_question = await generate_question(
                role=session.role,
                level=session.experience_level,
                question_number=question_number + 1,
                previous_questions=previous_questions,
                language=language,
                company_context=company_context,
                mode=getattr(session, 'mode', 'technical'),
                model=model,
            )

            return {
                "done": False,
                "evaluation": evaluation,
                "next_question": next_question,
                "question_number": question_number + 1,
                "transcribed": transcribed,
                "mode": getattr(session, 'mode', 'technical'),
            }

        # Session complete — generate summary
        avg_score = sum(a["score"] for a in await get_session_answers(session_id)) / question_number
        await complete_session(session_id, avg_score)

        summary = await generate_summary(
            role=session.role,
            level=session.experience_level,
            answers=await get_session_answers(session_id),
            avg_score=avg_score,
            language=language,
            mode=getattr(session, 'mode', 'technical'),
            model=model,
        )

        return {
            "done": True,
            "evaluation": evaluation,
            "summary": summary,
            "transcribed": transcribed,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("voice_answer error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to process voice answer")


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
            "mode": getattr(session, 'mode', 'technical'),
            "started_at": session.started_at.isoformat(),
            "completed": session.completed,
            "total_score": session.total_score,
            "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        }

        summary = None
        if session.completed and answers:
            avg_score = sum(a["score"] for a in answers) / len(answers)
            from db.database import get_user_settings
            settings = await get_user_settings(telegram_id)
            language = settings.get("language", "en")
            summary = await generate_summary(
                role=session.role,
                level=session.experience_level,
                answers=answers,
                avg_score=avg_score,
                language=language,
                mode=getattr(session, 'mode', 'technical'),
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

        from db.database import get_user_settings
        settings = await get_user_settings(telegram_id)
        language = settings.get("language", "en")

        question = await generate_question(
            role=session.role,
            level=session.experience_level,
            question_number=next_num,
            previous_questions=[a["question_text"] for a in existing_answers],
            language=language,
            mode=getattr(session, 'mode', 'technical'),
        )

        return {
            "question": question,
            "question_number": next_num,
            "mode": getattr(session, 'mode', 'technical'),
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
                "total_completed": 0,
                "avg_score": 0.0,
                "plan_name": "Free",
                "max_per_month": 2,
                "recent_sessions": [],
                "features": [],
                "features_ru": [],
            }

        # Fetch tariff features
        features: list[str] = []
        features_ru: list[str] | None = None
        try:
            async with async_session() as sess:
                from sqlalchemy import text as sa_text
                plan_result = await sess.execute(
                    sa_text(
                        "SELECT tp.features, tp.features_ru FROM subscriptions s "
                        "JOIN tariff_plans tp ON s.tariff_plan_id = tp.id "
                        "WHERE s.user_id = (SELECT id FROM users WHERE telegram_id = :tid) "
                        "AND s.status = 'active' AND s.end_date > datetime('now') "
                        "ORDER BY s.created_at DESC LIMIT 1"
                    ),
                    {"tid": telegram_id},
                )
                row = plan_result.one_or_none()
                if row:
                    raw = row[0]
                    if raw:
                        try:
                            parsed = json.loads(raw) if isinstance(raw, str) else raw
                            if isinstance(parsed, list):
                                features = parsed
                            elif isinstance(parsed, str):
                                features = [f.strip() for f in parsed.split(",") if f.strip()]
                            else:
                                features = []
                        except (json.JSONDecodeError, TypeError):
                            features = [f.strip() for f in str(raw).split(",") if raw] if raw else []
                    raw_ru = row[1]
                    if raw_ru:
                        try:
                            parsed = json.loads(raw_ru) if isinstance(raw_ru, str) else raw_ru
                            if isinstance(parsed, list):
                                features_ru = parsed
                            elif isinstance(parsed, str):
                                features_ru = [f.strip() for f in parsed.split(",") if f.strip()]
                            else:
                                features_ru = []
                        except (json.JSONDecodeError, TypeError):
                            features_ru = [f.strip() for f in str(raw_ru).split(",") if raw_ru] if raw_ru else []
        except Exception:
            pass  # fallback to empty features

        return {
            "total_sessions": stats["total_sessions"],
            "total_completed": stats["total_completed"],
            "avg_score": round(stats["avg_score"], 1),
            "plan_name": stats["plan_name"],
            "max_per_month": stats["max_per_month"],
            "recent_sessions": stats["recent_sessions"],
            "features": features,
            "features_ru": features_ru or [],
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_profile error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to get profile")


# ── User Resumes ──────────────────────────────────────────────────────────────

_RESUMES_DIR = os.path.join(os.path.dirname(config.DATABASE_PATH), "resumes")


@router.get("/user-resumes")
async def list_user_resumes(
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Return the current user's saved resume analyses."""
    telegram_id = user_data.get("id", 0)
    if telegram_id <= 0:
        raise HTTPException(status_code=401, detail="Not authenticated")
    db_user_id = await _get_db_user_id(telegram_id)

    async with async_session() as sess:
        result = await sess.execute(
            text(
                "SELECT id, original_filename, role, experience_level, "
                "company_name, analysis_result, created_at "
                "FROM user_resumes WHERE user_id = :uid ORDER BY created_at DESC"
            ),
            {"uid": db_user_id},
        )
        rows = result.fetchall()

    resumes = []
    for r in rows:
        analysis = json.loads(r[5]) if r[5] else {}
        resumes.append({
            "id": r[0],
            "original_filename": r[1],
            "role": r[2],
            "experience_level": r[3],
            "company_name": r[4] or "",
            "overall_score": analysis.get("overall_score"),
            "ats_score": analysis.get("ats_score"),
            "created_at": r[6],
        })
    return {"resumes": resumes}


@router.get("/user-resumes/usage")
async def get_resume_usage(
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Return resume analysis usage stats for the current user."""
    telegram_id = user_data.get("id", 0)
    if telegram_id <= 0:
        raise HTTPException(status_code=401, detail="Not authenticated")
    db_user_id = await _get_db_user_id(telegram_id)

    plan_name = await get_user_plan_name(telegram_id)
    MONTHLY_LIMITS = {"Free": 2, "Pro": 999999, "Premium": 999999}
    max_monthly = MONTHLY_LIMITS.get(plan_name, 2)

    async with async_session() as sess:
        count_row = await sess.execute(
            text(
                "SELECT COUNT(*) FROM user_resumes "
                "WHERE user_id = :uid "
                "AND strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now')"
            ),
            {"uid": db_user_id},
        )
        used = count_row.scalar() or 0

    return {
        "plan_name": plan_name,
        "used_this_month": used,
        "max_monthly": max_monthly,
        "remaining": max(0, max_monthly - used),
        "unlimited": max_monthly >= 999999,
    }


@router.post("/user-resumes/upload")
async def upload_user_resume(
    file: UploadFile = File(...),
    target_role: str = Form(...),
    experience_level: str = Form(...),
    company_context: str = Form(""),
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Upload a PDF resume, analyze it with deep AI, and store the result."""
    telegram_id = user_data.get("id", 0)
    if telegram_id <= 0:
        raise HTTPException(status_code=401, detail="Not authenticated")
    db_user_id = await _get_db_user_id(telegram_id)

    # ── Limit check: Free = 2/month, Pro/Premium = unlimited ──
    plan_name = await get_user_plan_name(telegram_id)
    MONTHLY_LIMITS = {"Free": 2, "Pro": 999999, "Premium": 999999}
    max_monthly = MONTHLY_LIMITS.get(plan_name, 2)

    async with async_session() as count_sess:
        count_row = await count_sess.execute(
            text(
                "SELECT COUNT(*) FROM user_resumes "
                "WHERE user_id = :uid "
                "AND strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now')"
            ),
            {"uid": db_user_id},
        )
        used_this_month = count_row.scalar() or 0

    logger.info(
        "Resume upload check: user=%s plan=%s used=%d max=%d",
        telegram_id, plan_name, used_this_month, max_monthly,
    )

    if used_this_month >= max_monthly:
        raise HTTPException(
            status_code=429,
            detail=f"Resume analysis limit reached for {plan_name} plan ({max_monthly}/month)",
        )

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    # Read and extract text
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    tmp_path = os.path.join(tempfile.gettempdir(), f"resume_upload_{telegram_id}.pdf")
    try:
        with open(tmp_path, "wb") as f:
            f.write(content)

        pdf_doc = fitz.open(tmp_path)
        pdf_text = "\n".join(page.get_text() for page in pdf_doc)
        pdf_doc.close()

        if not pdf_text.strip():
            raise HTTPException(
                status_code=400,
                detail="Could not extract text from this PDF. It may be a scanned/image-only document.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("PDF extraction failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to extract PDF text")
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass

    # Deep analysis
    analysis = await analyze_resume_deep(
        pdf_text=pdf_text,
        target_role=target_role,
        experience_level=experience_level,
        company_context=company_context,
    )

    # Save PDF file to persistent storage
    os.makedirs(_RESUMES_DIR, exist_ok=True)
    safe_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{telegram_id}_{file.filename}"
    file_path = os.path.join(_RESUMES_DIR, safe_name)
    with open(file_path, "wb") as f:
        f.write(content)

    fixed_content = analysis.get("fixed_content", "")

    async with async_session() as sess:
        result = await sess.execute(
            text(
                "INSERT INTO user_resumes "
                "(user_id, original_filename, file_path, role, experience_level, "
                "company_name, analysis_result, fixed_content, created_at) "
                "VALUES (:uid, :fname, :fpath, :role, :level, :ctx, :analysis, :fixed, :now) "
                "RETURNING id, created_at"
            ),
            {
                "uid": db_user_id,
                "fname": file.filename,
                "fpath": file_path,
                "role": target_role,
                "level": experience_level,
                "ctx": company_context,
                "analysis": json.dumps(analysis),
                "fixed": fixed_content,
                "now": datetime.utcnow().isoformat(),
            },
        )
        await sess.commit()
        row = result.fetchone()

    return {
        "id": row[0],
        "original_filename": file.filename,
        "role": target_role,
        "experience_level": experience_level,
        "analysis": analysis,
        "created_at": row[1],
    }


@router.delete("/user-resumes/{resume_id}")
async def delete_user_resume(
    resume_id: int,
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Delete a saved resume analysis and its file."""
    telegram_id = user_data.get("id", 0)
    if telegram_id <= 0:
        raise HTTPException(status_code=401, detail="Not authenticated")
    db_user_id = await _get_db_user_id(telegram_id)

    async with async_session() as sess:
        # Fetch and verify ownership
        row = await sess.execute(
            text(
                "SELECT id, file_path FROM user_resumes "
                "WHERE id = :rid AND user_id = :uid"
            ),
            {"rid": resume_id, "uid": db_user_id},
        )
        resume = row.fetchone()
        if not resume:
            raise HTTPException(status_code=404, detail="Resume not found or not owned")

        # Remove file if exists
        file_path = resume[1]
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as exc:
                logger.warning("Failed to remove resume file %s: %s", file_path, exc)

        await sess.execute(
            text("DELETE FROM user_resumes WHERE id = :rid AND user_id = :uid"),
            {"rid": resume_id, "uid": db_user_id},
        )
        await sess.commit()

    return {"ok": True}


@router.get("/user-resumes/{resume_id}/download-pdf")
async def download_user_resume_pdf(
    resume_id: int,
    user_data: dict = Depends(get_current_user),
) -> Response:
    """Return the improved resume as a PDF file, generated from fixed_content."""
    telegram_id = user_data.get("id", 0)
    if telegram_id <= 0:
        raise HTTPException(status_code=401, detail="Not authenticated")
    db_user_id = await _get_db_user_id(telegram_id)

    async with async_session() as sess:
        row = await sess.execute(
            text(
                "SELECT original_filename, fixed_content, role, experience_level "
                "FROM user_resumes WHERE id = :rid AND user_id = :uid"
            ),
            {"rid": resume_id, "uid": db_user_id},
        )
        resume = row.fetchone()
        if not resume:
            raise HTTPException(status_code=404, detail="Resume not found or not owned")

    original_filename = resume[0] or "resume"
    fixed_content = resume[1] or ""
    role = resume[2] or ""
    level = resume[3] or ""

    # Generate PDF from fixed content using fpdf2
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.add_font("DV", "", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    pdf.add_font("DV", "B", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    pdf.set_font("DV", "B", 18)
    pdf.cell(0, 12, "Improved Resume", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(4)

    pdf.set_font("DV", "", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, f"Role: {role}  |  Level: {level}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(6)

    pdf.set_draw_color(41, 128, 185)
    pdf.set_line_width(0.5)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(6)

    pdf.set_text_color(30, 30, 30)
    pdf.set_font("DV", "", 10)
    for line in fixed_content.split("\n"):
        s = line.strip()
        if s:
            pdf.set_x(pdf.l_margin)
            # Bold for section headers (ALL CAPS or ending with :)
            if s.isupper() and len(s) < 60:
                pdf.set_font("DV", "B", 11)
                pdf.multi_cell(0, 6, s)
                pdf.set_font("DV", "", 10)
            elif s.endswith(":") and len(s) < 50:
                pdf.set_font("DV", "B", 10)
                pdf.multi_cell(0, 6, s)
                pdf.set_font("DV", "", 10)
            else:
                pdf.multi_cell(0, 6, s)
        else:
            pdf.ln(3)

    basename = original_filename.replace(".pdf", "").replace(".PDF", "")
    safe_name = f"{basename}_improved.pdf"

    import io
    buf = io.BytesIO()
    pdf.output(buf)
    buf.seek(0)

    return Response(
        content=buf.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


@router.get("/user-resumes/{resume_id}/download")
async def download_user_resume(
    resume_id: int,
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Return the analysis result including the rewritten fixed_content."""
    telegram_id = user_data.get("id", 0)
    if telegram_id <= 0:
        raise HTTPException(status_code=401, detail="Not authenticated")
    db_user_id = await _get_db_user_id(telegram_id)

    async with async_session() as sess:
        row = await sess.execute(
            text(
                "SELECT id, original_filename, role, experience_level, "
                "company_name, analysis_result, fixed_content, created_at "
                "FROM user_resumes WHERE id = :rid AND user_id = :uid"
            ),
            {"rid": resume_id, "uid": db_user_id},
        )
        resume = row.fetchone()
        if not resume:
            raise HTTPException(status_code=404, detail="Resume not found or not owned")

    analysis = json.loads(resume[5]) if resume[5] else {}

    return {
        "id": resume[0],
        "original_filename": resume[1],
        "role": resume[2],
        "experience_level": resume[3],
        "company_name": resume[4] or "",
        "analysis": analysis,
        "fixed_content": resume[6] or "",
        "created_at": resume[7],
    }


# ── Resume analysis ───────────────────────────────────────────────────────────


class ResumeAnalyzeRequest(BaseModel):
    pdf_text: str


class ResumeAnalyzeResponse(BaseModel):
    target_role: Optional[str]
    seniority_level: Optional[str]
    suggested_role: Optional[str]
    suggested_level: Optional[str]
    tech_stack: list[str]
    years_experience: Optional[int]
    key_skills: list[str]
    confidence: float
    raw_title: Optional[str]


@router.post("/resume/analyze")
async def analyze_resume_endpoint(
    request: ResumeAnalyzeRequest,
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Analyze resume text and return parsed position/level/skills."""
    from ai.resume_analyzer import analyze_resume as _analyze_resume

    try:
        pdf_text = request.pdf_text[:10_000]
        result = await _analyze_resume(pdf_text)
        return result
    except Exception as exc:
        logger.error("analyze_resume_endpoint error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to analyze resume")


@router.post("/resume/upload")
async def analyze_resume_upload(
    file: UploadFile = File(...),
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Upload a PDF resume file, extract text with PyMuPDF, analyze it, and persist to DB."""
    from ai.resume_analyzer import analyze_resume as _analyze_resume

    telegram_id = user_data.get("id", 0)
    if telegram_id <= 0:
        raise HTTPException(status_code=401, detail="Not authenticated")
    db_user_id = await _get_db_user_id(telegram_id)

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    tmp_path = os.path.join(tempfile.gettempdir(), f"upload_resume_{telegram_id}.pdf")
    try:
        content = await file.read()
        with open(tmp_path, "wb") as f:
            f.write(content)

        pdf_doc = fitz.open(tmp_path)
        pdf_text = "\n".join(page.get_text() for page in pdf_doc)
        pdf_doc.close()

        if not pdf_text.strip():
            raise HTTPException(
                status_code=400,
                detail="Could not extract text from this PDF. It may be a scanned/image-only document.",
            )

        pdf_text = pdf_text[:10_000]
        result = await _analyze_resume(pdf_text)

        # Persist to user_resumes table so gap analysis & interview can reference it
        role = result.get("suggested_role") or ""
        level = result.get("suggested_level") or ""
        analysis_json = json.dumps(result)

        # Save PDF to persistent storage
        os.makedirs(_RESUMES_DIR, exist_ok=True)
        safe_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{telegram_id}_{file.filename}"
        file_path = os.path.join(_RESUMES_DIR, safe_name)
        with open(file_path, "wb") as f:
            f.write(content)

        async with async_session() as sess:
            res = await sess.execute(
                text(
                    "INSERT INTO user_resumes (user_id, role, experience_level, original_filename, file_path, analysis_result, created_at) "
                    "VALUES (:uid, :role, :level, :fname, :fpath, :analysis, :now) RETURNING id"
                ),
                {
                    "uid": db_user_id,
                    "role": role,
                    "level": level,
                    "fname": file.filename,
                    "fpath": file_path,
                    "analysis": analysis_json,
                    "now": datetime.utcnow().isoformat(),
                },
            )
            resume_id = res.scalar()
            await sess.commit()

        result["id"] = resume_id
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("analyze_resume_upload error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to analyze resume")
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


# ── Text-to-Speech (TTS) ─────────────────────────────────────────────────────


class TTSRequest(BaseModel):
    text: str
    voice: str = "alloy"


@router.post("/tts")
async def text_to_speech(request: TTSRequest) -> dict:
    """Generate speech audio from text using OpenAI TTS.

    Returns a base64-encoded MP3 audio blob that the Mini App can play.
    Also stores the audio file locally for caching.
    """
    import base64

    from ai.voice import text_to_speech as tts

    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    if len(request.text) > 2000:
        raise HTTPException(status_code=400, detail="Text too long (max 2000 chars)")

    audio_bytes = await tts(request.text, voice=request.voice)

    if audio_bytes is None:
        raise HTTPException(status_code=500, detail="TTS generation failed")

    # Cache to a file for replay
    os.makedirs("data/tts_cache", exist_ok=True)
    cache_key = hashlib.md5(request.text.encode()).hexdigest()
    cache_path = f"data/tts_cache/{cache_key}.mp3"
    if not os.path.exists(cache_path):
        with open(cache_path, "wb") as f:
            f.write(audio_bytes)

    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

    return {
        "audio_base64": audio_b64,
        "format": "mp3",
        "cache_key": cache_key,
    }


# ── Speech-to-Text (STT / Transcribe) ────────────────────────────────────────


@router.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Transcribe an uploaded audio file (webm, ogg, mp3, wav) via Whisper.

    Returns the transcribed text. Used by the Mini App voice recording feature.
    """
    from ai.voice import transcribe_audio as whisper_transcribe

    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Read the uploaded file bytes
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Empty file")

    if len(contents) > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(status_code=400, detail="Audio file too large (max 10MB)")

    # Determine file extension from filename or content type
    ext = ".webm"
    if file.filename:
        _, ext = os.path.splitext(file.filename)
        if not ext:
            ext = ".webm"
    elif file.content_type:
        mime_map = {
            "audio/webm": ".webm",
            "audio/ogg": ".ogg",
            "audio/mp3": ".mp3",
            "audio/mpeg": ".mp3",
            "audio/wav": ".wav",
            "audio/x-wav": ".wav",
            "audio/mp4": ".m4a",
        }
        ext = mime_map.get(file.content_type, ".webm")

    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(contents)
            tmp_path = tmp.name

        transcript = await whisper_transcribe(contents, suffix=ext)

        os.unlink(tmp_path)

        if not transcript:
            return {"text": "", "error": "Could not transcribe audio. Try speaking clearly."}

        return {"text": transcript, "error": None}

    except Exception as exc:
        logger.error("Transcribe endpoint error: %s", exc)
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail="Transcription failed")


# ── Tariff Plans ────────────────────────────────────────────────────────────────


@router.get("/plans", response_model_exclude_none=True)
async def get_plans() -> list[dict]:
    """Return all active tariff plans with features in multiple languages."""
    from db.database import get_tariff_plans

    plans = await get_tariff_plans()
    return plans


# ── User Settings ─────────────────────────────────────────────────────────────


class SettingsRequest(BaseModel):
    language: Optional[str] = None
    voice: Optional[str] = None
    ui_language: Optional[str] = None


ALLOWED_LANGUAGES = {"en", "ru"}
ALLOWED_UI_LANGUAGES = {"en", "ru"}
ALLOWED_VOICES = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}
VOICE_FREE_PLANS = {"Pro", "Premium"}


@router.get("/settings")
async def get_settings(user_data: dict = Depends(get_current_user)) -> dict:
    """Return the current user's settings (language + voice)."""
    telegram_id = user_data.get("id", 0)
    if telegram_id <= 0:
        return {"language": "en", "voice": "alloy"}

    from db.database import get_user_settings

    return await get_user_settings(telegram_id)


@router.put("/settings")
async def update_settings(
    request: SettingsRequest,
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Update user settings. Voice changes are restricted to paying users."""
    telegram_id = user_data.get("id", 0)
    if telegram_id <= 0:
        raise HTTPException(status_code=401, detail="Not authenticated")

    from db.database import get_user_settings, update_user_settings

    current = await get_user_settings(telegram_id)

    language = request.language or current["language"]
    voice = request.voice or current["voice"]
    ui_language = request.ui_language or current.get("ui_language", "en")

    # Validate language
    if language and language not in ALLOWED_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language. Allowed: {', '.join(sorted(ALLOWED_LANGUAGES))}",
        )

    # Validate UI language
    if ui_language and ui_language not in ALLOWED_UI_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported UI language. Allowed: {', '.join(sorted(ALLOWED_UI_LANGUAGES))}",
        )

    # Validate voice
    if voice and voice not in ALLOWED_VOICES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported voice. Allowed: {', '.join(sorted(ALLOWED_VOICES))}",
        )

    # Voice change requires Pro or Premium
    if voice and voice != current.get("voice", "alloy"):
        from db.database import check_subscription_limit

        # Check if user has a paid subscription
        can_proceed = await check_subscription_limit(telegram_id)
        # Can't fully check subscription tier from here, use user's tariff_plans
        async with async_session() as sess:
            from sqlalchemy import text as sa_text

            sub_result = await sess.execute(
                sa_text(
                    "SELECT tp.name FROM subscriptions s "
                    "JOIN tariff_plans tp ON s.tariff_plan_id = tp.id "
                    "WHERE s.user_id = (SELECT id FROM users WHERE telegram_id = :tid) "
                    "AND s.status = 'active' AND s.end_date > datetime('now') "
                    "ORDER BY s.created_at DESC LIMIT 1"
                ),
                {"tid": telegram_id},
            )
            row = sub_result.one_or_none()
            plan_name = row[0] if row else "Free"

        if plan_name not in VOICE_FREE_PLANS:
            raise HTTPException(
                status_code=403,
                detail="Voice selection is available on Pro and Premium plans only. Upgrade with /plan.",
            )

    return await update_user_settings(telegram_id, language=language, voice=voice, ui_language=ui_language)


# ── Telegram Stars Invoice ──────────────────────────────────────────────────────


class StarsInvoiceRequest(BaseModel):
    plan_name: str


@router.post("/stars/invoice")
async def create_stars_invoice(
    request: StarsInvoiceRequest,
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Create a Telegram Stars invoice link for a tariff plan."""
    import httpx

    from db.database import get_tariff_plans

    telegram_id = user_data.get("id", 0)
    if telegram_id <= 0:
        raise HTTPException(status_code=401, detail="Not authenticated")

    plans = await get_tariff_plans()
    plan = next((p for p in plans if p["name"].lower() == request.plan_name.lower()), None)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    if not plan.get("star_price"):
        raise HTTPException(status_code=400, detail="This plan is not available for Stars payment")

    star_price = int(plan["star_price"])
    plan_name = plan["name"]
    payload = f"{plan_name.lower()}_1month"

    # Create invoice link via Telegram Bot API
    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/createInvoiceLink"
    body = {
        "title": f"AI Interview {plan_name}",
        "description": f"{plan_name} plan — {star_price} Stars\n30 days of unlimited interviews.",
        "payload": payload,
        "provider_token": "",
        "currency": "XTR",
        "prices": [{"label": plan_name, "amount": star_price}],
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=body, timeout=15)

    if resp.status_code != 200:
        logger.error("createInvoiceLink failed: %s %s", resp.status_code, resp.text)
        raise HTTPException(status_code=502, detail="Failed to create invoice")

    data = resp.json()
    if not data.get("ok"):
        logger.error("createInvoiceLink error: %s", data)
        raise HTTPException(status_code=502, detail="Telegram API error")

    invoice_link = data["result"]
    return {"invoice_url": invoice_link, "star_price": star_price, "plan": plan_name}


# ── User Companies ─────────────────────────────────────────────────────────


class CreateUserCompanyRequest(BaseModel):
    telegram_id: int
    company_name: str
    vacancy_url: str
    position: str


class DeleteUserCompanyRequest(BaseModel):
    telegram_id: int
    company_id: int


@router.get("/user-companies")
async def list_user_companies(user_data: dict = Depends(get_current_user)) -> dict:
    """Return user's custom companies."""
    telegram_id = user_data.get("id", 0)
    if telegram_id <= 0:
        raise HTTPException(status_code=401, detail="Not authenticated")
    db_user_id = await _get_db_user_id(telegram_id)
    async with async_session() as sess:
        result = await sess.execute(
            text(
                "SELECT id, company_name, vacancy_url, position, ai_context, created_at "
                "FROM user_companies WHERE user_id = :uid ORDER BY created_at DESC"
            ),
            {"uid": db_user_id},
        )
        rows = result.fetchall()
    companies = [
        {
            "id": r[0],
            "company_name": r[1],
            "vacancy_url": r[2] or "",
            "position": r[3] or "",
            "ai_context": r[4] or "",
            "created_at": r[5],
        }
        for r in rows
    ]
    return {"companies": companies}


@router.post("/user-companies/create")
async def create_user_company(request: CreateUserCompanyRequest) -> dict:
    """Create a new user company with AI-generated context from vacancy URL."""
    telegram_id = request.telegram_id
    if telegram_id <= 0:
        raise HTTPException(status_code=401, detail="Not authenticated")

    db_user_id = await _get_db_user_id(telegram_id)

    if not request.company_name.strip():
        raise HTTPException(status_code=400, detail="Company name is required")
    if not request.position.strip():
        raise HTTPException(status_code=400, detail="Position is required")
    if not request.vacancy_url.strip():
        raise HTTPException(status_code=400, detail="Vacancy URL is required")

    # Generate AI context from vacancy URL + position
    ai_context = await _generate_company_context(
        company_name=request.company_name,
        vacancy_url=request.vacancy_url,
        position=request.position,
    )

    async with async_session() as sess:
        result = await sess.execute(
            text(
                "INSERT INTO user_companies (user_id, company_name, vacancy_url, position, ai_context) "
                "VALUES (:uid, :name, :url, :pos, :ctx) RETURNING id, created_at"
            ),
            {
                "uid": db_user_id,
                "name": request.company_name,
                "url": request.vacancy_url,
                "pos": request.position,
                "ctx": ai_context,
            },
        )
        await sess.commit()
        row = result.fetchone()

    return {
        "id": row[0],
        "company_name": request.company_name,
        "vacancy_url": request.vacancy_url,
        "position": request.position,
        "ai_context": ai_context,
        "created_at": row[1],
    }


@router.delete("/user-companies/{company_id}")
async def delete_user_company(
    company_id: int,
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Delete a user's custom company."""
    telegram_id = user_data.get("id", 0)
    if telegram_id <= 0:
        raise HTTPException(status_code=401, detail="Not authenticated")
    db_user_id = await _get_db_user_id(telegram_id)

    async with async_session() as sess:
        # Verify ownership
        row = await sess.execute(
            text("SELECT id FROM user_companies WHERE id = :cid AND user_id = :uid"),
            {"cid": company_id, "uid": db_user_id},
        )
        if not row.fetchone():
            raise HTTPException(status_code=404, detail="Company not found or not owned")

        await sess.execute(
            text("DELETE FROM user_companies WHERE id = :cid AND user_id = :uid"),
            {"cid": company_id, "uid": db_user_id},
        )
        await sess.commit()

    return {"ok": True}


async def _generate_company_context(
    company_name: str,
    vacancy_url: str,
    position: str,
) -> str:
    """Fetch vacancy page text and generate an AI context prompt using OpenAI."""
    page_text = ""
    if vacancy_url:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(vacancy_url, headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code == 200:
                    import re
                    html = resp.text
                    # Strip HTML tags
                    page_text = re.sub(r"<[^>]+>", " ", html)
                    page_text = re.sub(r"\s+", " ", page_text).strip()
                    page_text = page_text[:3000]  # Limit text length
        except Exception as exc:
            logger.warning("Failed to fetch vacancy URL %s: %s", vacancy_url, exc)

    # Build the prompt for OpenAI
    parts = [f"You are preparing the candidate for an interview at {company_name}."]
    if position:
        parts.append(f"The target position is: {position}.")
    if page_text:
        parts.append(f"The vacancy description says: {page_text}")
    parts.append(
        "Generate a concise AI interviewer context prompt (2-3 paragraphs) "
        "that describes the company's interview style, technical focus areas, "
        "and key competencies to assess. Include behavioral aspects relevant to "
        "the company culture. The context will be used by an AI interviewer "
        "to ask tailored interview questions."
    )
    user_prompt = "\n\n".join(parts)

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=config.OPENAI_CHAT_API_KEY or config.OPENAI_API_KEY,
            base_url=config.OPENAI_BASE_URL,
        )
        response = await client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert interview coach who creates tailored "
                        "AI interviewer contexts for specific companies and roles. "
                        "Write in English."
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.5,
            max_completion_tokens=400,
        )
        return response.choices[0].message.content or ""
    except Exception as exc:
        logger.error("OpenAI context generation failed: %s", exc)
        # Fallback basic context
        fallback = (
            f"You are interviewing the candidate for {company_name}."
        )
        if position:
            fallback += f" The target position is: {position}."
        fallback += (
            " Ask relevant technical and behavioral questions appropriate for "
            "this company and role. Assess both technical skills and cultural fit."
        )
        return fallback


# ── Study Plan endpoints ──────────────────────────────────────────────────────


@router.get("/study/sessions-for-plan")
async def get_sessions_for_plan(
    mode: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Fetch interview sessions that can be used for study plan generation."""
    telegram_id = user_data.get("id", 0)
    if telegram_id <= 0:
        raise HTTPException(status_code=401, detail="Not authenticated")
    db_user_id = await _get_db_user_id(telegram_id)

    from db.database import get_user_sessions_for_plan
    sessions = await get_user_sessions_for_plan(
        db_user_id=db_user_id,
        mode=mode,
        date_from=date_from,
        date_to=date_to,
    )
    return {"sessions": sessions}


@router.post("/study/plans/generate")
async def generate_plan(
    request: GeneratePlanRequest,
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Generate a personalised study plan based on interview performance.

    Filters interviews by mode (technical/behavioral/both) and date range,
    then sends them to AI for plan generation.
    """
    telegram_id = user_data.get("id", 0)
    if telegram_id <= 0:
        raise HTTPException(status_code=401, detail="Not authenticated")
    db_user_id = await _get_db_user_id(telegram_id)

    from db.database import get_user_sessions_for_plan, get_sessions_with_answers, create_study_plan
    from ai.study_planner import generate_study_plan as _generate
    from db.database import get_user_plan_name

    # 1. Get matching sessions (includes both completed AND incomplete)
    sessions_meta = await get_user_sessions_for_plan(
        db_user_id=db_user_id,
        mode=request.mode,
        date_from=request.date_from,
        date_to=request.date_to,
    )

    if not sessions_meta:
        raise HTTPException(status_code=404, detail="No interviews found matching your filters. Try a wider date range or different mode.")

    session_ids = [s["id"] for s in sessions_meta]

    # 2. Fetch full session data with answers
    sessions_data = await get_sessions_with_answers(session_ids)

    if not sessions_data:
        raise HTTPException(status_code=404, detail="Could not load interview data. Please try again.")

    # 3. Resolve model by plan
    plan_name = await get_user_plan_name(telegram_id)
    model = config.OPENAI_MODEL_PREMIUM if plan_name == "Premium" else config.OPENAI_MODEL

    # 4. Generate plan via AI
    plan_result = await _generate(
        user_id=db_user_id,
        session_data=sessions_data,
        duration_days=request.duration_days,
        mode=request.mode,
        language=request.language,
        model=model,
    )

    # 5. Save to database
    source_params = {
        "mode": request.mode,
        "date_from": request.date_from,
        "date_to": request.date_to,
        "session_count": len(session_ids),
    }

    created = await create_study_plan(
        user_id=db_user_id,
        title=plan_result["title"],
        description=plan_result["description"],
        focus_areas=plan_result["focus_areas"],
        duration_days=plan_result["duration_days"],
        source_type="interview",
        source_params=source_params,
        language=request.language,
        session_ids=session_ids,
        days_data=plan_result["days_data"],
    )

    return {
        "ok": True,
        "plan": created,
        "message": f"Study plan '{plan_result['title']}' created!",
    }


@router.get("/study/plans")
async def list_study_plans(
    user_data: dict = Depends(get_current_user),
) -> dict:
    """List all study plans for the current user."""
    telegram_id = user_data.get("id", 0)
    if telegram_id <= 0:
        raise HTTPException(status_code=401, detail="Not authenticated")
    db_user_id = await _get_db_user_id(telegram_id)

    from db.database import get_user_study_plans
    plans = await get_user_study_plans(db_user_id)
    return {"plans": plans}


@router.get("/study/plans/{plan_id}")
async def get_study_plan_detail(
    plan_id: int,
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Get full study plan detail with days."""
    telegram_id = user_data.get("id", 0)
    if telegram_id <= 0:
        raise HTTPException(status_code=401, detail="Not authenticated")
    db_user_id = await _get_db_user_id(telegram_id)

    from db.database import get_study_plan_detail
    plan = await get_study_plan_detail(plan_id, db_user_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return {"plan": plan}


@router.patch("/study/plans/{plan_id}/status")
async def update_plan_status(
    plan_id: int,
    request: UpdatePlanStatusRequest,
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Update study plan status (active / paused / completed)."""
    telegram_id = user_data.get("id", 0)
    if telegram_id <= 0:
        raise HTTPException(status_code=401, detail="Not authenticated")
    db_user_id = await _get_db_user_id(telegram_id)

    valid_statuses = {"active", "paused", "completed"}
    if request.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}")

    from db.database import update_study_plan_status
    ok = await update_study_plan_status(plan_id, db_user_id, request.status)
    if not ok:
        raise HTTPException(status_code=404, detail="Plan not found or not owned")
    return {"ok": True, "status": request.status}


@router.post("/study/plans/{plan_id}/toggle-day")
async def toggle_plan_day(
    plan_id: int,
    request: MarkDayRequest,
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Toggle a day's completion status and recalculate progress."""
    telegram_id = user_data.get("id", 0)
    if telegram_id <= 0:
        raise HTTPException(status_code=401, detail="Not authenticated")
    db_user_id = await _get_db_user_id(telegram_id)

    from db.database import mark_study_plan_day
    ok = await mark_study_plan_day(plan_id, request.day_id, db_user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Day or plan not found")
    return {"ok": True}


# ── Guided System Design API (7-step flow, Premium) ─────────────────────


class SystemDesignStartRequest(BaseModel):
    problem: str
    level: str
    company: str = "general"


class SystemDesignStepRequest(BaseModel):
    session_id: int
    answer: str


@router.post("/system-design/start")
async def sd_start(
    request: SystemDesignStartRequest,
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Start a guided 7-step System Design session. Premium feature."""
    telegram_id = user_data.get("id", 0)
    if telegram_id <= 0:
        raise HTTPException(status_code=401, detail="Not authenticated")

    plan = await get_user_plan_name(telegram_id)
    if plan == "Free":
        raise HTTPException(status_code=403, detail="System Design interviews are available for Pro and Premium users only. Upgrade your plan.")

    db_user_id = await _get_db_user_id(telegram_id)

    from db.models import SystemDesignSession

    async with async_session() as s:
        sd_session = SystemDesignSession(
            user_id=db_user_id,
            problem=request.problem,
            level=request.level,
            company=request.company,
            current_step=1,
            step_scores="[]",
            step_context="[]",
            completed=False,
        )
        s.add(sd_session)
        await s.commit()
        await s.refresh(sd_session)

    model = _resolve_model(plan)
    from api.companies import get_company_context
    company_context = get_company_context(request.company)

    # Fetch user's language preference
    from db.database import get_user_settings
    settings = await get_user_settings(telegram_id)
    language = settings.get("language", "en")

    step_data = await generate_sd_step(
        problem=request.problem,
        role="System Design",
        level=request.level,
        step=1,
        previous_context="",
        company_context=company_context,
        language=language,
        model=model,
    )

    return {
        "session_id": sd_session.id,
        "step": 1,
        "step_name": step_data.get("step_name", "Requirements Clarification"),
        "prompt": step_data.get("prompt", ""),
        "hints": step_data.get("hints", []),
        "total_steps": 7,
    }


@router.post("/system-design/step")
async def sd_step(
    request: SystemDesignStepRequest,
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Submit an answer for the current step and get the next one."""
    telegram_id = user_data.get("id", 0)
    if telegram_id <= 0:
        raise HTTPException(status_code=401, detail="Not authenticated")

    plan = await get_user_plan_name(telegram_id)
    if plan == "Free":
        raise HTTPException(status_code=403, detail="Premium feature")

    from db.models import SystemDesignSession

    async with async_session() as s:
        sd = await s.get(SystemDesignSession, request.session_id)
        if not sd:
            raise HTTPException(status_code=404, detail="Session not found")
        if sd.completed:
            raise HTTPException(status_code=400, detail="Session already completed")

        current_step = sd.current_step
        step_context = json.loads(sd.step_context or "[]")
        step_scores = json.loads(sd.step_scores or "[]")

    prev_step_data = step_context[-1] if step_context else {}
    context_lines = []
    for sc in step_context:
        context_lines.append(f"Step {sc['step']} ({sc['step_name']}):\nPrompt: {sc['prompt']}\nAnswer: {sc['answer']}")
    previous_context = "\n\n".join(context_lines)

    model = _resolve_model(plan)
    from ai.prompts import _SD_STEP_NAMES
    from db.database import get_user_settings

    # Fetch user's language preference
    settings = await get_user_settings(telegram_id)
    language = settings.get("language", "en")

    step_name = _SD_STEP_NAMES.get(current_step, f"Step {current_step}")

    eval_result = await evaluate_sd_step(
        problem=sd.problem,
        step=current_step,
        step_name=step_name,
        level=sd.level,
        step_prompt="",
        answer=request.answer,
        previous_context=previous_context,
        language=language,
        model=model,
    )

    score = eval_result.get("score", 5)
    feedback = eval_result.get("feedback", "")

    step_context.append({
        "step": current_step,
        "step_name": step_name,
        "prompt": prev_step_data.get("prompt", ""),
        "answer": request.answer,
        "score": score,
        "feedback": feedback,
    })
    step_scores.append({"step": current_step, "score": score})

    is_last_step = current_step >= 7

    if is_last_step:
        all_context = "\n\n".join(
            f"Step {sc['step']} ({sc['step_name']}):\nPrompt: {sc['prompt']}\nAnswer: {sc['answer']}\nScore: {sc['score']}/10"
            for sc in step_context
        )

        summary = await generate_sd_summary(
            problem=sd.problem,
            level=sd.level,
            all_context=all_context,
            language=language,
            model=model,
        )

        async with async_session() as s:
            sd_obj = await s.get(SystemDesignSession, request.session_id)
            sd_obj.current_step = current_step + 1
            sd_obj.step_scores = json.dumps(step_scores)
            sd_obj.step_context = json.dumps(step_context)
            sd_obj.summary = json.dumps(summary)
            sd_obj.completed = True
            sd_obj.total_score = summary.get("overall", 5)
            await s.commit()

        return {
            "done": True,
            "step": current_step,
            "score": score,
            "feedback": feedback,
            "evaluation": summary,
            "next_prompt": None,
            "next_hints": [],
        }

    next_step = current_step + 1
    company_context = ""
    if sd.company:
        from api.companies import get_company_context
        company_context = get_company_context(sd.company)

    next_step_data = await generate_sd_step(
        problem=sd.problem,
        role="System Design",
        level=sd.level,
        step=next_step,
        previous_context=previous_context,
        company_context=company_context,
        language=language,
        model=model,
    )

    async with async_session() as s:
        sd_obj = await s.get(SystemDesignSession, request.session_id)
        sd_obj.current_step = next_step
        sd_obj.step_scores = json.dumps(step_scores)
        sd_obj.step_context = json.dumps(step_context)
        await s.commit()

    return {
        "done": False,
        "step": next_step,
        "step_name": next_step_data.get("step_name", f"Step {next_step}"),
        "prompt": next_step_data.get("prompt", ""),
        "hints": next_step_data.get("hints", []),
        "score": score,
        "feedback": feedback,
        "evaluation": None,
    }


@router.get("/system-design/session/{session_id}")
async def sd_session_detail(
    session_id: int,
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Return full details of a System Design session (for viewing results or resuming)."""
    telegram_id = user_data.get("id", 0)
    if telegram_id <= 0:
        raise HTTPException(status_code=401, detail="Not authenticated")

    from db.models import SystemDesignSession

    async with async_session() as s:
        sd = await s.get(SystemDesignSession, session_id)
        if not sd:
            raise HTTPException(status_code=404, detail="Session not found")

        db_user_id = await _get_db_user_id(telegram_id)
        if sd.user_id != db_user_id:
            raise HTTPException(status_code=403, detail="Not your session")

        step_context = json.loads(sd.step_context or "[]")
        step_scores = json.loads(sd.step_scores or "[]")
        summary = json.loads(sd.summary) if sd.summary else None

    return {
        "id": sd.id,
        "problem": sd.problem,
        "level": sd.level,
        "company": sd.company,
        "completed": sd.completed,
        "current_step": sd.current_step,
        "total_steps": 7,
        "total_score": sd.total_score,
        "step_context": step_context,
        "step_scores": step_scores,
        "summary": summary,
        "started_at": sd.started_at.isoformat() if sd.started_at else None,
    }


@router.get("/system-design/history")
async def sd_history(
    user_data: dict = Depends(get_current_user),
) -> dict:
    """Return the user's System Design session history."""
    telegram_id = user_data.get("id", 0)
    if telegram_id <= 0:
        raise HTTPException(status_code=401, detail="Not authenticated")

    from db.models import SystemDesignSession
    from sqlalchemy import select, desc

    async with async_session() as s:
        db_user_id = await _get_db_user_id(telegram_id)
        result = await s.execute(
            select(SystemDesignSession)
            .where(SystemDesignSession.user_id == db_user_id)
            .order_by(desc(SystemDesignSession.started_at))
            .limit(50)
        )
        sessions = result.scalars().all()

    return {
        "sessions": [
            {
                "id": sd.id,
                "problem": sd.problem,
                "level": sd.level,
                "completed": sd.completed,
                "total_score": sd.total_score,
                "started_at": sd.started_at.isoformat() if sd.started_at else None,
                "current_step": sd.current_step,
            }
            for sd in sessions
        ],
    }
