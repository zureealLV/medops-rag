"""Application policy checks independent from HTTP routing."""

from __future__ import annotations

import re

from app.config import PolicyProfile

MEDICAL_ADVICE = re.compile(r"(诊断|确诊|吃什么药|用药|剂量|治疗方案|处方|diagnos|dosage|treatment)", re.I)
SUPPORTED_DOMAIN = re.compile(
    r"(医|病|症|药|血|菌|病毒|感染|炎|癌|瘤|疼|痛|压疮|检查|手术|预防|护理|"
    r"康复|器械|患者|心脏?|肺|肝|肾|脑|胃|肠|骨|皮肤|眼|牙|孕|新生儿|营养|"
    r"体重|饮食|过敏|免疫|遗传|并发症|副作用|不良反应|临床|健康|生理|体征|呼吸|脉搏|卫生|"
    r"消毒|灭菌|洗手|A1C|medical|medicine|disease|symptom|drug|blood|infection|"
    r"asthma|diabetes|arthritis|diagnos|treatment|surgery|prevention|patient|clinical|"
    r"device|oximeter|infusion|PACS|DICOM|HIS|EMR|LIS|HL7|SSO|Redis|Kafka|NTP|"
    r"影像|挂号|电子签名|信息系统|故障|运维|告警|日志|知识助手|"
    r"backup|VPN|gateway|archive|queue)",
    re.I,
)


def is_medical_advice_request(question: str, profile: PolicyProfile = "medical") -> bool:
    return profile == "medical" and bool(MEDICAL_ADVICE.search(question))


def is_supported_domain_query(question: str, profile: PolicyProfile = "medical") -> bool:
    """Apply a domain allowlist only for the legacy medical validation profile."""
    return profile == "enterprise" or bool(SUPPORTED_DOMAIN.search(question))
