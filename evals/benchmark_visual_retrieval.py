"""Compare OCR-only, CLIP image retrieval, and OCR+image fusion on icon evidence."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from fastembed import ImageEmbedding, TextEmbedding
from PIL import Image, ImageDraw
from rank_bm25 import BM25Okapi
from rapidocr import RapidOCR

from app.retrieval.embeddings import tokenize

ROOT = Path(__file__).resolve().parents[1]
MODEL_PAIRS = (
    ("qdrant_clip_b32", "Qdrant/clip-ViT-B-32-vision", "Qdrant/clip-ViT-B-32-text"),
    ("jina_clip_v1", "jinaai/jina-clip-v1", "jinaai/jina-clip-v1"),
)
CASES = (
    ("red_triangle", "a red triangle icon", "红色三角形图标"),
    ("red_circle", "a red circle icon", "红色圆形图标"),
    ("green_triangle", "a green triangle icon", "绿色三角形图标"),
    ("green_circle", "a green circle icon", "绿色圆形图标"),
    ("blue_square", "a blue square icon", "蓝色正方形图标"),
    ("yellow_star", "a yellow star icon", "黄色五角星图标"),
    ("purple_diamond", "a purple diamond icon", "紫色菱形图标"),
    ("orange_hexagon", "an orange hexagon icon", "橙色六边形图标"),
    ("black_cross", "a black cross icon", "黑色十字图标"),
    ("cyan_ring", "a cyan ring icon", "青色圆环图标"),
    ("magenta_heart", "a magenta heart icon", "洋红色心形图标"),
    ("gray_gear", "a gray gear icon", "灰色齿轮图标"),
    ("blue_arrow_up", "a blue upward arrow icon", "蓝色向上箭头图标"),
    ("red_arrow_down", "a red downward arrow icon", "红色向下箭头图标"),
    ("yellow_moon", "a yellow crescent moon icon", "黄色月牙图标"),
    ("orange_sun", "an orange sun icon", "橙色太阳图标"),
    ("purple_cloud", "a purple cloud icon", "紫色云朵图标"),
    ("black_lock", "a black padlock icon", "黑色挂锁图标"),
    ("cyan_network", "cyan connected network nodes", "青色互联网络节点图标"),
    ("green_check", "a green check mark icon", "绿色对勾图标"),
)
COLORS = {
    "red": "#e53935",
    "green": "#20a464",
    "blue": "#2775d8",
    "yellow": "#f2c94c",
    "purple": "#8e44ad",
    "orange": "#f2994a",
    "black": "#202124",
    "cyan": "#22b8cf",
    "magenta": "#d63384",
    "gray": "#80868b",
}


def _star(cx: int, cy: int, outer: int, inner: int) -> list[tuple[float, float]]:
    points = []
    for index in range(10):
        radius = outer if index % 2 == 0 else inner
        angle = -np.pi / 2 + index * np.pi / 5
        points.append((cx + radius * np.cos(angle), cy + radius * np.sin(angle)))
    return points


def render_icon(name: str) -> Image.Image:
    image = Image.new("RGB", (384, 384), "white")
    draw = ImageDraw.Draw(image)
    color_name, shape = name.split("_", 1)
    color = COLORS[color_name]
    if shape == "triangle":
        draw.polygon([(192, 55), (55, 315), (329, 315)], fill=color)
    elif shape == "circle":
        draw.ellipse((60, 60, 324, 324), fill=color)
    elif shape == "square":
        draw.rounded_rectangle((65, 65, 319, 319), radius=18, fill=color)
    elif shape == "star":
        draw.polygon(_star(192, 195, 145, 62), fill=color)
    elif shape == "diamond":
        draw.polygon([(192, 45), (339, 192), (192, 339), (45, 192)], fill=color)
    elif shape == "hexagon":
        draw.polygon([(110, 55), (274, 55), (350, 192), (274, 329), (110, 329), (34, 192)], fill=color)
    elif shape == "cross":
        draw.polygon(
            [
                (145, 45),
                (239, 45),
                (239, 145),
                (339, 145),
                (339, 239),
                (239, 239),
                (239, 339),
                (145, 339),
                (145, 239),
                (45, 239),
                (45, 145),
                (145, 145),
            ],
            fill=color,
        )
    elif shape == "ring":
        draw.ellipse((45, 45, 339, 339), fill=color)
        draw.ellipse((115, 115, 269, 269), fill="white")
    elif shape == "heart":
        draw.polygon(
            [
                (192, 330),
                (65, 205),
                (65, 125),
                (115, 75),
                (170, 85),
                (192, 120),
                (214, 85),
                (269, 75),
                (319, 125),
                (319, 205),
            ],
            fill=color,
        )
        draw.ellipse((65, 70, 205, 220), fill=color)
        draw.ellipse((179, 70, 319, 220), fill=color)
    elif shape == "gear":
        draw.ellipse((70, 70, 314, 314), fill=color)
        for x, y in (
            (160, 35),
            (220, 35),
            (160, 309),
            (220, 309),
            (35, 160),
            (35, 220),
            (309, 160),
            (309, 220),
        ):
            draw.rectangle((x, y, x + 35, y + 40), fill=color)
        draw.ellipse((145, 145, 239, 239), fill="white")
    elif shape == "arrow_up":
        draw.polygon(
            [(192, 40), (335, 185), (250, 185), (250, 335), (134, 335), (134, 185), (49, 185)], fill=color
        )
    elif shape == "arrow_down":
        draw.polygon(
            [(134, 49), (250, 49), (250, 199), (335, 199), (192, 344), (49, 199), (134, 199)], fill=color
        )
    elif shape == "moon":
        draw.ellipse((60, 45, 330, 330), fill=color)
        draw.ellipse((145, 20, 345, 285), fill="white")
    elif shape == "sun":
        draw.ellipse((105, 105, 279, 279), fill=color)
        for angle in np.linspace(0, 2 * np.pi, 12, endpoint=False):
            x1, y1 = 192 + 115 * np.cos(angle), 192 + 115 * np.sin(angle)
            x2, y2 = 192 + 165 * np.cos(angle), 192 + 165 * np.sin(angle)
            draw.line((x1, y1, x2, y2), fill=color, width=15)
    elif shape == "cloud":
        draw.ellipse((55, 155, 190, 290), fill=color)
        draw.ellipse((120, 90, 270, 280), fill=color)
        draw.ellipse((215, 145, 335, 285), fill=color)
        draw.rectangle((90, 205, 300, 285), fill=color)
    elif shape == "lock":
        draw.rounded_rectangle((85, 160, 299, 330), radius=20, fill=color)
        draw.arc((115, 45, 269, 225), 180, 360, fill=color, width=35)
    elif shape == "network":
        nodes = [(80, 100), (300, 85), (190, 190), (85, 300), (300, 295)]
        for left, right in ((0, 2), (1, 2), (2, 3), (2, 4), (0, 1), (3, 4)):
            draw.line((*nodes[left], *nodes[right]), fill=color, width=12)
        for x, y in nodes:
            draw.ellipse((x - 25, y - 25, x + 25, y + 25), fill=color)
    elif shape == "check":
        draw.line((70, 200, 155, 290, 320, 85), fill=color, width=45, joint="curve")
    else:
        raise ValueError(name)
    return image


def _normalize(vector) -> np.ndarray:
    output = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(output))
    return output / norm if norm else output


def _rank(scores: list[float]) -> list[int]:
    return sorted(range(len(scores)), key=lambda index: (-scores[index], index))


def _scaled(scores: list[float]) -> list[float]:
    low, high = min(scores), max(scores)
    if high <= low:
        return [0.0] * len(scores)
    return [(score - low) / (high - low) for score in scores]


def _summary(ranks: list[int], latencies: list[float]) -> dict[str, float]:
    return {
        "hit_at_1": round(sum(rank == 1 for rank in ranks) / len(ranks), 4),
        "hit_at_5": round(sum(rank <= 5 for rank in ranks) / len(ranks), 4),
        "mrr": round(statistics.fmean(1.0 / rank for rank in ranks), 4),
        "query_mean_ms": round(statistics.fmean(latencies), 3),
        "query_p95_ms": round(sorted(latencies)[round((len(latencies) - 1) * 0.95)], 3),
    }


def run(cache_dir: Path) -> dict[str, object]:
    names = [case[0] for case in CASES]
    images = [render_icon(name) for name in names]
    ocr = RapidOCR()
    ocr_started = time.perf_counter()
    ocr_texts = []
    for image in images:
        result = ocr(image)
        ocr_texts.append(" ".join(result.txts or ()))
    ocr_index_ms = (time.perf_counter() - ocr_started) * 1000
    ocr_corpus = [tokenize(text) or ["__no_ocr__"] for text in ocr_texts]
    bm25 = BM25Okapi(ocr_corpus)

    model_results: list[dict[str, object]] = []
    for label, image_model_name, text_model_name in MODEL_PAIRS:
        started = time.perf_counter()
        image_model = ImageEmbedding(image_model_name, cache_dir=str(cache_dir))
        text_model = TextEmbedding(text_model_name, cache_dir=str(cache_dir))
        load_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        image_vectors = [_normalize(vector) for vector in image_model.embed(images)]
        index_ms = (time.perf_counter() - started) * 1000
        # Remove one-time tokenizer/session setup from per-query steady-state figures.
        next(text_model.query_embed("warmup query"))

        languages: dict[str, object] = {}
        for language, query_index in (("english", 1), ("chinese", 2)):
            image_ranks: list[int] = []
            ocr_ranks: list[int] = []
            fusion_ranks: list[int] = []
            image_latencies: list[float] = []
            ocr_latencies: list[float] = []
            for expected, case in enumerate(CASES):
                query = case[query_index]
                started = time.perf_counter()
                query_vector = _normalize(next(text_model.query_embed(query)))
                image_scores = [float(np.dot(query_vector, vector)) for vector in image_vectors]
                image_latencies.append((time.perf_counter() - started) * 1000)

                started = time.perf_counter()
                ocr_scores = [float(score) for score in bm25.get_scores(tokenize(query))]
                ocr_latencies.append((time.perf_counter() - started) * 1000)
                fusion_scores = [
                    0.8 * image_score + 0.2 * ocr_score
                    for image_score, ocr_score in zip(_scaled(image_scores), _scaled(ocr_scores), strict=True)
                ]
                image_ranks.append(_rank(image_scores).index(expected) + 1)
                ocr_ranks.append(_rank(ocr_scores).index(expected) + 1)
                fusion_ranks.append(_rank(fusion_scores).index(expected) + 1)
            languages[language] = {
                "image_only": _summary(image_ranks, image_latencies),
                "ocr_only": _summary(ocr_ranks, ocr_latencies),
                "image_80_ocr_20": _summary(
                    fusion_ranks,
                    [left + right for left, right in zip(image_latencies, ocr_latencies, strict=True)],
                ),
            }
        model_results.append(
            {
                "label": label,
                "image_model": image_model_name,
                "text_model": text_model_name,
                "cached_load_ms": round(load_ms, 3),
                "index_20_images_ms": round(index_ms, 3),
                "languages": languages,
            }
        )
    return {
        "benchmark": "visual-icons-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "cases": len(CASES),
        "queries": len(CASES) * 2,
        "visual_only": True,
        "fixture": "generated 384x384 icons without text",
        "ocr_index_20_images_ms": round(ocr_index_ms, 3),
        "ocr_nonempty_images": sum(bool(text.strip()) for text in ocr_texts),
        "models": model_results,
        "limitations": [
            "Synthetic icons test cross-modal color/shape matching, not charts or clinical images.",
            "Model files were cached before timed load; network download is excluded.",
            "Fusion weight 80/20 was fixed before evaluation and was not tuned on these cases.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "data/models/fastembed")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run(args.cache_dir)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
