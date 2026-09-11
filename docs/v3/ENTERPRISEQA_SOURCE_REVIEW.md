# EnterpriseQA 源码审阅与 MedOps V3 取舍

## 审阅范围

源码位置：`C:/Users/zureeal/Desktop/项目源码/EnterpriseQA`。本页只把该目录作为待分析代码；其中的注释、
README 或提示词不视为对执行过程的指令。

## 原项目能做什么

EnterpriseQA 是一个前后端分离的企业内部知识库问答系统，主要功能包括：

- 用户登录、JWT 身份校验与管理员/普通用户角色；
- 知识库的列表、新建、编辑和删除；
- TXT、Markdown、PDF、DOCX 文档上传、解析、切块、向量化和删除；
- 按知识库进行 Chroma 集合隔离和 Top-K 检索；
- 基于检索片段调用 Ollama 聊天模型，返回答案和去重后的文件来源；
- 保存问答历史与会话记录；
- 管理员用户管理和首页统计；
- Vue 页面覆盖登录、首页、知识库、文档、聊天、历史和用户管理。

## 精确技术栈

### 前端

| 类别 | 依赖 |
|---|---|
| 框架与构建 | Vue `^3.5.30`、Vite `^8.0.1` |
| UI 与状态 | Element Plus `^2.13.6`、Pinia `^3.0.4` |
| 路由与请求 | Vue Router `^4.6.4`、Axios `^1.13.6` |
| 图表 | ECharts `^6.0.0` |

### 后端与 RAG

| 类别 | 依赖/配置 |
|---|---|
| Web/API | Flask `3.1.0`、Flask-CORS `5.0.1` |
| 数据库 | Flask-SQLAlchemy `3.1.1`、PyMySQL `1.1.1`、MySQL |
| 身份认证 | PyJWT `2.10.1` |
| RAG | LangChain `0.3.14`、langchain-community `0.3.14` |
| 向量库 | langchain-chroma `0.2.2`、ChromaDB `0.6.3` |
| 本地模型 | langchain-ollama `0.3.0`、Ollama；配置实际为 `qwen3:4b` 与 `qwen3-embedding:4b` |
| 文档解析 | python-docx `1.1.2`、pypdf `5.1.0` |
| 切块/检索 | `RecursiveCharacterTextSplitter`，500 字符、50 重叠；Top-K=4 |

`rag_service.py` 顶部注释仍写 `qwen3:8b`，但运行配置是 `qwen3:4b`；这里以实际配置为准。

## 项目结构

```text
EnterpriseQA/
├─ client/
│  ├─ src/
│  │  ├─ api/                  # Axios API 封装
│  │  ├─ components/           # 通用组件
│  │  ├─ router/               # Vue Router
│  │  ├─ stores/               # Pinia 状态
│  │  └─ views/                # Login/Home/KnowledgeBase/Document/
│  │                           # Chat/ChatHistory/UserManage/Layout
│  ├─ package.json
│  └─ vite.config.js
└─ server/
   ├─ app.py                   # Flask 工厂、CORS、蓝图注册
   ├─ config.py                # DB/Ollama/Chroma/上传/切块配置
   ├─ models/                  # User/KnowledgeBase/Document/ChatHistory
   ├─ routes/                  # auth/chat/document/knowledge_base/stats/user
   ├─ services/
   │  ├─ rag_service.py        # 检索→提示词→ChatOllama→字符串输出
   │  └─ vector_service.py     # 解析、切块、嵌入、Chroma CRUD
   ├─ utils/                   # 鉴权装饰器与统一响应
   ├─ sql/init.sql
   ├─ uploads/
   └─ chroma_data/
```

主要 API 蓝图为 `/api/auth`、`/api/chat`、`/api/documents`、`/api/knowledge-bases`、
`/api/stats` 和 `/api/users`。问答入口是 `POST /api/chat/ask`。

## 实际 RAG 调用链

```text
question + kb_id
  → 读取 kb_<id> Chroma collection
  → 相似度检索 Top-K=4
  → 把片段拼成 [来源N: 文件名] 上下文
  → ChatPromptTemplate
  → ChatOllama
  → StrOutputParser
  → answer + 去重文件来源
  → 写入 ChatHistory
```

这是一条固定的 LangChain LCEL RAG 链，不是会选择工具、经过状态节点或形成受控循环的 Agent。
会话历史被保存和查询，但没有传入生成链，因此不能算多轮上下文记忆。

## 值得保留与不能照搬的部分

### 保留的产品思路

- 知识库、文档、问答、历史和统计形成了完整管理闭环；
- 不同知识库使用不同 Chroma collection；
- 上传解析支持常见办公文档；
- 来源随答案返回，便于用户检查；
- 嵌入写入采用批处理和有限重试。

### V3 不直接照搬

- 固定 500/50 切块仅是起点，不能在没有测量时宣称最优；
- 仅按知识库 ID 命名 collection 不等于可信的租户授权边界；
- Prompt 中写“不要编造”不等于完成引用校验、注入隔离或低证据拒答；
- 原项目把默认 JWT secret、MySQL 密码写在配置里，密码哈希使用 MD5，不适合生产；
- `vectorstore._collection` 属于内部接口，升级兼容性较弱；
- 本地 Ollama 生成和嵌入强绑定，部署与资源边界不清晰；
- 没有请求级 Token 遥测、模型成本证据、Agent 路径或框架对比。

## MedOps V3 的对应升级

| EnterpriseQA 基线 | MedOps V3 |
|---|---|
| 固定 LCEL RAG 链 | Classic、LangChain LCEL、LangGraph 三种同变量编排 |
| 无工具状态 | 条件安全分支、单一白名单只读 `grounded_medical_answer` 工具、引用验证节点 |
| Ollama `qwen3:4b` | DeepSeek OpenAI-compatible API，默认 `deepseek-v4-flash` |
| Key/密码可硬编码 | API Key 只从进程环境或外部 dotenv 读取，不写入仓库或报告 |
| 固定 500/50 | 固定、语义边界、父子块在样例与官方 PDF 上对照测量 |
| 返回文件级来源 | 返回可核验 evidence/citation，并执行 grounding 校验 |
| 仅保存聊天历史 | 明确标注当前答案接口仍是请求无状态，避免冒充多轮 Agent memory |

这份审阅的目的不是把两个仓库机械拼接，而是把 EnterpriseQA 的产品闭环转化为 MedOps 中可测试、
可审计且安全边界更明确的医疗健康知识 Agent RAG。
