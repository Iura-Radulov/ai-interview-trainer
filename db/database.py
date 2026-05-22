"""Async database helpers using SQLAlchemy + aiosqlite."""
import json
import logging
import os
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import config
from db.models import Answer, Base, Session, User

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


async def create_session(user_id: int, role: str, level: str) -> int:
    """Insert a new interview session and return its primary key."""
    async with async_session() as sess:
        new_session = Session(user_id=user_id, role=role, experience_level=level)
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


async def count_today_sessions(user_id: int) -> int:
    """Count sessions started today (UTC) by this user."""
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    async with async_session() as sess:
        result = await sess.execute(
            select(func.count(Session.id)).where(
                and_(
                    Session.user_id == user_id,
                    Session.started_at >= today_start,
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
                    "SELECT tp.max_interviews_per_day "
                    "FROM subscriptions s "
                    "JOIN tariff_plans tp ON s.tariff_plan_id = tp.id "
                    "WHERE s.user_id = :uid AND s.status = 'active' AND s.end_date > datetime('now') "
                    "ORDER BY s.end_date DESC LIMIT 1"
                ),
                {"uid": user.id},
            )
            row = sub_result.one_or_none()
            if row:
                limit = row[0]
            else:
                limit = 2  # free tier
        except Exception:
            limit = 2  # fallback

        # Count today's sessions
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        count_result = await sess.execute(
            select(func.count(Session.id)).where(
                Session.user_id == user.id,
                Session.started_at >= today_start,
            )
        )
        today_count = count_result.scalar_one()

        return today_count < limit


async def get_user_stats(telegram_id: int) -> dict:
    """Return a stats dict for the profile command."""
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
        total_all = len(all_sessions)
        total_completed = len(completed_sessions)

        avg = (
            sum(s.total_score for s in completed_sessions if s.total_score is not None) / total_completed
            if total_completed > 0
            else 0.0
        )

        role_counts: dict[str, int] = {}
        for s in all_sessions:
            role_counts[s.role] = role_counts.get(s.role, 0) + 1

        recent = [
            {
                "id": s.id,
                "role": s.role,
                "experience_level": s.experience_level,
                "total_score": s.total_score,
                "started_at": s.started_at.isoformat() if s.started_at else "",
                "completed": s.completed,
            }
            for s in all_sessions[:10]
        ]

        return {
            "user_id": user.id,
            "display_name": user.first_name or user.username or "User",
            "preferred_role": user.preferred_role,
            "total_sessions": total_all,
            "avg_score": avg,
            "recent_sessions": recent,
            "role_breakdown": role_counts,
        }


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
