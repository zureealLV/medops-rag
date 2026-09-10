# MedOps 医疗健康知识 Agent RAG V3.3

[English README](README.md) · [企业演进路线](docs/v4/ENTERPRISE_ROADMAP.md) · [自适应挑战集 V2](docs/v3/ADAPTIVE_CHALLENGE_V2_EVALUATION.md) · [独立中文留出集](docs/v3/ADAPTIVE_HELDOUT_EVALUATION.md) · [并发审计与方案](docs/v3/CONCURRENCY_OPTIONS.md) · [Agent 工具与检查点](docs/v4/AGENT_TOOLS_AND_CHECKPOINTS.md) · [Agent 编排基准](docs/v3/BENCHMARK_AGENT_ORCHESTRATION.md) · [中国官方语料](docs/v2/OFFICIAL_CHINESE_CORPUS.md) · [鉴权设计](docs/v2/AUTHORIZATION.md) · [部署](docs/v2/DEPLOYMENT.md) · [威胁模型](THREAT_MODEL.md)

这是一个面向**公开医疗知识与医疗器械证据**的可审计、多租户 Agent RAG 知识助手。V3.3 将在线回答改为
共享 AsyncClient 的真正异步模型路径，加入租户公平调度、分类重试、熔断器、Provider 运行面板和独立挑战集 V2；并保留管理员专用检索实验室、Agent 控制检查点、Vue 3 企业控制台、可解释自适应检索与受控 LangGraph 编排、
DeepSeek V4 Flash、Token/成本遥测和分片策略门禁；同时保留 V2.4 的 6 份中国政府哈希固定 PDF、15,000 条 Huatuo-26M
中文研究语料、NLM MedlinePlus、多模态证据、SQLite FTS5 中文索引和明亮 Web 控制台。

> 本项目是教学与作品集案例，不是医疗器械；不提供诊断、处方或治疗建议，不处理真实患者资料，也不会执行改变系统状态的工具。

> **能力边界：** Alpha.2 已能路由视觉问题、召回完全没有文字的图片并返回原始图片证据，但尚不能宣称理解图表数值、示意图关系，也未通过中文跨模态质量门禁。

## 当前已实现

- 实验性 V3 受控 Agent 层：同一 `/answer` 接口可对比 Classic Python、LangChain LCEL 与 LangGraph；
  托管路径最多选择两个代码所有的只读工具（证据回答与引用租户复核），执行安全/引用门禁并展示节点路径；
  SQLite 只保存有界控制状态，不保存问题、Prompt、证据或答案；
- DeepSeek V4 Flash 官方 OpenAI-compatible API 预配置，API Key 只从本地环境读取；在线 `/answer` 使用
  lifespan 共享 `httpx.AsyncClient`、租户间 round-robin、公平的活动/等待配额、分类有限重试、closed/open/half-open 熔断器、显式 `503` 和有界关闭；
- Vue 3.5 + TypeScript 5.9 + Vite 7 + Vue Router 4 + Pinia 3 + Element Plus 2 企业控制台：知识空间、并发受控上传、带引用问答、健康状态和租户指标；
  文档目录使用服务端元数据分页和标题/来源筛选，不再把整个知识库正文一次性塞进浏览器；
- 普通 viewer/editor 只能提交业务问题，文本/视觉检索、`top_k`、证据策略与编排引擎均由后端自动管理；
  管理员在独立实验室保留基准、灰度与故障诊断覆盖能力；
- FastAPI 应用工厂、类型化 Router、依赖注入、统一错误与 OpenAPI；
- SQLite 事务、外键、索引和重启持久化；
- 知识库与文档 CRUD，基于 SHA-256 的同租户/知识库幂等上传；
- 持久化异步摄取任务：租户级幂等键、Worker 租约、有限重试、取消与崩溃恢复；
- 独立轮询 Worker，把解析、OCR、分块和 Embedding 从 API 进程剥离；
- 可恢复的多文档 Map-Reduce 摘要任务：逐文档结果持久化、最终引用、局部失败可见，并把单次模型调用硬限制在 30 秒内；
- TXT/Markdown/PDF/DOCX/PPTX/PNG/JPEG/WebP/CSV/JSON/JSONL 解析与文本、表格、结构化行、OCR 元素归一化；
- Office 解压前条目/膨胀/压缩比门禁、危险路径与宏拒绝、PDF 页数/渲染限制，以及确定性畸形输入回归集；
- 通过 `GET /documents/{id}/elements` 查询页码、幻灯片、标题、模态来源及固定版式边界框；
- RapidOCR/ONNX Runtime 的扫描 PDF 条件式 OCR 与 Office 内嵌图片 OCR；
- 同租户 SHA-256 图片 BLOB 去重，以及页码/幻灯片/形状位置元数据；
- `GET /documents/{id}/artifacts`、租户隔离的原图读取与哈希 ETag；
- 可选配对 CLIP 图文向量，以及 `ocr`/`image`/`fusion` 三种视觉检索；
- `/answer` 自动区分文本/视觉问题，以相似度和候选差值双门禁拒答，并返回可读取的图片引用；
- 哈希向量、关键词、BM25、加权及 RRF 五种可比较检索策略；
- 显式 Rewrite、Multi-query、确定性模板 HyDE，以及受策略开关约束的自动 HyDE；
- 可选的结构感知 `parent_child` 检索：小块命中，大块恢复回答上下文；
- 确定性自适应路由会在 BM25、RRF 与父子分片间选择，并返回原因代码、置信度和候选分数供审计；
- API 保留 `source`、`document_id`、`chunk_id` 的结构化溯源；正文不再插入来源标记，仅在下方来源卡片显示编号，也不暴露内部行号或匹配分数；
- 可复现下载并导入 NLM 官方 MedlinePlus 健康主题全量 XML，每个主题保留 URL、主题 ID、语言、MeSH 与来源清单；
- 固定数据版本导入 12,000 条 Huatuo-26M 中文医学知识图谱问答和 3,000 条中文医学百科问答，并生成本地哈希来源清单；
- 从版本化目录下载 6 份中国政府医疗/医疗器械 PDF，执行 HTTPS 主机白名单、大小、PDF 文件头与 SHA-256 门禁，原文不进入 Git；
- 使用中文句号、问号、感叹号、分号和段落边界切片，并把重叠起点吸附到语义边界，减少半句和重复句；
- 在租户及知识库边界内使用 SQLite FTS5 三元字符索引召回候选，再由 BM25 排序，避免中文大语料每次全表扫描；
- 可选 OpenAI-compatible 模型调用，包含超时、有限重试和离线 fallback；
- 在 SQL 检索阶段执行租户过滤，其他租户内容不会先进入模型再过滤；
- 可选 scrypt 哈希 API Key、即时吊销、服务端租户绑定，以及 viewer/editor/admin 三级权限；
- 间接 Prompt Injection 隔离、PII 审计脱敏、医疗建议拒绝；
- 三个只读白名单工具及非法工具/参数拒绝；
- 请求 ID、`Server-Timing`，以及租户隔离的请求/队列/解析/OCR/模型/fallback/路由指标和进程内 Provider 容量/熔断状态；
- 187 个 API/安全/解析器/迁移/任务队列/UI/异步竞态测试，以及可重复的摄取、检索与并发基准；
- 先备份再执行的 V1→V2 迁移、显式 Schema 版本，以及经过测试的整库回滚路径；
- Docker Compose 已覆盖 API、摄取 Worker、摘要 Worker、健康检查与持久化数据/模型卷；旧 V3 镜像曾完成真实构建，
  但 V3.3 异步 Provider 与前端构建阶段后的新镜像仍需在 Docker Linux Engine 可用的主机上重新验证；
- 默认幂等创建“临床基础知识”和“医疗器械安全与维护”知识库，内容根据 FDA、CDC、WHO、MedlinePlus 公开资料重写，仅用于教学。

## Windows 快速启动

需要 Python 3.11+。构建 Vue 控制台还需要 Node.js 20.19+、22.12+ 或 24（本次验证使用 Node 24.15.0 / npm 11.14.1）。

```powershell
git clone https://github.com/zureealLV/medops-rag.git
cd medops-rag
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\scripts\build_frontend.ps1
.\.venv\Scripts\python.exe .\scripts\seed_sample_data.py --profile medical
.\.venv\Scripts\python.exe -m scripts.import_chinese_official
.\.venv\Scripts\python.exe -m scripts.import_huatuo
.\.venv\Scripts\python.exe -m scripts.import_medlineplus
.\.venv\Scripts\fastapi.exe dev
```

如果已有外部 DeepSeek dotenv 文件，可直接复用而不把密钥复制进本仓库：

```powershell
.\scripts\run_dev.ps1 -EnvFile <外部-.env-路径>
```

官方中文命令导入 6 份哈希固定的政府公开 PDF；Huatuo 命令默认导入 15,000 条中文研究语料，MedlinePlus 命令导入完整英文公开健康主题库。官方来源、再分发边界与验收见 [`docs/v2/OFFICIAL_CHINESE_CORPUS.md`](docs/v2/OFFICIAL_CHINESE_CORPUS.md)。其他数据源比较、许可边界、
西班牙文导入方式与测试问题见
[`docs/v2/PUBLIC_MEDICAL_CORPORA.md`](docs/v2/PUBLIC_MEDICAL_CORPORA.md)。

打开 `http://127.0.0.1:8000/` 查看 Web 控制台，或打开 `http://127.0.0.1:8000/docs` 使用 Swagger。控制台默认使用以下本地演示信任边界 Header：

```text
X-Tenant-ID: hospital-a
X-Actor-ID: local-demo
```

这里的租户 Header 是方便本地演示的信任边界。若要让服务自身鉴权，先创建管理员 Key，再切换模式：

```powershell
.\.venv\Scripts\python.exe .\scripts\manage_api_keys.py create `
  --tenant hospital-a --name local-admin --role admin
$env:AUTH_MODE = "api_key"
$headers = @{ Authorization = "Bearer <只显示一次的-key>" }
```

`api_key` 模式从数据库中的哈希凭据解析租户、身份与角色，忽略伪造的 `X-Tenant-ID` 与
`X-Actor-ID`。完整边界见 [`docs/v2/AUTHORIZATION.md`](docs/v2/AUTHORIZATION.md)。

异步摄取示例：

```powershell
$headers = @{
  "X-Tenant-ID" = "hospital-a"
  "X-Actor-ID" = "local-demo"
  "Idempotency-Key" = "demo-upload-0001"
}
"PACS 网关恢复：检查 DNS、TLS 与 DICOM 连通性。" | Set-Content .\demo-runbook.md
Invoke-RestMethod http://127.0.0.1:8000/knowledge-bases/1/ingestion-jobs `
  -Method Post -Headers $headers -Form @{ file = Get-Item .\demo-runbook.md }
.\.venv\Scripts\python.exe .\scripts\ingestion_worker.py --once
```

首次接收返回 `202`；以相同键重放相同文件返回原任务和 `200`；相同键对应不同内容或知识库则返回 `409`。

多文档摘要任务示例：

```powershell
$headers["Idempotency-Key"] = "demo-summary-0001"
$body = @{ question = "汇总故障恢复检查项"; document_ids = @(1, 2) } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/knowledge-bases/1/summary-jobs `
  -Method Post -Headers $headers -ContentType "application/json" -Body $body
.\.venv\Scripts\python.exe .\scripts\summary_worker.py --once
```

## 测试与评测

Agent 编排对比见 [`docs/v3/BENCHMARK_AGENT_ORCHESTRATION.md`](docs/v3/BENCHMARK_AGENT_ORCHESTRATION.md)。
冻结 30-case、每种编排 600 次离线调用中，三者 Hit@5、引用正确率和拒答正确率均为 `1.0000`；
LangChain LCEL 相比 Classic 平均增加 `0.901 ms`，LangGraph 增加 `1.986 ms`。另有真实
`deepseek-v4-flash` 付费测试：8 个官方语料用例、3 次重复、每种模式 24 次运行，全部质量指标为
`1.0000`，平均端到端耗时依次为 `2332.197 / 2269.603 / 2294.754 ms`。它用于证明兼容性和
Token/成本遥测，不拿八个不同问题伪装成宽泛、稳定的框架性能排名。

自适应路由冻结集包含 120 个正例和 20 个负例：Adaptive Hit@1 为 `1.0000`，平均 `37.203 ms`；
固定 BM25/RRF/父子分片 Hit@1 分别为 `0.9583 / 0.9917 / 0.9583`，平均耗时分别为
`0.338 / 74.230 / 0.371 ms`。该阈值是在此集合上校准的 in-sample 结果，不是泛化保证。

新增的独立中文留出集包含 20 篇合成运维文档、32 个可回答问题和 8 个负例。Adaptive Hit@1 为
`1.0000`，与固定 BM25、父子分片打平，并没有“神奇地赢过所有引擎”；固定 RRF 为 `0.9062`。
Adaptive 在 32 个正例中选择 BM25/RRF/父子分片 `16/10/6` 次，22 次避开了稠密查询成本。该结果只衡量
来源排序，不等于生成答案正确、生产流量或临床验证；测试未复用阈值调优问题，且强制本地离线模型、零 Provider/API 调用。

第二套独立挑战集 V2 再加入 28 篇文档和 48 个用例，并与调参集、留出集 V1 保持规范化问题/来源名
`0/0` 重复。24 个单来源题上 BM25/Parent-Child/Adaptive Hit@1 均为 `1.0000`，RRF 为 `0.9583`；
8 个双来源题四策略 Recall@3 均为 `1.0000`，说明这组多来源题区分力仍不足，不能硬吹成全面胜利。8 个不可回答题只统计路由，不冒充拒答准确率；8 个真实 SQLite 租户探针泄漏 `0`、外租户 KB 隐藏 `8/8`。

单进程、15,000 文档、2,304 次离线并发测量中没有请求错误；完整回答路径吞吐在并发 16 达到峰值
`67.655 req/s`，但 P95 已从并发 4 的 `141.483 ms` 增至 `309.240 ms`，并发 32 又恶化至
`973.943 ms`。这证明需要背压和容量门禁，不代表真实 DeepSeek 能达到同样吞吐。详见
[`docs/v3/CONCURRENCY_OPTIONS.md`](docs/v3/CONCURRENCY_OPTIONS.md)。

一条命令执行发布核心门禁（Ruff、187 项测试、Vue 类型检查与生产构建、30-case 回答/引用/拒答评测、摄取与检索基准）；
`-Full` 还会执行已缓存 MiniLM 的置信度校准与 BGE 性能剖面：

```powershell
.\scripts\reproduce_release.ps1
.\scripts\reproduce_release.ps1 -Full
```

以下 Runner 可用于单项排查：

```powershell
.\scripts\run_tests.ps1
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe .\evals\run_eval.py
.\.venv\Scripts\python.exe .\evals\benchmark_ingestion.py
.\.venv\Scripts\python.exe .\evals\benchmark_retrieval.py
.\.venv\Scripts\python.exe .\evals\benchmark_semantic_retrieval.py
.\.venv\Scripts\python.exe .\evals\benchmark_visual_retrieval.py
.\.venv\Scripts\python.exe .\evals\benchmark_parent_child.py
.\.venv\Scripts\python.exe .\evals\benchmark_query_transforms.py
.\.venv\Scripts\python.exe .\evals\evaluate_confidence_thresholds.py
.\.venv\Scripts\python.exe .\evals\benchmark_qdrant_server.py
.\.venv\Scripts\python.exe .\evals\benchmark_v2_performance.py
.\.venv\Scripts\python.exe .\evals\benchmark_agent_orchestration.py --repetitions 20
.\.venv\Scripts\python.exe .\evals\benchmark_chunk_profiles.py
.\.venv\Scripts\python.exe .\evals\benchmark_official_chunk_profiles.py
.\.venv\Scripts\python.exe .\evals\benchmark_adaptive_routing.py
.\.venv\Scripts\python.exe .\evals\benchmark_adaptive_heldout_zh.py --repetitions 3
.\.venv\Scripts\python.exe .\evals\benchmark_adaptive_challenge_v2.py --repetitions 1
.\.venv\Scripts\python.exe .\evals\benchmark_concurrency_v3.py
```

详细数据见 [`docs/v2/BENCHMARK_REPORT_ALPHA2.md`](docs/v2/BENCHMARK_REPORT_ALPHA2.md)。20 张无文字图标上，CLIP-B/32 英文 Hit@1 为 0.95，OCR-only 只有 0.05；但中文 Hit@1 仅 0.10，因此图片向量保持显式开启，不能冒充合格的中文生产方案。

父子块实测见 [`docs/v2/BENCHMARK_REPORT_BETA1.md`](docs/v2/BENCHMARK_REPORT_BETA1.md)：50 个问题中，
父块恢复让关联操作出现在返回上下文的比例从 0/50 提升到 50/50，本机平均检索耗时由
13.628 ms 增至 19.702 ms。

绝对证据门限避免 BM25/RRF 的逐查询归一化把“最不差的无关结果”伪装成 `1.0` 置信度。在冻结的
120 正例/20 负例集合上，BM25 与 RRF 均接收 120/120 个可回答问题并拒绝 20/20 个负例；更换领域
必须重新校准，不能照搬数字。Docker Qdrant Server 1.19.0 门禁在 10k 向量、并发 8 下达到
`77.959 query/s`、Recall@10 `1.0` 且跨租户命中为 0；发布配置仍选择更简单的 SQLite 精确检索。

## Docker Compose

```powershell
docker compose up --build
```

服务只绑定 `127.0.0.1:8000`，SQLite 数据保存在 `medops_data` 命名卷。
已选的本地精确向量索引随 SQLite 一起持久化，可选模型缓存位于 `medops_models`。三服务镜像已在
Docker Engine 29.1.3 / Compose 2.40.3 上构建，并通过 `scripts/compose_smoke.py` 跨进程烟测；详见
[`docs/v2/DEPLOYMENT.md`](docs/v2/DEPLOYMENT.md)。

如需启用本地视觉向量，在 `.env` 中设置 `IMAGE_EMBEDDING_ENABLED=true`。首次使用会把配对 ONNX 模型下载到 `MODEL_CACHE_DIR`，模型目录不会进入 Git。

如需把原图发给 OpenAI-compatible 视觉模型，还必须显式设置 `MODEL_VISION_ENABLED=true`；
`MODEL_MAX_VISUAL_IMAGES` 与 `MODEL_MAX_VISUAL_BYTES` 分别限制图片数和原始字节总量。默认相似度
`0.28`、候选差值 `0.002` 只按当前 Qdrant CLIP-B/32 小型基准校准，更换模型后必须重新评测。

设置 `TEXT_EMBEDDING_ENABLED=true` 可启用真实 FastEmbed 文本向量。每条向量持久化模型标识，避免
不同维度/模型的向量混算。本机 MiniLM 中英混合冒烟中，目标文档以余弦 `0.497208` 排名第一，
查询 `63.082 ms`，三文档首次建索引 `2094.785 ms`；它仍是可选配置，不凭一次冒烟升级成默认。

查询转换同样不默认开启：冻结集上，无转换与 Rewrite 的 Hit@1 均为 `0.9917`，Multi-query 降为
`0.9833`，确定性模板 HyDE 更降至 `0.7833`。可通过 `query_transform` 显式实验；自动 HyDE 还需
设置 `HYDE_AUTO_ENABLED=true`。

真实 WSL2 Redis 7.0.15 上，Celery 5.6.3 的无操作任务吞吐中位数为 `480.528 tasks/s`，SQLite
租约队列为 `347.085 tasks/s`。单机配置仍选择 SQLite：这点传输差值远小于 OCR/模型耗时，而
Celery 仍不能替代进度、局部结果和引用所需的领域表。详见[任务队列基准](docs/v2/BENCHMARK_REPORT_JOB_QUEUES.md)。

[V2 硬化性能剖面](docs/v2/BENCHMARK_REPORT_PERFORMANCE.md)实测：包含 API Key scrypt 校验的 BM25
搜索为 `56.127 ms` 均值 / `76.903 ms` p95，离线回答为 `73.866 ms` 均值 / `81.472 ms` p95；
缓存 BGE 对 Top-10 单独重排仍需 `369.715 ms` 均值，因此不进入默认在线路径。逐请求原始样本保存在
`reports/v2-performance-profile.json`，不是只留一张漂亮表格。

## 建议学习顺序

不要按文件名从头硬啃。先读 [`docs/LEARNING_GUIDE.md`](docs/LEARNING_GUIDE.md)，再按下面的调用链打断点：

```text
POST /answer
→ app/api/answers.py
→ app/services/answers.py
→ app/services/retrieval.py
→ app/repositories/documents.py
→ app/retrieval/hybrid.py
→ app/agents/model.py
```

## 明确限制

- CLIP 能召回无文字图片，但不能推理图表数值或示意图关系；
- PDF、PPTX 与独立图片返回固定版式区域；未接入渲染引擎前，不宣称 DOCX 流式排版具有稳定页码或图片坐标；
- 当前测试的两个 CLIP 配置均未通过中文跨模态门禁，默认保持关闭；
- 哈希 Embedding 是低依赖教学实现，不等同于生产向量模型；
- 本地 HyDE 是确定性假设文档模板，不是 LLM 生成结果；它显著拉低冻结基准，因此不会自动启用；
- Prompt Injection 检测只是启发式纵深防御，不能宣称完全阻断；
- `trusted_headers` 仍是演示边界；API Key 模式已有认证授权，但公网部署仍需网关 TLS、限流与密钥管理；
- SQLite 和进程内检索面向本地案例，不面向医院级流量；
- 官方与研究语料都不等于本项目完成了临床复核；当前官方冻结评测仅 8 例，仍需领域专家签核。
