"""Application policy checks independent from HTTP routing."""

from __future__ import annotations

import re

MEDICAL_ADVICE = re.compile(r"(诊断|确诊|吃什么药|用药|剂量|治疗方案|处方|diagnos|dosage|treatment)", re.I)


def is_medical_advice_request(question: str) -> bool:
    return bool(MEDICAL_ADVICE.search(question))
