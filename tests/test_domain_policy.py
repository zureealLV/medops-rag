"""Configurable domain-policy regression tests."""

import pytest

from app.security.policies import is_supported_domain_query


@pytest.mark.parametrize(
    "question",
    [
        "影像存储容量告警应观察什么？",
        "挂号接口错误率升高时怎样排查？",
        "电子签名服务异常可能影响什么操作？",
        "收到信息系统告警后第一步是什么？",
        "故障复盘要区分哪些因素？",
        "知识助手被禁止执行哪些操作？",
    ],
)
def test_medical_operations_queries_stay_in_scope(question: str):
    assert is_supported_domain_query(question)


@pytest.mark.parametrize(
    "question",
    [
        "月球基地的氧气产量是多少？",
        "量子计算机有多少个量子比特？",
        "明天合肥会不会下雨？",
    ],
)
def test_obviously_unrelated_queries_stay_out_of_scope(question: str):
    assert not is_supported_domain_query(question)


def test_enterprise_profile_defers_domain_scope_to_retrieval_evidence():
    assert is_supported_domain_query("员工年假可以结转到下一年吗？", profile="enterprise")
