"""
Реальная проверка VLESS-сервера: поднимаем локальный xray-процесс с этим
сервером как outbound, и через него делаем HTTP-запрос наружу.
Если запрос прошёл — сервер живой.

Требует бинарник xray-core. Путь к нему берётся из переменной окружения
XRAY_BIN (по умолчанию просто "xray" — если он есть в PATH).
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import time
from contextlib import closing

import requests

from parser import VlessConfig

XRAY_BIN = os.environ.get("XRAY_BIN", "xray")
TEST_URL = "https://www.gstatic.com/generate_204"   # лёгкий, быстрый, без контента
STARTUP_WAIT_SEC = 1.2   # сколько ждать после запуска xray, прежде чем стучаться в прокси


def _free_port() -> int:
    """Находит свободный TCP-порт на localhost."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _build_outbound(cfg: VlessConfig) -> dict:
    """Собирает xray outbound-конфиг под конкретный тип транспорта/security."""
    stream_settings: dict = {"network": cfg.network}

    if cfg.security == "tls":
        stream_settings["security"] = "tls"
        stream_settings["tlsSettings"] = {
            "serverName": cfg.sni or cfg.address,
            "fingerprint": cfg.fingerprint or "chrome",
            "alpn": cfg.alpn.split(",") if cfg.alpn else None,
        }
    elif cfg.security == "reality":
        stream_settings["security"] = "reality"
        stream_settings["realitySettings"] = {
            "serverName": cfg.sni,
            "fingerprint": cfg.fingerprint or "chrome",
            "publicKey": cfg.public_key,
            "shortId": cfg.short_id,
        }
    else:
        stream_settings["security"] = "none"

    if cfg.network == "ws":
        stream_settings["wsSettings"] = {
            "path": cfg.path or "/",
            "headers": {"Host": cfg.host_header} if cfg.host_header else {},
        }
    elif cfg.network == "grpc":
        stream_settings["grpcSettings"] = {"serviceName": cfg.service_name or ""}
    elif cfg.network in ("xhttp", "http"):
        stream_settings["xhttpSettings"] = {
            "path": cfg.path or "/",
            "host": cfg.host_header or cfg.sni or cfg.address,
        }

    # Убираем пустые ключи (xray не любит мусор в конфиге)
    stream_settings = {k: v for k, v in stream_settings.items() if v not in (None, [], {})}

    return {
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": cfg.address,
                "port": cfg.port,
                "users": [{
                    "id": cfg.uuid,
                    "encryption": cfg.encryption or "none",
                    "flow": cfg.flow or "",
                }],
            }]
        },
        "streamSettings": stream_settings,
    }


def _build_full_config(cfg: VlessConfig, socks_port: int) -> dict:
    return {
        "log": {"loglevel": "none"},
        "inbounds": [{
            "listen": "127.0.0.1",
            "port": socks_port,
            "protocol": "socks",
            "settings": {"udp": False},
        }],
        "outbounds": [
            _build_outbound(cfg),
            {"protocol": "freedom", "tag": "direct"},
        ],
    }


def test_config(cfg: VlessConfig, timeout: float = 7.0) -> tuple[bool, float | None, str]:
    """
    Проверяет один сервер.
    Возвращает (ok, latency_ms, error_message).
    """
    port = _free_port()
    full_config = _build_full_config(cfg, port)

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(full_config, f)
        config_path = f.name

    proc = None
    try:
        proc = subprocess.Popen(
            [XRAY_BIN, "run", "-c", config_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(STARTUP_WAIT_SEC)

        if proc.poll() is not None:
            return False, None, "xray упал сразу при старте (битый конфиг)"

        proxies = {
            "http": f"socks5h://127.0.0.1:{port}",
            "https": f"socks5h://127.0.0.1:{port}",
        }

        start = time.monotonic()
        resp = requests.get(TEST_URL, proxies=proxies, timeout=timeout)
        latency_ms = (time.monotonic() - start) * 1000

        if resp.status_code in (200, 204):
            return True, round(latency_ms, 1), ""
        return False, None, f"неожиданный статус {resp.status_code}"

    except requests.exceptions.RequestException as e:
        return False, None, str(e)[:200]
    except Exception as e:
        return False, None, f"internal: {e}"[:200]
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
        try:
            os.unlink(config_path)
        except OSError:
            pass
