"""CV gap analysis: compare candidate profile vs target role requirements."""

import json
import logging
from typing import Optional

from openai import AsyncOpenAI

import config

logger = logging.getLogger(__name__)

_GAP_ANALYSIS_PROMPT = """\
You are an expert tech recruiter and career coach. Analyze the gap between a candidate's profile (from their CV/resume) and the requirements for their target position.

TARGET POSITION:
- Role: {target_role}
- Level: {target_level}
- Company context: {company_context}

CANDIDATE PROFILE (from CV):
- Detected role: {cv_role}
- Detected level: {cv_level}
- Tech stack: {tech_stack}
- Years of experience: {years_experience}
- Key skills: {key_skills}
- Confidence in analysis: {cv_confidence}

Additional skills specified: {skills}

{language_instruction}

Analyze the gap and respond with ONLY valid JSON:
{{
  "profile_summary": "<1 sentence summary of the candidate's current profile>",
  "overall_fit": "<Excellent | Good | Moderate | Weak>",
  "strengths": ["<skill/area where candidate meets or exceeds requirements>", "..."],
  "gaps": ["<skill/area where candidate falls short>", "..."],
  "focus_areas": ["<topics/questions that are most likely to come up given the gap>", "..."],
  "expected_difficulty": "<Expected | Harder | Easier>",
  "preparation_tip": "<one specific actionable tip for this interview based on the gap>"
}}
"""

_LANGUAGE_MAP = {
    "en": "Respond in English.",
    "ru": "Отвечай на русском языке.",
}


async def analyze_gap(
    target_role: str,
    target_level: str,
    cv_role: str,
    cv_level: str,
    tech_stack: list[str],
    years_experience: Optional[int],
    key_skills: list[str],
    cv_confidence: float,
    company_context: str = "",
    skills: str = "",
    language: str = "en",
    model: Optional[str] = None,
) -> dict:
    """Analyze the gap between candidate's CV profile and target position.

    Args:
        target_role: The role the user wants to interview for (e.g. "Frontend").
        target_level: Target level (Junior / Mid / Senior).
        cv_role: Role detected from CV analysis.
        cv_level: Level detected from CV analysis.
        tech_stack: Technologies listed in the CV.
        years_experience: Years of experience from CV.
        key_skills: Key skills extracted from CV.
        cv_confidence: Confidence score of the CV analysis (0-1).
        company_context: Optional company-specific context for the interview.
        skills: Optional comma-separated additional skills specified by user.
        language: Output language ("en" or "ru").
        model: Optional model override (e.g. "gpt-5.4" for Premium).

    Returns:
        Dict with keys:
            profile_summary, overall_fit, strengths[], gaps[],
            focus_areas[], expected_difficulty, preparation_tip
    """
    client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    lang_inst = _LANGUAGE_MAP.get(language, _LANGUAGE_MAP["en"])
    tech_stack_str = ", ".join(tech_stack) if tech_stack else "Not specified"
    key_skills_str = ", ".join(key_skills) if key_skills else "Not specified"
    exp_str = str(years_experience) if years_experience is not None else "Not specified"
    conf_str = f"{cv_confidence:.1f}" if cv_confidence else "N/A"

    system_prompt = _GAP_ANALYSIS_PROMPT.format(
        target_role=target_role,
        target_level=target_level,
        company_context=company_context or "General (no specific company)",
        cv_role=cv_role or "Not detected",
        cv_level=cv_level or "Not detected",
        tech_stack=tech_stack_str,
        years_experience=exp_str,
        key_skills=key_skills_str,
        cv_confidence=conf_str,
        skills=skills or "None specified",
        language_instruction=lang_inst,
    )

    try:
        response = await client.chat.completions.create(
            model=model or config.OPENAI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Analyze gap for {target_role} ({target_level}) position."},
            ],
            temperature=0.3,
            max_completion_tokens=600,
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("Empty response from AI")
        data = json.loads(content)
        return {
            "profile_summary": data.get("profile_summary", ""),
            "overall_fit": data.get("overall_fit", "Moderate"),
            "strengths": data.get("strengths", []),
            "gaps": data.get("gaps", []),
            "focus_areas": data.get("focus_areas", []),
            "expected_difficulty": data.get("expected_difficulty", "Expected"),
            "preparation_tip": data.get("preparation_tip", ""),
        }
    except Exception as exc:
        logger.error("analyze_gap failed: %s", exc)
        return {
            "profile_summary": f"CV analysis for {target_role} ({target_level})",
            "overall_fit": "Moderate",
            "strengths": ["Candidate has relevant experience based on CV"],
            "gaps": ["Unable to perform detailed gap analysis"],
            "focus_areas": [f"Focus on {target_role} fundamentals at {target_level} level"],
            "expected_difficulty": "Expected",
            "preparation_tip": "Review core concepts for your target role before the interview.",
        }
