import json, logging
from openai import OpenAI
import config

logger = logging.getLogger(__name__)

_DEEP_SYSTEM_PROMPT = """You are an expert technical recruiter and resume reviewer. Analyze this resume for the target role and provide detailed improvement recommendations.

Return a JSON object with these fields:
- overall_score: number 0-100 (how well the resume fits the target role)
- strengths: array of strings (what the resume does well)
- weaknesses: array of strings (gaps and issues)
- section_scores: object with keys summary, experience, education, skills, each 0-100
- recommendations: array of specific actionable strings
- missing_keywords: array of strings (keywords missing for the role)
- fixed_content: string (completely rewritten improved version of the entire resume)
- formatting_suggestions: array of strings
- ats_score: number 0-100 (estimated ATS compatibility)
"""

async def analyze_resume_deep(pdf_text: str, target_role: str, experience_level: str, company_context: str = "") -> dict:
    try:
        client = OpenAI(
            api_key=config.OPENAI_CHAT_API_KEY or config.OPENAI_API_KEY,
            base_url=config.OPENAI_BASE_URL,
        )
        user_prompt = f"Target Role: {target_role}\nExperience Level: {experience_level}\n"
        if company_context:
            user_prompt += f"Company Context: {company_context}\n"
        user_prompt += f"\nResume Text:\n{pdf_text[:12000]}"
        
        resp = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _DEEP_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=4096,
        )
        result = json.loads(resp.choices[0].message.content)
        logger.info("deep resume analysis complete, score=%s", result.get("overall_score"))
        return result
    except Exception as exc:
        logger.error("analyze_resume_deep failed: %s", exc)
        return {
            "overall_score": 0,
            "strengths": ["Analysis failed. Please try again."],
            "weaknesses": [],
            "section_scores": {},
            "recommendations": ["Analysis failed. Please try again."],
            "missing_keywords": [],
            "fixed_content": "",
            "formatting_suggestions": [],
            "ats_score": 0,
        }