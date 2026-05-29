"""GPT-4o resume analysis: extract role, level, and tech stack from PDF text."""
import json
import logging
from typing import Optional

import config
from ai.interviewer import _get_client

logger = logging.getLogger(__name__)

_FALLBACK_RESULT: dict = {
    "target_role": None,
    "seniority_level": None,
    "suggested_role": None,
    "suggested_level": None,
    "tech_stack": [],
    "years_experience": None,
    "key_skills": [],
    "confidence": 0.0,
    "raw_title": None,
}

_SYSTEM_PROMPT = """You are an expert technical recruiter analyzing a candidate's resume.

Extract structured information and return ONLY a JSON object with these exact keys:
- target_role: the candidate's current/target job title as written on the resume (string or null)
- seniority_level: "Junior", "Mid", or "Senior" based on years of experience and responsibilities
- suggested_role: the best role/specialization title for this candidate (e.g. "Frontend", "Graphic Designer", "Data Analyst", "DevOps Engineer", "Product Designer", "QA Engineer", "Mobile Developer", "Cloud Architect") — be specific and match what the resume describes
- suggested_level: one of ["Junior", "Mid", "Senior"]
- tech_stack: list of technologies/frameworks/languages mentioned (array of strings)
- years_experience: estimated years of professional experience as an integer (or null if unclear)
- key_skills: top 3-6 most prominent skills from the resume (array of strings)
- confidence: your confidence in the analysis from 0.0 to 1.0 (float)
- raw_title: the exact job title text found in the resume (string or null)

Role mapping rules:
- For standard engineering roles (Frontend, Backend, Fullstack, ML): suggest as-is
- For other specializations: use the actual role title from the resume (e.g. "Graphic Designer", "DevOps Engineer", "Data Analyst", "Product Manager", "QA Engineer", "iOS Developer", "Cloud Architect", etc.)
- Be specific — don't lump everything into "Frontend" or "Backend" if the resume clearly describes a different specialization

Set confidence < 0.6 if the resume is ambiguous, too short, or the role is unclear.
Return ONLY valid JSON, no markdown, no explanation."""


async def analyze_resume(pdf_text: str) -> dict:
    """Analyze extracted PDF resume text and return structured candidate data.

    Args:
        pdf_text: Plain text extracted from a PDF resume (max 10 000 chars).

    Returns:
        Dict with keys: target_role, seniority_level, suggested_role (any
        specialization, not limited to predefined roles), suggested_level,
        tech_stack, years_experience, key_skills, confidence, raw_title.
    """
    if not pdf_text or not pdf_text.strip():
        return dict(_FALLBACK_RESULT)

    client = _get_client()
    try:
        response = await client.chat.completions.create(
            model=config.OPENAI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Analyze this resume:\n\n{pdf_text}",
                },
            ],
            temperature=0.2,
            max_tokens=600,
        )
        data = json.loads(response.choices[0].message.content)

        suggested_role = data.get("suggested_role")

        suggested_level = data.get("suggested_level")
        if suggested_level not in config.EXPERIENCE_LEVELS:
            suggested_level = None

        years_raw = data.get("years_experience")
        try:
            years_experience: Optional[int] = int(years_raw) if years_raw is not None else None
        except (ValueError, TypeError):
            years_experience = None

        confidence = float(data.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))

        return {
            "target_role": data.get("target_role"),
            "seniority_level": data.get("seniority_level"),
            "suggested_role": suggested_role,
            "suggested_level": suggested_level,
            "tech_stack": list(data.get("tech_stack") or []),
            "years_experience": years_experience,
            "key_skills": list(data.get("key_skills") or []),
            "confidence": confidence,
            "raw_title": data.get("raw_title"),
        }
    except Exception as exc:
        logger.error("analyze_resume failed: %s", exc)
        return dict(_FALLBACK_RESULT)
