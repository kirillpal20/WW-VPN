"""
bot_server.py — единственный процесс, который крутится как "Web Service" на Render.

Внутри два дела одновременно:
  1. Telegram-бот (aiogram 3), работающий через вебхук, а не long-polling —
     это нужно, чтобы бот нормально жил на бесплатном тарифе, который "спит".
  2. Обычный HTTP-эндпоинт /sub/{token}, отдающий готовую подписку.

Переменные окружения, которые нужны:
  BOT_TOKEN          — токен бота от @BotFather
  BASE_URL           — публичный адрес этого сервиса на Render,
                        например https://my-vpn-bot.onrender.com
  REDIS_URL          — адрес Redis (Render Key Value даёт готовую строку)
  WEBHOOK_SECRET     — любая случайная строка, для проверки, что вебхук
                        стучится действительно от Telegram (защита от подделки)
"""
from __future__ import annotations

import asyncio
import base64
import os
import uuid
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Update, Message
from aiogram.client.default import DefaultBotProperties
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse

import storage
import checker

BOT_TOKEN = os.environ["BOT_TOKEN"]
BASE_URL = os.environ["BASE_URL"].rstrip("/")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "change-me")
WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET}"

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()


# ---------------------------------------------------------------------------
# Хендлеры бота
# ---------------------------------------------------------------------------

@dp.message(Command("start"))
async def cmd_start(message: Message) -> None:
    tg_id = str(message.from_user.id)

    token = storage.get_str(f"user:{tg_id}")
    if not token:
        token = uuid.uuid4().hex
        storage.set_str(f"user:{tg_id}", token)
        storage.set_str(f"token:{token}", tg_id)

    sub_url = f"{BASE_URL}/sub/{token}"
    await message.answer(
        "Привет! 👋\n\n"
        "Твоя персональная ссылка на подписку (вставь в v2rayNG / Hiddify / Streisand и т.п.):\n\n"
        f"<code>{sub_url}</code>\n\n"
        "Список серверов внутри обновляется автоматически раз в час.\n"
        "Команды: /update — обновить сейчас, /stats — статистика по серверам."
    )


@dp.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    stats = storage.get_json("stats")
    if not stats:
        await message.answer("Пока нет данных — проверка ещё не запускалась. Попробуй /update.")
        return

    lines = [
        f"📊 Обновлено: {stats['updated_at']}",
        f"Всего проверено: {stats['total_checked']}",
        f"Рабочих: {stats['total_working']}",
        f"В подписке сейчас: {stats['top_saved']}",
        "",
        "По категориям (рабочих / всего):",
    ]
    for cat, d in stats.get("by_category", {}).items():
        lines.append(f"  {cat}: {d['working']} / {d['total']}")

    await message.answer("\n".join(lines))


@dp.message(Command("update"))
async def cmd_update(message: Message) -> None:
    await message.answer("Запускаю проверку серверов, это займёт пару минут ⏳")

    loop = asyncio.get_event_loop()

    def _run_and_report():
        try:
            result = checker.run()
            text = (
                f"✅ Проверка завершена.\n"
                f"Рабочих: {result['working']} / {result['total']}\n"
                f"В подписке: {result['saved']}"
            )
        except Exception as e:
            text = f"❌ Проверка сломалась: {e}"
        asyncio.run_coroutine_threadsafe(message.answer(text), loop)

    # checker.run() — синхронный и небыстрый (реальные сетевые проверки),
    # поэтому уводим его в отдельный поток, чтобы не блокировать вебхук
    loop.run_in_executor(None, _run_and_report)


@dp.message(F.text)
async def fallback(message: Message) -> None:
    await message.answer("Не понял команду. Доступно: /start, /update, /stats")


# ---------------------------------------------------------------------------
# FastAPI-приложение
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.set_webhook(
        url=f"{BASE_URL}{WEBHOOK_PATH}",
        drop_pending_updates=True,
    )
    yield
    await bot.delete_webhook()
    await bot.session.close()


app = FastAPI(lifespan=lifespan)


@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update(**data)
    await dp.feed_update(bot, update)
    return {"ok": True}


@app.get("/sub/{token}")
async def get_subscription(token: str):
    tg_id = storage.get_str(f"token:{token}")
    if not tg_id:
        raise HTTPException(status_code=404, detail="Неизвестный токен")

    data = storage.get_json("latest_configs")
    if not data or not data.get("servers"):
        # Отдаём пустую, но валидную подписку, а не ошибку —
        # клиенты вроде v2rayNG не любят получать 404/500 на подписку
        return PlainTextResponse(base64.b64encode(b"").decode())

    links_text = "\n".join(s["raw"] for s in data["servers"])
    encoded = base64.b64encode(links_text.encode()).decode()
    return PlainTextResponse(encoded)


@app.get("/")
async def health():
    return {"status": "ok"}
