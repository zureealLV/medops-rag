"""Deterministic query routing for text and visual evidence paths."""

from __future__ import annotations

from typing import Literal

ResolvedProfile = Literal["text", "visual"]

VISUAL_TERMS = (
    "图片",
    "图像",
    "截图",
    "图标",
    "颜色",
    "形状",
    "示意图",
    "流程图",
    "拓扑图",
    "曲线",
    "柱状图",
    "饼图",
    "看起来",
    "image",
    "picture",
    "screenshot",
    "icon",
    "color",
    "shape",
    "diagram",
    "chart",
    "graph",
    "visual",
)


def route_query(question: str, requested: str = "auto") -> ResolvedProfile:
    if requested == "text":
        return "text"
    if requested == "visual":
        return "visual"
    normalized = question.casefold()
    return "visual" if any(term in normalized for term in VISUAL_TERMS) else "text"
