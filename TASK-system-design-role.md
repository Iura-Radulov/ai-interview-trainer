# TASK: System Design interview role — complete implementation

## Goal
Finish adding "System Design" as a full interview role in the AI Interview Trainer project, replacing the removed "ML" role. All 5 questions must be 100% system design questions with dedicated evaluation criteria.

## What's already done
- config.py: ROLES updated, ROLE_EMOJIS updated
- db/database.py: `get_interview_roles()` reads from DB — no changes needed
- bot/keyboards.py: builds from config.ROLES — no changes needed
- bot/handlers/start.py: welcome message updated
- ai/interviewer.py: fallback questions added (URL shortener, Twitter, WhatsApp, YouTube, Uber)
- ai/resume_analyzer.py: comment updated
- CLAUDE.md: role list updated
- SQLite interview_roles: ML deactivated, System Design set as primary
- Bot restarted

## What must be done

### 1. Fix question generation prompt (`ai/prompts.py`)

In `_QUESTION_SYSTEM` template, the mix rule line:
```
"- Mix question types across the session: Technical (60 %), Behavioral (20 %), System Design (20 %)
```

When role is "System Design", this rule produces wrong question mix. Fix:

**Approach:** Modify `get_question_prompt()` to pass a different `mix_rule` based on role:
- If `role == "System Design"` → `"ALL questions must be system design questions — design a scalable distributed system (e.g., a URL shortener, Twitter, YouTube, chat service, Uber, etc.). Each question should focus on architecture, trade-offs, scalability, and component design."`
- Otherwise → keep existing `"Mix question types across the session: Technical (60 %), Behavioral (20 %), System Design (20 %)"`

The _QUESTION_SYSTEM template needs a `{mix_rule}` placeholder replacing the hardcoded mix line.

### 2. Create System Design evaluation (`ai/prompts.py`)

The current `_EVALUATION_SYSTEM` prompt evaluates answers with generic criteria (depth, clarity). For System Design, add dedicated criteria in `get_evaluation_prompt()`:

```python
if role == "System Design":
    # Use system-design-specific evaluation
    return _SD_EVALUATION_SYSTEM.format(...)
```

Create `_SD_EVALUATION_SYSTEM` with these scoring criteria:
- 9-10: Clear architecture, well-reasoned trade-offs, covers components (DB, cache, API, load balancers, CDN), mentions scalability, fault tolerance, and data flow
- 7-8: Good high-level design, covers main components, some trade-offs discussed, moderate depth
- 5-6: Basic design, missing key components, few or no trade-offs discussed
- 3-4: Vague architecture, missing critical components, no trade-off analysis
- 1-2: No coherent design, wrong approach for the problem

JSON output fields: score, feedback, strengths, improvements, tip (same as existing schema).

### 3. Create System Design summary (`ai/prompts.py`)

Create `_SD_SUMMARY_SYSTEM` for post-session debrief. Same output format as `_SUMMARY_SYSTEM` but analysis focused on system design growth areas (architecture thinking, trade-off reasoning, scalability mindset, component depth).

Update `get_summary_prompt()` to dispatch based on role.

### 4. Update API routes (`api/routes.py`)

The `StartInterviewRequest.mode` field (line 48) defaults to "technical". When `role == "System Design"`, the AI functions need to know this is a system design session. 

The simplest fix: in `start_interview()` (line 184), when `request.role == "System Design"`, force `request.mode = "system_design"` so the AI layer uses the correct prompts. Similarly in the answer flow.

Actually, even simpler: the AI functions (`generate_question`, `evaluate_answer`, `generate_summary`) already check `mode` in their prompt dispatch. Since we're using role-based dispatch (not mode-based), we just need to ensure the flow works. 

**Fix:** In the API routes `start_interview` and `submit_answer`, when `request.role == "System Design"`, pass `mode="system_design"` to `generate_question()`, `evaluate_answer()`, and `generate_summary()`. This way the prompt layer can switch on both `mode` (technical/behavioral/system_design) and the role context.

### 5. Update bot handler (`bot/handlers/interview.py`)

Same issue as API: the bot's `handle_answer()` calls `ai.evaluate_answer()` and `ai.generate_summary()` without passing the role-aware mode. 

**Fix:** In `handle_answer()` and `select_level()`, when `role == "System Design"`, pass `mode="system_design"` to the AI functions.

### 6. Update Mini App types (`src/types/index.ts` in interview-mini-app)

Update `InterviewMode` type (line 8) to include 'system_design':
```typescript
export type InterviewMode = 'technical' | 'behavioral' | 'system_design';
```

Also update `StartInterviewResponse.mode` and `AnswerResponse.mode` types — they use `InterviewMode`.

### 7. Verify nothing else references "ML"

Run a search for `"ML"` and `'ML'` across the whole project to catch any remaining references.

## Files to modify
1. `~/projects/ai-interview-trainer/ai/prompts.py` — SD question prompt, SD evaluation, SD summary, dispatch logic
2. `~/projects/ai-interview-trainer/bot/handlers/interview.py` — pass mode="system_design" for SD role
3. `~/projects/ai-interview-trainer/api/routes.py` — pass mode="system_design" for SD role
4. `~/projects/interview-mini-app/src/types/index.ts` — add 'system_design' to InterviewMode

## Do NOT modify
- Any file in `interview-landing/`
- config.py (already done)
- ai/interviewer.py (already done except the tips)
- Bot handlers except interview.py
- Database tables or migrations

## Verification
1. `python3 -c "from ai.prompts import get_question_prompt; p = get_question_prompt('System Design', 'Senior', 1, []); print('Mix rule correct:', 'ALL questions must be' in p or 'Design a scalable' in p)"` — should show True
2. `python3 -c "from ai.prompts import get_evaluation_prompt; p = get_evaluation_prompt('System Design', 'Senior', 'Design X', 'My answer'); print('Has SD criteria:', 'architecture' in p.lower() or 'trade-off' in p.lower() or 'scalab' in p.lower())"` — should show True
3. Bot restart: `sudo systemctl restart interview-bot`
4. Final: `python3 -c "import config; print(config.ROLES); from ai.interviewer import _FALLBACK_QUESTIONS; print('SD fallback:', len(_FALLBACK_QUESTIONS['System Design']), 'questions')"`
