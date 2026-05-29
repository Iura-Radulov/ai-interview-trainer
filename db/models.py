"""SQLAlchemy ORM models for the interview trainer database."""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    # Allow legacy Column()-style annotations alongside Mapped[] in SQLAlchemy 2.x
    __allow_unmapped__ = True


class User(Base):
    """Registered Telegram users."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(Integer, unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    preferred_role = Column(String(50), nullable=True)
    preferred_language = Column(String(10), nullable=True, default="en")
    preferred_voice = Column(String(20), nullable=True, default="alloy")
    preferred_ui_language = Column(String(10), nullable=True, default="en")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    sessions = relationship("Session", back_populates="user", lazy="select")


class Session(Base):
    """A single interview session."""

    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String(50), nullable=False)
    experience_level = Column(String(50), nullable=False)
    mode = Column(String(20), nullable=False, server_default="technical")  # "technical" or "behavioral"
    company_id = Column(String(50), nullable=True)  # company set key (general, google, amazon, etc.)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    total_score = Column(Float, nullable=True)
    completed = Column(Boolean, default=False, nullable=False)

    user = relationship("User", back_populates="sessions")
    answers = relationship(
        "Answer",
        back_populates="session",
        order_by="Answer.question_number",
    )


class Feedback(Base):
    """User feedback messages stored in the shared SQLite."""

    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(Integer, nullable=False)
    username = Column(String(255), nullable=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Answer(Base):
    """A single question-answer pair within a session."""

    __tablename__ = "answers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    question_number = Column(Integer, nullable=False)
    question_text = Column(Text, nullable=False)
    user_answer = Column(Text, nullable=False)
    score = Column(Integer, nullable=False)
    feedback = Column(Text, nullable=False)
    strengths = Column(Text, nullable=True)    # JSON-encoded list
    improvements = Column(Text, nullable=True)  # JSON-encoded list
    tip = Column(Text, nullable=True)
    category = Column(String(100), nullable=True)
    answered_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("Session", back_populates="answers")
