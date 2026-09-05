"""Heuristics for quarantining instructions embedded in retrieved documents."""

from __future__ import annotations

import re

SUSPICIOUS_PATTERNS = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"ignore (all |the )?(previous|system) instructions",
        r"忽略(之前|以上|系统)(的)?指令",
        r"(reveal|leak|print).{0,20}(secret|prompt|all documents)",
        r"(泄露|输出).{0,20}(全部文档|系统提示|密钥)",
        r"(run_shell|delete_database|send_email)\s*\(",
    )
)


def has_injection_signals(text: str) -> bool:
    return any(pattern.search(text) for pattern in SUSPICIOUS_PATTERNS)
