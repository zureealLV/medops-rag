# Adaptive Routing Challenge V3：冻结后的独立离线评测

## 结论

这轮不是继续把题做得像训练集，而是在**数据冻结后**直接运行当前
`app/retrieval/adaptive.py` 路由策略。V3 的 36 个中文问题和 28 份文档与以下三套既有数据均隔离：

1. threshold tuning：`v2_retrieval_*`；
2. heldout-v1：`adaptive_heldout_*`；
3. challenge-v2：`adaptive_challenge_v2_*`。

当前 adaptive 路径在 20 个单来源问题上取得：

- Hit@1：`16/20 = 0.8000`；
- Hit@3：`19/20 = 0.9500`；
- Hit@5：`20/20 = 1.0000`；
- MRR@5：`0.8767`；
- nDCG@5：`0.9074`。

分组结果不是全满分：错别字/噪声 `10/10` Hit@1，低词面重叠 `6/10` Hit@1。三来源题的
adaptive macro Recall@3 为 `17/24 = 0.7083`，Recall@5 为 `20/24 = 0.8333`；三份必需来源
全部进入 Top-3 的问题为 `3/8 = 0.3750`，全部进入 Top-5 的问题为 `5/8 = 0.6250`。

这些结果说明当前路由与检索在错字场景中较稳，但低词面重叠和三来源完整覆盖仍是清晰短板。
V3 不声称 adaptive 优于固定策略：同一冻结集上，BM25 的单来源 Hit@1 为 `0.8500`，三来源
Recall@5 为 `0.8750`、完整覆盖率为 `0.7500`，均高于 adaptive。

## 数据集与冻结门禁

| 评测范围 | 类别 | 数量 | 计分方式 |
| --- | --- | ---: | --- |
| 单来源检索 | typo/noise | 10 | Hit@K、MRR@5、nDCG@5 |
| 单来源检索 | low lexical overlap | 10 | Hit@K、MRR@5、nDCG@5 |
| 三来源证据 | conflict | 5 | macro Recall@K、全来源覆盖率 |
| 三来源证据 | combination | 3 | macro Recall@K、全来源覆盖率 |
| 独立负样本 | unanswerable | 8 | 仅记录 route/reason，不进入质量分母 |

冻结文件是 `evals/adaptive_challenge_v3_freeze.json`。runner 在载入模型、调用路由器之前校验
两份 JSONL 的 SHA-256 与行数；任一不一致都会中止。冻结时间为
`2026-09-10T15:15:47.584Z`，实际报告生成时间为
`2026-09-10T23:26:54.862900+08:00`。

冻结后没有修改 `app/retrieval/adaptive.py`，也没有根据本轮分数改变
`semantic_score_threshold=1.25` 或 `parent_score_threshold=2.0`。

## 泄漏审计

问题文本先做 Unicode NFKC、casefold，再删除空白和标点。每个 V3 问题还与三套既有问题逐对
执行 `SequenceMatcher`，相似度 `>= 0.85` 视为近重复并中止评测。

| 对照集 | 精确问题重叠 | 近重复问题 | 来源名重叠 | 文档内容哈希重叠 | 最大问题相似度 |
| --- | ---: | ---: | ---: | ---: | ---: |
| threshold tuning | 0 | 0 | 0 | 0 | 0.3051 |
| heldout-v1 | 0 | 0 | 0 | 0 | 0.3333 |
| challenge-v2 | 0 | 0 | 0 | 0 | 0.2759 |

这只能证明上述**可计算的文本与来源标识隔离**。它不证明主题、作者经验或标注习惯在统计意义上
完全独立，也不是由外部团队完成的盲测。

## 当前引擎路由观察

adaptive 的实际选择分布：

| 范围 | BM25 | RRF | parent-child |
| --- | ---: | ---: | ---: |
| 单来源 20 题 | 11 | 9 | 0 |
| 三来源 8 题 | 2 | 6 | 0 |
| 独立负样本 8 题 | 5 | 3 | 0 |

三来源问题没有触发 parent-child，因为当前策略只在“全文、完整流程、跨章节”等 broad-context
线索达到阈值时选择该路径；“同时、综合、相互制约”等大多进入 RRF。这是冻结后观察到的行为，
不是本轮要修的路由参数。

主要未完全命中的样本：

- `ch3-sem-06/07/08/10`：低词面重叠下 adaptive 的目标来源未排到第一；其中
  `ch3-sem-10` 到第 5 位，`ch3-sem-07` 到第 3 位；
- `ch3-triad-02`：Top-5 缺少召回序列冻结来源；
- `ch3-triad-07`：Top-5 只覆盖三份冷链来源中的 1 份；
- `ch3-triad-08`：Top-5 覆盖三份冷链来源中的 2 份。

## 离线与调用边界

执行命令（未使用 `uv run`）：

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -X utf8 .\evals\benchmark_adaptive_challenge_v3.py --repetitions 5
```

runner 强制设置 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`，FastEmbed 使用
`local_files_only=True` 和仓库内 `data/models/fastembed` 缓存。评测期间还 patch 了
`socket.socket.connect` 与 `socket.create_connection`，任何联网尝试都会失败。

- provider 调用：`0`；
- application API 调用：`0`；
- 网络访问：硬禁用；
- 生成回答：未执行。

## 证据边界

本报告能证明：

1. 冻结数据上的离线来源排序结果；
2. 当前生产路由器对这些问题的策略选择和 reason code；
3. benchmark-local BM25、RRF、parent-child 实现之间的同集对照；
4. 对三套既有评测集的精确、近重复、来源名和内容哈希隔离。

本报告**不能**证明：

1. 回答生成是否正确引用、忠实组合或解决三来源之间的冲突；
2. 负样本会正确拒答。当前路由器只选检索策略，不是 abstention/evidence gate，因此 8 个负样本
   只记录 `5 BM25 / 3 RRF`，不计算“拒答准确率”；
3. 应用 API、鉴权、租户隔离、数据库过滤或线上 provider 行为；
4. 医疗有效性、临床安全性或真实医院流量上的泛化；
5. benchmark-local parent-child 排名与完整生产检索服务的所有实现细节完全等价；
6. 单机 latency 可以外推到部署环境。模型加载与索引构建时间已与查询延迟分开。

机器快照中的 adaptive 查询延迟（140 次样本）为 mean `40.144 ms`、P50 `64.248 ms`、
P95 `84.667 ms`；该数值仅用于本机本次运行记录。

## 可复核产物

- 数据：`evals/adaptive_challenge_v3_documents_zh.jsonl`
- 问题：`evals/adaptive_challenge_v3_cases_zh.jsonl`
- 冻结清单：`evals/adaptive_challenge_v3_freeze.json`
- runner：`evals/benchmark_adaptive_challenge_v3.py`
- 原始报告：`reports/adaptive-routing-challenge-zh-v3.json`
- 完整性测试：`tests/test_adaptive_challenge_v3_benchmark.py`

本轮没有修改主应用路由、API 路由、README 或前端，也没有 commit/push。
