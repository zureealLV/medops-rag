# MedOps 多模态 RAG V2 Alpha.1

[English README](README.md) · [V2 工程设计](docs/v2/ENGINEERING_DESIGN.md) · [Alpha.1 基准报告](docs/v2/BENCHMARK_REPORT_ALPHA1.md) · [实施路线](docs/v2/ROADMAP.md) · [威胁模型](THREAT_MODEL.md)

这是一个面向**合成医院信息化运维资料**的可审计、多租户多模态 RAG 知识助手。Alpha.1 在 V1 链路上加入真实 PDF/DOCX/PPTX/图片摄取、OCR 证据、来源追踪、幂等上传和可复现检索基准。

> 本项目是教学与作品集案例，不是医疗器械；不提供诊断、处方或治疗建议，不处理真实患者资料，也不会执行改变系统状态的工具。

> **能力边界：** Alpha.1 完成了多格式与 OCR 多模态摄取；图表/示意图的视觉语义检索、视觉模型推理和区域引用将在 Alpha.2 实现。OCR 不会被冒充成完整视觉 RAG。

## Alpha.1 已实现

- FastAPI 应用工厂、类型化 Router、依赖注入、统一错误与 OpenAPI；
- SQLite 事务、外键、索引和重启持久化；
- 知识库与文档 CRUD，基于 SHA-256 的同租户/知识库幂等上传；
- TXT/Markdown/PDF/DOCX/PPTX/PNG/JPEG/WebP 解析与文本、表格、OCR 元素归一化；
- 通过 `GET /documents/{id}/elements` 查询页码、幻灯片、标题和模态来源；
- RapidOCR/ONNX Runtime 的扫描 PDF 条件式 OCR 与 Office 内嵌图片 OCR；
- 哈希向量、关键词、BM25、加权及 RRF 五种可比较检索策略；
- 带 `source`、`document_id`、`chunk_id` 的引用回答与低证据拒答；
- 可选 OpenAI-compatible 模型调用，包含超时、有限重试和离线 fallback；
- 在 SQL 检索阶段执行租户过滤，其他租户内容不会先进入模型再过滤；
- 间接 Prompt Injection 隔离、PII 审计脱敏、医疗建议拒绝；
- 三个只读白名单工具及非法工具/参数拒绝；
- 请求 ID、`Server-Timing`、持久化请求指标；
- 34 个 API/安全/解析器/迁移测试，以及可重复的摄取与检索基准；
- 本地运行脚本和 Docker Compose。

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

## 测试与评测

```powershell
.\scripts\run_tests.ps1
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe .\evals\run_eval.py
.\.venv\Scripts\python.exe .\evals\benchmark_ingestion.py
.\.venv\Scripts\python.exe .\evals\benchmark_retrieval.py
.\.venv\Scripts\python.exe .\evals\benchmark_semantic_retrieval.py
```

详细数据见 [`docs/v2/BENCHMARK_REPORT_ALPHA1.md`](docs/v2/BENCHMARK_REPORT_ALPHA1.md)。当前 6 文档小语料明显偏向词法匹配，因此 BM25 暂时优于更昂贵的本地稠密检索；在更困难的 V2 留出集完成前，不把 MiniLM、BGE 重排或 RRF 硬设为默认。

## Docker Compose

```powershell
docker compose up --build
```

服务只绑定 `127.0.0.1:8000`，SQLite 数据保存在 `medops_data` 命名卷。

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

- OCR 能从图片提取文字，但尚不能理解纯视觉图表和示意图；
- 哈希 Embedding 是低依赖教学实现，不等同于生产向量模型；
- Prompt Injection 检测只是启发式纵深防御，不能宣称完全阻断；
- 租户 Header 是演示边界，真实部署必须接入认证与授权；
- SQLite 和进程内检索面向本地案例，不面向医院级流量；
- 语料全部为合成资料，评测集规模有限。
