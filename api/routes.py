"""All API route handlers for the Mini App backend."""
import hashlib
import logging
from typing import Optional

import os
import tempfile

import fitz
from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
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
    get_user_plan_name,
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
    company_id: Optional[str] = None
    mode: str = "technical"  # "technical" or "behavioral"


class AnswerRequest(BaseModel):
    session_id: int
    question_text: str  # The question that was asked — needed for stateless evaluation
    answer: str
    time_taken_seconds: Optional[int] = None


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

        session_id = await create_session(db_user_id, request.role, request.level, request.company_id, request.mode)

        # Fetch user's language preference
        from db.database import get_user_settings
        settings = await get_user_settings(telegram_id)
        language = settings.get("language", "en")

        # Get company context if specified
        company_context = ""
        if request.company_id:
            from api.companies import get_company_context
            company_context = get_company_context(request.company_id)

        question = await generate_question(
            role=request.role,
            level=request.level,
            question_number=1,
            previous_questions=[],
            language=language,
            company_context=company_context,
            mode=request.mode,
        )

        return {
            "session_id": session_id,
            "question": question,
            "question_number": 1,
            "mode": request.mode,
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

        evaluation = await evaluate_answer(
            role=session.role,
            level=session.experience_level,
            question=request.question_text,
            answer=request.answer,
            language=language,
            time_taken_seconds=request.time_taken_seconds,
            mode=getattr(session, 'mode', 'technical'),
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
    session_id: int = ...,  # noqa — FastAPI handles via form
    question_text: str = ...,
    time_taken_seconds: Optional[int] = None,
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
                company_context=company_context,
                mode=getattr(session, 'mode', 'technical'),
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
                "total_completed": 0,
                "avg_score": 0.0,
                "plan_name": "Free",
                "max_per_month": 2,
                "recent_sessions": [],
            }

        return {
            "total_sessions": stats["total_sessions"],
            "total_completed": stats["total_completed"],
            "avg_score": round(stats["avg_score"], 1),
            "plan_name": stats["plan_name"],
            "max_per_month": stats["max_per_month"],
            "recent_sessions": stats["recent_sessions"],
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_profile error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to get profile")


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
    """Upload a PDF resume file, extract text with PyMuPDF, and analyze it."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    from ai.resume_analyzer import analyze_resume as _analyze_resume

    tmp_path = os.path.join(tempfile.gettempdir(), f"upload_resume_{user_data.get('id', '0')}.pdf")
    try:
        content = await file.read()
        with open(tmp_path, "wb") as f:
            f.write(content)

        pdf_doc = fitz.open(tmp_path)
        text = "\n".join(page.get_text() for page in pdf_doc)
        pdf_doc.close()

        if not text.strip():
            raise HTTPException(
                status_code=400,
                detail="Could not extract text from this PDF. It may be a scanned/image-only document.",
            )

        text = text[:10_000]
        result = await _analyze_resume(text)
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
                    "ORDER BY s.end_date DESC LIMIT 1"
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
