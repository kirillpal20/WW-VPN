"""
checker.py — запускается по расписанию (Render Cron Job, раз в час).

Что делает:
1. Скачивает актуальный output/vless.txt из твоего форка на GitHub.
2. Парсит все ссылки.
3. Каждую реально проверяет через xray-core (поднимает временный процесс,
   стучится через него в интернет).
4. Сортирует рабочие по скорости отклика.
5. Берёт топ-N (по умолчанию 10) и кладёт в Redis — их дальше и раздаёт бот.
6. Заодно считает статистику (сколько всего, сколько живых, по категориям)
   для команды /stats в боте.

Можно запустить и руками: `python checker.py`
"""
from __future__ import annotations

import datetime
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

import storage
from parser import parse_all, VlessConfig
from xray_test import test_config

VLESS_SOURCE_URL = os.environ.get(
    "VLESS_SOURCE_URL",
    "https://raw.githubusercontent.com/kirillpal20/vpn-vless-configs-russia/main/output/vless.txt",
)
TOP_N = int(os.environ.get("TOP_N", "10"))
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "6"))   # осторожно с ресурсами на бесплатном тарифе
FETCH_TIMEOUT = 15


def fetch_configs() -> list[VlessConfig]:
    resp = requests.get(VLESS_SOURCE_URL, timeout=FETCH_TIMEOUT)
    resp.raise_for_status()
    configs = parse_all(resp.text)
    # дедуп по (address, port, uuid) — источник часто дублирует строки
    seen = set()
    unique = []
    for c in configs:
        key = (c.address, c.port, c.uuid)
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def run() -> dict:
    print(f"[checker] Скачиваю список серверов из {VLESS_SOURCE_URL}")
    configs = fetch_configs()
    print(f"[checker] Найдено {len(configs)} уникальных vless-ссылок. Проверяю...")

    working: list[dict] = []
    by_protocol: dict[str, int] = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(test_config, cfg): cfg for cfg in configs}
        done = 0
        for future in as_completed(futures):
            cfg = futures[future]
            done += 1
            ok, latency_ms, err = future.result()

            by_protocol.setdefault(cfg.category, {"total": 0, "working": 0})
            by_protocol[cfg.category]["total"] += 1

            if ok:
                by_protocol[cfg.category]["working"] += 1
                working.append({
                    "raw": cfg.raw,
                    "remark": cfg.remark or f"{cfg.address}:{cfg.port}",
                    "category": cfg.category,
                    "latency_ms": latency_ms,
                })

            if done % 20 == 0 or done == len(configs):
                print(f"[checker] Проверено {done}/{len(configs)}, рабочих пока {len(working)}")

    working.sort(key=lambda x: x["latency_ms"])
    top = working[:TOP_N]

    now = datetime.datetime.utcnow().isoformat()

    storage.set_json("latest_configs", {"updated_at": now, "servers": top})
    storage.set_json("stats", {
        "updated_at": now,
        "total_checked": len(configs),
        "total_working": len(working),
        "top_saved": len(top),
        "by_category": by_protocol,
    })

    print(f"[checker] Готово. Рабочих: {len(working)}/{len(configs)}. Сохранил топ-{len(top)}.")
    return {"total": len(configs), "working": len(working), "saved": len(top)}


if __name__ == "__main__":
    run()
