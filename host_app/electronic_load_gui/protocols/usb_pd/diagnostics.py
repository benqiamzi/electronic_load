from dataclasses import dataclass
from enum import StrEnum


class ParseStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"
    CONTEXT_MISSING = "context_missing"


@dataclass(frozen=True, slots=True)
class ParseDiagnostic:
    layer: str
    code: str
    message: str
