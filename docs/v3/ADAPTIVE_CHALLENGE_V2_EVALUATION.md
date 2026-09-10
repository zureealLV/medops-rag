# Adaptive Challenge V2 离线评测

## 1. 为什么另建 V2 挑战集

`adaptive challenge v2` 是独立于以下两组数据的新评测：

- 阈值开发集：`evals/v2_retrieval_cases.jsonl`
- 第一版留出集：`evals/adaptive_heldout_cases_zh.jsonl`

本次 48 个问题与前两组数据的**规范化问题完全重复数为 0**，28 个文档的
`source` 重复数也为 0。运行器不修改路由阈值、不接受用户指定策略，也不调用
模型 Provider 或应用 HTTP API。

此评测刻意拆开四种不能混为一谈的证据：

1. 单来源问题衡量 source ranking；
2. 多来源问题衡量 recall 和完整覆盖；
3. 不可回答问题只观察路由，不能伪装成拒答准确率；
4. 租户隔离问题使用真实 SQLite repository/service 过滤，不能按普通负例计算。

## 2. 数据设计

| 范围 | 数量 | 计分方式 |
|---|---:|---|
| 模糊/短查询 | 8 | 单来源 Hit@K、MRR@5、nDCG@5 |
| Markdown 表格文本 | 8 | 单来源 Hit@K、MRR@5、nDCG@5 |
| 长上下文 | 8 | 单来源 Hit@K、MRR@5、nDCG@5 |
| 多来源覆盖 | 8 | macro Recall@3/5、全部来源覆盖率@3/5 |
| 不可回答 | 8 | 仅 route/reason 分布 |
| 租户隔离 | 8 | 泄漏数、跨租户 KB 是否隐藏 |

文档按三个租户分布：

- `hospital-green`：20 篇正常检索文档；
- `hospital-amber`：4 篇带唯一敏感标记的外租户文档；
- `hospital-violet`：4 篇带唯一敏感标记的外租户文档。

长文档均超过 350 个字符，并会被当前 `350/50` child 配置切成至少两个子块。
表格用例实际包含 Markdown 管道表，而不是把普通段落贴上“表格”标签。

## 3. 指标边界

### 3.1 Source ranking

只纳入恰好有一个相关来源的 24 个问题。Hit@K、MRR@5 与 nDCG@5 的分母均为
24，不包含多来源、不可回答或租户隔离用例。

### 3.2 Multi-source coverage

每个问题要求两个来源。指标为：

- `mean_recall_at_k`：每个问题找回的必需来源比例，再做宏平均；
- `full_coverage_at_k`：前 K 个结果是否同时覆盖全部必需来源。

这里不能使用 Hit@1，因为一个结果天然不可能证明两个来源均已覆盖。

### 3.3 Negative route-only

不可回答问题没有相关文档，因此不计算 Hit@K，也不声称测得拒答准确率。路由器
只决定检索引擎，领域门、证据充分性门和最终 abstention 属于后续阶段。

### 3.4 真实租户隔离探针

运行器会建立临时 SQLite 数据库，把三个租户的全部文档真实写入当前 schema，随后
调用：

- `app.repositories.documents.retrieval_rows`
- `app.repositories.documents.lexical_candidate_rows`
- `app.services.retrieval.search`

每个探针先在数据库中证明外租户目标和敏感标记确实存在，再以
`hospital-green` 身份执行全库检索，并尝试指定外租户 KB ID。检查发生在真实 SQL
租户谓词和服务层路径上，而不是先在 Python 列表里删掉外租户文档。

这仍不是 PostgreSQL RLS、分布式向量库过滤或 API-key 认证测试，相关边界不得扩大
解释。

## 4. 可复现实测结果

运行环境：

- MedOps RAG `3.2.0`
- Git 基线 `19d7a691a56b740c166bf217dd712034d222b06f`
- Python `3.11.5`
- FastEmbed `0.7.4`
- rank-bm25 `0.2.2`
- NumPy `2.4.6`
- 本地模型 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- query repetitions：`1`

### 4.1 单来源排名

| 策略 | Hit@1 | Hit@3 | MRR@5 | 平均延迟 | P95 |
|---|---:|---:|---:|---:|---:|
| BM25 | 1.0000 | 1.0000 | 1.0000 | 0.475 ms | 0.873 ms |
| RRF | 0.9583 | 1.0000 | 0.9792 | 72.482 ms | 90.118 ms |
| Parent-Child | 1.0000 | 1.0000 | 1.0000 | 0.545 ms | 1.006 ms |
| Adaptive | 1.0000 | 1.0000 | 1.0000 | 17.924 ms | 85.010 ms |

RRF 唯一的 Top-1 失败是 `ch2-long-04`：目标
`radiotherapy-plan-handoff-full.md` 排在第 2。Adaptive 将全部 8 个长上下文问题送入
Parent-Child，因此该题恢复到 Top-1。但这不能证明 Adaptive 普遍优于固定策略：BM25
和 Parent-Child 在当前单来源集上同样为 1.0000。

### 4.2 多来源覆盖

四种策略在本次 8 个问题上均得到：

- macro Recall@3：`1.0000`
- full coverage@3：`1.0000`
- macro Recall@5：`1.0000`
- full coverage@5：`1.0000`

这说明当前手写双来源问题还不足以区分四个引擎，不能反向宣称所有真实多来源查询
都已解决。下一轮应增加三来源、术语冲突和跨文档弱词汇关联。

### 4.3 自适应路由分布

| 范围 | BM25 | RRF | Parent-Child |
|---|---:|---:|---:|
| 单来源排名 | 16 | 0 | 8 |
| 多来源覆盖 | 1 | 7 | 0 |
| Negative route-only | 5 | 3 | 0 |
| 租户隔离问题 | 7 | 1 | 0 |

`ch2-multi-08` 虽是多来源问题，但因含 `NTP` 标识且中文分词后的 token 数未触发
语义阈值，被路由到 BM25。这是值得后续分析的可观察行为，不在本评测中改阈值掩盖。

### 4.4 租户隔离

- 外租户目标已证明确实存在：`8/8`
- repository 全量候选泄漏：`0`
- FTS 候选泄漏：`0`
- service 搜索来源或敏感标记泄漏：`0`
- 外租户 KB ID 被隐藏：`8/8`

## 5. 离线与可追溯性

运行器在导入 FastEmbed 前强制：

```text
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
HF_HUB_DISABLE_TELEMETRY=1
```

模型构造使用 `local_files_only=True`，同时用 socket guard 禁止 `connect` 和
`create_connection`。任何网络尝试会让评测直接失败，而不是悄悄联网。

本次报告记录的 SHA-256：

```text
adaptive_challenge_v2_documents_zh.jsonl
0f06fca87b2c60cefe2078659122fe5a09c3d059d5725c9a3e8a39df25279466

adaptive_challenge_v2_cases_zh.jsonl
0d8a6a84bd9272c8164df013402045b3426cd823c86580db8177d6dfdbf1f810

benchmark_adaptive_challenge_v2.py
1851516deb5f9fbee9843490359aca034846996614e167f7b4e15c9dd417b2c8

app/retrieval/adaptive.py
09ee92695a6dc86a840460028b37c77f386af3f7bd56e42d57a4ee7ff580761a
```

## 6. 复现命令

```powershell
cd 'D:\Codex Program files\medops-rag'
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe evals\benchmark_adaptive_challenge_v2.py `
  --repetitions 1 `
  --output reports\adaptive-routing-challenge-zh-v2.json
.\.venv\Scripts\pytest.exe -q tests\test_adaptive_challenge_v2_benchmark.py
.\.venv\Scripts\ruff.exe check `
  evals\benchmark_adaptive_challenge_v2.py `
  tests\test_adaptive_challenge_v2_benchmark.py
```

## 7. 限制

1. 这是手工合成挑战集，不是盲测、真实流量或临床验证。
2. 短查询的标签依赖 `hospital-green` 运维语境，真实输入会更模糊且含错别字。
3. 表格只测试已抽取 Markdown 文本，不测试 PDF 表格抽取质量。
4. 多来源指标只检查来源是否找回，不检查生成答案是否忠实合并事实。
5. 租户探针不覆盖 API-key、PostgreSQL RLS 或外部分布式向量库。
6. 延迟是单机快照，且不把模型加载和建索引时间计入查询延迟。
7. MiniLM 只是本地已缓存模型，不是独立中文 embedding bake-off 的胜者。
8. 本评测没有为了分数修改路由阈值或任何 `app` 主代码。
