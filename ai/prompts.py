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
    "System Design": (
        "Focus areas: Designing scalable and reliable systems, "
        "high-level architecture, component design (load balancers, databases, caches, "
        "message queues, CDN), data flow and storage, trade-off analysis (consistency vs "
        "availability, read vs write optimization), API design, microservices vs monoliths, "
        "distributed systems fundamentals (CAP theorem, consensus protocols, sharding, "
        "replication), performance optimization, fault tolerance, disaster recovery. "
        "Questions are real-world: design YouTube, Twitter, URL shortener, Uber, chat system, etc."
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
{skills_context}
Rules:
- {mix_rule}
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
{skills_context}
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
}}
"""


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

_SD_EVALUATION_SYSTEM = """\
You are an expert system design interviewer evaluating a candidate's architecture answer.

Role: {role} at {level} level
Question: {question}
Candidate answer: {answer}

Evaluate on system design quality:

Scoring guide:
9-10 Exceptional — clear architecture, well-reasoned trade-offs, covers all key components (DB, cache, API layer, load balancers, CDN), explicitly addresses scalability, fault tolerance, and data flow
7-8  Good — solid high-level design, most components covered, some trade-offs discussed, moderate depth
5-6  Adequate — basic design present, missing key components, few or no trade-offs discussed
3-4  Weak — vague architecture, missing critical components, no trade-off analysis
1-2  Very poor — no coherent design or fundamentally wrong approach for the problem

{language_instruction}

Respond with ONLY valid JSON:
{{
  "score": <integer 1-10>,
  "feedback": "<2-3 sentence overall assessment of the architecture quality>",
  "strengths": ["<architectural strength>", "..."],
  "improvements": ["<missing component or weak area>", "..."],
  "tip": "<one specific actionable tip to improve system design answers>"
}}"""

_SD_SUMMARY_SYSTEM = """\
You are an expert system design interview coach providing a post-session debrief.

Role: {role} at {level} level
Average score: {avg_score:.1f}/10

Session Q&A:
{qa_summary}

{language_instruction}

Analyze the candidate's system design thinking across all answers. Focus on architecture maturity, trade-off reasoning, scalability mindset, and component depth.

Respond with ONLY valid JSON:
{{
  "overall_assessment": "<2-3 sentence assessment focused on system design growth areas>",
  "key_strengths": ["<architectural strength>", "<strength>", "<strength>"],
  "key_improvements": ["<design area to improve>", "<area>", "<area>"],
  "topics_to_study": ["<system design topic>", "<topic>", "<topic>", "<topic>"],
  "overall_rating": "<Excellent | Good | Needs Improvement | Significant Work Required>"
}}"""

_RESUME_EVALUATION_SECTION = """

--- CV Context ---
The candidate's resume indicates:
{resume_context}

When evaluating the answer, consider whether the candidate leveraged their stated experience and skills. If their answer aligns well with their CV background, acknowledge it. If they missed an area they should know based on their CV, note it in improvements. If the answer demonstrates deep knowledge in their stated area of expertise, reflect that in the score."""

_RESUME_SUMMARY_SECTION = """

--- CV Context ---
The candidate's resume indicates:
{resume_context}

When generating the summary, personalize it based on the candidate's CV profile. Mention if they performed well in areas matching their stated expertise, and suggest study topics that would fill gaps in their profile. Tailor the overall assessment to their experience level as shown in the CV."""


# ── Guided System Design flow (7-step, Premium only) ─────────────────────────

_SD_STEP_NAMES: dict[int, str] = {
    1: "Requirements Clarification",
    2: "Traffic & Data Estimations",
    3: "Data Model",
    4: "API Design",
    5: "High-Level Architecture",
    6: "Deep Dive",
    7: "Trade-Offs Discussion",
}

_SD_STEP_CRITERIA: dict[int, str] = {
    1: "functional requirements, non-functional requirements (scale, latency, durability), edge cases considered",
    2: "DAU/MAU estimation, reads/sec, writes/sec, storage calculation, quality of reasoning methodology",
    3: "schema design, normalization, indexing strategy, relationships between entities, scalability considerations",
    4: "endpoint completeness, RESTful conventions, request/response design, auth endpoints, versioning",
    5: "component coverage (load balancer, API servers, DB, cache, CDN, message queue), data flow clarity, scalability",
    6: "implementation depth, practical details, failure handling, trade-off awareness within the component",
    7: "trade-off reasoning quality (e.g. consistency vs availability, SQL vs NoSQL), awareness of design limitations, justification of choices",
}

_SD_GUIDED_PROMPTS: dict[int, str] = {
    1: """\
You are an expert system design interviewer at a FAANG company conducting a structured 7-step interview.
Problem to design: {problem}
Candidate level: {level}
{company_context}

This is STEP 1 of 7: REQUIREMENTS CLARIFICATION.

{language_instruction}

Your task: Present the problem concisely and ask the candidate to clarify requirements before designing.
Prompt them to identify:
- Functional requirements (what the system does)
- Non-functional requirements (scale, latency, durability, availability)
- Scope assumptions and edge cases

Respond with ONLY valid JSON — no markdown fences:
{{
  "step": 1,
  "step_name": "Requirements Clarification",
  "prompt": "<your engaging 2-3 sentence question/prompt to the candidate>",
  "hints": ["<hint about functional requirements>", "<hint about scale/NFRs>", "<hint about scope/edge cases>"],
  "evaluation_criteria": ["functional requirements", "non-functional requirements", "scale assumptions", "edge cases"]
}}""",

    2: """\
You are an expert system design interviewer at a FAANG company.
Problem: {problem}
Candidate level: {level}

This is STEP 2 of 7: TRAFFIC & DATA ESTIMATIONS.

{language_instruction}

Session so far:
{previous_context}

Your task: Ask the candidate to estimate traffic and data scale for their stated requirements.
Guide them toward: DAU/MAU, reads/sec vs writes/sec, storage growth over time.

Respond with ONLY valid JSON — no markdown fences:
{{
  "step": 2,
  "step_name": "Traffic & Data Estimations",
  "prompt": "<your prompt asking for traffic and data estimates>",
  "hints": ["<hint about DAU/MAU starting point>", "<hint about read/write ratio>", "<hint about storage math>"],
  "evaluation_criteria": ["DAU/MAU estimation", "reads/sec and writes/sec", "storage calculation", "reasoning methodology"]
}}""",

    3: """\
You are an expert system design interviewer at a FAANG company.
Problem: {problem}
Candidate level: {level}

This is STEP 3 of 7: DATA MODEL.

{language_instruction}

Session so far:
{previous_context}

Your task: Ask the candidate to design the data model — core entities, fields, relationships, indexes.

Respond with ONLY valid JSON — no markdown fences:
{{
  "step": 3,
  "step_name": "Data Model",
  "prompt": "<your prompt asking for schema / data model design>",
  "hints": ["<hint about core entities>", "<hint about relationships/foreign keys>", "<hint about indexing for hot paths>"],
  "evaluation_criteria": ["schema design", "normalization", "indexing strategy", "scalability"]
}}""",

    4: """\
You are an expert system design interviewer at a FAANG company.
Problem: {problem}
Candidate level: {level}

This is STEP 4 of 7: API DESIGN.

{language_instruction}

Session so far:
{previous_context}

Your task: Ask the candidate to define the core API endpoints (REST, gRPC, or GraphQL as appropriate).

Respond with ONLY valid JSON — no markdown fences:
{{
  "step": 4,
  "step_name": "API Design",
  "prompt": "<your prompt asking for API endpoint design>",
  "hints": ["<hint about core CRUD endpoints>", "<hint about auth/pagination>", "<hint about idempotency or versioning>"],
  "evaluation_criteria": ["endpoint completeness", "REST conventions", "request/response design", "auth and versioning"]
}}""",

    5: """\
You are an expert system design interviewer at a FAANG company.
Problem: {problem}
Candidate level: {level}

This is STEP 5 of 7: HIGH-LEVEL ARCHITECTURE.

{language_instruction}

Session so far:
{previous_context}

Your task: Ask the candidate to describe the high-level system architecture — components, their roles, and data flow.

Respond with ONLY valid JSON — no markdown fences:
{{
  "step": 5,
  "step_name": "High-Level Architecture",
  "prompt": "<your prompt asking for high-level architecture description>",
  "hints": ["<hint about load balancers and API gateway>", "<hint about caching layer / CDN>", "<hint about async processing / message queues>"],
  "evaluation_criteria": ["component coverage", "data flow clarity", "scalability", "fault tolerance"]
}}""",

    6: """\
You are an expert system design interviewer at a FAANG company.
Problem: {problem}
Candidate level: {level}

This is STEP 6 of 7: DEEP DIVE.

{language_instruction}

Session so far:
{previous_context}

Your task: Pick the single most complex or interesting component the candidate mentioned and ask them to deep-dive into it.
Ask about implementation details, failure scenarios, and optimizations.

Respond with ONLY valid JSON — no markdown fences:
{{
  "step": 6,
  "step_name": "Deep Dive",
  "prompt": "<your prompt asking for a deep-dive into a specific component they mentioned>",
  "hints": ["<hint about implementation detail>", "<hint about handling failure / retries>", "<hint about performance optimization>"],
  "evaluation_criteria": ["implementation depth", "practical details", "failure handling", "trade-off awareness within component"]
}}""",

    7: """\
You are an expert system design interviewer at a FAANG company.
Problem: {problem}
Candidate level: {level}

This is STEP 7 of 7: TRADE-OFFS DISCUSSION.

{language_instruction}

Session so far:
{previous_context}

Your task: Ask the candidate to reflect on and discuss the key trade-offs in their overall design.
Example trade-offs: consistency vs availability, SQL vs NoSQL, monolith vs microservices, latency vs throughput.

Respond with ONLY valid JSON — no markdown fences:
{{
  "step": 7,
  "step_name": "Trade-Offs Discussion",
  "prompt": "<your prompt asking the candidate to discuss the key trade-offs in their design>",
  "hints": ["<hint about CAP theorem application>", "<hint about consistency models>", "<hint about cost/complexity trade-offs>"],
  "evaluation_criteria": ["trade-off reasoning", "awareness of design limitations", "justification of choices"]
}}""",
}

_SD_GUIDED_EVALUATION: str = """\
You are an expert system design interviewer at a FAANG company evaluating one step of a structured session.

Problem: {problem}
Step: {step} of 7 — {step_name}
Candidate level: {level}

The prompt/question that was given:
{step_prompt}

The candidate's answer:
{answer}

{language_instruction}

Prior session context:
{previous_context}

Evaluate the candidate's answer for THIS step only. Score 1-10 based on:
{step_criteria}

Scoring guide:
9-10 Exceptional — thorough, accurate, demonstrates clear depth
7-8  Good — covers main points with minor gaps
5-6  Adequate — covers basics but lacks depth or precision
3-4  Weak — major gaps or misunderstanding
1-2  Very poor — incorrect or no coherent answer

Respond with ONLY valid JSON — no markdown fences:
{{
  "score": <integer 1-10>,
  "feedback": "<1-2 sentence constructive feedback specific to this step>",
  "hints": ["<specific actionable hint for improvement on this step>", "<another hint if relevant>"]
}}"""

_SD_GUIDED_SUMMARY: str = """\
You are an expert system design interviewer providing a final evaluation of a complete 7-step guided session.

Problem: {problem}
Candidate level: {level}

Complete session transcript:
{all_context}

{language_instruction}

Provide a comprehensive final evaluation with per-component scoring (1-10).

Respond with ONLY valid JSON — no markdown fences:
{{
  "requirements_clarity": <1-10>,
  "estimations": <1-10>,
  "data_model": <1-10>,
  "api_design": <1-10>,
  "architecture": <1-10>,
  "deep_dive": <1-10>,
  "trade_offs": <1-10>,
  "overall": <1-10>,
  "assessment": "<3-4 sentence overall assessment of the candidate's system design ability and session performance>",
  "strengths": ["<strength 1>", "<strength 2>", "<strength 3>"],
  "improvements": ["<improvement area 1>", "<improvement area 2>", "<improvement area 3>"],
  "topics_to_study": ["<topic 1>", "<topic 2>", "<topic 3>"]
}}"""


def get_sd_step_prompt(
    problem: str,
    role: str,
    level: str,
    step: int,
    previous_context: str = "",
    company_context: str = "",
    language: str = "en",
) -> str:
    """Return a filled system prompt for generating a guided SD step question."""
    template = _SD_GUIDED_PROMPTS.get(step, _SD_GUIDED_PROMPTS[1])
    lang_inst = _LANGUAGE_MAP.get(language, _LANGUAGE_MAP["en"])
    return template.format(
        problem=problem,
        role=role,
        level=level,
        previous_context=previous_context or "None",
        company_context=company_context or "",
        language_instruction=lang_inst,
    )


def get_sd_evaluation_prompt(
    problem: str,
    step: int,
    step_name: str,
    level: str,
    step_prompt: str,
    answer: str,
    previous_context: str = "",
    language: str = "en",
) -> str:
    """Return a filled system prompt for evaluating a guided SD step answer."""
    lang_inst = _LANGUAGE_MAP.get(language, _LANGUAGE_MAP["en"])
    return _SD_GUIDED_EVALUATION.format(
        problem=problem,
        step=step,
        step_name=step_name,
        level=level,
        step_prompt=step_prompt,
        answer=answer,
        previous_context=previous_context or "None",
        step_criteria=_SD_STEP_CRITERIA.get(step, "depth, accuracy, completeness"),
        language_instruction=lang_inst,
    )


def get_sd_summary_prompt(
    problem: str,
    level: str,
    all_context: str,
    language: str = "en",
) -> str:
    """Return a filled system prompt for generating the guided SD final summary."""
    lang_inst = _LANGUAGE_MAP.get(language, _LANGUAGE_MAP["en"])
    return _SD_GUIDED_SUMMARY.format(
        problem=problem,
        level=level,
        all_context=all_context,
        language_instruction=lang_inst,
    )


def get_question_prompt(
    role: str,
    level: str,
    question_number: int,
    previous_questions: list[str],
    language: str = "en",
    company_context: str = "",
    mode: str = "technical",
    skills: str = "",
) -> str:
    """Return a filled system prompt for question generation."""
    prev = "\n".join(f"- {q}" for q in previous_questions) if previous_questions else "None"
    lang_inst = _LANGUAGE_MAP.get(language, _LANGUAGE_MAP["en"])
    skills_context = (
        f"Candidate's specified skills: {skills}\n"
        f"Focus questions on these skills where possible.\n"
        if skills
        else ""
    )

    if mode == "behavioral":
        return _BEHAVIORAL_QUESTION_SYSTEM.format(
            role=role,
            level=level,
            question_number=question_number,
            previous_questions=prev,
            company_context=company_context,
            skills_context=skills_context,
            language_instruction=lang_inst,
        )

    if mode == "system_design" or role == "System Design":
        mix_rule = (
            "ALL questions must be system design questions — design a scalable distributed system "
            "(e.g., a URL shortener, Twitter, YouTube, chat service, Uber, etc.). "
            "Each question should focus on architecture, trade-offs, scalability, and component design."
        )
    else:
        mix_rule = "Mix question types across the session: Technical (60 %), Behavioral (20 %), System Design (20 %)"

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
        skills_context=skills_context,
        mix_rule=mix_rule,
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
    resume_context: str = "",
) -> str:
    """Return a filled system prompt for answer evaluation."""
    lang_inst = _LANGUAGE_MAP.get(language, _LANGUAGE_MAP["en"])

    if mode == "behavioral":
        result = _BEHAVIORAL_EVALUATION_SYSTEM.format(
            role=role,
            level=level,
            question=question,
            answer=answer,
            language_instruction=lang_inst,
        )

    elif mode == "system_design" or role == "System Design":
        result = _SD_EVALUATION_SYSTEM.format(
            role=role,
            level=level,
            question=question,
            answer=answer,
            language_instruction=lang_inst,
        )

    else:
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

        result = _EVALUATION_SYSTEM.format(
            role=role,
            level=level,
            question=question,
            answer=answer,
            timing_section=timing_section,
            timing_json=timing_json,
            language_instruction=lang_inst,
        )

    if resume_context:
        result += _RESUME_EVALUATION_SECTION.format(resume_context=resume_context)

    return result


def get_summary_prompt(
    role: str,
    level: str,
    answers: list[dict],
    avg_score: float,
    language: str = "en",
    mode: str = "technical",
    resume_context: str = "",
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
        result = _BEHAVIORAL_SUMMARY_SYSTEM.format(
            role=role,
            level=level,
            avg_score=avg_score,
            qa_summary=qa_summary,
            language_instruction=lang_inst,
        )

    elif mode == "system_design" or role == "System Design":
        result = _SD_SUMMARY_SYSTEM.format(
            role=role,
            level=level,
            avg_score=avg_score,
            qa_summary=qa_summary,
            language_instruction=lang_inst,
        )

    else:
        result = _SUMMARY_SYSTEM.format(
            role=role,
            level=level,
            avg_score=avg_score,
            qa_summary=qa_summary,
            language_instruction=lang_inst,
        )

    if resume_context:
        result += _RESUME_SUMMARY_SECTION.format(resume_context=resume_context)

    return result
