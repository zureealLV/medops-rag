"""Generate README diagrams from committed benchmark reports.

The output is dependency-free SVG so GitHub can render the figures directly and
the values remain traceable to the JSON files under ``reports/``.
"""

# ruff: noqa: E501

from __future__ import annotations

import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"
FONT = "Inter,Segoe UI,Microsoft YaHei,sans-serif"


def write_svg(name: str, body: str, *, width: int, height: int) -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#fff7f5"/><stop offset="0.52" stop-color="#f8fbff"/><stop offset="1" stop-color="#eafcff"/></linearGradient>
    <linearGradient id="brand" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#5267f5"/><stop offset="1" stop-color="#20beb7"/></linearGradient>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="160%"><feDropShadow dx="0" dy="10" stdDeviation="12" flood-color="#23335c" flood-opacity="0.10"/></filter>
    <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#7d8bb4"/></marker>
  </defs>
  <rect width="{width}" height="{height}" rx="28" fill="url(#bg)"/>
  {body}
</svg>'''
    (ASSETS / name).write_text(svg, encoding="utf-8")


def text(x: float, y: float, value: str, *, size: int = 22, weight: int = 500,
         fill: str = "#233153", anchor: str = "start", opacity: float = 1.0) -> str:
    return (f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" opacity="{opacity}">{escape(value)}</text>')


def box(x: int, y: int, w: int, h: int, title: str, subtitle: str,
        *, accent: str = "#5267f5", fill: str = "#ffffff") -> str:
    return "\n".join([
        f'<g filter="url(#shadow)"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="22" fill="{fill}" stroke="#dce4f5"/></g>',
        f'<rect x="{x}" y="{y}" width="8" height="{h}" rx="4" fill="{accent}"/>',
        text(x + 28, y + 44, title, size=22, weight=700),
        text(x + 28, y + 76, subtitle, size=14, fill="#697897"),
    ])


def flow_diagram() -> None:
    parts = [
        text(56, 65, "MEDOPS RAG · 从资料到可审计回答", size=30, weight=800),
        text(56, 98, "同一条安全边界内完成摄取、检索、编排、引用与审计", size=16, fill="#6d7895"),
        box(56, 145, 250, 112, "资料 / 业务问题", "PDF · Office · 图片 · API · MCP", accent="#ff7065"),
        box(390, 145, 250, 112, "身份与租户边界", "API Key · RBAC · SQL 前置隔离", accent="#7a67ee"),
        box(724, 145, 250, 112, "策略路由", "摄取路径 / 问答路径自动分流", accent="#5267f5"),
        box(1058, 145, 286, 112, "任务与可观测性", "队列 · Deadline · 熔断 · 指标", accent="#20beb7"),
        '<path d="M306 201 H382" stroke="#7d8bb4" stroke-width="3" marker-end="url(#arrow)"/>',
        '<path d="M640 201 H716" stroke="#7d8bb4" stroke-width="3" marker-end="url(#arrow)"/>',
        '<path d="M974 201 H1050" stroke="#7d8bb4" stroke-width="3" marker-end="url(#arrow)"/>',
        text(80, 330, "A · 知识摄取", size=16, weight=800, fill="#ff7065"),
        box(56, 355, 280, 120, "安全解析", "格式门禁 · OCR · 元素/坐标", accent="#ff7065"),
        box(390, 355, 280, 120, "语义分块", "中文边界 · Parent–Child", accent="#ff9d64"),
        box(724, 355, 280, 120, "索引与证据", "FTS5 · BM25 · 向量 · 原图", accent="#f6bb4b"),
        '<path d="M336 415 H382" stroke="#7d8bb4" stroke-width="3" marker-end="url(#arrow)"/>',
        '<path d="M670 415 H716" stroke="#7d8bb4" stroke-width="3" marker-end="url(#arrow)"/>',
        text(80, 535, "B · 证据问答", size=16, weight=800, fill="#5267f5"),
        box(56, 560, 280, 120, "自适应检索", "BM25 · RRF · Parent–Child", accent="#5267f5"),
        box(390, 560, 280, 120, "证据与安全门禁", "阈值拒答 · 注入隔离 · 引用复核", accent="#7a67ee"),
        box(724, 560, 280, 120, "受控 Agent", "LangGraph · 只读工具 · Checkpoint", accent="#8f5de7"),
        '<g filter="url(#shadow)"><rect x="1058" y="457" width="286" height="223" rx="22" fill="#f4ffff" stroke="#dce4f5"/></g>',
        '<rect x="1058" y="457" width="8" height="223" rx="4" fill="#20beb7"/>',
        text(1086, 501, "输出", size=22, weight=700),
        '<path d="M336 620 H382" stroke="#7d8bb4" stroke-width="3" marker-end="url(#arrow)"/>',
        '<path d="M670 620 H716" stroke="#7d8bb4" stroke-width="3" marker-end="url(#arrow)"/>',
        '<path d="M1004 620 H1050" stroke="#7d8bb4" stroke-width="3" marker-end="url(#arrow)"/>',
        text(1201, 548, "回答正文", size=24, weight=800, anchor="middle"),
        text(1201, 585, "+ 来源卡片", size=22, weight=700, anchor="middle", fill="#5267f5"),
        text(1201, 622, "+ 审计轨迹", size=22, weight=700, anchor="middle", fill="#20a8a2"),
        text(1201, 654, "证据不足就不编", size=14, anchor="middle", fill="#697897"),
    ]
    write_svg("medops-flow.svg", "\n".join(parts), width=1400, height=730)


def grouped_bar_chart() -> None:
    report = json.loads((ROOT / "reports" / "adaptive-routing-challenge-zh-v3.json").read_text(encoding="utf-8"))
    rows = [(name, report["source_ranking"][name]) for name in ("bm25", "rrf", "parent_child", "adaptive")]
    labels = {"bm25": "BM25", "rrf": "RRF", "parent_child": "Parent–Child", "adaptive": "Adaptive"}
    parts = [
        text(50, 58, "独立中文挑战集 V3 · 来源排序", size=28, weight=800),
        text(50, 90, "20 个单来源用例；冻结数据，零 Provider/API 调用", size=15, fill="#6d7895"),
        '<line x1="120" y1="410" x2="1140" y2="410" stroke="#b9c5dd" stroke-width="2"/>',
    ]
    for pct in (0, 25, 50, 75, 100):
        y = 410 - pct * 2.8
        parts += [f'<line x1="120" y1="{y}" x2="1140" y2="{y}" stroke="#dfe6f3"/>', text(98, y + 6, f"{pct}%", size=13, fill="#7c89a5", anchor="end")]
    for i, (name, values) in enumerate(rows):
        cx = 225 + i * 245
        for j, (metric, color) in enumerate((("hit_at_1", "#5267f5"), ("hit_at_5", "#20beb7"))):
            value = values[metric]
            h = value * 280
            x = cx + j * 64 - 56
            parts += [f'<rect x="{x}" y="{410-h}" width="48" height="{h}" rx="10" fill="{color}"/>', text(x + 24, 396 - h, f"{value*100:.0f}%", size=14, weight=700, anchor="middle")]
        parts.append(text(cx - 24, 448, labels[name], size=15, weight=700, anchor="middle"))
    parts += [
        '<rect x="895" y="48" width="18" height="18" rx="5" fill="#5267f5"/>', text(922, 63, "Hit@1", size=14),
        '<rect x="1000" y="48" width="18" height="18" rx="5" fill="#20beb7"/>', text(1027, 63, "Hit@5", size=14),
        text(50, 500, "结论：Adaptive 与 RRF 在 Hit@5 达到 100%，但 Adaptive 的 Hit@1 仅 80%；这是暴露短板的挑战集，不是满分海报。", size=15, fill="#566582"),
    ]
    write_svg("benchmark-retrieval.svg", "\n".join(parts), width=1200, height=540)


def concurrency_chart() -> None:
    report = json.loads((ROOT / "reports" / "concurrency-benchmark-v3.json").read_text(encoding="utf-8"))
    rows = report["scenarios"]["answer_controlled_model"]
    levels = [1, 4, 16, 32]
    throughput = [rows[str(v)]["median_throughput_requests_per_second"] for v in levels]
    p95 = [rows[str(v)]["median_client_p95_ms"] for v in levels]
    parts = [
        text(50, 58, "15,000 文档 · 完整回答路径并发剖面", size=28, weight=800),
        text(50, 90, "单进程 ASGITransport；确定性离线模型延迟 75 ms；所有请求 0 错误", size=15, fill="#6d7895"),
    ]
    panels = [(55, "吞吐量 (req/s)", throughput, 80, "#5267f5"), (625, "客户端 P95 (ms)", p95, 1000, "#ff7065")]
    for left, title_value, values, ceiling, color in panels:
        parts += [text(left, 140, title_value, size=18, weight=700), f'<line x1="{left}" y1="410" x2="{left+500}" y2="410" stroke="#b9c5dd" stroke-width="2"/>']
        points = []
        for i, (level, value) in enumerate(zip(levels, values, strict=True)):
            x = left + 65 + i * 135
            y = 390 - min(value / ceiling, 1) * 220
            points.append(f"{x},{y}")
            parts += [f'<circle cx="{x}" cy="{y}" r="9" fill="{color}"/>', text(x, y - 20, f"{value:.1f}", size=14, weight=700, anchor="middle"), text(x, 445, f"并发 {level}", size=14, anchor="middle", fill="#65728e")]
        parts.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>')
    parts.append(text(50, 505, "并发 16 时吞吐达到 67.7 req/s；并发 32 的 P95 升至 973.9 ms，说明背压与容量门禁比盲目加并发更重要。", size=15, fill="#566582"))
    write_svg("benchmark-concurrency.svg", "\n".join(parts), width=1200, height=545)


def orchestration_chart() -> None:
    report = json.loads((ROOT / "reports" / "agent-orchestration-benchmark-v3.json").read_text(encoding="utf-8"))
    modes = [("classic", "Classic"), ("langchain", "LangChain LCEL"), ("langgraph", "LangGraph")]
    colors = ["#5267f5", "#20beb7", "#8f5de7"]
    parts = [
        text(50, 58, "Agent 编排开销 · 600 次/模式", size=28, weight=800),
        text(50, 90, "同数据、同检索、同 Prompt、同离线模型；三种模式质量指标均为 100%", size=15, fill="#6d7895"),
        '<line x1="125" y1="410" x2="1135" y2="410" stroke="#b9c5dd" stroke-width="2"/>',
    ]
    for tick in (0, 3, 6, 9, 12):
        y = 410 - tick * 20
        parts += [f'<line x1="125" y1="{y}" x2="1135" y2="{y}" stroke="#dfe6f3"/>', text(105, y + 5, f"{tick} ms", size=13, fill="#7c89a5", anchor="end")]
    for i, ((key, label), color) in enumerate(zip(modes, colors, strict=True)):
        value = report["results"][key]["latency_ms"]["p95"]
        h = value * 20
        x = 235 + i * 300
        parts += [f'<rect x="{x}" y="{410-h}" width="120" height="{h}" rx="16" fill="{color}"/>', text(x + 60, 392 - h, f"P95 {value:.3f} ms", size=15, weight=700, anchor="middle"), text(x + 60, 450, label, size=16, weight=700, anchor="middle")]
    parts.append(text(50, 505, "LangGraph 相比 Classic 的平均额外开销为 1.986 ms；换来可观察节点、只读工具选择与可恢复控制状态。", size=15, fill="#566582"))
    write_svg("benchmark-orchestration.svg", "\n".join(parts), width=1200, height=545)


if __name__ == "__main__":
    flow_diagram()
    grouped_bar_chart()
    concurrency_chart()
    orchestration_chart()
    print(f"Generated README SVG assets in {ASSETS}")
