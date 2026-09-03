"""
Тонкая обёртка над Redis (Render Key Value / любой redis-совместимый сервис).
Всё хранится как JSON-строки под простыми ключами.

Ключи, которые использует проект:
  "latest_configs" -> {"updated_at": "...", "servers": [...]}
  "stats"          -> {"updated_at": "...", "total": .., "working": .., "by_protocol": {...}}
  "user:<tg_id>"   -> "<token>"          (какой токен у юзера)
  "token:<token>"  -> "<tg_id>"          (обратная связь, для проверки в /sub/{token})
"""
from __future__ import annotations

import json
import os

import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

_client: redis.Redis | None = None


def get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(REDIS_URL, decode_responses=True)
    return _client


def get_json(key: str):
    raw = get_client().get(key)
    if raw is None:
        return None
    return json.loads(raw)


def set_json(key: str, value, ex: int | None = None) -> None:
    get_client().set(key, json.dumps(value, ensure_ascii=False), ex=ex)


def get_str(key: str) -> str | None:
    return get_client().get(key)


def set_str(key: str, value: str, ex: int | None = None) -> None:
    get_client().set(key, value, ex=ex)
