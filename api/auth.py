"""Telegram Mini App init data validation via HMAC-SHA256."""
import hashlib
import hmac
import json
import time
from typing import Optional
from urllib.parse import parse_qsl

import config


def validate_init_data(init_data: str) -> Optional[dict]:
    """Validate Telegram WebApp init data and return the user dict on success.

    The secret key is derived as HMAC-SHA256(key=bot_token, msg="WebAppData").
    The data-check string is all params except `hash`, sorted by key, joined with newlines.
    auth_date must be within the last 86 400 seconds (24 h).

    Returns:
        Parsed `user` dict on success, None on any failure.
    """
    try:
        params = dict(parse_qsl(init_data, keep_blank_values=True))

        received_hash = params.pop("hash", None)
        if not received_hash:
            return None

        auth_date = int(params.get("auth_date", 0))
        if time.time() - auth_date > 86_400:
            return None

        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(params.items())
        )

        secret_key = hmac.new(
            b"WebAppData",
            config.BOT_TOKEN.encode(),
            hashlib.sha256,
        ).digest()

        computed_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(computed_hash, received_hash):
            return None

        user_str = params.get("user", "{}")
        return json.loads(user_str)

    except Exception:
        return None
