# MedOps RAG

这是一个面向**医院信息化运维与制度文档**的可审计知识助手学习项目，只使用公开或合成资料，不进行医疗诊断。

## 正确的学习方式

这不是 30 个互不相关的小练习，而是一个仓库连续升级：

1. 当天先学习完成任务所需的最小知识；
2. 关掉教程，在本仓库独立实现；
3. 主动制造至少一个失败场景；
4. 保存运行命令、测试结果或截图作为证据；
5. 用自己的话解释设计选择；
6. 只提交当天相关文件，并写一个清楚的 Git commit。

如果当天验收没有通过，不按日历硬冲下一天。修到通过后再继续。教程进度不是项目进度，能运行、能测试、能解释才算进度。

## 项目边界

- 只使用公开或合成的 HIS、EMR、LIS、PACS 运维资料；
- 不存储真实患者信息、Cookie、Token 或密码；
- 不实现诊断、处方或治疗建议；
- Day 1 不提前造数据库、RAG 或复杂目录；
- 只选择一套 RAG 技术链，不同时堆 LangChain、LlamaIndex、Dify 等框架；
- 安全结论必须有负向测试，不能声称“绝对安全”。

## 从哪里开始

1. 阅读 [`docs/PROJECT_SPEC.md`](docs/PROJECT_SPEC.md)。
2. 查看 [`docs/plans/2026-09-03-medops-rag-30-day-plan.md`](docs/plans/2026-09-03-medops-rag-30-day-plan.md) 的 Day 1。
3. 将 [`docs/progress/DAY_REPORT_TEMPLATE.md`](docs/progress/DAY_REPORT_TEMPLATE.md) 复制为当天记录。
4. 从空文件实现 Day 1；不要让 AI 直接生成验收答案。
5. 把证据和结论填写到 [`docs/progress/DAILY_LOG.md`](docs/progress/DAILY_LOG.md)。

## 四个版本门禁

| 日期 | 版本 | 必须证明 |
|---|---|---|
| Day 7 | MedKB API v0.1 | Python / FastAPI / SQL / pytest 能组成可维护服务 |
| Day 14 | MedOps RAG v0.2 | 文档导入、检索、引用、评测和受约束工具调用可运行 |
| Day 21 | Secure MedOps RAG v0.3 | 权限隔离、注入测试、脱敏与审计有负向证据 |
| Day 30 | MedOps RAG v1.0 | 可运行、可评估、可解释、可部署、可演示、可投递 |
