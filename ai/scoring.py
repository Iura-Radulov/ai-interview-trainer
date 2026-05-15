"""Score formatting helpers that produce Markdown-safe strings for Telegram."""
import config


def _bar(score: float, width: int = 10, max_val: float = 10.0) -> str:
    """Return a Unicode block progress bar."""
    filled = round(score / max_val * width)
    return "█" * filled + "░" * (width - filled)


def format_evaluation_message(
    question_number: int,
    total_questions: int,
    score: int,
    feedback: str,
    strengths: list[str],
    improvements: list[str],
    tip: str,
) -> str:
    """Build the per-question feedback message shown after each answer."""
    parts = [
        f"📊 *Question {question_number}/{total_questions} — Evaluation*",
        f"Score: *{score}/10* {_bar(score)}",
        "",
        f"📝 {feedback}",
    ]
    if strengths:
        parts += ["", "✅ *Strengths:*"] + [f"• {s}" for s in strengths[:3]]
    if improvements:
        parts += ["", "📈 *To improve:*"] + [f"• {s}" for s in improvements[:3]]
    if tip:
        parts += ["", f"💡 *Tip:* {tip}"]
    return "\n".join(parts)


def format_summary_message(
    role: str,
    level: str,
    avg_score: float,
    answers: list[dict],
    overall_assessment: str,
    key_strengths: list[str],
    key_improvements: list[str],
    topics_to_study: list[str],
    overall_rating: str,
) -> str:
    """Build the session-end summary message."""
    role_emoji = config.ROLE_EMOJIS.get(role, "💼")
    level_emoji = config.LEVEL_EMOJIS.get(level, "")
    rating_emoji = {
        "Excellent": "🏆",
        "Good": "👍",
        "Needs Improvement": "📚",
        "Significant Work Required": "💪",
    }.get(overall_rating, "📊")

    parts = [
        "🎯 *Interview Complete!*",
        f"{role_emoji} {role}  •  {level_emoji} {level}",
        "",
        f"*Overall score: {avg_score:.1f}/10* {_bar(avg_score)}",
        f"{rating_emoji} *{overall_rating}*",
        "",
        f"📋 *Assessment:* {overall_assessment}",
        "",
        "📊 *Per-question breakdown:*",
    ]
    for a in answers:
        mini = _bar(a["score"], width=5, max_val=10)
        parts.append(
            f"Q{a['question_number']} [{a.get('category', '?')}]: {a['score']}/10 {mini}"
        )
    if key_strengths:
        parts += ["", "✅ *Key strengths:*"] + [f"• {s}" for s in key_strengths[:3]]
    if key_improvements:
        parts += ["", "📈 *Key improvements:*"] + [f"• {s}" for s in key_improvements[:3]]
    if topics_to_study:
        parts += ["", "📚 *Study these topics:*"] + [f"• {t}" for t in topics_to_study[:4]]
    parts += [
        "",
        "🚀 Use /interview to start another session.",
        "👤 Check progress with /profile",
    ]
    return "\n".join(parts)


def format_profile_message(stats: dict) -> str:
    """Build the /profile response message."""
    if not stats:
        return "No profile found. Use /start to register first."

    total = stats["total_sessions"]
    avg = stats["avg_score"]

    parts = [
        "👤 *Your Profile*",
        "",
        f"📊 *Interviews completed:* {total}",
    ]
    if total > 0:
        parts.append(f"⭐ *Average score:* {avg:.1f}/10 {_bar(avg)}")

    if stats.get("preferred_role"):
        role = stats["preferred_role"]
        parts.append(f"🎯 *Preferred role:* {config.ROLE_EMOJIS.get(role, '')} {role}")

    if stats.get("role_breakdown"):
        parts += ["", "📈 *Sessions by role:*"]
        for role, cnt in stats["role_breakdown"].items():
            parts.append(f"  {config.ROLE_EMOJIS.get(role, '')} {role}: {cnt}")

    if stats.get("recent_sessions"):
        parts += ["", "🕐 *Recent sessions:*"]
        for s in stats["recent_sessions"][:3]:
            score_str = f"{s['score']:.1f}/10" if s["score"] is not None else "—"
            parts.append(
                f"  {config.ROLE_EMOJIS.get(s['role'], '')} {s['role']} "
                f"{s['level']}: {score_str}  ({s['date']})"
            )

    if total == 0:
        parts += ["", "👉 Start your first interview with /interview"]

    return "\n".join(parts)
