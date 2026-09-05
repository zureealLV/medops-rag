# MedOps V1 代码学习指南

这个文档回答两个问题：FastAPI 请求怎样穿过分层，以及一条 RAG 问答怎样从文档变成带引用的答案。

## 第一遍：只追一条 FastAPI CRUD 请求

以 `POST /knowledge-bases` 为例：

1. `app/main.py`：应用工厂创建 FastAPI，注册 Router、中间件和异常处理；
2. `app/api/knowledge_bases.py`：解析 HTTP、Header、Body，决定 HTTP 状态；
3. `app/services/knowledge_bases.py`：处理“同租户知识库名称不能重复”等业务语义；
4. `app/repositories/knowledge_bases.py`：只负责参数化 SQL；
5. `app/db.py`：连接、外键、事务和 Schema。

观察依赖方向：API 可以依赖 Service，Service 可以依赖 Repository；Repository 不应该导入 FastAPI。

### 动手实验

1. 创建知识库；
2. 重启服务后再次读取，确认 SQLite 持久化；
3. 给相同租户创建同名知识库，观察 `409`；
4. 去掉 Repository SQL 的 `tenant_id` 条件并运行测试，观察隔离测试报红，然后恢复。

## 第二遍：追文档导入链路

```text
DocumentCreate
→ services/documents.py
→ retrieval/chunking.py
→ retrieval/embeddings.py
→ repositories/documents.py
→ documents + chunks tables
```

文档内容变化时必须重新切分和建立向量；只改标题时不应重复生成 Chunk。`documents.py` 把文档与 Chunk 写入同一个事务，避免只写入一半。

### 动手实验

- 将 `CHUNK_SIZE` 从 `600` 改为 `300`，重新导入并比较 `chunk_count`；
- 将 overlap 改为 `0` 和 `80`，观察跨边界信息；
- 阅读数据库中的 `embedding_json`，理解向量是索引数据，不是答案。

## 第三遍：追混合检索

```text
services/retrieval.py
→ repositories/documents.retrieval_rows()
→ retrieval/keyword.py + retrieval/vector.py
→ retrieval/hybrid.py
→ Evidence[]
```

当前混合分数为 `0.55 × vector + 0.45 × keyword`。每个结果保留两个分量，目的是让排序可以解释和调试，而不是只展示一个神秘总分。

哈希向量的作用是让项目在无模型、无网络时仍能完整演示。它适合学习数据流与评测，不适合冒充生产 Embedding。

## 第四遍：追引用回答与拒答

`app/services/answers.py` 依次完成：

1. 医疗建议策略检查；
2. tenant-scoped 检索；
3. 隔离带有注入信号的 Chunk；
4. 判断 Top-1 是否超过证据阈值；
5. 调用模型适配器或离线抽取式 fallback；
6. 从实际使用的 Evidence 构造 Citation。

这解释了为什么 Citation 不能让模型凭空生成：引用必须来自检索结果中的数据库标识。

## 第五遍：理解安全边界

- `security/tenant.py`：提取租户上下文；
- `repositories/documents.py`：在 SQL 中先做租户过滤；
- `security/prompt_injection.py`：把恶意文档视为不可信数据；
- `services/tools.py`：工具名白名单与 Pydantic 参数校验；
- `security/pii.py`：日志和审计元数据脱敏；
- `THREAT_MODEL.md`：哪些风险已缓解、哪些仍存在。

最重要的原则：模型提出调用工具，只是一项请求，不代表它获得了权限。

## 第六遍：用测试反向理解工程需求

按顺序阅读：

1. `tests/test_documents.py`：关系、事务和级联删除；
2. `tests/test_retrieval.py`：Chunk 与混合分数；
3. `tests/test_answers.py`：引用和拒答；
4. `tests/test_tenant_isolation.py`：检索前隔离；
5. `tests/test_prompt_injection.py`：恶意语料；
6. `tests/test_tools.py`：工具 allowlist；
7. `evals/run_eval.py`：测试与 RAG 评测的区别。

单元/API 测试验证确定性规则；评测验证一组问题上的检索、引用和拒答质量。二者不能互相替代。
