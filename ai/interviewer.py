"""GPT-4o integration: question generation, answer evaluation, summary."""
import json
import logging
from typing import Optional

from openai import AsyncOpenAI

import config
from ai.prompts import get_evaluation_prompt, get_question_prompt, get_summary_prompt

logger = logging.getLogger(__name__)

_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    """Lazily create and cache the OpenAI async client."""
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    return _client


async def generate_question(
    role: str,
    level: str,
    question_number: int,
    previous_questions: list[str],
    language: str = "en",
    company_context: str = "",
    mode: str = "technical",
) -> dict:
    """Generate one interview question via GPT-4o.

    Args:
        role: Developer role (Frontend / Backend / Fullstack / ML).
        level: Experience level (Junior / Mid / Senior).
        question_number: Position in the session (1-5).
        previous_questions: Already-asked question texts to avoid repetition.
        language: Output language code ("en" or "ru").
        company_context: AI context prompt for company-specific interviews (e.g. Google, Amazon).
        mode: "technical" for tech interviews, "behavioral" for pure STAR/behavioral sessions.

    Returns:
        Dict with keys: question, category, expected_topics, difficulty.
    """
    client = _get_client()
    system_prompt = get_question_prompt(role, level, question_number, previous_questions, language=language, company_context=company_context, mode=mode)
    try:
        response = await client.chat.completions.create(
            model=config.OPENAI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Generate question {question_number} of 5."},
            ],
            temperature=0.8,
            max_tokens=500,
        )
        data = json.loads(response.choices[0].message.content)
        return {
            "question": data.get("question", ""),
            "category": data.get("category", "Technical"),
            "expected_topics": data.get("expected_topics", []),
            "difficulty": data.get("difficulty", "Medium"),
        }
    except Exception as exc:
        logger.error("generate_question failed: %s", exc)
        return _fallback_question(role, question_number)


async def evaluate_answer(role: str, level: str, question: str, answer: str, language: str = "en", time_taken_seconds: int | None = None, mode: str = "technical") -> dict:
    """Evaluate a candidate's answer via GPT-4o.

    Args:
        role: Developer role.
        level: Experience level.
        question: The interview question that was asked.
        answer: The candidate's textual answer.
        language: Output language code ("en" or "ru").
        time_taken_seconds: Optional time spent answering (for Premium timing analysis).
        mode: "technical" for tech interviews, "behavioral" for behavioral/STAR sessions.

    Returns:
        Dict with keys: score, feedback, strengths, improvements, tip, timing_analysis,
        and for behavioral mode also: star_analysis.
    """
    client = _get_client()
    system_prompt = get_evaluation_prompt(role, level, question, answer, language=language, time_taken_seconds=time_taken_seconds, mode=mode)
    try:
        response = await client.chat.completions.create(
            model=config.OPENAI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": answer},
            ],
            temperature=0.3,
            max_tokens=600,
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
    role: str, level: str, answers: list[dict], avg_score: float, language: str = "en", mode: str = "technical"
) -> dict:
    """Generate a post-session summary via GPT-4o.

    Args:
        role: Developer role.
        level: Experience level.
        answers: List of answer dicts from the completed session.
        avg_score: Pre-computed mean score.
        language: Output language code ("en" or "ru").
        mode: "technical" for tech interviews, "behavioral" for behavioral/STAR sessions.

    Returns:
        Dict with keys: overall_assessment, key_strengths, key_improvements,
        topics_to_study, overall_rating.
        For behavioral mode also: star_breakdown, competency_scores.
    """
    client = _get_client()
    system_prompt = get_summary_prompt(role, level, answers, avg_score, language=language, mode=mode)
    try:
        response = await client.chat.completions.create(
            model=config.OPENAI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Generate the session summary."},
            ],
            temperature=0.4,
            max_tokens=800,
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
    "ML": [
        "Explain the bias-variance tradeoff and how it affects model selection.",
        "How does gradient descent work and what are common variants?",
        "How would you handle a heavily imbalanced dataset?",
        "What is cross-validation and why is it important?",
        "Describe the difference between supervised and unsupervised learning.",
    ],
}


def _fallback_question(role: str, question_number: int) -> dict:
    """Return a hardcoded question when the API is unavailable."""
    questions = _FALLBACK_QUESTIONS.get(role, _FALLBACK_QUESTIONS["Backend"])
    return {
        "question": questions[(question_number - 1) % len(questions)],
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
