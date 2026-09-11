# RAG-Pro 对比、MCP 迁移与界面改造记录

[English version](RAG_PRO_COMPARISON_AND_MIGRATION.md)

## 审计范围

- 源项目：`D:/Codex Program files/RAG-Pro`（本地源码快照，不是 Git 工作区）。
- 目标项目：MedOps RAG V3.4。
- 结论基于源码、依赖、路由、数据目录和浏览器实机页面，而不是只复述 README。

## RAG-Pro 相对 MedOps 的可取优势

| 优势 | RAG-Pro 实现证据 | MedOps 的取舍与迁移判断 |
|---|---|---|
| 更完整的普通用户工作流 | 会话历史、快捷指令、模型设置、API/MCP 测试页；对应 `models/conversation.py`、`shortcut.py` 和多个 Vue View | 值得迁移交互思路；不迁移其无租户边界的数据模型 |
| 真正的流式聊天体验 | `api/v1/chat.py` 与前端 Chat 页面使用 SSE 持续输出 | 值得作为下一阶段能力；当前 MedOps `/answer` 仍是一次性响应 |
| 输出形态丰富 | Chart/Report/Webpage/Data Agent、ECharts 渲染、网页预览和发布 | 可借鉴为“证据派生展示”；不能让生成页面绕开引用与只读工具门禁 |
| 多模型接入面广 | LiteLLM 统一连接 OpenAI、Anthropic、DeepSeek、Ollama、智谱、通义、vLLM | 值得抽象 Provider registry；MedOps 现阶段优先保留已验证的并发、deadline、重试和熔断控制 |
| 本地语义检索开箱即用 | 仓库快照包含 BGE-M3、BGE reranker v2 m3、Milvus Lite，以及可选分块方法 | 检索质量方向值得做基准后迁移；模型二进制与运行数据不应直接提交到 MedOps Git |
| 更亲和的产品视觉 | 暗色圆角顶栏、柔和径向渐变、彩色数据卡、独立功能入口 | 已吸收视觉语言，但保留 MedOps 的身份、角色、健康状态和医疗边界提示 |

RAG-Pro 的优势主要是**产品广度与演示完成度**，不是医疗生产安全。MedOps 仍明显领先于租户隔离、
服务端 API Key 身份解析、角色控制、审计脱敏、Prompt Injection 隔离、医疗建议拒绝、官方语料、
可解释检索、异步 Provider 韧性和自动化测试。

## 为什么没有直接复制 RAG-Pro MCP

RAG-Pro 的 MCP 是手写 JSON-RPC/SSE 适配层，存在这些源码级问题：

1. 固定声明旧协议版本，未使用 MCP 官方 SDK 的初始化、能力协商和输入 Schema。
2. 文档提到 `rag_search`，实际工具定义只暴露知识库列表与聊天工具。
3. 工具 Schema 接受 `top_k`，但调用链没有把它传入检索函数，参数表面存在、运行时无效。
4. 没有复用租户鉴权、角色限制、引用范围复核和审计链。
5. 当前 LLM 配置字段名带有 `encrypted`，但源码仍以 TODO 形式明文保存/读取 Key。

因此迁移采用“能力重写”而不是“文件复制”。

## MedOps MCP 实现

- Endpoint：`POST /mcp/`，Streamable HTTP、JSON 响应、stateless session。
- SDK：`mcp>=2.2,<3.0`。
- 工具：
  - `list_knowledge_bases`：列出当前身份可见的知识库；
  - `rag_search`：租户内检索，`top_k` 经过 Pydantic 约束并实际生效；
  - `rag_answer`：调用 MedOps LangGraph 受控回答链，返回引用、拒答原因和 Agent 步骤。
- 身份：开发环境复用 `X-Tenant-ID` / `X-Actor-ID`；生产 `api_key` 模式仅信任数据库中哈希 Key
  所解析出的租户、角色和身份，忽略客户端伪造身份 Header。
- 安全：保留 viewer/editor 技术参数降权、医疗建议拒绝、引用租户复核、PII 安全审计和只读边界。
- 传输：Host 与浏览器 Origin 默认仅允许 loopback，并限制单条消息为 1 MiB；生产域名通过
  `MCP_ALLOWED_HOSTS` / `MCP_ALLOWED_ORIGINS` 显式加入 allowlist。

### 客户端配置

本地演示信任 Header：

```json
{
  "url": "http://127.0.0.1:8000/mcp/",
  "headers": {
    "X-Tenant-ID": "hospital-a",
    "X-Actor-ID": "local-mcp"
  }
}
```

生产 API Key 模式：

```json
{
  "url": "https://medops.example.com/mcp/",
  "headers": {
    "Authorization": "Bearer <one-time-issued-api-key>"
  }
}
```

## 前端改造

MedOps 没有照抄 RAG-Pro 组件，而是迁移其信息架构和视觉节奏：

- 左侧企业控制台改为暗色圆角顶栏，五个一级入口直接可见；
- 背景、Hero、统计卡加入珊瑚色、青色、薄荷色柔和渐变；
- 保留 MedOps 的租户、Actor、角色、健康状态和医疗安全提示；
- 新增 MCP 服务页，可从浏览器真实执行 initialize 与 `tools/list`，展示服务版本和发现的工具 Schema；
- 响应式布局在窄屏变为纵向导航，不牺牲已有知识库、文档分页、证据问答和管理控制台。

## 验收门禁

```powershell
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m pytest -q
Push-Location .\frontend
npm run typecheck
npm run build
Pop-Location
git diff --check
```

MCP 还需验证初始化、工具 Schema、跨租户不可见、API Key 服务端绑定、医疗建议拒绝和审计落库；
前端需用真实运行中的 API 验证 Dashboard 与 MCP 页面，而不能把 TypeScript 编译通过冒充视觉验收。

## 明确未迁移

- RAG-Pro 的模型二进制、`venv`、SQLite 运行库、上传内容和已发布 HTML；
- 无权限边界的 LLM 配置保存；
- 手写旧 MCP 协议与失效的 `top_k` 参数；
- 不带引用门禁的任意 Chart/Report/Webpage Agent；
- 仅在 README 中出现、源码或自动化测试无法证实的能力。
