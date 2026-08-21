"""Application configuration loaded from environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
# OpenAI key — used ONLY for voice (Whisper STT + TTS), which requires api.openai.com
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
# OrcaRouter chat key + base URL (free models via api.orcarouter.ai/v1)
OPENAI_CHAT_API_KEY: str = os.getenv("OPENAI_CHAT_API_KEY", "")
OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.orcarouter.ai/v1")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")
OPENAI_MODEL_PREMIUM: str = os.getenv("OPENAI_MODEL_PREMIUM", "gpt-5.4")
OPENAI_MODEL_ALT: str = os.getenv("OPENAI_MODEL_ALT", "qwen/qwen3.8-27b-free")
DATABASE_PATH: str = os.getenv("DATABASE_PATH", "./data/interviews.db")
MINI_APP_URL: str = os.getenv("MINI_APP_URL", "https://mini.techinterviewai.com")
FEEDBACK_CHAT_ID: str = os.getenv("FEEDBACK_CHAT_ID", "")
MAX_FREE_INTERVIEWS_PER_MONTH: int = int(os.getenv("MAX_FREE_INTERVIEWS_PER_MONTH", "2"))
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

QUESTIONS_PER_SESSION: int = 5
SESSION_TIMEOUT_MINUTES: int = 30

ROLES: list[str] = ["Frontend", "Backend", "Fullstack", "System Design"]
EXPERIENCE_LEVELS: list[str] = ["Junior", "Mid", "Senior"]

ROLE_EMOJIS: dict[str, str] = {
    "Frontend": "🎨",
    "Backend": "⚙️",
    "Fullstack": "🔄",
    "System Design": "🏗️",
}

LEVEL_EMOJIS: dict[str, str] = {
    "Junior": "🌱",
    "Mid": "🌿",
    "Senior": "🌳",
}
