"""Conversation state constants for python-telegram-bot ConversationHandler."""
from enum import IntEnum


class InterviewState(IntEnum):
    """States for the interview conversation flow."""

    SELECTING_ROLE = 0
    SELECTING_LEVEL = 1
    IN_INTERVIEW = 2


class ResumeState(IntEnum):
    """States for the resume upload and analysis flow."""

    WAITING_PDF = 3
    CONFIRMING = 4
