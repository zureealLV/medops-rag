# MedOps RAG 项目规格

## 1. 项目目标

构建一个面向医院信息科或 IT 运维人员的知识助手。系统从公开或合成的医院信息化运维文档中检索证据，回答问题时给出来源；没有可靠证据时拒答；所有检索、工具调用和安全事件均可审计。

## 2. 目标用户与场景

**目标用户：** 医院信息科、软件实施与运维人员。

**示例问题：**

- “LIS 接口连续超时，应先检查哪些非患者数据项？”
- “PACS 服务健康检查失败时有哪些排查步骤？”
- “某份合成运维规范的版本和来源是什么？”

**禁止场景：**

- 根据症状进行疾病诊断；
- 推荐药物、剂量或治疗方案；
- 导入或处理真实患者病历；
- 让模型直接执行 Shell、删除数据库或发送外部消息。

## 3. 最终功能范围

1. FastAPI REST API 与 Pydantic 数据边界；
2. SQLite 演示持久化；
3. 知识库与文档 CRUD；
4. 文档抽取、切分、Embedding 与索引；
5. 关键词与向量混合检索；
6. 带文件名、文档 ID、Chunk ID 的引用回答；
7. 低置信度或无证据拒答；
8. 30–50 条离线评测集与失败分类；
9. 仅允许三个只读工具的受约束 Tool Calling；
10. tenant_id 检索前过滤与跨租户负向测试；
11. 间接 Prompt Injection 测试；
12. PII 基础脱敏、安全审计与请求追踪；
13. Docker Compose 一键启动；
14. 延迟、错误、Token 与检索命中率基线；
15. README、架构图、威胁模型、评测报告和演示脚本。

## 4. 非目标

- 训练或微调大模型；
- 自建 GPU 推理集群；
- 多智能体自治系统；
- Kubernetes 或微服务拆分；
- 复杂前端；
- 真实医院系统集成；
- 声称达到医疗器械或生产合规要求。

## 5. 目标架构

```text
Client
  -> FastAPI API
      -> Service layer
          -> Repository -> SQLite
          -> Retrieval pipeline -> keyword/vector index
          -> RAG workflow -> model adapter
          -> Allowlisted tools
      -> Security controls
          -> tenant filter
          -> input/output validation
          -> PII redaction
          -> audit events
```

架构按天演进，不在 Day 1 一次性建完。Day 2 才引入分层；Day 3 才加入数据库；Day 8 以后才进入 RAG。

## 6. 预期目录（最终状态）

```text
medops-rag/
├─ README.md
├─ README_CN.md
├─ .env.example
├─ pyproject.toml
├─ compose.yaml
├─ app/
│  ├─ main.py
│  ├─ api/
│  ├─ services/
│  ├─ repositories/
│  ├─ models/
│  ├─ retrieval/
│  ├─ agents/
│  └─ security/
├─ tests/
├─ evals/
├─ sample_data/
├─ docs/
│  ├─ plans/
│  ├─ progress/
│  ├─ architecture.svg
│  └─ demo.md
└─ scripts/
```

## 7. 每日完成定义

一天只有同时满足以下条件才标记为完成：

- [ ] 当天范围内的功能可以运行；
- [ ] 至少留下一个失败场景或负向测试；
- [ ] 写明精确运行与复现命令；
- [ ] 能脱稿解释当天核心概念；
- [ ] 没有真实患者数据、凭证和机器专属绝对路径；
- [ ] 更新每日记录；
- [ ] 创建一个聚焦的 Git commit。

## 8. 最终验收定义

- 新环境可按 README 启动；
- API、数据库、检索、引用和拒答链路可演示；
- 评测报告包含指标、失败案例和改进，而不只有“准确率”；
- 跨租户、恶意文档、越权工具、非法参数与超时均有负向测试；
- 日志不含原始敏感信息和真实凭证；
- 架构图、威胁模型、演示脚本和 3–5 分钟视频齐全；
- 每项简历表述都可以运行、解释或展示证据。
