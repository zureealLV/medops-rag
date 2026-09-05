# MedOps RAG V1

[English README](README.md) · [代码学习指南](docs/LEARNING_GUIDE.md) · [威胁模型](THREAT_MODEL.md)

这是一个面向**合成医院信息化运维资料**的可审计、多租户 RAG 知识助手。它把 FastAPI、SQLite、文档导入、混合检索、引用回答、安全控制与评测串成一条完整链路，默认不需要模型 API Key。

> 本项目是教学与作品集案例，不是医疗器械；不提供诊断、处方或治疗建议，不处理真实患者资料，也不会执行改变系统状态的工具。

## V1 已实现

- FastAPI 应用工厂、类型化 Router、依赖注入、统一错误与 OpenAPI；
- SQLite 事务、外键、索引和重启持久化；
- 知识库与文档 CRUD，文档写入时自动切分和建立索引；
- 本地哈希向量与关键词/向量混合排序；
- 带 `source`、`document_id`、`chunk_id` 的引用回答与低证据拒答；
- 可选 OpenAI-compatible 模型调用，包含超时、有限重试和离线 fallback；
- 在 SQL 检索阶段执行租户过滤，其他租户内容不会先进入模型再过滤；
- 间接 Prompt Injection 隔离、PII 审计脱敏、医疗建议拒绝；
- 三个只读白名单工具及非法工具/参数拒绝；
- 请求 ID、`Server-Timing`、持久化请求指标；
- 26 个 API/安全测试与 30 条离线评测；
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
```

V1 本地验收基线：**26 tests passed**；合成语料的 30 条评测中，Retrieval Hit@5、引用正确率和正确拒答率均为 `1.00`。这是小规模、确定性的项目回归集，不能外推为生产准确率。

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

- 哈希 Embedding 是低依赖教学实现，不等同于生产向量模型；
- Prompt Injection 检测只是启发式纵深防御，不能宣称完全阻断；
- 租户 Header 是演示边界，真实部署必须接入认证与授权；
- SQLite 和进程内检索面向本地案例，不面向医院级流量；
- 语料全部为合成资料，评测集规模有限。
