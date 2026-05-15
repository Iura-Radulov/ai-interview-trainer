"""Application configuration loaded from environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")
DATABASE_PATH: str = os.getenv("DATABASE_PATH", "./data/interviews.db")
MAX_FREE_INTERVIEWS_PER_DAY: int = int(os.getenv("MAX_FREE_INTERVIEWS_PER_DAY", "2"))
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

QUESTIONS_PER_SESSION: int = 5
SESSION_TIMEOUT_MINUTES: int = 30

ROLES: list[str] = ["Frontend", "Backend", "Fullstack", "ML"]
EXPERIENCE_LEVELS: list[str] = ["Junior", "Mid", "Senior"]

ROLE_EMOJIS: dict[str, str] = {
    "Frontend": "🎨",
    "Backend": "⚙️",
    "Fullstack": "🔄",
    "ML": "🤖",
}

LEVEL_EMOJIS: dict[str, str] = {
    "Junior": "🌱",
    "Mid": "🌿",
    "Senior": "🌳",
}
