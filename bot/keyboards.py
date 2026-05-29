"""Inline keyboard builders for all bot interactions."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

import config


def _mini_app_button() -> InlineKeyboardButton:
    """Mini App button that opens the web app in Telegram."""
    return InlineKeyboardButton(
        "🚀 Open Mini App",
        web_app=WebAppInfo(url=config.MINI_APP_URL),
    )


def role_keyboard() -> InlineKeyboardMarkup:
    """Role selection keyboard used inside the interview flow."""
    buttons = [
        InlineKeyboardButton(
            f"{config.ROLE_EMOJIS.get(r, '')} {r}",
            callback_data=f"role_{r}",
        )
        for r in config.ROLES
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


def level_keyboard() -> InlineKeyboardMarkup:
    """Experience-level selection keyboard."""
    buttons = [
        InlineKeyboardButton(
            f"{config.LEVEL_EMOJIS.get(lvl, '')} {lvl}",
            callback_data=f"level_{lvl}",
        )
        for lvl in config.EXPERIENCE_LEVELS
    ]
    return InlineKeyboardMarkup([buttons])


def start_role_keyboard() -> InlineKeyboardMarkup:
    """Role selection keyboard used from the /start command (different callback prefix)."""
    buttons = [
        InlineKeyboardButton(
            f"{config.ROLE_EMOJIS.get(r, '')} {r}",
            callback_data=f"set_role_{r}",
        )
        for r in config.ROLES
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton("📄 Upload Resume", callback_data="upload_resume")])
    rows.append([_mini_app_button()])
    return InlineKeyboardMarkup(rows)


def resume_confirm_keyboard() -> InlineKeyboardMarkup:
    """Confirm resume analysis: Start | Edit | Cancel."""
    buttons = [
        [
            InlineKeyboardButton("✅ Start Interview", callback_data="resume_start"),
            InlineKeyboardButton("✏️ Edit", callback_data="resume_edit"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="resume_cancel")],
    ]
    return InlineKeyboardMarkup(buttons)


def _resume_role_keyboard() -> InlineKeyboardMarkup:
    """Role selection keyboard for the resume edit flow (resume_role_ prefix)."""
    buttons = [
        InlineKeyboardButton(
            f"{config.ROLE_EMOJIS.get(r, '')} {r}",
            callback_data=f"resume_role_{r}",
        )
        for r in config.ROLES
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


def _resume_level_keyboard() -> InlineKeyboardMarkup:
    """Level selection keyboard for the resume edit flow (resume_level_ prefix)."""
    buttons = [
        InlineKeyboardButton(
            f"{config.LEVEL_EMOJIS.get(lvl, '')} {lvl}",
            callback_data=f"resume_level_{lvl}",
        )
        for lvl in config.EXPERIENCE_LEVELS
    ]
    return InlineKeyboardMarkup([buttons])
