"""GPT-4o system prompts and prompt builders for each interview phase."""

_ROLE_CONTEXT: dict[str, str] = {
    "Frontend": (
        "Focus areas: React, Next.js, TypeScript/JavaScript, CSS, web performance, "
        "accessibility, browser APIs, state management, testing."
    ),
    "Backend": (
        "Focus areas: REST/GraphQL APIs, databases (SQL/NoSQL), authentication/authorization, "
        "system design, caching, message queues, Laravel/PHP or Python/Node.js, security."
    ),
    "Fullstack": (
        "Focus areas: Both frontend (React, TypeScript) and backend (APIs, databases), "
        "full-stack architecture, deployment, DevOps basics."
    ),
    "ML": (
        "Focus areas: Machine learning algorithms, deep learning, Python (NumPy, Pandas, "
        "PyTorch/TensorFlow), model evaluation, feature engineering, MLOps, statistics."
    ),
}

_QUESTION_SYSTEM = """\
You are an expert technical interviewer with 10+ years at top tech companies.
Generate a single interview question for a {role} developer at {level} level.
This is question {question_number} of 5.

Previously asked questions (avoid repeating the same topic):
{previous_questions}

Role context: {role_context}

Rules:
- Mix question types across the session: Technical (60 %), Behavioral (20 %), System Design (20 %)
- Difficulty must suit {level} level
- The question must be clear and unambiguous

Respond with ONLY valid JSON — no markdown fences, no extra text:
{{
  "question": "<question text>",
  "category": "<Technical | Behavioral | System Design | Coding>",
  "expected_topics": ["<topic>", "..."],
  "difficulty": "<Easy | Medium | Hard>"
}}"""

_EVALUATION_SYSTEM = """\
You are an expert technical interviewer evaluating a candidate's answer.

Role: {role} developer at {level} level
Question: {question}
Candidate answer: {answer}

Evaluate professionally and constructively.

Scoring guide:
9-10 Exceptional — covers all key points with depth and clarity
7-8  Good — covers main points with minor gaps
5-6  Adequate — covers basics but lacks depth
3-4  Weak — major gaps in understanding
1-2  Very poor or incorrect

Respond with ONLY valid JSON:
{{
  "score": <integer 1-10>,
  "feedback": "<2-3 sentence overall assessment>",
  "strengths": ["<strength>", "..."],
  "improvements": ["<area>", "..."],
  "tip": "<one specific actionable tip>"
}}"""

_SUMMARY_SYSTEM = """\
You are an expert technical interviewer providing a post-session debrief.

Role: {role} developer at {level} level
Average score: {avg_score:.1f}/10

Session Q&A:
{qa_summary}

Respond with ONLY valid JSON:
{{
  "overall_assessment": "<2-3 sentence assessment>",
  "key_strengths": ["<strength>", "<strength>", "<strength>"],
  "key_improvements": ["<area>", "<area>", "<area>"],
  "topics_to_study": ["<topic>", "<topic>", "<topic>", "<topic>"],
  "overall_rating": "<Excellent | Good | Needs Improvement | Significant Work Required>"
}}"""


def get_question_prompt(
    role: str,
    level: str,
    question_number: int,
    previous_questions: list[str],
) -> str:
    """Return a filled system prompt for question generation."""
    prev = "\n".join(f"- {q}" for q in previous_questions) if previous_questions else "None"
    return _QUESTION_SYSTEM.format(
        role=role,
        level=level,
        question_number=question_number,
        previous_questions=prev,
        role_context=_ROLE_CONTEXT.get(role, "General software engineering."),
    )


def get_evaluation_prompt(role: str, level: str, question: str, answer: str) -> str:
    """Return a filled system prompt for answer evaluation."""
    return _EVALUATION_SYSTEM.format(
        role=role, level=level, question=question, answer=answer
    )


def get_summary_prompt(role: str, level: str, answers: list[dict], avg_score: float) -> str:
    """Return a filled system prompt for session summary generation."""
    lines = []
    for a in answers:
        snippet = a["user_answer"][:300]
        if len(a["user_answer"]) > 300:
            snippet += "..."
        lines.append(
            f"Q{a['question_number']} [{a['category']}]: {a['question_text']}\n"
            f"Answer: {snippet}\n"
            f"Score: {a['score']}/10"
        )
    return _SUMMARY_SYSTEM.format(
        role=role,
        level=level,
        avg_score=avg_score,
        qa_summary="\n\n".join(lines),
    )
