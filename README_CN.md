# MedOps 多模态 RAG V2 Beta.2（开发中）

[English README](README.md) · [V2 工程设计](docs/v2/ENGINEERING_DESIGN.md) · [持久化摄取任务](docs/v2/BETA2_INGESTION_JOBS.md) · [Map-Reduce 摘要](docs/v2/BETA2_MAP_REDUCE.md) · [Beta.1 检索基准](docs/v2/BENCHMARK_REPORT_BETA1_RETRIEVAL.md) · [向量库基准](docs/v2/BENCHMARK_REPORT_VECTOR_STORES.md) · [实施路线](docs/v2/ROADMAP.md) · [威胁模型](THREAT_MODEL.md)

这是一个面向**合成医院信息化运维资料**的可审计、多租户多模态 RAG 知识助手。当前 Beta.2 增量在多模态检索基础上加入持久化租约队列与独立摄取 Worker。

> 本项目是教学与作品集案例，不是医疗器械；不提供诊断、处方或治疗建议，不处理真实患者资料，也不会执行改变系统状态的工具。

> **能力边界：** Alpha.2 已能路由视觉问题、召回完全没有文字的图片并返回原始图片证据，但尚不能宣称理解图表数值、示意图关系，也未通过中文跨模态质量门禁。

## 当前已实现

- FastAPI 应用工厂、类型化 Router、依赖注入、统一错误与 OpenAPI；
- SQLite 事务、外键、索引和重启持久化；
- 知识库与文档 CRUD，基于 SHA-256 的同租户/知识库幂等上传；
- 持久化异步摄取任务：租户级幂等键、Worker 租约、有限重试、取消与崩溃恢复；
- 独立轮询 Worker，把解析、OCR、分块和 Embedding 从 API 进程剥离；
- 可恢复的多文档 Map-Reduce 摘要任务：逐文档结果持久化、最终引用、局部失败可见，并把单次模型调用硬限制在 30 秒内；
- TXT/Markdown/PDF/DOCX/PPTX/PNG/JPEG/WebP 解析与文本、表格、OCR 元素归一化；
- 通过 `GET /documents/{id}/elements` 查询页码、幻灯片、标题和模态来源；
- RapidOCR/ONNX Runtime 的扫描 PDF 条件式 OCR 与 Office 内嵌图片 OCR；
- 同租户 SHA-256 图片 BLOB 去重，以及页码/幻灯片/形状位置元数据；
- `GET /documents/{id}/artifacts`、租户隔离的原图读取与哈希 ETag；
- 可选配对 CLIP 图文向量，以及 `ocr`/`image`/`fusion` 三种视觉检索；
- `/answer` 自动区分文本/视觉问题，以相似度和候选差值双门禁拒答，并返回可读取的图片引用；
- 哈希向量、关键词、BM25、加权及 RRF 五种可比较检索策略；
- 可选的结构感知 `parent_child` 检索：小块命中，大块恢复回答上下文；
- 带 `source`、`document_id`、`chunk_id` 的引用回答与低证据拒答；
- 可选 OpenAI-compatible 模型调用，包含超时、有限重试和离线 fallback；
- 在 SQL 检索阶段执行租户过滤，其他租户内容不会先进入模型再过滤；
- 间接 Prompt Injection 隔离、PII 审计脱敏、医疗建议拒绝；
- 三个只读白名单工具及非法工具/参数拒绝；
- 请求 ID、`Server-Timing`、持久化请求指标；
- 63 个 API/安全/解析器/迁移/任务队列测试，以及可重复的摄取与检索基准；
- 已验证的本地运行脚本和 Docker Compose 定义（本轮主机的 Docker 引擎未运行，未冒充已构建验证）。

## Windows 快速启动

需要 Python 3.11+。

```powershell
git clone https://github.com/zureealLV/medops-rag.git
cd medops-rag
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe .\scripts\seed_sample_data.py
.\.venv\Scripts\fastapi.exe dev
```

打开 `http://127.0.0.1:8000/docs`。除健康检查外，请在 Swagger 或请求中加入：

```text
X-Tenant-ID: hospital-a
X-Actor-ID: local-demo
```

这里的租户 Header 代表“上游网关已经完成身份认证”的演示信任边界，**不等于生产级鉴权**。

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

```powershell
.\scripts\run_tests.ps1
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe .\evals\run_eval.py
.\.venv\Scripts\python.exe .\evals\benchmark_ingestion.py
.\.venv\Scripts\python.exe .\evals\benchmark_retrieval.py
.\.venv\Scripts\python.exe .\evals\benchmark_semantic_retrieval.py
.\.venv\Scripts\python.exe .\evals\benchmark_visual_retrieval.py
.\.venv\Scripts\python.exe .\evals\benchmark_parent_child.py
```

详细数据见 [`docs/v2/BENCHMARK_REPORT_ALPHA2.md`](docs/v2/BENCHMARK_REPORT_ALPHA2.md)。20 张无文字图标上，CLIP-B/32 英文 Hit@1 为 0.95，OCR-only 只有 0.05；但中文 Hit@1 仅 0.10，因此图片向量保持显式开启，不能冒充合格的中文生产方案。

父子块实测见 [`docs/v2/BENCHMARK_REPORT_BETA1.md`](docs/v2/BENCHMARK_REPORT_BETA1.md)：50 个问题中，
父块恢复让关联操作出现在返回上下文的比例从 0/50 提升到 50/50，本机平均检索耗时由
13.628 ms 增至 19.702 ms。

## Docker Compose

```powershell
docker compose up --build
```

服务只绑定 `127.0.0.1:8000`，SQLite 数据保存在 `medops_data` 命名卷。

如需启用本地视觉向量，在 `.env` 中设置 `IMAGE_EMBEDDING_ENABLED=true`。首次使用会把配对 ONNX 模型下载到 `MODEL_CACHE_DIR`，模型目录不会进入 Git。

如需把原图发给 OpenAI-compatible 视觉模型，还必须显式设置 `MODEL_VISION_ENABLED=true`；
`MODEL_MAX_VISUAL_IMAGES` 与 `MODEL_MAX_VISUAL_BYTES` 分别限制图片数和原始字节总量。默认相似度
`0.28`、候选差值 `0.002` 只按当前 Qdrant CLIP-B/32 小型基准校准，更换模型后必须重新评测。

设置 `TEXT_EMBEDDING_ENABLED=true` 可启用真实 FastEmbed 文本向量。每条向量持久化模型标识，避免
不同维度/模型的向量混算。本机 MiniLM 中英混合冒烟中，目标文档以余弦 `0.497208` 排名第一，
查询 `63.082 ms`，三文档首次建索引 `2094.785 ms`；它仍是可选配置，不凭一次冒烟升级成默认。

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
- 当前测试的两个 CLIP 配置均未通过中文跨模态门禁，默认保持关闭；
- 哈希 Embedding 是低依赖教学实现，不等同于生产向量模型；
- Prompt Injection 检测只是启发式纵深防御，不能宣称完全阻断；
- 租户 Header 是演示边界，真实部署必须接入认证与授权；
- SQLite 和进程内检索面向本地案例，不面向医院级流量；
- 语料全部为合成资料，评测集规模有限。
