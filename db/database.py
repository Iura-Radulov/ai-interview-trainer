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
                    "ORDER BY s.end_date DESC LIMIT 1"
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
        total_all = len(all_sessions)
        total_completed = len(completed_sessions)
        total_incomplete = total_all - total_completed

        avg = (
            sum(s.total_score for s in completed_sessions if s.total_score is not None) / total_completed
            if total_completed > 0
            else 0.0
        )

        # Fetch subscription info
        plan_name = "Free"
        max_per_day = 2
        max_per_month = 2
        try:
            sub_result = await sess.execute(
                text(
                    "SELECT tp.name, tp.max_interviews_per_day, tp.max_interviews_per_month "
                    "FROM subscriptions s "
                    "JOIN tariff_plans tp ON s.tariff_plan_id = tp.id "
                    "WHERE s.user_id = :uid AND s.status = 'active' AND s.end_date > datetime('now') "
                    "ORDER BY s.end_date DESC LIMIT 1"
                ),
                {"uid": user.id},
            )
            row = sub_result.one_or_none()
            if row:
                plan_name = row[0]
                max_per_day = row[1]
                max_per_month = row[2]
        except Exception:
            pass  # fallback to Free

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
            "total_completed": total_completed,
            "total_incomplete": total_incomplete,
            "avg_score": avg,
            "plan_name": plan_name,
            "max_per_day": max_per_day,
            "max_per_month": max_per_month,
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
                "SELECT id, name, price, max_interviews_per_month, features, stripe_price_id, star_price "
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
            }
            for r in rows
        ]


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
