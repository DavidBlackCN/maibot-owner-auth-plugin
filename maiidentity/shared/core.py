from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
import time


class Denied(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def require(condition: bool, code: str) -> None:
    if condition is not True:
        raise Denied(code)


def opaque(value: str) -> str:
    require(type(value) is str and 0 < len(value) <= 256 and value.strip() == value
            and not any(ord(c) < 32 for c in value) and "*" not in value, "INVALID_ID")
    return value


def qq(value: str) -> str:
    require(type(value) is str and re.fullmatch(r"[1-9][0-9]{0,19}", value) is not None, "INVALID_ACCOUNT_ID")
    return value


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Clock:
    def now(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()

    def iso(self) -> str:
        return datetime.fromtimestamp(self.now(), timezone.utc).isoformat()


@dataclass(frozen=True)
class AccountKey:
    platform: str
    adapter_namespace: str
    account_id: str

    def __post_init__(self):
        opaque(self.platform)
        opaque(self.adapter_namespace)
        opaque(self.account_id)
        if self.platform == "qq":
            qq(self.account_id)

    @property
    def key(self) -> str:
        return canonical(asdict(self))
