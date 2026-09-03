"""
Разбирает vless://... ссылку на составные части.

Формат ссылки:
vless://<uuid>@<host>:<port>?<query-параметры>#<remark>

Пример:
vless://884f23e9-caab-4775-9ed9-6a3a9cae677f@151.101.69.253:443
    ?type=xhttp&security=tls&sni=example.com&path=%2Fabc&fp=chrome
    #Germany%20Frankfurt
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse, parse_qs, unquote


@dataclass
class VlessConfig:
    raw: str                     # исходная ссылка целиком, без изменений
    uuid: str
    address: str
    port: int
    remark: str = ""             # человекочитаемое имя сервера (из #fragment)

    # транспорт / безопасность — то, что определяет категорию сервера
    network: str = "tcp"         # tcp | ws | grpc | xhttp | http
    security: str = "none"       # none | tls | reality
    sni: str = ""
    fingerprint: str = ""
    flow: str = ""
    path: str = ""
    host_header: str = ""
    alpn: str = ""
    service_name: str = ""       # для grpc
    public_key: str = ""         # pbk, для reality
    short_id: str = ""           # sid, для reality
    encryption: str = "none"

    extra: dict = field(default_factory=dict)  # всё остальное, на всякий случай

    @property
    def category(self) -> str:
        """Грубая категория для статистики/фильтрации: REALITY / WS / XHTTP / OTHER."""
        if self.security == "reality":
            return "REALITY"
        if self.network == "ws":
            return "WS"
        if self.network == "xhttp":
            return "XHTTP"
        if self.network == "grpc":
            return "GRPC"
        return "OTHER"


def parse_vless(link: str) -> VlessConfig | None:
    """Пытается распарсить одну строку. Возвращает None, если строка не похожа на валидный vless://."""
    link = link.strip()
    if not link or not link.startswith("vless://"):
        return None

    try:
        parsed = urlparse(link)
        uuid = parsed.username
        host = parsed.hostname
        port = parsed.port

        if not uuid or not host or not port:
            return None

        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        remark = unquote(parsed.fragment) if parsed.fragment else ""

        cfg = VlessConfig(
            raw=link,
            uuid=uuid,
            address=host,
            port=port,
            remark=remark,
            network=params.pop("type", "tcp").lower(),
            security=params.pop("security", "none").lower(),
            sni=params.pop("sni", ""),
            fingerprint=params.pop("fp", ""),
            flow=params.pop("flow", ""),
            path=unquote(params.pop("path", "")),
            host_header=params.pop("host", ""),
            alpn=params.pop("alpn", ""),
            service_name=params.pop("serviceName", ""),
            public_key=params.pop("pbk", ""),
            short_id=params.pop("sid", ""),
            encryption=params.pop("encryption", "none"),
        )
        cfg.extra = params  # то, что осталось нераспознанным (headerType и т.п.)
        return cfg
    except Exception:
        # Битая/кривая ссылка — просто пропускаем, а не роняем весь скрипт
        return None


def parse_all(text: str) -> list[VlessConfig]:
    """Парсит многострочный текст (файл vless.txt), пропуская пустые строки и комментарии."""
    result = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cfg = parse_vless(line)
        if cfg:
            result.append(cfg)
    return result
