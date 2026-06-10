"""
AI-powered study plan generator.
Analyses interview performance data and generates a personalised learning plan.
"""
import json
import logging
from typing import Optional

from openai import AsyncOpenAI

import config

logger = logging.getLogger(__name__)

_STUDY_PLAN_PROMPT = """\
You are an expert AI Study Coach and tech career advisor. Based on the candidate's interview performance data below, create a personalised, structured study plan.

CANDIDATE PROFILE:
- Target role: {target_role}
- Target level: {target_level}
- Interview mode(s): {interview_modes}
- Number of sessions analysed: {session_count}

INTERVIEW PERFORMANCE SUMMARY:
- Average score across all sessions: {avg_score:.1f}/10
- Best session score: {best_score}/10
- Worst session score: {worst_score}/10

WEAK AREAS (from improvements & low-scoring answers):
{weak_areas}

STRONG AREAS (from strengths & high-scoring answers):
{strong_areas}

TOPICS TO STUDY (from session summaries):
{topics_to_study}

PER-QUESTION BREAKDOWN:
{per_question_breakdown}

SESSIONS LIST:
{sessions_list}

{language_instruction}

Based on this data, create a structured study plan for {duration_days} days.

IMPORTANT RULES:
1. Focus ONLY on the weak areas — do NOT include topics the candidate already knows well
2. Each day must have a specific, concrete topic — not generic advice
3. Each day MUST include real, WORKING learning resources with real URLs. CRITICAL: Use ONLY well-known, established URLs that definitely exist:
   - YouTube: https://youtube.com/@NeetCode, https://youtube.com/@freeCodeCamp, https://youtube.com/@SystemDesignInterview, https://youtube.com/@TechWithTim, https://youtube.com/@Fireship
   - LeetCode: https://leetcode.com/problems/... (use real problem slugs like two-sum, valid-parentheses)
   - Articles: https://developer.mozilla.org, https://freecodecamp.org/news, https://roadmap.sh
   - Books: link to Amazon or O'Reilly page if relevant, otherwise just mention the title
   - For behavioral/STAR: https://www.themuse.com/advice/star-interview-method
   - For system design: https://github.com/donnemartin/system-design-primer
   - NEVER use fake URLs like https://google.com or https://example.com
   - NEVER make up URLs — if you're not sure of a URL, use a search link like "https://google.com/search?q=<topic>" as last resort
4. Adjust difficulty to the candidate's level (Junior = fundamentals, Mid = applied concepts, Senior = depth and architecture)
5. Keep each day achievable within the estimated time (max 120 min)
6. The plan should be practical and actionable — the candidate should be able to start immediately

Respond with ONLY valid JSON:
{{
  "title": "<concise plan title, e.g. 'System Design Foundations — 5 days'>",
  "description": "<2-3 sentence overview of what this plan covers and why>",
  "focus_areas": ["<weak area 1>", "<weak area 2>", "<weak area 3>"],
  "days": [
    {{
      "day_number": 1,
      "title": "<specific topic for day 1>",
      "description": "<detailed description of what to study and practice>",
      "resources": [
        {{"title": "<resource name>", "url": "<URL>", "type": "youtube|article|leetcode|book|practice"}}
      ],
      "estimated_minutes": <integer, 15-120>
    }}
  ]
}}
"""

_LANGUAGE_MAP = {
    "en": "Respond in English.",
    "ru": "Отвечай на русском языке.",
}


async def generate_study_plan(
    user_id: int,
    session_data: list[dict],
    duration_days: int,
    mode: Optional[str],
    language: str = "en",
    model: Optional[str] = None,
) -> dict:
    """Generate a personalised study plan from interview session data.

    Args:
        user_id: Internal DB user ID (for final storage).
        session_data: List of session dicts with answers from get_sessions_with_answers().
        duration_days: How many days the plan should cover.
        mode: 'technical', 'behavioral', or None (both).
        language: 'en' or 'ru'.
        model: Optional model override.

    Returns:
        Dict with keys matching create_study_plan() args: title, description,
        focus_areas, duration_days, days_data, plus raw_ai_response for debugging.
    """
    if not session_data:
        raise ValueError("No session data provided for study plan generation")

    client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    lang_inst = _LANGUAGE_MAP.get(language, _LANGUAGE_MAP["en"])

    # Compute aggregate stats
    all_answers = []
    for s in session_data:
        all_answers.extend(s.get("answers", []))

    scores = [a["score"] for a in all_answers if a.get("score")]
    avg_score = sum(scores) / len(scores) if scores else 5.0
    best_score = max(scores) if scores else 5
    worst_score = min(scores) if scores else 5

    session_scores = [s["total_score"] for s in session_data if s.get("total_score") is not None]
    if not session_scores:
        session_scores = scores

    # Collect weak areas (improvements + low-scoring answers)
    weak_lines = []
    strong_lines = []
    topics_lines = set()
    per_question_parts = []

    for s in session_data:
        if not s.get("answers"):
            continue
        session_label = f"Session #{s['id']} ({s['role']} / {s['mode']})"
        for a in s.get("answers", []):
            improvements = a.get("improvements", [])
            strengths = a.get("strengths", [])
            score = a.get("score", 5)

            if improvements:
                for imp in improvements:
                    weak_lines.append(f"  - [{session_label}] {imp}")
            if strengths:
                for st in strengths:
                    strong_lines.append(f"  - [{session_label}] {st}")

            per_question_parts.append(
                f"Q{a['question_number']} (score: {score}/10, category: {a.get('category', 'N/A')}): "
                f"{a['question_text'][:120]}"
            )

            # Add low-scoring answers as weak areas
            if score <= 4:
                weak_lines.append(f"  - [{session_label}] Low score ({score}/10) on: {a['question_text'][:100]}")

    # Strong areas (deduplicate)
    strong_areas = "\n".join(sorted(set(strong_lines))[:10]) if strong_lines else "No specific strong areas identified."

    # Weak areas (deduplicate)
    weak_areas = "\n".join(sorted(set(weak_lines))[:15]) if weak_lines else "Areas need improvement based on scores."

    per_question = "\n".join(per_question_parts[:20]) if per_question_parts else "No question-level data available."

    sessions_list = "\n".join(
        f"- Session #{s['id']}: {s['role']} ({s['mode']}), "
        f"score: {s['total_score'] or 'N/A'}/10, "
        f"{'completed' if s['completed'] else 'incomplete'}, "
        f"answers: {len(s.get('answers', []))}"
        for s in session_data
    )

    interview_modes = mode or "mixed (technical + behavioral)"
    # Determine target role and level from sessions
    target_role = session_data[0].get("role", "Developer")
    target_level = session_data[0].get("experience_level", "Mid")

    system_prompt = _STUDY_PLAN_PROMPT.format(
        target_role=target_role,
        target_level=target_level,
        interview_modes=interview_modes,
        session_count=len(session_data),
        avg_score=avg_score,
        best_score=best_score,
        worst_score=worst_score,
        weak_areas=weak_areas,
        strong_areas=strong_areas,
        topics_to_study="\n".join(f"  - {t}" for t in topics_lines) if topics_lines else "Based on score analysis.",
        per_question_breakdown=per_question,
        sessions_list=sessions_list,
        duration_days=duration_days,
        language_instruction=lang_inst,
    )

    try:
        response = await client.chat.completions.create(
            model=model or config.OPENAI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Generate a {duration_days}-day study plan based on my interview data."},
            ],
            temperature=0.4,
            max_completion_tokens=2000,
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("Empty response from AI")

        data = json.loads(content)

        days_data = data.get("days", [])
        if not days_data:
            raise ValueError("AI returned no days in the study plan")

        return {
            "title": data.get("title", f"Study Plan — {duration_days} days"),
            "description": data.get("description", ""),
            "focus_areas": data.get("focus_areas", []),
            "duration_days": duration_days,
            "days_data": days_data,
            "raw_ai_response": content[:500],  # for debugging
        }

    except Exception as exc:
        logger.error("generate_study_plan failed: %s", exc)
        # Fallback: generate a minimalist plan
        return _fallback_plan(duration_days, target_role, target_level)


def _fallback_plan(duration_days: int, role: str, level: str) -> dict:
    """Return a basic fallback plan when AI generation fails."""
    topics = {
        "Frontend": ["React Hooks & State Management", "CSS & Responsive Design", "JavaScript Fundamentals"],
        "Backend": ["API Design & REST Best Practices", "Database Design & SQL", "Authentication & Security"],
        "System Design": ["Scalability Fundamentals", "Database Architecture", "Caching & CDN"],
        "Fullstack": ["Full-stack Architecture", "API Integration Patterns", "Deployment & DevOps"],
    }
    base_topics = topics.get(role, ["Core Concepts", "Best Practices", "Problem Solving"])

    days = []
    for i in range(min(duration_days, len(base_topics))):
        days.append({
            "day_number": i + 1,
            "title": base_topics[i],
            "description": f"Review and practice {base_topics[i].lower()} for {level} level interviews.",
            "resources": [
                {"title": f"Study: {base_topics[i]}", "url": "https://roadmap.sh", "type": "article"},
                {"title": "Practice on LeetCode", "url": "https://leetcode.com/problemset/", "type": "leetcode"},
            ],
            "estimated_minutes": 45,
        })

    return {
        "title": f"Interview Prep Plan — {duration_days} days",
        "description": f"Focused practice plan for {role} ({level}) based on your interview results.",
        "focus_areas": base_topics[:3],
        "duration_days": duration_days,
        "days_data": days,
        "raw_ai_response": "",
    }
