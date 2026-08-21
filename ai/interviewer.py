"""GPT-4o integration: question generation, answer evaluation, summary."""
import json
import logging
from typing import Optional

from openai import AsyncOpenAI

import config
from ai.prompts import (
    get_evaluation_prompt,
    get_question_prompt,
    get_sd_evaluation_prompt,
    get_sd_step_prompt,
    get_sd_summary_prompt,
    get_summary_prompt,
    _SD_STEP_NAMES,
)

logger = logging.getLogger(__name__)


# ── Guided System Design (7-step flow) ──────────────────────────────────


async def generate_sd_step(
    problem: str,
    role: str,
    level: str,
    step: int,
    previous_context: str = "",
    company_context: str = "",
    language: str = "en",
    model: Optional[str] = None,
) -> dict:
    """Generate the AI prompt for a guided SD step.

    Returns: {step, step_name, prompt, hints, evaluation_criteria}
    """
    client = _get_client()
    system_prompt = get_sd_step_prompt(
        problem=problem,
        role=role,
        level=level,
        step=step,
        previous_context=previous_context,
        company_context=company_context,
        language=language,
    )
    try:
        response = await client.chat.completions.create(
            model=model or config.OPENAI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Generate step {step} of 7."},
            ],
            temperature=0.7,
            max_completion_tokens=600,
        )
        data = json.loads(response.choices[0].message.content)
        return {
            "step": data.get("step", step),
            "step_name": data.get("step_name", f"Step {step}"),
            "prompt": data.get("prompt", ""),
            "hints": data.get("hints", []),
            "evaluation_criteria": data.get("evaluation_criteria", []),
        }
    except Exception as exc:
        logger.error("generate_sd_step failed: %s", exc)
        return _fallback_sd_step(step)


async def evaluate_sd_step(
    problem: str,
    step: int,
    step_name: str,
    level: str,
    step_prompt: str,
    answer: str,
    previous_context: str = "",
    language: str = "en",
    model: Optional[str] = None,
) -> dict:
    """Evaluate the user's answer for one guided SD step.

    Returns: {score, feedback, hints}
    """
    client = _get_client()
    system_prompt = get_sd_evaluation_prompt(
        problem=problem,
        step=step,
        step_name=step_name,
        level=level,
        step_prompt=step_prompt,
        answer=answer,
        previous_context=previous_context,
        language=language,
    )
    try:
        response = await client.chat.completions.create(
            model=model or config.OPENAI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": answer},
            ],
            temperature=0.3,
            max_completion_tokens=400,
        )
        data = json.loads(response.choices[0].message.content)
        return {
            "score": max(1, min(10, int(data.get("score", 5)))),
            "feedback": data.get("feedback", ""),
            "hints": data.get("hints", []),
        }
    except Exception as exc:
        logger.error("evaluate_sd_step failed: %s", exc)
        return {"score": 5, "feedback": "Evaluation temporarily unavailable.", "hints": []}


async def generate_sd_summary(
    problem: str,
    level: str,
    all_context: str,
    language: str = "en",
    model: Optional[str] = None,
) -> dict:
    """Generate the final comprehensive evaluation for a guided SD session.

    Returns: {requirements_clarity, estimations, data_model, api_design,
              architecture, deep_dive, trade_offs, overall, assessment,
              strengths, improvements, topics_to_study}
    """
    client = _get_client()
    system_prompt = get_sd_summary_prompt(problem=problem, level=level, all_context=all_context, language=language)
    try:
        response = await client.chat.completions.create(
            model=model or config.OPENAI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Generate the final system design evaluation."},
            ],
            temperature=0.4,
            max_completion_tokens=800,
        )
        data = json.loads(response.choices[0].message.content)
        return {
            "requirements_clarity": data.get("requirements_clarity", 5),
            "estimations": data.get("estimations", 5),
            "data_model": data.get("data_model", 5),
            "api_design": data.get("api_design", 5),
            "architecture": data.get("architecture", 5),
            "deep_dive": data.get("deep_dive", 5),
            "trade_offs": data.get("trade_offs", 5),
            "overall": data.get("overall", 5),
            "assessment": data.get("assessment", ""),
            "strengths": data.get("strengths", []),
            "improvements": data.get("improvements", []),
            "topics_to_study": data.get("topics_to_study", []),
        }
    except Exception as exc:
        logger.error("generate_sd_summary failed: %s", exc)
        return _fallback_sd_summary()


def _fallback_sd_step(step: int) -> dict:
    """Return a hardcoded step prompt when AI is unavailable."""
    prompts = {
        1: {"prompt": "Let's start designing the system. What requirements would you clarify first?", "hints": ["Think about scale", "Consider functional vs non-functional"]},
        2: {"prompt": "Now estimate the traffic and data scale. How many DAU? Reads vs writes?", "hints": ["Start with DAU", "Estimate reads and writes per second"]},
        3: {"prompt": "Design the data model. What tables/collections do you need?", "hints": ["Core entities", "Relationships"]},
        4: {"prompt": "Define the API endpoints. What endpoints would you create?", "hints": ["CRUD operations", "REST conventions"]},
        5: {"prompt": "Describe the high-level architecture. What components are involved?", "hints": ["Load balancers", "Caching", "Database"]},
        6: {"prompt": "Let's deep-dive into one component. Pick your most interesting component.", "hints": ["Implementation details", "Failure scenarios"]},
        7: {"prompt": "Discuss the key trade-offs in your design.", "hints": ["CAP theorem", "Consistency vs availability"]},
    }
    fallback = prompts.get(step, prompts[1])
    return {
        "step": step,
        "step_name": f"Step {step}",
        "prompt": fallback["prompt"],
        "hints": fallback["hints"],
        "evaluation_criteria": ["depth", "accuracy", "completeness"],
    }


def _fallback_sd_summary() -> dict:
    """Return a fallback summary when AI is unavailable."""
    return {
        "requirements_clarity": 5, "estimations": 5, "data_model": 5,
        "api_design": 5, "architecture": 5, "deep_dive": 5, "trade_offs": 5,
        "overall": 5,
        "assessment": "Your system design session was completed. Review each component score to identify areas for improvement.",
        "strengths": ["Completed the full guided session"],
        "improvements": ["Try to provide more detail in each step", "Practice trade-off discussions"],
        "topics_to_study": ["System design fundamentals", "Database scaling", "Caching strategies"],
    }

_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    """Lazily create and cache the OpenAI async client."""
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=config.OPENAI_CHAT_API_KEY or config.OPENAI_API_KEY,
            base_url=config.OPENAI_BASE_URL,
        )
    return _client


async def generate_question(
    role: str,
    level: str,
    question_number: int,
    previous_questions: list[str],
    language: str = "en",
    company_context: str = "",
    mode: str = "technical",
    skills: str = "",
    model: Optional[str] = None,
) -> dict:
    """Generate one interview question via AI.

    Args:
        role: Developer role (Frontend / Backend / Fullstack / System Design).
        level: Experience level (Junior / Mid / Senior).
        question_number: Position in the session (1-5).
        previous_questions: Already-asked question texts to avoid repetition.
        language: Output language code ("en" or "ru").
        company_context: AI context prompt for company-specific interviews (e.g. Google, Amazon).
        mode: "technical" for tech interviews, "behavioral" for pure STAR/behavioral sessions.
        skills: Optional comma-separated skills to focus questions on (e.g. "React, TypeScript").
        model: Optional model override (e.g. "gpt-5.4" for Premium). Defaults to config.OPENAI_MODEL.

    Returns:
        Dict with keys: question, category, expected_topics, difficulty.
    """
    client = _get_client()
    system_prompt = get_question_prompt(role, level, question_number, previous_questions, language=language, company_context=company_context, mode=mode, skills=skills)
    try:
        response = await client.chat.completions.create(
            model=model or config.OPENAI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Generate question {question_number} of 5."},
            ],
            temperature=0.8,
            max_completion_tokens=500,
        )
        data = json.loads(response.choices[0].message.content)
        q_text = data.get("question", "")
        return {
            "question": q_text,
            "question_text": q_text,
            "category": data.get("category", "Technical"),
            "expected_topics": data.get("expected_topics", []),
            "difficulty": data.get("difficulty", "Medium"),
        }
    except Exception as exc:
        logger.error("generate_question failed: %s", exc)
        return _fallback_question(role, question_number)


async def evaluate_answer(role: str, level: str, question: str, answer: str, language: str = "en", time_taken_seconds: int | None = None, mode: str = "technical", model: Optional[str] = None, resume_context: str = "") -> dict:
    """Evaluate a candidate's answer via AI.

    Args:
        role: Developer role.
        level: Experience level.
        question: The interview question that was asked.
        answer: The candidate's textual answer.
        language: Output language code ("en" or "ru").
        time_taken_seconds: Optional time spent answering (for Premium timing analysis).
        mode: "technical" for tech interviews, "behavioral" for behavioral/STAR sessions.
        model: Optional model override (e.g. "gpt-5.4" for Premium). Defaults to config.OPENAI_MODEL.
        resume_context: Optional context from CV/resume for personalised evaluation.

    Returns:
        Dict with keys: score, feedback, strengths, improvements, tip, timing_analysis,
        and for behavioral mode also: star_analysis.
    """
    client = _get_client()
    system_prompt = get_evaluation_prompt(role, level, question, answer, language=language, time_taken_seconds=time_taken_seconds, mode=mode, resume_context=resume_context)
    try:
        response = await client.chat.completions.create(
            model=model or config.OPENAI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": answer},
            ],
            temperature=0.3,
            max_completion_tokens=600,
        )
        data = json.loads(response.choices[0].message.content)
        result = {
            "score": max(1, min(10, int(data.get("score", 5)))),
            "feedback": data.get("feedback", "Thank you for your answer."),
            "strengths": data.get("strengths", []),
            "improvements": data.get("improvements", []),
            "tip": data.get("tip", ""),
            "timing_analysis": data.get("timing_analysis"),
        }
        if mode == "behavioral" and "star_analysis" in data:
            result["star_analysis"] = data["star_analysis"]
        return result
    except Exception as exc:
        logger.error("evaluate_answer failed: %s", exc)
        return _fallback_evaluation()


async def generate_summary(
    role: str, level: str, answers: list[dict], avg_score: float, language: str = "en", mode: str = "technical", model: Optional[str] = None, resume_context: str = ""
) -> dict:
    """Generate a post-session summary via AI.

    Args:
        role: Developer role.
        level: Experience level.
        answers: List of answer dicts from the completed session.
        avg_score: Pre-computed mean score.
        language: Output language code ("en" or "ru").
        mode: "technical" for tech interviews, "behavioral" for behavioral/STAR sessions.
        model: Optional model override (e.g. "gpt-5.4" for Premium). Defaults to config.OPENAI_MODEL.
        resume_context: Optional context from CV/resume for personalised summary.

    Returns:
        Dict with keys: overall_assessment, key_strengths, key_improvements,
        topics_to_study, overall_rating.
        For behavioral mode also: star_breakdown, competency_scores.
    """
    client = _get_client()
    system_prompt = get_summary_prompt(role, level, answers, avg_score, language=language, mode=mode, resume_context=resume_context)
    try:
        response = await client.chat.completions.create(
            model=model or config.OPENAI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Generate the session summary."},
            ],
            temperature=0.4,
            max_completion_tokens=800,
        )
        data = json.loads(response.choices[0].message.content)
        result = {
            "overall_assessment": data.get("overall_assessment", ""),
            "key_strengths": data.get("key_strengths", []),
            "key_improvements": data.get("key_improvements", []),
            "topics_to_study": data.get("topics_to_study", []),
            "overall_rating": data.get("overall_rating", "Needs Improvement"),
        }
        if mode == "behavioral":
            if "star_breakdown" in data:
                result["star_breakdown"] = data["star_breakdown"]
            if "competency_scores" in data:
                result["competency_scores"] = data["competency_scores"]
        return result
    except Exception as exc:
        logger.error("generate_summary failed: %s", exc)
        return _fallback_summary(avg_score)


# ── fallbacks ────────────────────────────────────────────────────────────────

_FALLBACK_QUESTIONS: dict[str, list[str]] = {
    "Frontend": [
        "Explain the difference between `var`, `let`, and `const` in JavaScript.",
        "How does the Virtual DOM work in React and why does it exist?",
        "Describe how CSS specificity is calculated and give an example.",
        "How would you diagnose and fix a slow-loading web page?",
        "When and why would you use `useCallback` or `useMemo` in React?",
    ],
    "Backend": [
        "What is the difference between SQL and NoSQL databases? When would you choose each?",
        "Describe the key principles of RESTful API design.",
        "How would you implement JWT-based authentication?",
        "What is database indexing and when should you use it?",
        "Explain the SOLID principles with a brief example.",
    ],
    "Fullstack": [
        "How do you manage shared state between frontend and backend?",
        "Compare server-side rendering, static generation, and client-side rendering.",
        "How would you implement real-time notifications in a web app?",
        "Describe a CI/CD pipeline for a full-stack application.",
        "How do you version a public REST API without breaking clients?",
    ],
    "System Design": [
        "Design a URL shortener like TinyURL. Discuss the data model, API, and how you'd handle 1 billion URLs.",
        "Design Twitter's timeline. How would you support 500M users posting and reading tweets in real-time?",
        "Design a real-time chat application like WhatsApp. Cover message delivery, offline support, and scaling.",
        "Design YouTube. Discuss video upload, transcoding pipeline, CDN strategy, and recommendation serving.",
        "Design Uber's ride-matching system. How would you handle millions of concurrent ride requests?",
    ],
}


def _fallback_question(role: str, question_number: int) -> dict:
    """Return a hardcoded question when the API is unavailable."""
    questions = _FALLBACK_QUESTIONS.get(role, _FALLBACK_QUESTIONS["Backend"])
    q_text = questions[(question_number - 1) % len(questions)]
    return {
        "question": q_text,
        "question_text": q_text,
        "category": "Technical",
        "expected_topics": [],
        "difficulty": "Medium",
    }


def _fallback_evaluation() -> dict:
    """Return a neutral evaluation when the API is unavailable."""
    return {
        "score": 5,
        "feedback": (
            "The AI evaluation service is temporarily unavailable. "
            "Your answer has been recorded."
        ),
        "strengths": ["You attempted to answer the question"],
        "improvements": ["Try to provide more technical detail"],
        "tip": "Practice explaining concepts out loud as if teaching someone else.",
    }


def _fallback_summary(avg_score: float) -> dict:
    """Return a minimal summary when the API is unavailable."""
    if avg_score >= 8:
        rating = "Excellent"
    elif avg_score >= 6:
        rating = "Good"
    elif avg_score >= 4:
        rating = "Needs Improvement"
    else:
        rating = "Significant Work Required"
    return {
        "overall_assessment": (
            f"You completed the session with an average score of {avg_score:.1f}/10."
        ),
        "key_strengths": ["Completed the full interview session"],
        "key_improvements": ["Review your answers and practice weaker areas"],
        "topics_to_study": ["Core concepts", "Coding practice", "System design"],
        "overall_rating": rating,
    }
