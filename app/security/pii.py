"""Conservative redaction for logs and audit metadata."""

from __future__ import annotations

import re

PATTERNS = (
    (re.compile(r"\b1[3-9]\d{9}\b"), "[REDACTED_PHONE]"),
    (re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
    (re.compile(r"\b\d{17}[\dXx]\b"), "[REDACTED_ID]"),
    (
        re.compile(r"\b(?:patient|患者)[-_ ]?(?:id|编号)?[:： ]*[A-Za-z0-9-]{4,}\b", re.I),
        "[REDACTED_PATIENT_ID]",
    ),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._-]+"), r"\1[REDACTED_TOKEN]"),
)


def redact(text: str) -> str:
    result = text
    for pattern, replacement in PATTERNS:
        result = pattern.sub(replacement, result)
    return result
