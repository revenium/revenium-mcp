from __future__ import annotations

import json
import re
import uuid
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Set, Tuple

if TYPE_CHECKING:
    from .auth.tenant_context import TenantContext

_SENSITIVE_KEY_PATTERNS = frozenset({"api_key", "api-key", "x-api-key", "authorization"})
_SECRET_FIELD_SUFFIXES = (
    "secret",
    "password",
    "passphrase",
    "token",
    "apikey",
    "privatekey",
    "authorization",
)
_NON_LETTERS_RE = re.compile(r"[^a-z]")
REDACTED = "***"
# Echo-masking replaces every substring occurrence, so a shorter value would shred
# unrelated error text; the field itself is still masked by name.
MIN_MASKED_SECRET_LENGTH = 4

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


# Metric and pricing names end in the word "token" without holding one:
# timeToFirstToken, costPerToken, inputCostPerToken, pricePerToken.
_TOKEN_METRIC_ENDINGS = (("per", "token"), ("first", "token"))
_WORD_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")


def _words(name: str) -> List[str]:
    return [word.lower() for word in _WORD_RE.findall(name)]


def is_secret_field(name: str) -> bool:
    if tuple(_words(name)[-2:]) in _TOKEN_METRIC_ENDINGS:
        return False
    return _NON_LETTERS_RE.sub("", name.lower()).endswith(_SECRET_FIELD_SUFFIXES)


def redact_secret_fields(value: Any) -> Any:
    """Return a copy of ``value`` with every secret-named field masked, at any depth."""
    if isinstance(value, dict):
        return {
            key: REDACTED
            if isinstance(key, str) and is_secret_field(key)
            else redact_secret_fields(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_secret_fields(item) for item in value]
    return value


def _scalar_leaves(value: Any) -> Set[str]:
    if isinstance(value, bool):
        return set()
    if isinstance(value, (str, int, float)):
        return {str(value)}
    if isinstance(value, dict):
        return set().union(*(_scalar_leaves(item) for item in value.values()))
    if isinstance(value, (list, tuple)):
        return set().union(*(_scalar_leaves(item) for item in value))
    return set()


def secret_field_values(value: Any) -> Set[str]:
    """Every value ``redact_secret_fields`` masks that is long enough to be masked where echoed."""
    found: Set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and is_secret_field(key):
                found |= _scalar_leaves(item)
            else:
                found |= secret_field_values(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            found |= secret_field_values(item)
    return {secret for secret in found if len(secret) >= MIN_MASKED_SECRET_LENGTH}


def _echoed_forms(secret: str) -> Set[str]:
    return {
        secret,
        json.dumps(secret)[1:-1],
        json.dumps(secret, ensure_ascii=False)[1:-1],
    }


def mask_secret_values(text: Optional[str], secrets: Iterable[str]) -> Optional[str]:
    if not text:
        return text
    forms = set().union(*(_echoed_forms(secret) for secret in secrets if secret))
    for form in sorted(forms, key=len, reverse=True):
        text = text.replace(form, REDACTED)
    return text


def _mask_string_leaves(value: Any, secrets: Set[str]) -> Any:
    if isinstance(value, str):
        return mask_secret_values(value, secrets)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return REDACTED if str(value) in secrets else value
    if isinstance(value, dict):
        return {key: _mask_string_leaves(item, secrets) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mask_string_leaves(item, secrets) for item in value]
    return value


def redact_secrets(value: Any, secrets: Iterable[str]) -> Any:
    """Mask secret-named fields, then every known secret value inside any string, at any depth."""
    return _mask_string_leaves(redact_secret_fields(value), set(secrets))


def _redact_extras(extras: Dict[str, Any]) -> None:
    for key in list(extras):
        val = extras[key]
        if key.lower() in _SENSITIVE_KEY_PATTERNS and isinstance(val, str):
            extras[key] = redact_key(val)
        elif is_secret_field(key):
            extras[key] = REDACTED
        elif isinstance(val, (dict, list, tuple)):
            extras[key] = redact_secret_fields(val)


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
