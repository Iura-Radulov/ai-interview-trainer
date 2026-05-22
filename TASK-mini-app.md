# Telegram Mini App — MVP

## Overview
Create a Telegram Mini App for the AI Interview Trainer. Users open the Mini App inside Telegram, select their role/level, answer 5 interview questions, get AI-evaluated feedback in real-time, and view their session summary + profile stats.

The Mini App shares the existing SQLite database and AI modules with the Python bot.

## Architecture

```
Telegram (Mini App) ← WebView → Next.js Frontend (:3000)
                                    ↓ API calls
                              FastAPI Backend (:8000)
                                    ↓
                  ┌─────────────────┼─────────────────┐
              SQLite DB        OpenAI API       Bot's AI modules
```

## Part 1: FastAPI Backend (`~/projects/ai-interview-trainer/api/`)

Create directory `~/projects/ai-interview-trainer/api/` with a FastAPI server.

### Dependencies (api/requirements.txt)
```
fastapi==0.115.0
uvicorn[standard]==0.30.0
python-dotenv==1.0.1
python-telegram-bot==21.10
pyTelegramBotAPI==4.26.0
```

### API Endpoints

All endpoints return JSON. Auth is via Telegram init data header `X-Telegram-Init-Data`.

#### POST /api/auth
Validate Telegram init data using the BOT_TOKEN (loaded from `config.py`).
- Input: `{"init_data": "query_id=...&auth_date=...&hash=..."}`
- Output: `{"ok": true, "user": {"id": 123, "username": "...", "first_name": "..."}}`
- Creates user in DB if not exists (reuse `db/models.py` `User` model)
- If init data is invalid: `{"ok": false, "error": "Invalid authentication"}`

#### POST /api/interview/start
Start new interview session.
- Auth required
- Input: `{"role": "Frontend", "level": "Mid"}`
- Calls `ai/interviewer.generate_question()` to get first question
- Creates `Session` in DB (not completed yet)
- Output: `{"session_id": 1, "question": {...}, "question_number": 1}`

#### POST /api/interview/answer
Submit answer to current question, get evaluation + next question.
- Auth required  
- Input: `{"session_id": 1, "answer": "..."}`
- Calls `ai/interviewer.evaluate_answer()` 
- Saves `Answer` to DB
- If question_number < 5: calls `generate_question()` for next question
- If question_number == 5: marks session completed, calls `generate_summary()`
- Output (mid-session): `{"done": false, "evaluation": {...}, "next_question": {...}, "question_number": 2}`
- Output (final): `{"done": true, "evaluation": {...}, "summary": {...}}`

#### GET /api/interview/{session_id}
Get session details (for resuming or viewing).
- Auth required
- Output: `{"session": {...}, "answers": [...], "summary": {...}}`

#### GET /api/profile
Get user's stats.
- Auth required
- Output: `{"total_sessions": 5, "avg_score": 7.2, "recent_sessions": [...]}`

#### GET /api/roles
Get available roles and levels.
- Output: `{"roles": ["Frontend", "Backend", "Fullstack", "ML"], "levels": ["Junior", "Mid", "Senior"]}`

### CORS
Allow all origins (for dev). In production, restrict to the Mini App domain.

### Running
`cd ~/projects/ai-interview-trainer && source venv/bin/activate && pip install -r api/requirements.txt && uvicorn api.main:app --host 0.0.0.0 --port 8000`

### Key Implementation Notes
- Import existing modules: `from db.models import Base, User, Session, Answer`, `from db.database import get_session as get_db_session`
- Import AI logic: `from ai.interviewer import generate_question, evaluate_answer, generate_summary`
- Import config: `import config`
- Use `async def` for all endpoints
- The existing SQLite database is at `./data/interviews.db` (relative to the project root)
- Session state is persistent in DB — no in-memory state needed
- For Telegram init data validation: use `hashlib.hmac` with the bot token as secret key. Validate `auth_date` is not older than 86400 seconds (24h). The init data is sorted alphabetically by key, joined with `\n`, then HMAC-SHA256 signed with a key that is HMAC-SHA256("WebAppData", bot_token)

## Part 2: Next.js Frontend (`~/projects/interview-mini-app/`)

Create directory `~/projects/interview-mini-app/` as a standalone Next.js project.

### Setup
```bash
cd ~/projects/
npx create-next-app@latest interview-mini-app --typescript --tailwind --eslint --app --src-dir --no-import-alias --use-npm
```

### Dependencies (package.json)
- `next` (latest)
- `react`, `react-dom` (included)
- `@telegram-apps/sdk` — Telegram Mini App SDK

### Pages/Structure

```
src/
├── app/
│   ├── layout.tsx          ← Global layout with Telegram theme
│   ├── page.tsx            ← Landing: role + level selection
│   ├── interview/
│   │   └── page.tsx        ← Interview flow (question → answer → feedback)
│   ├── summary/
│   │   └── page.tsx        ← Session summary
│   └── profile/
│       └── page.tsx        ← User statistics
├── components/
│   ├── TelegramProvider.tsx   ← Telegram WebApp init provider
│   ├── StartScreen.tsx        ← Role + level selector
│   ├── QuestionCard.tsx       ← Question display + answer input
│   ├── EvaluationCard.tsx     ← Feedback display after each answer
│   ├── SummaryCard.tsx        ← Final session summary
│   ├── ProfileStats.tsx       ← User statistics display
│   ├── ProgressBar.tsx        ← Question progress (1/5, 2/5...)
│   └── LoadingSpinner.tsx     ← Loading state
├── lib/
│   ├── api.ts                 ← API client (fetch wrapper)
│   └── telegram.ts            ← Telegram SDK helpers
└── types/
    └── index.ts               ← TypeScript types
```

### Design Requirements
- **Telegram-native look** — use Telegram's theme parameters (`window.Telegram.WebApp.themeParams`):
  - `bg_color` for backgrounds
  - `text_color` for text
  - `hint_color` for secondary text
  - `button_color` / `button_text_color` for primary actions
  - Support dark mode automatically via Telegram
- **Mobile-first** — optimized for mobile screens (320-428px width)
- **Minimal animations** — smooth transitions between questions
- **Expandable textarea** — answer input grows with text
- **Character counter** on answer input (max 2000 chars)
- **Clear error states** — messages if API is down

### Interview Flow (User Journey)

1. **Start Screen** (page.tsx):
   - Welcome text: "AI Interview Practice"
   - Role selector (cards): Frontend, Backend, Fullstack, ML
   - Level selector: Junior, Mid, Senior
   - "Start Interview" button
   - "My Profile" link

2. **Interview** (/interview):
   - Progress bar: "Question 2 of 5"
   - Category + difficulty badge
   - Question text (centered, readable)
   - Textarea for answer (with Telegram keyboard handling)
   - "Submit Answer" button (disabled while empty)
   - After submit: Loading spinner → Evaluation card appears
   - Evaluation shows: score (1-10), feedback, strengths, improvements, tip
   - "Next Question" button after evaluation
   - After question 5: "View Summary" button

3. **Summary** (/summary):
   - Overall score (animated counter 0 → final score)
   - Per-question breakdown (expandable cards)
   - Key strengths + improvements
   - Topics to study
   - Overall rating badge
   - "Practice Again" button → redirects to start page
   - "View Profile" link

4. **Profile** (/profile):
   - Total sessions count
   - Average score
   - Recent sessions list (clickable → session detail)
   - "Start New Interview" button
   - Back to interview link

### API Client (`src/lib/api.ts`)
- Base URL: configurable (default `http://89.167.22.75:8000`)
- `setInitData(initData)` — store Telegram init data
- `auth()` — POST /api/auth
- `startInterview(role, level)` — POST /api/interview/start
- `submitAnswer(sessionId, answer)` — POST /api/interview/answer
- `getSession(sessionId)` — GET /api/interview/{id}
- `getProfile()` — GET /api/profile
- `getRoles()` — GET /api/roles

All authenticated requests include `X-Telegram-Init-Data` header.

### Telegram Integration (`src/lib/telegram.ts`)
- Export `getTelegram()` — returns `window.Telegram.WebApp`
- Export `getInitData()` — returns raw init data string
- Export `expand()` — expand Mini App to full height
- Export `showMainButton(text, callback)` — show Telegram main button
- Export `hideMainButton()` — hide main button
- Export `showAlert(message)` — show Telegram native alert
- Export `ready()` — notify Telegram that Mini App is loaded
- Export `close()` — close Mini App
- Export `getTheme()` — get current Telegram theme params

### TelegramProvider (`src/components/TelegramProvider.tsx`)
- Client component
- Calls `Telegram.WebApp.ready()` and `Telegram.WebApp.expand()` on mount
- Calls `/api/auth` with `initData` on mount
- Provides auth context to child components
- Shows loading spinner while authenticating
- Shows error if auth fails

### Error Handling
- All API calls wrapped in try/catch
- Network errors show "Connection lost. Check your internet." message
- Rate limit errors show "Daily limit reached. Try again tomorrow."
- Auth errors show "Session expired. Please reopen the Mini App."
- Auto-retry on 5xx errors (up to 3 times with 1s delay)

### TypeScript Types (`src/types/index.ts`)
```typescript
export interface TelegramUser {
  id: number;
  username?: string;
  first_name?: string;
}

export interface Question {
  question: string;
  category: string;
  expected_topics: string[];
  difficulty: string;
}

export interface Evaluation {
  score: number;
  feedback: string;
  strengths: string[];
  improvements: string[];
  tip: string;
}

export interface InterviewSession {
  id: number;
  role: string;
  experience_level: string;
  started_at: string;
  completed: boolean;
  total_score?: number;
}

export interface SessionSummary {
  overall_assessment: string;
  key_strengths: string[];
  key_improvements: string[];
  topics_to_study: string[];
  overall_rating: string;
}

export interface ProfileData {
  total_sessions: number;
  avg_score: number;
  recent_sessions: InterviewSession[];
}

export interface ApiError {
  ok: false;
  error: string;
}
```

## Steps for Implementation

### Step 1: FastAPI Backend
1. Create `~/projects/ai-interview-trainer/api/` directory
2. Create `api/__init__.py`
3. Create `api/main.py` — FastAPI app with CORS, startup, all routes
4. Create `api/auth.py` — Telegram init data validation helper
5. Create `api/routes.py` — All API route handlers
6. Test: `uvicorn api.main:app --port 8000` and `curl http://localhost:8000/api/roles`
7. Install requirements: `source venv/bin/activate && pip install fastapi uvicorn python-telegram-bot`

### Step 2: Next.js Frontend
1. Create Next.js project in `~/projects/interview-mini-app/`
2. Install `@telegram-apps/sdk`
3. Create `src/lib/api.ts`, `src/lib/telegram.ts`
4. Create `src/types/index.ts`
5. Create `src/components/TelegramProvider.tsx`
6. Create `src/app/layout.tsx` with TelegramProvider
7. Create `src/app/page.tsx` — Start screen
8. Create `src/app/interview/page.tsx` — Interview flow
9. Create `src/app/summary/page.tsx` — Summary
10. Create `src/app/profile/page.tsx` — Profile
11. Build and verify: `npm run build`

### Step 3: Integration Test
1. Start FastAPI: `uvicorn api.main:app --host 0.0.0.0 --port 8000`
2. Start Next.js: `npm run dev` (port 3000)
3. Set Mini App URL in BotFather to `http://89.167.22.75:3000`
4. Open Mini App in Telegram and test the full flow

## Telemetry
- `BOT_TOKEN` already exists in `.env`
- All AI logic already exists in `ai/interviewer.py`, `ai/prompts.py`
- DB models already exist in `db/models.py`
- Database path: `./data/interviews.db`

## What NOT to do
- Do NOT modify any existing bot files (bot/, ai/, db/ without explicit need)
- Do NOT create new database tables — reuse the existing models
- Do NOT add user registration flow — auth is via Telegram init data only
- Do NOT implement payment or subscription logic in MVP
- Do NOT add WebSocket or real-time features
