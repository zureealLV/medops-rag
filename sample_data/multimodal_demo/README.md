# 多模态与外部数据导入测试包

这些文件全部是合成教学数据，不包含患者资料、真实设备日志或机构内部流程。

## 推荐测试顺序

1. 启动服务并打开 `http://127.0.0.1:8000/`。
2. 新建知识库“多模态导入测试”。
3. 依次上传本目录中的 CSV、JSONL、PNG/JPEG/WebP、DOCX、PDF 和 PPTX。
4. 文档状态变为可用后，依次提问：
   - `DEMO-PUMP-042 的告警是什么？`
   - `输液泵上游阻塞告警时，资料建议先检查什么？`
   - `模拟脉搏血氧仪显示的 SpO2 和脉率是多少？`
5. 回答正文应显示 `[来源1]` 或 `[图像1]`，下方来源卡片应能对应到文件；界面不应出现 `[2:2]` 或 `SCORE 0.x`。

## 文件覆盖

| 文件 | 验证点 |
| --- | --- |
| `medical_device_inventory.csv` | 数据库/表格导出的结构化行 |
| `medical_device_events.jsonl` | JSON Lines 记录 |
| `infusion_pump_alarm_panel.png` | 独立图片 OCR 与图像证据 |
| `pulse_oximeter_display.jpg` / `.webp` | 常见栅格格式 |
| `infusion_pump_training_pack.docx` | 正文、表格、内嵌图片 |
| `medical_device_quick_reference.pdf` | PDF 文本、表格、页面与视觉证据 |
| `medical_device_training_slides_v2.pptx` | 幻灯片文本与内嵌图片 |

## 外部数据库

不要把任意 `.db`、生产数据库转储或含患者标识符的文件直接塞进知识库。先在数据拥有方授权范围内筛选字段、去标识化并导出为 UTF-8 CSV/JSON/JSONL，再上传审核后的快照。

本仓库附带只读 SQLite 表导出器：

```powershell
.\.venv\Scripts\python.exe .\scripts\export_sqlite_table.py `
  --database .\example.db --table approved_documents `
  --columns title,content,source_url `
  --output .\approved_documents.jsonl
```

MySQL、PostgreSQL、Excel 或数据仓库可使用各自客户端导出同样的 CSV/JSON/JSONL 交换格式。当前版本没有保存数据库密码，也不会直连生产库。

除 PPTX 外，其余合成测试文件可由下面的命令重新生成：

```powershell
.\.venv\Scripts\python.exe .\scripts\build_multimodal_test_pack.py all
```
