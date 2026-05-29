"""Company sets configuration."""
import sqlite3
import os
from typing import Optional

# Built-in company sets with their AI context
COMPANY_SETS = {
    "general": {
        "name_en": "General",
        "name_ru": "Общий",
        "emoji": "🌍",
        "is_free": True,
        "context": "",
    },
    "google": {
        "name_en": "Google",
        "name_ru": "Google",
        "emoji": "🔍",
        "is_free": False,
        "context": (
            "You are interviewing for Google. "
            "Focus areas: algorithms & data structures (difficult LeetCode-style), "
            "system design at scale, Go/Python/C++, distributed systems, "
            "Googleyness (cultural fit, ambiguity handling, leadership). "
            "Ask questions in the style of Google's interview process: "
            "start broad, probe deeper, expect candidates to ask clarifying questions. "
            "For behavioral questions, use Google's structured interview style."
        ),
    },
    "amazon": {
        "name_en": "Amazon",
        "name_ru": "Amazon",
        "emoji": "📦",
        "is_free": False,
        "context": (
            "You are interviewing for Amazon. "
            "Focus areas: Leadership Principles (Customer Obsession, Ownership, "
            "Bias for Action, etc.), scale (millions of customers), "
            "microservices architecture, AWS services, bar-raising culture. "
            "Ask behavioral questions in STAR format based on Amazon Leadership Principles. "
            "For technical questions, focus on building scalable, fault-tolerant systems. "
            "Make sure every question ties back to Amazon's peculiar culture and standards."
        ),
    },
    "yandex": {
        "name_en": "Yandex",
        "name_ru": "Яндекс",
        "emoji": "🔴",
        "is_free": False,
        "context": (
            "You are interviewing for Yandex. "
            "Focus areas: algorithms (competitive programming style — complex, multi-step), "
            "C++/Python/Go, large-scale search & recommendation systems, "
            "Yandex infrastructure (YTsaurus, YDB, catboost), machine learning in production. "
            "Questions should be challenging algorithmically with multiple edge cases. "
            "Expect candidates to write optimal solutions and analyze time/space complexity. "
            "Mix in system design for distributed data processing."
        ),
    },
    "tinkoff": {
        "name_en": "Tinkoff",
        "name_ru": "Тинькофф",
        "emoji": "💳",
        "is_free": False,
        "context": (
            "You are interviewing for Tinkoff (T-Bank). "
            "Focus areas: Java/Kotlin (primary stack), Spring Boot, "
            "fintech domain (payments, transactions, anti-fraud, regulatory compliance), "
            "high-load backend architecture, microservices, Kafka, PostgreSQL. "
            "Ask practical backend questions with fintech context. "
            "Include questions about transaction processing, idempotency, "
            "distributed transactions, and financial data consistency. "
            "For behavioral questions, focus on engineering ownership and reliability."
        ),
    },
    "meta": {
        "name_en": "Meta",
        "name_ru": "Meta",
        "emoji": "💙",
        "is_free": False,
        "context": (
            "You are interviewing for Meta (Facebook). "
            "Focus areas: React/JavaScript (frontend), Hack/Python/Haskell (backend), "
            "real-time systems, social graph at scale, distributed caching, "
            "system design with focus on performance and personalization. "
            "Ask product-aware engineering questions — tie every technical choice "
            "to user impact. Emphasize moving fast, iteration, and data-driven decisions. "
            "Include system design for feed/realtime/chat at billions of users."
        ),
    },
    "netflix": {
        "name_en": "Netflix",
        "name_ru": "Netflix",
        "emoji": "🎬",
        "is_free": False,
        "context": (
            "You are interviewing for Netflix. "
            "Focus areas: microservices architecture, chaos engineering, "
            "CDN & video streaming tech, Java/Spring, high availability patterns. "
            "Ask about building resilient distributed systems. "
            "Include questions about chaos engineering, circuit breakers, "
            "content delivery optimization, and A/B testing at scale. "
            "Emphasize freedom & responsibility culture — expect candidates "
            "to own decisions end-to-end."
        ),
    },
    "stripe": {
        "name_en": "Stripe",
        "name_ru": "Stripe",
        "emoji": "⚡",
        "is_free": False,
        "context": (
            "You are interviewing for Stripe. "
            "Focus areas: API design (RESTful, developer experience), "
            "payments infrastructure, idempotency, idempotency, idempotency, "
            "distributed systems, Ruby/Go/Java, developer tools. "
            "Every question should tie back to building for developers. "
            "Include questions about API design trade-offs, idempotent operations, "
            "webhook reliability, idempotency keys, and handling financial reconciliation. "
            "Emphasize correctness, reliability, and API usability."
        ),
    },
}

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "interviews.db")

def get_company_context(company_id: Optional[str]) -> str:
    """Return the AI context prompt for a company set, or empty string for general."""
    if not company_id or company_id == "general":
        return ""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        result = conn.execute(
            "SELECT context FROM company_sets WHERE slug = ? AND is_active = 1",
            (company_id,),
        ).fetchone()
        conn.close()
        if result and result["context"]:
            return result["context"]
    except Exception:
        pass
    return ""
