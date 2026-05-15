# AI Interview Trainer

## Project Overview
Telegram bot for AI-powered IT interview practice. Target: global market (English language). Users practice coding, system design, and behavioral interviews with an AI interviewer.

## Tech Stack
- Python 3.11+
- python-telegram-bot v21.x (Telegram Bot API)
- OpenAI API (GPT-4o) for interview simulation
- SQLite (Phase 1) → PostgreSQL (Phase 2)
- FastAPI for AI service layer

## Phase 1 Scope (MVP)
Build a fully functional Telegram bot with:

### Commands
- `/start` — Welcome message, choose role (Frontend/Backend/Fullstack/ML)
- `/interview` — Start a new interview session
- `/profile` — View stats (interviews completed, average score, progress)
- `/help` — Usage instructions
- `/feedback` — Send feedback

### Interview Flow (Conversation)
1. User selects role + experience level (junior/mid/senior)
2. AI asks 5 questions per session (mix of technical and behavioral)
3. After each answer → AI evaluates:
   - Score (1-10)
   - Brief feedback (strength, weakness, tip)
4. After session → Summary with:
   - Overall score
   - Per-question breakdown
   - Improvement suggestions
   - Topics to study

### Question Categories
- **Frontend**: React, Next.js, CSS, JS/TS fundamentals, web perf
- **Backend**: APIs, databases, auth, system design basics, Laravel
- **Fullstack**: Combined frontend + backend questions
- **System Design**: Architecture, scaling, trade-offs
- **Behavioral**: STAR method, leadership, conflict resolution

### Key Features
- GPT-4o with structured output (JSON mode) for consistent scoring
- Conversation state management (python-telegram-bot ConversationHandler)
- Session timeout after 30 min inactivity
- Error handling + retry logic for API calls
- Rate limiting (5 interviews/day for free tier)

### Data Storage (SQLite)
- Users table: telegram_id, username, role, created_at
- Sessions table: user_id, date, questions_asked, total_score, completed
- Answers table: session_id, question_text, user_answer, score, feedback, category

### Project Structure
```
ai-interview-trainer/
├── bot/
│   ├── __init__.py
│   ├── main.py              # Entry point, bot setup
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── start.py         # /start command
│   │   ├── interview.py     # Interview conversation flow
│   │   ├── profile.py       # /profile command
│   │   └── feedback.py      # /feedback command
│   ├── keyboards.py         # Inline keyboards
│   └── states.py            # Conversation states (Enum)
├── ai/
│   ├── __init__.py
│   ├── interviewer.py       # GPT-4o integration
│   ├── prompts.py           # System prompts per role
│   └── scoring.py           # Score calculation & formatting
├── db/
│   ├── __init__.py
│   ├── models.py            # SQLAlchemy/SQLite models
│   └── database.py          # DB connection & helpers
├── config.py                # Env vars, constants
├── requirements.txt
├── .env.example
└── README.md
```

## Code Standards
- Type hints on ALL functions
- Google-style docstrings
- Async where possible (python-telegram-bot is async-native)
- Logging with Python's logging module
- Environment variables via python-dotenv
- Error handling: try/except with meaningful error messages
- Constants in uppercase at module level

## Key Config (via .env)
```
BOT_TOKEN=your_telegram_bot_token
OPENAI_API_KEY=your_openai_key
OPENAI_MODEL=gpt-4o
DATABASE_PATH=./data/interviews.db
MAX_FREE_INTERVIEWS_PER_DAY=2
LOG_LEVEL=INFO
```

## Deliverables
1. Fully functional Telegram bot (run with `python bot/main.py`)
2. README with setup instructions
3. Requirements file
4. All source code with type hints and docstrings
