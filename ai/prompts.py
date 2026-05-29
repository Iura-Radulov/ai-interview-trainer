"""GPT-4o system prompts and prompt builders for each interview phase."""

from typing import Optional

_LANGUAGE_MAP = {
    "en": "Respond in English.",
    "ru": ("Отвечай на русском языке. Все вопросы, фидбек и оценка должны быть на русском. "
           "Технические термины можно оставлять на английском (например, REST API, React, TypeScript)."),
}

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

{company_context}

Rules:
- Mix question types across the session: Technical (60 %), Behavioral (20 %), System Design (20 %)
- Difficulty must suit {level} level
- The question must be clear and unambiguous
- {language_instruction}

Respond with ONLY valid JSON — no markdown fences, no extra text:
{{
  "question": "<question text>",
  "category": "<Technical | Behavioral | System Design | Coding>",
  "expected_topics": ["<topic>", "..."],
  "difficulty": "<Easy | Medium | Hard>"
}}"""

_BEHAVIORAL_QUESTION_SYSTEM = """\
You are an expert behavioral interviewer with 10+ years of experience conducting interviews at top tech companies (Google, Amazon, Meta, Microsoft, Apple, Netflix).
Generate a SINGLE behavioral interview question for a {role} professional at {level} level.
This is question {question_number} of 5.

Previously asked questions (avoid repeating the same topic):
{previous_questions}

{company_context}

Interview method: STAR (Situation, Task, Action, Result)

Rules:
- ALL 5 questions must be behavioral — NO technical questions at all
- Cover different competencies across the session: Leadership, Conflict Resolution, Communication, Problem Solving, Teamwork, Adaptability, Ownership, Growth Mindset
- Each question must be based on a realistic work scenario
- Questions should prompt the candidate to describe a specific past experience
- Difficulty must suit {level} level
- {language_instruction}

Respond with ONLY valid JSON — no markdown fences, no extra text:
{{
  "question": "<question text — must clearly ask for a past experience example>",
  "category": "<Leadership | Conflict Resolution | Communication | Problem Solving | Teamwork | Adaptability | Ownership | Growth Mindset>",
  "expected_topics": ["<STAR component>", "<skill>", "..."],
  "difficulty": "<Easy | Medium | Hard>"
}}"""

_EVALUATION_SYSTEM = """\
You are an expert technical interviewer evaluating a candidate's answer.

Role: {role} developer at {level} level
Question: {question}
Candidate answer: {answer}{timing_section}

Evaluate professionally and constructively.

Scoring guide:
9-10 Exceptional — covers all key points with depth and clarity
7-8  Good — covers main points with minor gaps
5-6  Adequate — covers basics but lacks depth
3-4  Weak — major gaps in understanding
1-2  Very poor or incorrect

{language_instruction}

Respond with ONLY valid JSON:
{{
  "score": <integer 1-10>,
  "feedback": "<2-3 sentence overall assessment>",
  "strengths": ["<strength>", "..."],
  "improvements": ["<area>", "..."],
  "tip": "<one specific actionable tip>"{timing_json}
}}"""

_BEHAVIORAL_EVALUATION_SYSTEM = """\
You are an expert behavioral interviewer evaluating a candidate's STAR (Situation, Task, Action, Result) answer.

Role: {role} professional at {level} level
Question: {question}
Candidate answer: {answer}

Evaluate using the STAR method framework:

S — Situation: Did they clearly describe the context/background?
T — Task: Did they explain their specific responsibility/challenge?
A — Action: Did they detail the concrete steps THEY took? (not what the team did)
R — Result: Did they share the outcome with specific metrics/impact where possible?

Scoring guide:
9-10 Exceptional — all STAR components fully present with specific, impressive results
7-8  Good — most STAR components solid, result could be stronger
5-6  Adequate — some STAR components missing or vague
3-4  Weak — major STAR components missing
1-2  Very poor — no clear structure, no specific example

{language_instruction}

Respond with ONLY valid JSON:
{{
  "score": <integer 1-10 overall>,
  "feedback": "<2-3 sentence assessment focusing on STAR quality>",
  "strengths": ["<strength in STAR structure>", "..."],
  "improvements": ["<area to improve in their STAR approach>", "..."],
  "tip": "<one specific actionable tip to improve their STAR answers>",
  "star_analysis": {{
    "situation_score": <integer 1-10>,
    "task_score": <integer 1-10>,
    "action_score": <integer 1-10>,
    "result_score": <integer 1-10>,
    "situation_feedback": "<brief feedback on situation component>",
    "task_feedback": "<brief feedback on task component>",
    "action_feedback": "<brief feedback on action component>",
    "result_feedback": "<brief feedback on result component>"
  }}
}}"""

_SUMMARY_SYSTEM = """\
You are an expert technical interviewer providing a post-session debrief.

Role: {role} developer at {level} level
Average score: {avg_score:.1f}/10

Session Q&A:
{qa_summary}

{language_instruction}

Respond with ONLY valid JSON:
{{
  "overall_assessment": "<2-3 sentence assessment>",
  "key_strengths": ["<strength>", "<strength>", "<strength>"],
  "key_improvements": ["<area>", "<area>", "<area>"],
  "topics_to_study": ["<topic>", "<topic>", "<topic>", "<topic>"],
  "overall_rating": "<Excellent | Good | Needs Improvement | Significant Work Required>"
}}"""

_BEHAVIORAL_SUMMARY_SYSTEM = """\
You are an expert behavioral interview coach providing a post-session debrief focused on STAR (Situation, Task, Action, Result) method improvement.

Role: {role} professional at {level} level
Average score: {avg_score:.1f}/10

Session Q&A:
{qa_summary}

{language_instruction}

Analyze the STAR quality across all answers and provide competency-level scoring.

Respond with ONLY valid JSON:
{{
  "overall_assessment": "<2-3 sentence assessment focusing on STAR/behavioral growth areas>",
  "key_strengths": ["<behavioral strength>", "<strength>", "<strength>"],
  "key_improvements": ["<area to improve in behavioral answers>", "<area>", "<area>"],
  "topics_to_study": ["<competency to practice>", "<competency>", "<topic>", "<topic>"],
  "overall_rating": "<Excellent | Good | Needs Improvement | Significant Work Required>",
  "star_breakdown": {{
    "situation": <average situation score 0-10>,
    "task": <average task score 0-10>,
    "action": <average action score 0-10>,
    "result": <average result score 0-10>,
    "overall_star_score": <overall STAR average 0-10>
  }},
  "competency_scores": {{
    "<competency name>": <average score 0-10>,
    "<competency name>": <average score 0-10>
  }}
}}"""


def get_question_prompt(
    role: str,
    level: str,
    question_number: int,
    previous_questions: list[str],
    language: str = "en",
    company_context: str = "",
    mode: str = "technical",
) -> str:
    """Return a filled system prompt for question generation."""
    prev = "\n".join(f"- {q}" for q in previous_questions) if previous_questions else "None"
    lang_inst = _LANGUAGE_MAP.get(language, _LANGUAGE_MAP["en"])

    if mode == "behavioral":
        return _BEHAVIORAL_QUESTION_SYSTEM.format(
            role=role,
            level=level,
            question_number=question_number,
            previous_questions=prev,
            company_context=company_context,
            language_instruction=lang_inst,
        )

    return _QUESTION_SYSTEM.format(
        role=role,
        level=level,
        question_number=question_number,
        previous_questions=prev,
        role_context=_ROLE_CONTEXT.get(
            role,
            f"Role: {role}. Generate relevant interview questions based on this role's typical responsibilities, required skills, tools, and domain knowledge at {level} level. Adapt the question content to match this specific role.",
        ),
        company_context=company_context,
        language_instruction=lang_inst,
    )


def get_evaluation_prompt(
    role: str,
    level: str,
    question: str,
    answer: str,
    language: str = "en",
    time_taken_seconds: int | None = None,
    mode: str = "technical",
) -> str:
    """Return a filled system prompt for answer evaluation."""
    lang_inst = _LANGUAGE_MAP.get(language, _LANGUAGE_MAP["en"])

    if mode == "behavioral":
        return _BEHAVIORAL_EVALUATION_SYSTEM.format(
            role=role,
            level=level,
            question=question,
            answer=answer,
            language_instruction=lang_inst,
        )

    if time_taken_seconds is not None:
        timing_section = (
            f"\n\nAnswer time: {time_taken_seconds} seconds\n"
            "Consider whether the candidate answered too quickly (rushed, insufficient depth),\n"
            "too slowly (hesitation, lack of fluency), or at a good pace for this question type."
        )
        timing_json = ',\n  "timing_analysis": "<brief 1-sentence assessment of response speed>"'
    else:
        timing_section = ""
        timing_json = ""

    return _EVALUATION_SYSTEM.format(
        role=role,
        level=level,
        question=question,
        answer=answer,
        timing_section=timing_section,
        timing_json=timing_json,
        language_instruction=lang_inst,
    )


def get_summary_prompt(
    role: str,
    level: str,
    answers: list[dict],
    avg_score: float,
    language: str = "en",
    mode: str = "technical",
) -> str:
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
    qa_summary = "\n\n".join(lines)
    lang_inst = _LANGUAGE_MAP.get(language, _LANGUAGE_MAP["en"])

    if mode == "behavioral":
        return _BEHAVIORAL_SUMMARY_SYSTEM.format(
            role=role,
            level=level,
            avg_score=avg_score,
            qa_summary=qa_summary,
            language_instruction=lang_inst,
        )

    return _SUMMARY_SYSTEM.format(
        role=role,
        level=level,
        avg_score=avg_score,
        qa_summary=qa_summary,
        language_instruction=lang_inst,
    )
