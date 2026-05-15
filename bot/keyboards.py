"""Inline keyboard builders for all bot interactions."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import config


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
    return InlineKeyboardMarkup(rows)
