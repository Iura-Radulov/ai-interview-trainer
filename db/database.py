"""Async database helpers using SQLAlchemy + aiosqlite."""
import json
import logging
import os
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import config
from db.models import Answer, Base, Session, StudyPlan, StudyPlanDay, StudyPlanSession, User

logger = logging.getLogger(__name__)

engine = create_async_engine(
    f"sqlite+aiosqlite:///{config.DATABASE_PATH}",
    echo=False,
)
async_session: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)


async def init_db() -> None:
    """Create all tables if they don't exist, making the data directory first."""
    db_dir = os.path.dirname(os.path.abspath(config.DATABASE_PATH))
    os.makedirs(db_dir, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialised at %s", config.DATABASE_PATH)


async def get_or_create_user(
    telegram_id: int,
    username: Optional[str],
    first_name: Optional[str],
) -> User:
    """Return an existing user row or insert a new one."""
    async with async_session() as sess:
        result = await sess.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
            )
            sess.add(user)
            await sess.commit()
            await sess.refresh(user)
        return user


async def update_user_role(telegram_id: int, role: str) -> None:
    """Persist the user's preferred role."""
    async with async_session() as sess:
        result = await sess.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user:
            user.preferred_role = role
            await sess.commit()


async def create_session(user_id: int, role: str, level: str, company_id: Optional[str] = None, mode: str = "technical") -> int:
    """Insert a new interview session and return its primary key."""
    async with async_session() as sess:
        new_session = Session(user_id=user_id, role=role, experience_level=level, company_id=company_id, mode=mode)
        sess.add(new_session)
        await sess.commit()
        await sess.refresh(new_session)
        return new_session.id


async def save_answer(
    session_id: int,
    question_number: int,
    question_text: str,
    user_answer: str,
    score: int,
    feedback: str,
    strengths: list[str],
    improvements: list[str],
    tip: str,
    category: str,
) -> None:
    """Persist one evaluated answer."""
    async with async_session() as sess:
        answer = Answer(
            session_id=session_id,
            question_number=question_number,
            question_text=question_text,
            user_answer=user_answer,
            score=score,
            feedback=feedback,
            strengths=json.dumps(strengths),
            improvements=json.dumps(improvements),
            tip=tip,
            category=category,
        )
        sess.add(answer)
        await sess.commit()


async def complete_session(session_id: int, total_score: float) -> None:
    """Mark a session completed and record the average score."""
    async with async_session() as sess:
        result = await sess.execute(
            select(Session).where(Session.id == session_id)
        )
        session = result.scalar_one_or_none()
        if session:
            session.completed = True
            session.total_score = total_score
            session.completed_at = datetime.utcnow()
            await sess.commit()


async def get_session_answers(session_id: int) -> list[dict]:
    """Return all answers for a session as plain dicts, ordered by question number."""
    async with async_session() as sess:
        result = await sess.execute(
            select(Answer)
            .where(Answer.session_id == session_id)
            .order_by(Answer.question_number)
        )
        rows = result.scalars().all()
        return [
            {
                "question_number": a.question_number,
                "question_text": a.question_text,
                "user_answer": a.user_answer,
                "score": a.score,
                "feedback": a.feedback,
                "strengths": json.loads(a.strengths) if a.strengths else [],
                "improvements": json.loads(a.improvements) if a.improvements else [],
                "tip": a.tip or "",
                "category": a.category or "Technical",
            }
            for a in rows
        ]


async def count_month_sessions(user_id: int) -> int:
    """Count sessions started this month (UTC) by this user."""
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    async with async_session() as sess:
        result = await sess.execute(
            select(func.count(Session.id)).where(
                and_(
                    Session.user_id == user_id,
                    Session.started_at >= month_start,
                )
            )
        )
        return result.scalar_one()


async def check_subscription_limit(telegram_id: int) -> bool:
    """Check if user can start a new interview based on subscription.

    Reads tariff_plans + subscriptions + users from the shared SQLite.
    Returns True if the user can proceed, False if limit reached.
    """
    async with async_session() as sess:
        user_result = await sess.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            return True  # new users get a grace period

        # Check if user has active subscription via Laravel's tables
        try:
            sub_result = await sess.execute(
                text(
                    "SELECT tp.max_interviews_per_month "
                    "FROM subscriptions s "
                    "JOIN tariff_plans tp ON s.tariff_plan_id = tp.id "
                    "WHERE s.user_id = :uid AND s.status = 'active' AND s.end_date > datetime('now') "
                    "ORDER BY s.created_at DESC LIMIT 1"
                ),
                {"uid": user.id},
            )
            row = sub_result.one_or_none()
            if row:
                limit = row[0]
            else:
                limit = 2  # free tier — 2/month
        except Exception:
            limit = 2  # fallback

        # Count this month's sessions
        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        count_result = await sess.execute(
            select(func.count(Session.id)).where(
                Session.user_id == user.id,
                Session.started_at >= month_start,
            )
        )
        month_count = count_result.scalar_one()

        return month_count < limit


PAID_PLANS = frozenset({"Pro", "Premium"})


async def get_user_plan_name(telegram_id: int) -> str:
    """Return the user's active plan name ('Free', 'Pro', 'Premium') or 'Free' if none."""
    async with async_session() as sess:
        user_result = await sess.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            return "Free"

        try:
            sub_result = await sess.execute(
                text(
                    "SELECT tp.name "
                    "FROM subscriptions s "
                    "JOIN tariff_plans tp ON s.tariff_plan_id = tp.id "
                    "WHERE s.user_id = :uid AND s.status = 'active' AND s.end_date > datetime('now') "
                    "ORDER BY s.created_at DESC LIMIT 1"
                ),
                {"uid": user.id},
            )
            row = sub_result.one_or_none()
            if row:
                return row[0]
        except Exception:
            pass
        return "Free"


async def get_user_stats(telegram_id: int) -> dict:
    """Return a stats dict for the profile command, including subscription info."""
    async with async_session() as sess:
        user_result = await sess.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            return {}

        all_sessions_result = await sess.execute(
            select(Session)
            .where(Session.user_id == user.id)
            .order_by(Session.started_at.desc())
        )
        all_sessions = all_sessions_result.scalars().all()

        completed_sessions = [s for s in all_sessions if s.completed == True]  # noqa: E712
        sessions_with_scores = [s for s in completed_sessions if s.total_score is not None]
        total_all = len(all_sessions)
        total_completed = len(completed_sessions)
        total_incomplete = total_all - total_completed

        avg = (
            sum(s.total_score for s in sessions_with_scores) / len(sessions_with_scores)
            if len(sessions_with_scores) > 0
            else 0.0
        )

        # Fetch subscription info
        plan_name = "Free"
        max_per_day = 2
        max_per_month = 2
        payment_type = None
        try:
            sub_result = await sess.execute(
                text(
                    "SELECT tp.name, tp.max_interviews_per_day, tp.max_interviews_per_month, s.payment_type "
                    "FROM subscriptions s "
                    "JOIN tariff_plans tp ON s.tariff_plan_id = tp.id "
                    "WHERE s.user_id = :uid AND s.status = 'active' AND s.end_date > datetime('now') "
                    "ORDER BY s.created_at DESC LIMIT 1"
                ),
                {"uid": user.id},
            )
            row = sub_result.one_or_none()
            if row:
                plan_name = row[0]
                max_per_day = row[1]
                max_per_month = row[2]
                payment_type = row[3]
        except Exception:
            pass  # fallback to Free

        # For completed sessions with NULL total_score, compute from answers
        async def _score_for(session_id: int) -> float | None:
            result = await sess.execute(
                text("SELECT ROUND(AVG(score), 1) FROM answers WHERE session_id = :sid"),
                {"sid": session_id},
            )
            return result.scalar_one()

        recent = []
        for s in all_sessions[:10]:
            score = s.total_score
            if score is None and s.completed:
                try:
                    score = await _score_for(s.id)
                except Exception:
                    pass  # keep None
            recent.append(
                {
                    "id": s.id,
                    "role": s.role,
                    "experience_level": s.experience_level,
                    "mode": getattr(s, 'mode', 'technical'),
                    "total_score": score,
                    "started_at": s.started_at.isoformat() if s.started_at else "",
                    "completed": s.completed,
                }
            )

        return {
            "user_id": user.id,
            "display_name": user.first_name or user.username or "User",
            "preferred_role": user.preferred_role,
            "total_sessions": total_all,
            "total_completed": total_completed,
            "total_incomplete": total_incomplete,
            "avg_score": avg,
            "plan_name": plan_name,
            "max_per_day": max_per_day,
            "max_per_month": max_per_month,
            "payment_type": payment_type,
            "recent_sessions": recent,
        }


async def save_feedback(
    telegram_id: int,
    username: str | None,
    message: str,
) -> None:
    """Persist a user feedback message to the shared SQLite."""
    from db.models import Feedback as FeedbackModel

    async with async_session() as sess:
        fb = FeedbackModel(
            telegram_id=telegram_id,
            username=username,
            message=message,
        )
        sess.add(fb)
        await sess.commit()


async def get_tariff_plans() -> list[dict]:
    """Return all active tariff plans from the shared SQLite."""
    async with async_session() as sess:
        result = await sess.execute(
            text(
                "SELECT id, name, price, max_interviews_per_month, features, stripe_price_id, star_price, features_ru "
                "FROM tariff_plans WHERE is_active = 1 ORDER BY id"
            )
        )
        rows = result.all()
        return [
            {
                "id": r[0],
                "name": r[1],
                "price": float(r[2]),
                "max_per_month": r[3],
                "features": r[4],
                "stripe_price_id": r[5],
                "star_price": r[6] or 0,
                "features_ru": r[7],
            }
            for r in rows
        ]


async def get_interview_roles(telegram_id: Optional[int] = None) -> list[dict]:
    """Return interview roles from DB. If telegram_id is provided, filter by plan."""
    async with async_session() as sess:
        result = await sess.execute(
            text("SELECT id, name_en, name_ru, emoji, is_primary, is_free FROM interview_roles WHERE is_active = 1 ORDER BY id")
        )
        rows = result.all()

        # Determine if user has paid plan
        is_paid = False
        if telegram_id:
            sub_result = await sess.execute(
                text(
                    "SELECT tp.name FROM subscriptions s "
                    "JOIN tariff_plans tp ON s.tariff_plan_id = tp.id "
                    "WHERE s.user_id = (SELECT id FROM users WHERE telegram_id = :tid) "
                    "AND s.status = 'active' AND s.end_date > datetime('now') "
                    "ORDER BY s.created_at DESC LIMIT 1"
                ),
                {"tid": telegram_id},
            )
            row = sub_result.one_or_none()
            is_paid = row and row[0] in ("Pro", "Premium")

        return [
            {
                "id": r[0],
                "name_en": r[1],
                "name_ru": r[2],
                "emoji": r[3] or "",
                "is_primary": bool(r[4]),
                "is_free": bool(r[5]),
                "available": is_paid or bool(r[5]),
            }
            for r in rows
        ]


async def get_companies(telegram_id: Optional[int] = None) -> list[dict]:
    """Return available company sets. If telegram_id is provided, filter by plan."""
    is_paid = False
    if telegram_id:
        async with async_session() as sess:
            sub_result = await sess.execute(
                text(
                    "SELECT tp.name FROM subscriptions s "
                    "JOIN tariff_plans tp ON s.tariff_plan_id = tp.id "
                    "WHERE s.user_id = (SELECT id FROM users WHERE telegram_id = :tid) "
                    "AND s.status = 'active' AND s.end_date > datetime('now') "
                    "ORDER BY s.created_at DESC LIMIT 1"
                ),
                {"tid": telegram_id},
            )
            row = sub_result.one_or_none()
            is_paid = row and row[0] in ("Pro", "Premium")

    async with async_session() as sess:
        result = await sess.execute(
            text(
                "SELECT slug, name_en, name_ru, emoji, is_free, sort_order "
                "FROM company_sets WHERE is_active = 1 ORDER BY sort_order"
            )
        )
        rows = result.fetchall()

    companies = []
    for r in rows:
        available = is_paid or bool(r[4])
        companies.append({
            "id": r[0],
            "name_en": r[1],
            "name_ru": r[2],
            "emoji": r[3] or "",
            "is_free": bool(r[4]),
            "available": available,
        })
    return companies


async def activate_subscription(
    telegram_id: int,
    tariff_plan_id: int,
    payment_type: str = "stars",
) -> None:
    """Create or extend a subscription after successful payment."""
    from datetime import datetime, timedelta

    async with async_session() as sess:
        # Get user
        user_result = await sess.execute(
            text("SELECT id FROM users WHERE telegram_id = :tid"),
            {"tid": telegram_id},
        )
        user = user_result.one_or_none()
        if not user:
            return
        user_id = user[0]

        # Check for existing active subscription to same plan — just extend
        existing = await sess.execute(
            text(
                "SELECT id, end_date FROM subscriptions "
                "WHERE user_id = :uid AND status = 'active' AND end_date > datetime('now') "
                "ORDER BY end_date DESC LIMIT 1"
            ),
            {"uid": user_id},
        )
        row = existing.one_or_none()
        if row:
            # Extend by 30 days from current end_date
            from datetime import datetime as dt
            current_end = dt.fromisoformat(row[1]) if isinstance(row[1], str) else row[1]
            new_end = current_end + timedelta(days=30)
            await sess.execute(
                text(
                    "UPDATE subscriptions SET end_date = :end, payment_type = :pt "
                    "WHERE id = :sid"
                ),
                {"end": new_end.isoformat(), "pt": payment_type, "sid": row[0]},
            )
        else:
            # New subscription
            start = datetime.utcnow()
            end = start + timedelta(days=30)
            await sess.execute(
                text(
                    "INSERT INTO subscriptions (user_id, tariff_plan_id, start_date, end_date, status, payment_type) "
                    "VALUES (:uid, :tpid, :start, :end, 'active', :pt)"
                ),
                {
                    "uid": user_id,
                    "tpid": tariff_plan_id,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "pt": payment_type,
                },
            )
        await sess.commit()


async def create_auth_code(telegram_id: int) -> str:
    """Generate a 6-digit numeric auth code, save to DB, return the code."""
    import secrets
    from datetime import datetime, timedelta

    # Generate a 6-digit code
    code = ''.join(str(secrets.randbelow(10)) for _ in range(6))
    expires_at = (datetime.utcnow() + timedelta(minutes=5)).isoformat()

    async with async_session() as sess:
        await sess.execute(
            text(
                "INSERT INTO auth_tokens (telegram_id, token, expires_at) "
                "VALUES (:tid, :tok, :exp)"
            ),
            {"tid": telegram_id, "tok": code, "exp": expires_at},
        )
        await sess.commit()
    return code


async def create_auth_token(telegram_id: int) -> str:
    """Generate a one-time auth token for web login, save to DB, return the token."""
    import secrets
    from datetime import datetime, timedelta

    token = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + timedelta(minutes=5)).isoformat()

    async with async_session() as sess:
        await sess.execute(
            text(
                "INSERT INTO auth_tokens (telegram_id, token, expires_at) "
                "VALUES (:tid, :tok, :exp)"
            ),
            {"tid": telegram_id, "tok": token, "exp": expires_at},
        )
        await sess.commit()
    return token


# ── User settings ─────────────────────────────────────────────────────────────


async def get_user_settings(telegram_id: int) -> dict:
    """Return preferred_language, preferred_voice and preferred_ui_language for a user."""
    async with async_session() as sess:
        result = await sess.execute(
            text(
                "SELECT preferred_language, preferred_voice, preferred_ui_language "
                "FROM users WHERE telegram_id = :tid"
            ),
            {"tid": telegram_id},
        )
        row = result.one_or_none()
        if row:
            return {
                "language": row[0] or "en",
                "voice": row[1] or "alloy",
                "ui_language": row[2] or "en",
            }
        return {"language": "en", "voice": "alloy", "ui_language": "en"}


async def update_user_settings(
    telegram_id: int,
    language: Optional[str] = None,
    voice: Optional[str] = None,
    ui_language: Optional[str] = None,
) -> dict:
    """Update preferred_language, preferred_voice, and/or preferred_ui_language for a user."""
    sets = {}
    if language is not None:
        sets["preferred_language"] = language
    if voice is not None:
        sets["preferred_voice"] = voice
    if ui_language is not None:
        sets["preferred_ui_language"] = ui_language

    if not sets:
        return await get_user_settings(telegram_id)

    set_clause = ", ".join(f"{k} = :{k}" for k in sets)
    sets["tid"] = telegram_id

    async with async_session() as sess:
        await sess.execute(
            text(f"UPDATE users SET {set_clause} WHERE telegram_id = :tid"),
            sets,
        )
        await sess.commit()

    return await get_user_settings(telegram_id)


async def get_user_companies(telegram_id: int) -> list[dict]:
    """Return user's custom companies for a given Telegram user."""
    async with async_session() as sess:
        result = await sess.execute(
            text(
                "SELECT id, company_name, vacancy_url, position, ai_context, created_at "
                "FROM user_companies WHERE user_id = (SELECT id FROM users WHERE telegram_id = :tid) "
                "ORDER BY created_at DESC"
            ),
            {"tid": telegram_id},
        )
        rows = result.fetchall()
        return [
            {
                "id": r[0],
                "company_name": r[1],
                "vacancy_url": r[2] or "",
                "position": r[3] or "",
                "ai_context": r[4] or "",
                "created_at": r[5] or "",
            }
            for r in rows
        ]


async def create_user_company(
    telegram_id: int,
    company_name: str,
    vacancy_url: str = "",
    position: str = "",
) -> dict:
    """Create a new user company entry and trigger AI context generation."""
    async with async_session() as sess:
        user_result = await sess.execute(
            text("SELECT id FROM users WHERE telegram_id = :tid"),
            {"tid": telegram_id},
        )
        user = user_result.one_or_none()
        if not user:
            raise ValueError("User not found")

        result = await sess.execute(
            text(
                "INSERT INTO user_companies (user_id, company_name, vacancy_url, position, ai_context, created_at) "
                "VALUES (:uid, :name, :url, :pos, '', datetime('now'))"
            ),
            {"uid": user[0], "name": company_name, "url": vacancy_url, "pos": position},
        )
        await sess.commit()

        company_id = result.lastrowid
        return {
            "id": company_id,
            "company_name": company_name,
            "vacancy_url": vacancy_url,
            "position": position,
            "ai_context": "",
        }


async def delete_user_company(company_id: int, telegram_id: int) -> bool:
    """Delete a user company entry if it belongs to the given user."""
    async with async_session() as sess:
        result = await sess.execute(
            text(
                "DELETE FROM user_companies WHERE id = :cid AND user_id = (SELECT id FROM users WHERE telegram_id = :tid)"
            ),
            {"cid": company_id, "tid": telegram_id},
        )
        await sess.commit()
        return result.rowcount > 0


# ── Study Plan CRUD ──────────────────────────────────────────────────────────────


async def get_user_sessions_for_plan(
    db_user_id: int,
    mode: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[dict]:
    """Fetch interview sessions for a user, optionally filtered by mode and date range."""
    conditions = ["s.user_id = :uid"]
    params: dict = {"uid": db_user_id}

    if mode:
        conditions.append("s.mode = :mode")
        params["mode"] = mode
    if date_from:
        conditions.append("s.started_at >= :date_from")
        params["date_from"] = date_from
    if date_to:
        conditions.append("s.started_at < date(:date_to, '+1 day')")
        params["date_to"] = date_to

    where_clause = " AND ".join(conditions)
    sql = (
        f"SELECT s.id, s.role, s.mode, s.started_at, s.completed, s.total_score, "
        f"s.experience_level "
        f"FROM sessions s WHERE {where_clause} ORDER BY s.started_at DESC"
    )

    async with async_session() as sess:
        result = await sess.execute(text(sql), params)
        rows = result.fetchall()
        return [
            {
                "id": r[0],
                "role": r[1],
                "mode": r[2],
                "started_at": str(r[3]) if r[3] else None,
                "completed": bool(r[4]),
                "total_score": r[5],
                "experience_level": r[6],
            }
            for r in rows
        ]


async def get_sessions_with_answers(session_ids: list[int]) -> list[dict]:
    """Fetch sessions with their answers for study plan generation."""
    if not session_ids:
        return []

    ids_placeholders = ", ".join(str(sid) for sid in session_ids)
    sql = (
        f"SELECT s.id, s.role, s.mode, s.experience_level, s.started_at, "
        f"s.completed, s.total_score, "
        f"a.question_number, a.question_text, a.user_answer, a.score, "
        f"a.feedback, a.strengths, a.improvements, a.tip, a.category "
        f"FROM sessions s "
        f"LEFT JOIN answers a ON a.session_id = s.id "
        f"WHERE s.id IN ({ids_placeholders}) "
        f"ORDER BY s.id, a.question_number"
    )

    async with async_session() as sess:
        result = await sess.execute(text(sql))
        rows = result.fetchall()

    sessions_map: dict[int, dict] = {}
    for row in rows:
        sid = row[0]
        if sid not in sessions_map:
            sessions_map[sid] = {
                "id": sid,
                "role": row[1],
                "mode": row[2],
                "experience_level": row[3],
                "started_at": str(row[4]) if row[4] else None,
                "completed": bool(row[5]),
                "total_score": row[6],
                "answers": [],
            }
        if row[7] is not None:
            import json as _json
            sessions_map[sid]["answers"].append({
                "question_number": row[7],
                "question_text": row[8],
                "user_answer": row[9],
                "score": row[10],
                "feedback": row[11],
                "strengths": _json.loads(row[12]) if row[12] else [],
                "improvements": _json.loads(row[13]) if row[13] else [],
                "tip": row[14] or "",
                "category": row[15] or "Technical",
            })

    return list(sessions_map.values())


async def create_study_plan(
    user_id: int,
    title: str,
    description: str,
    focus_areas: list[str],
    duration_days: int,
    source_type: str,
    source_params: dict,
    language: str,
    session_ids: list[int],
    days_data: list[dict],
) -> dict:
    """Create a new study plan with its days and session links."""
    import json as _json

    async with async_session() as sess:
        plan = StudyPlan(
            user_id=user_id,
            title=title,
            description=description,
            focus_areas=_json.dumps(focus_areas),
            duration_days=duration_days,
            status="active",
            progress_percent=0,
            source_type=source_type,
            source_params=_json.dumps(source_params),
            language=language,
        )
        sess.add(plan)
        await sess.flush()

        for day_data in days_data:
            day = StudyPlanDay(
                plan_id=plan.id,
                day_number=day_data["day_number"],
                title=day_data["title"],
                description=day_data.get("description", ""),
                resources=_json.dumps(day_data.get("resources", [])),
                estimated_minutes=day_data.get("estimated_minutes"),
            )
            sess.add(day)

        for sid in session_ids:
            link = StudyPlanSession(plan_id=plan.id, session_id=sid)
            sess.add(link)

        await sess.commit()

        return {
            "id": plan.id,
            "user_id": plan.user_id,
            "title": plan.title,
            "description": plan.description,
            "focus_areas": focus_areas,
            "duration_days": plan.duration_days,
            "status": plan.status,
            "progress_percent": plan.progress_percent,
            "source_type": plan.source_type,
            "source_params": source_params,
            "language": plan.language,
            "created_at": plan.created_at.isoformat() if plan.created_at else None,
        }


async def get_user_study_plans(db_user_id: int) -> list[dict]:
    """Fetch all study plans for a user with day counts and progress."""
    import json as _json

    async with async_session() as sess:
        result = await sess.execute(
            text(
                "SELECT sp.id, sp.title, sp.description, sp.focus_areas, "
                "sp.duration_days, sp.status, sp.progress_percent, "
                "sp.source_type, sp.source_params, sp.language, "
                "sp.created_at, sp.started_at, sp.completed_at, "
                "(SELECT COUNT(*) FROM study_plan_days spd WHERE spd.plan_id = sp.id) as total_days, "
                "(SELECT COUNT(*) FROM study_plan_days spd WHERE spd.plan_id = sp.id AND spd.is_completed = 1) as completed_days "
                "FROM study_plans sp "
                "WHERE sp.user_id = :uid "
                "ORDER BY sp.created_at DESC"
            ),
            {"uid": db_user_id},
        )
        rows = result.fetchall()
        return [
            {
                "id": r[0],
                "title": r[1],
                "description": r[2],
                "focus_areas": _json.loads(r[3]) if r[3] else [],
                "duration_days": r[4],
                "status": r[5],
                "progress_percent": r[6],
                "source_type": r[7],
                "source_params": _json.loads(r[8]) if r[8] else {},
                "language": r[9],
                "created_at": str(r[10]) if r[10] else None,
                "started_at": str(r[11]) if r[11] else None,
                "completed_at": str(r[12]) if r[12] else None,
                "total_days": r[13],
                "completed_days": r[14],
            }
            for r in rows
        ]


async def get_study_plan_detail(plan_id: int, db_user_id: int) -> dict | None:
    """Fetch a study plan with all its days, verifying ownership."""
    import json as _json

    async with async_session() as sess:
        result = await sess.execute(
            text(
                "SELECT sp.id, sp.user_id, sp.title, sp.description, sp.focus_areas, "
                "sp.duration_days, sp.status, sp.progress_percent, "
                "sp.source_type, sp.source_params, sp.language, "
                "sp.created_at, sp.started_at, sp.completed_at "
                "FROM study_plans sp WHERE sp.id = :pid"
            ),
            {"pid": plan_id},
        )
        row = result.one_or_none()
        if not row or row[1] != db_user_id:
            return None

        days_result = await sess.execute(
            text(
                "SELECT id, day_number, title, description, resources, "
                "estimated_minutes, is_completed, completed_at "
                "FROM study_plan_days WHERE plan_id = :pid ORDER BY day_number"
            ),
            {"pid": plan_id},
        )
        days = [
            {
                "id": d[0],
                "day_number": d[1],
                "title": d[2],
                "description": d[3],
                "resources": _json.loads(d[4]) if d[4] else [],
                "estimated_minutes": d[5],
                "is_completed": bool(d[6]),
                "completed_at": str(d[7]) if d[7] else None,
            }
            for d in days_result.fetchall()
        ]

        sess_result = await sess.execute(
            text("SELECT session_id FROM study_plan_sessions WHERE plan_id = :pid"),
            {"pid": plan_id},
        )
        session_ids = [s[0] for s in sess_result.fetchall()]

        return {
            "id": row[0],
            "user_id": row[1],
            "title": row[2],
            "description": row[3],
            "focus_areas": _json.loads(row[4]) if row[4] else [],
            "duration_days": row[5],
            "status": row[6],
            "progress_percent": row[7],
            "source_type": row[8],
            "source_params": _json.loads(row[9]) if row[9] else {},
            "language": row[10],
            "created_at": str(row[11]) if row[11] else None,
            "started_at": str(row[12]) if row[12] else None,
            "completed_at": str(row[13]) if row[13] else None,
            "days": days,
            "session_ids": session_ids,
            "total_days": len(days),
            "completed_days": sum(1 for d in days if d["is_completed"]),
        }


async def update_study_plan_status(plan_id: int, db_user_id: int, status: str) -> bool:
    """Update plan status (active/paused/completed) with ownership check."""
    async with async_session() as sess:
        result = await sess.execute(
            text("SELECT id, user_id FROM study_plans WHERE id = :pid"),
            {"pid": plan_id},
        )
        row = result.one_or_none()
        if not row or row[1] != db_user_id:
            return False

        completed_clause = ", completed_at = datetime('now')" if status == "completed" else ""
        started_clause = ", started_at = datetime('now')" if status == "active" else ""

        await sess.execute(
            text(
                f"UPDATE study_plans SET status = :status{completed_clause}{started_clause} WHERE id = :pid"
            ),
            {"status": status, "pid": plan_id},
        )
        await sess.commit()
        return True


async def mark_study_plan_day(plan_id: int, day_id: int, db_user_id: int) -> bool:
    """Toggle a day as completed and recalculate plan progress."""
    async with async_session() as sess:
        result = await sess.execute(
            text(
                "SELECT sp.id FROM study_plans sp "
                "JOIN study_plan_days spd ON spd.plan_id = sp.id "
                "WHERE sp.id = :pid AND spd.id = :did AND sp.user_id = :uid"
            ),
            {"pid": plan_id, "did": day_id, "uid": db_user_id},
        )
        if not result.one_or_none():
            return False

        await sess.execute(
            text(
                "UPDATE study_plan_days SET is_completed = CASE WHEN is_completed = 1 THEN 0 ELSE 1 END, "
                "completed_at = CASE WHEN is_completed = 0 THEN datetime('now') ELSE NULL END "
                "WHERE id = :did"
            ),
            {"did": day_id},
        )
        await sess.commit()

    await _recalc_plan_progress(plan_id)
    return True


async def _recalc_plan_progress(plan_id: int) -> None:
    """Recalculate progress_percent for a plan based on completed days."""
    async with async_session() as sess:
        result = await sess.execute(
            text(
                "SELECT COUNT(*), SUM(CASE WHEN is_completed = 1 THEN 1 ELSE 0 END) "
                "FROM study_plan_days WHERE plan_id = :pid"
            ),
            {"pid": plan_id},
        )
        row = result.one()
        total = row[0]
        completed = row[1] or 0
        pct = int((completed / total * 100)) if total > 0 else 0

        await sess.execute(
            text("UPDATE study_plans SET progress_percent = :pct WHERE id = :pid"),
            {"pct": pct, "pid": plan_id},
        )
        await sess.commit()
