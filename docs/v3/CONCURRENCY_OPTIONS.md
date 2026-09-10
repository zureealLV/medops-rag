# MedOps RAG V3 并发审计、实测与企业部署方案

> 审计基线：`786c51b15f60` 后的 V3.1 工作树；测试日期：2026-09-10；Windows 10 / Python 3.11.5 / 20 logical CPUs。
> 本文只对本机、单进程、离线可控负载负责，不把微基准包装成生产容量承诺。

## 1. 当前并发路径审计

当前 API 使用 FastAPI，但主要路由是同步 `def`。Starlette/AnyIO 会把这些处理函数放入线程池，
因此请求可以并行执行；这不等于路径已经具备无限并发能力：

- `app/db.py` 为每次仓储操作创建并关闭 SQLite 连接，连接超时为 10 秒；
- 每个连接执行 `foreign_keys=ON` 和 `journal_mode=WAL`；WAL 允许读写更好地并存，但同一时刻仍只有一个写者；
- `/health` 会读 SQLite，且观测中间件会在每个请求结束时写一行 `request_metrics`；
- 文档分页接口执行知识库校验、`COUNT(*)` 和一页元数据查询，不再读取全部文档正文；
- `/answer` 会进行策略检查、检索、LangGraph 编排、同步 `httpx.post` 模型调用、审计写入和指标写入；
- 模型调用当前占住一个 AnyIO 工作线程，尚无进程内模型并发上限、租户限流、排队上限或熔断器；
- Dockerfile 当前启动一个 Uvicorn worker；仓库已有 SQLite lease worker，以及 Celery/Redis 可选依赖和队列基准，
  但在线 `/answer` 尚未自动转为异步队列任务。

这意味着当前实现适合开发、演示和受控低并发部署；它还不是经过容量规划的横向扩展架构。

本轮已先落地一个不改变业务语义的修正：新增无数据库访问、无持久化指标写入的 `/live` 进程探针，
新增检查 SQLite 的 `/ready` 依赖探针，并让 Docker Compose 使用 `/live`。原 `/health` 保持兼容且仍等价于
readiness。模型客户端复用、背压和数据库迁移仍属于后续阶段，不能因为写进方案文档就冒充已实现。

## 2. 可复现的离线并发基准

运行命令：

```powershell
cd "D:/Codex Program files/medops-rag"
uv run python evals/benchmark_concurrency_v3.py `
  --concurrency 1,4,16,32 `
  --requests-per-level 64 `
  --repetitions 3 `
  --documents 15000 `
  --model-delay-ms 75 `
  --output reports/concurrency-benchmark-v3.json
```

安全边界：

- 启动时清除当前进程继承的模型 Key 环境变量；
- 测试设置只使用 `offline-benchmark-only` 哨兵值；
- 模型 URL 固定为保留的 `.invalid` 域名；
- `httpx.post` 被线程安全的确定性替身接管，任何其他 URL 都会被安全门拒绝；
- 报告记录 `network_model_calls=0`，不会产生真实 API 费用。

测试采用 closed-loop 负载，并通过 `httpx.ASGITransport` 在进程内调用真实 ASGI 应用。每个并发级别每轮
64 次请求、重复 3 轮。临时 SQLite 中有 15,000 条文档和 15,000 个 chunk。三个路径被分开测试：

1. `health_db_read`：健康检查的 SQLite 读，以及请求结束后的指标写；
2. `document_page_read`：15,000 文档下返回 50 条元数据的真实分页路径；
3. `answer_controlled_model`：真实检索、LangGraph、审计与指标路径，模型阶段固定延迟 75ms。

## 3. 本机实测结果

以下吞吐量是三轮中位数，P95 是三轮 P95 的中位数；每个单元累计 192 个请求，全部返回 2xx。

### 3.1 健康检查 + SQLite 指标写

| 并发 | 中位吞吐 req/s | 客户端 P95 | 累计错误 |
|---:|---:|---:|---:|
| 1 | 146.268 | 7.702 ms | 0 |
| 4 | 167.882 | 50.904 ms | 0 |
| 16 | **220.430** | 92.961 ms | 0 |
| 32 | 187.955 | 202.152 ms | 0 |

### 3.2 15,000 文档分页读 + SQLite 指标写

| 并发 | 中位吞吐 req/s | 客户端 P95 | 累计错误 |
|---:|---:|---:|---:|
| 1 | 49.903 | 27.789 ms | 0 |
| 4 | 88.145 | 82.155 ms | 0 |
| 16 | 104.800 | 226.586 ms | 0 |
| 32 | **112.155** | 319.702 ms | 0 |

### 3.3 完整回答路径 + 75ms 离线模型替身

| 并发 | 中位吞吐 req/s | 客户端 P95 | 累计错误 |
|---:|---:|---:|---:|
| 1 | 9.561 | 113.949 ms | 0 |
| 4 | 35.584 | 141.483 ms | 0 |
| 16 | **67.655** | 309.240 ms | 0 |
| 32 | 58.284 | 973.943 ms | 0 |

共测量 2,304 次请求，另有 3 次预热；数据库保存 2,307 行请求指标。模型替身调用 769 次，恰好等于
768 次回答测量加 1 次回答预热，没有静默绕过模型阶段。

## 4. 可以从数据得出什么

### 已有证据支持的结论

- 单进程在本机从并发 1 提高到 16 时，三个路径的吞吐都上升；
- 并发 32 时健康与回答路径吞吐下降；分页吞吐仍小幅上升，但三条路径的尾延迟都明显恶化；
- 回答路径在并发 4 时仍保持接近单请求的 P95（141.483ms 对 113.949ms），是当前离线替身条件下
  延迟与吞吐更稳健的点；
- 并发 16 的回答吞吐最高，但 P95 已升至 309.240ms；并发 32 的 P95 达 973.943ms，属于排队而不是
  “更多并发必然更快”；
- 分页避免了 15,000 条正文全量传输，但数据库查询、线程池调度和每请求指标写仍会在高并发形成尾延迟。

### 数据不能证明的事情

- 不能据此声称线上能稳定承载 67.655 个真实 DeepSeek 回答/秒；真实 Provider 有网络波动、配额和排队；
- 不能据此决定 Uvicorn worker 数；此次只有一个进程，且 ASGITransport 没有经过 TCP、TLS 和反向代理；
- 不能从“0 错误”推断无限稳定；每格只有 192 个样本，没有 soak test、故障注入或突发 open-loop 流量；
- 不能把 16 当成通用最佳并发值。机器 CPU、数据库、语料规模、模型配额和 SLO 变化后拐点会变化。

原始、逐轮数据见 `reports/concurrency-benchmark-v3.json`。

## 5. 多个企业级解决方案对比

| 方案 | 适用阶段 | 主要收益 | 代价与风险 | 必须验证 |
|---|---|---|---|---|
| A. 单 worker + SQLite WAL + 应用背压 | 内测、单部门、低写入 | 最简单；本地部署；故障面小 | 单写者；同步模型占线程；单进程故障 | 真实 Provider 下 4/8/16 并发、P95/P99、429 行为 |
| B. 2–4 Uvicorn workers + SQLite WAL | 短期过渡、读多写少 | 多进程隔离；利用多核；改造少 | WAL 仍单写者；模型/Embedding 缓存按进程复制；锁等待可能更差 | 1/2/4 worker 的 socket 基准、写锁率、内存、启动迁移竞争 |
| C. 多 worker + PostgreSQL + pgvector | 中型企业、事务与向量规模适中 | 多写者、连接池、ACID；元数据与向量同库事务更简单 | 需要重写 SQLite/FTS5 SQL；向量索引调优；数据库运维 | 迁移一致性、pool 大小、HNSW/IVFFlat 召回与延迟 |
| D. PostgreSQL + Qdrant | 大型知识库、向量检索独立扩展 | PostgreSQL 管业务事务，Qdrant 专注向量、过滤和扩容 | 双写一致性、备份恢复和监控更复杂 | Outbox/重放、租户 payload 过滤、删除一致性、召回回归 |
| E. Redis/Celery 有界异步队列 | OCR、导入、批量摘要、长耗时任务 | 请求快速受理；重试、调度、横向 worker；隔离在线请求 | 不是在线问答的自动加速器；需幂等、DLQ、结果存储 | broker 故障、重复投递、超时、重试风暴、队列等待 SLO |
| F. API Gateway + 进程内限流/熔断 | 所有生产阶段 | 公平配额、快速拒绝、保护 Provider 和数据库 | 参数过小损失吞吐，过大只会把故障变排队 | 每租户配额、Retry-After、突发流量、公平性与降级路径 |

### 方案 A：先修正单机并发模型

建议优先做，不需要等数据库迁移：

1. 把模型适配器改为复用的 `httpx.AsyncClient`，避免每次调用建立客户端，并使网络等待不占 AnyIO 同步线程；
2. 为模型 Provider 设置独立 `Semaphore`，初始值以真实配额和压测为准，不把本机 `16` 直接写死到生产；
3. 给等待信号量设置短 deadline，队列已满时返回 `429` 或 `503` 及 `Retry-After`，不要让请求无限排队；
4. 设置总体请求 deadline、Provider timeout、有限重试和带 jitter 的退避；重试必须计入并发与 Token 预算；
5. 健康探针拆为轻量 liveness 和数据库 readiness，避免编排系统高频探针持续写 `request_metrics`；
6. 指标写入可改为有界异步批量通道；通道满时允许丢弃低价值指标，但不能阻塞业务请求。

### 方案 B：单机多 Uvicorn worker

可做过渡验证，但不是企业最终数据库架构。示例启动形式：

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

注意：

- 不要同时使用 `--reload`；
- worker 数不能简单等于 CPU 核数。模型客户端主要是 I/O，Embedding/OCR 又可能是 CPU/内存密集；
- 每个进程都会加载自己的模型和缓存，2–4 worker 可能先耗尽内存；
- SQLite WAL 仍然串行提交写事务，多进程只解决 Python 进程隔离，不解决单写者上限；
- 当前 lifespan 每个 worker 都调用初始化，正式启用前应把 schema migration 拆为单独部署步骤。

### 方案 C：PostgreSQL + pgvector

适合希望减少组件数量的中型企业部署。需要：

- SQLAlchemy/asyncpg 或明确的 PostgreSQL repository，配有上限的连接池；
- 用 PostgreSQL FTS 或独立搜索引擎替代 SQLite FTS5；
- 使用 RLS 或强制 tenant predicate，不能只依赖应用调用约定；
- pgvector 建索引后重新跑冻结检索集，比较 Recall@K、MRR、P95、索引时间和内存；
- 迁移不是改 `DATABASE_URL`：当前配置明确只接受 `sqlite:///`，仓储 SQL 也使用 SQLite 语法。

### 方案 D：PostgreSQL + Qdrant

适合向量规模、过滤或独立扩缩容需求超过单库方案时。推荐业务数据与权限在 PostgreSQL，向量及检索
payload 在 Qdrant。通过 transactional outbox 发布索引事件，消费者幂等写入 Qdrant；回答只读取已确认的
索引版本。必须验证 tenant filter 在服务端生效，并设计删除、重建索引、备份与灾难恢复流程。

### 方案 E：Redis/Celery 与队列

当前摄取和摘要已有持久化 job/lease 语义，适合把 OCR、Embedding、批量导入和长摘要迁移到 Celery：

- API 只校验、落库并返回 `202 + job_id`；
- Redis 作为 broker，不作为唯一业务事实源；任务状态和幂等键保留在 PostgreSQL；
- 设置队列长度、任务时限、最大重试、指数退避、死信队列和取消语义；
- OCR/Embedding/摘要应分队列，避免一个超大 PDF 阻塞所有短任务；
- 在线 `/answer` 只有在产品接受异步轮询或 SSE/WebSocket 时才适合入队，否则应保持同步但受信号量保护。

### 方案 F：限流、背压与公平性

企业入口需要两层保护：

1. API Gateway/Ingress：按租户、API Key、IP 的 token bucket，限制 RPS 与 burst；
2. 应用层：按资源分别限制数据库查询、Dense/Rerank、模型调用，不用一个全局锁阻塞所有路径。

建议返回可观测的拒绝：`429 Too Many Requests`、`Retry-After`、队列深度、tenant quota ID。还应加入 Provider
熔断：连续失败时短路到证据抽取式回答或明确拒答；half-open 探测恢复，而不是让每个请求同时重试。

## 6. 推荐演进顺序

### 第一阶段：单机安全上线门槛

- 异步、复用的模型客户端；
- 每 Provider/租户的并发信号量和有界等待；
- liveness/readiness 分离；
- 指标批量写；
- 用真实 DeepSeek 测试 4/8/16 并发，但使用独立测试配额和明确成本上限；
- 加 10–30 分钟 soak、突发流量、Provider 429/超时/断网故障注入。

### 第二阶段：多 worker 过渡实验

- 用同一 socket 压测工具对 1/2/4 workers 做完全相同的请求矩阵；
- 记录进程 RSS、CPU、SQLite `database is locked`、P50/P95/P99 和拒绝率；
- 只有在 SLO 改善且没有锁/内存回归时才保留多 worker。

### 第三阶段：企业数据平面

- PostgreSQL 承担用户、租户、知识库、任务、审计和 Outbox；
- 小中规模先评估 pgvector，确有独立扩展证据后再引入 Qdrant；
- Redis/Celery 承担有界后台任务，不让 Broker 成为事实源；
- 多实例部署前完成租户隔离、幂等、迁移回滚、备份恢复与容量测试。

## 7. 验收门禁建议

上线前应针对目标硬件和真实 Provider 明确 SLO，而不是沿用本文数字。最低门禁建议包括：

- 固定并发和 open-loop 突发两种模型；
- P50/P95/P99、吞吐、错误率、拒绝率和排队时间；
- Provider 429、超时、慢响应、断网和返回畸形数据；
- SQLite/PostgreSQL 锁等待、连接池耗尽和数据库重启；
- 单 worker 退出、队列 worker 退出、Redis 重启与重复投递；
- 所有场景继续满足租户隔离、引用正确、拒答、安全策略和 Token 预算。

达到这些门禁后，才能称为“在某一明确负载与 SLO 下通过”，不能笼统声称“支持高并发”。
