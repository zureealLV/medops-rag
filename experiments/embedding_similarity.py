"""Inspect the offline hashing embedding on synthetic sentences."""

from app.retrieval.embeddings import cosine, embed

SENTENCES = [
    "LIS 实验室检查系统接口超时",
    "检验消息队列出现积压",
    "PACS 影像 DICOM 端口异常",
    "HIS 挂号接口错误率升高",
    "医院食堂菜单更新",
]


def main() -> None:
    query = "实验室检验系统连接超时"
    query_vector = embed(query)
    ranked = sorted(
        ((cosine(query_vector, embed(sentence)), sentence) for sentence in SENTENCES), reverse=True
    )
    print(f"query: {query}")
    for score, sentence in ranked:
        print(f"{score: .4f}  {sentence}")


if __name__ == "__main__":
    main()
