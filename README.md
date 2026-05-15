# AI Interview Trainer

A Telegram bot that simulates technical interviews for software developers using GPT-4o. Practice Frontend, Backend, Fullstack, and ML interviews with real-time AI feedback.

## Features

- **5-question interview sessions** — mix of Technical, Behavioral, and System Design
- **GPT-4o scoring** — every answer scored 1–10 with strengths, improvements, and a tip
- **Session summary** — overall rating, study topics, and per-question breakdown
- **Progress tracking** — SQLite database stores all sessions and answers
- **Daily rate limit** — configurable (default: 2 sessions/day)

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Register and set your preferred role |
| `/interview` | Start a new interview session |
| `/profile` | View stats and recent sessions |
| `/feedback` | Send feedback to the developers |
| `/help` | Show usage instructions |

## Setup

### Prerequisites

- Python 3.11+
- A Telegram bot token — create one with [@BotFather](https://t.me/BotFather)
- An OpenAI API key with access to GPT-4o

### Installation

```bash
# 1. Clone / enter the project directory
cd ai-interview-trainer

# 2. Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
# Edit .env and fill in BOT_TOKEN and OPENAI_API_KEY
```

### Configuration (`.env`)

```
BOT_TOKEN=your_telegram_bot_token
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4o
DATABASE_PATH=./data/interviews.db
MAX_FREE_INTERVIEWS_PER_DAY=2
LOG_LEVEL=INFO
```

### Run

```bash
python bot/main.py
```

The `data/` directory and SQLite database are created automatically on first run.

### Verify imports (smoke test)

```bash
python -c "from bot.main import *; print(OK)"
```

## Project Structure

```
ai-interview-trainer/
├── bot/
│   ├── main.py              # Entry point and Application setup
│   ├── states.py            # ConversationHandler state enum
│   ├── keyboards.py         # InlineKeyboardMarkup builders
│   └── handlers/
│       ├── start.py         # /start, /help, role-selection callback
│       ├── interview.py     # Full interview ConversationHandler
│       ├── profile.py       # /profile command
│       └── feedback.py      # /feedback ConversationHandler
├── ai/
│   ├── interviewer.py       # GPT-4o API calls (question, evaluate, summary)
│   ├── prompts.py           # System prompt builders per role
│   └── scoring.py           # Markdown message formatters
├── db/
│   ├── models.py            # SQLAlchemy ORM models (User, Session, Answer)
│   └── database.py          # Async CRUD helpers (aiosqlite)
├── config.py                # Environment variable loading
├── requirements.txt
├── .env.example
└── README.md
```

## Tech Stack

- **python-telegram-bot v21** — async bot framework with ConversationHandler
- **OpenAI Python SDK** — GPT-4o with JSON mode for structured output
- **SQLAlchemy 2 + aiosqlite** — fully async SQLite persistence
- **python-dotenv** — environment variable management
