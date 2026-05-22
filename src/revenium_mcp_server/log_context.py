from __future__ import annotations

import re
import uuid
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from .auth.tenant_context import TenantContext

_SENSITIVE_KEY_PATTERNS = frozenset({"api_key", "api-key", "x-api-key", "authorization"})

_team_id_var: ContextVar[Optional[str]] = ContextVar("team_id", default=None)
_tenant_id_var: ContextVar[Optional[str]] = ContextVar("tenant_id", default=None)
_request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


def bind_tenant_context(ctx: Optional[TenantContext] = None) -> List[Tuple[ContextVar, Token]]:
    tokens: List[Tuple[ContextVar, Token]] = []

    request_id = uuid.uuid4().hex[:12]
    tokens.append((_request_id_var, _request_id_var.set(request_id)))

    if ctx is not None:
        tokens.append((_team_id_var, _team_id_var.set(ctx.team_id)))
        tokens.append((_tenant_id_var, _tenant_id_var.set(ctx.tenant_id)))

    return tokens


def clear_tenant_context(tokens: List[Tuple[ContextVar, Token]]) -> None:
    for var, token in tokens:
        var.reset(token)


def redact_key(value: Optional[str]) -> str:
    if not value:
        return "<empty>"
    if len(value) <= 4:
        return "***"
    return f"***...{value[-4:]}"


def redact_headers(headers: Dict[str, str]) -> Dict[str, str]:
    return {
        k: (redact_key(v) if k.lower() in _SENSITIVE_KEY_PATTERNS else v)
        for k, v in headers.items()
    }


_SENSITIVE_MESSAGE_RE = re.compile(
    r"((?:api[_\-]?key|x-api-key|authorization)[=:\s]+[\"']?(?:bearer\s+)?)([\w\-\.]+)([\"']?(?:\s|,|$|\)))",
    re.IGNORECASE,
)


_STACK_TRACE_RE = re.compile(
    r"Traceback \(most recent call last\):.*?(?=\n\S|\Z)",
    re.DOTALL,
)
_PUBLIC_URL_RE = re.compile(
    r"https?://(?:revenium\.io|docs\.revenium\.io|github\.com)\S*",
)
_URL_PLACEHOLDER = "\x00URL_{}\x00"
_INTERNAL_URL_RE = re.compile(r"https?://[^\s,\"')]+")
_FILE_PATH_RE = re.compile(r'(?:File\s+")?(?<!\w)(?:/[\w.\-]+){2,}(?:")?')


def sanitize_error_message(message: str) -> str:
    preserved: list[str] = []

    def _preserve_url(m: re.Match) -> str:
        preserved.append(m.group(0))
        return _URL_PLACEHOLDER.format(len(preserved) - 1)

    result = _PUBLIC_URL_RE.sub(_preserve_url, message)
    result = _STACK_TRACE_RE.sub("[stack trace removed]", result)
    result = _INTERNAL_URL_RE.sub("[internal url removed]", result)
    result = _FILE_PATH_RE.sub("[path removed]", result)
    result = _redact_message(result)
    for i, url in enumerate(preserved):
        result = result.replace(_URL_PLACEHOLDER.format(i), url)
    return result


def _redact_extras(extras: Dict[str, Any]) -> None:
    for key in list(extras):
        if key.lower() in _SENSITIVE_KEY_PATTERNS:
            val = extras[key]
            if isinstance(val, str):
                extras[key] = redact_key(val)


def _redact_message(message: str) -> str:
    return _SENSITIVE_MESSAGE_RE.sub(
        lambda m: m.group(1) + redact_key(m.group(2)) + m.group(3),
        message,
    )


def tenant_log_patcher(record: Dict[str, Any]) -> None:
    team_id = _team_id_var.get()
    tenant_id = _tenant_id_var.get()
    request_id = _request_id_var.get()

    if request_id is not None:
        record["extra"]["request_id"] = request_id
    if team_id is not None:
        record["extra"]["team_id"] = team_id
    if tenant_id is not None:
        record["extra"]["tenant_id"] = tenant_id

    _redact_extras(record["extra"])
    if "message" in record:
        record["message"] = _redact_message(record["message"])
