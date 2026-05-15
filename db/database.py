"""Async database helpers using SQLAlchemy + aiosqlite."""
import json
import logging
import os
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, func, select
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


async def get_user_stats(telegram_id: int) -> dict:
    """Return a stats dict for the profile command."""
    async with async_session() as sess:
        user_result = await sess.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            return {}

        sessions_result = await sess.execute(
            select(Session)
            .where(and_(Session.user_id == user.id, Session.completed == True))  # noqa: E712
            .order_by(Session.completed_at.desc())
        )
        sessions = sessions_result.scalars().all()

        total = len(sessions)
        avg = (
            sum(s.total_score for s in sessions if s.total_score is not None) / total
            if total > 0
            else 0.0
        )

        role_counts: dict[str, int] = {}
        for s in sessions:
            role_counts[s.role] = role_counts.get(s.role, 0) + 1

        recent = [
            {
                "role": s.role,
                "level": s.experience_level,
                "score": s.total_score,
                "date": s.completed_at.strftime("%Y-%m-%d") if s.completed_at else "N/A",
            }
            for s in sessions[:5]
        ]

        return {
            "user_id": user.id,
            "display_name": user.first_name or user.username or "User",
            "preferred_role": user.preferred_role,
            "total_sessions": total,
            "avg_score": avg,
            "recent_sessions": recent,
            "role_breakdown": role_counts,
        }
