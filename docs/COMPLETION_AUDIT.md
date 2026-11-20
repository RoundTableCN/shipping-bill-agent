# Agent 完成度审计（2026-11-19 公网 URL 输入复检）

> 公开 GitHub 版本已移除真实业务样例；依赖这些样例的测试自动 skip。
> 公开仓库当前测试结果：**129 passed, 131 skipped**。完整本地工作区（含样例）：**260 passed**。

> 审计对象：`航运智能账单助手智能体` 当前工作区。
> 目的：区分「代码已实现」「真实服务已验证」「交付已就绪」，避免把实现当成验证。
> 范围：初次审计 2026-11-13；2026-11-16 复检配置/交付；2026-11-18 按四份样本账务规则复检 AR/AP、mapping_status、原始/规范化审计；同日按《完整问题修复清单》修复 P/C、编号分类、日期歧义、主题箱号、SHA/TAR、付款指令、状态分层和历史查重门禁；2026-11-19 增加公网 http/https URL 输入。交付前以最新文件哈希、测试结果和本页“交付就绪度”为准。

## 1. 结论

| 维度 | 完成度 | 判断 |
|---|---:|---|
| **功能代码** | **95%** | P0–P4 主链路完整，260 项测试通过，端到端 fixture 可跑通 |
| **真实服务验证** | **75–85%** | OCR 图片型 PDF 已验证；文字 PDF/直接 PNG 返回空；视觉模型 3 份样本 23/24；LangChain 平台 API 真实调用成功；`.doc` 内置 OLE 解析已验证 Office 模板 |
| **交付就绪度** | **85%** | zip 已重建并包含最新文档；邮件未发送 |
| **综合判断** | **约 85–90%** | 功能完整、关键外部服务已验证；剩余主要是真实业务数据覆盖和自定义 provider 验证 |

**一句话**：这是一个**功能完整、可演示、测试充分**的 Agent，但还不是“在真实业务数据上充分验证”的 Agent。

**Agent 定位**：这是“确定性账单流水线 + 可选 LangChain 语义抽取”的领域 Agent；解析、匹配、AR/AP、校验、operation 决策由代码控制，LangChain 只参与文档分类、费用语义和变更意图抽取。它不是自主规划、自由调用工具的通用 Agent。

---

## 2. 本轮实测证据

| 检查 | 命令/方式 | 结果 |
|---|---|---|
| 全量测试 | `python -m pytest -q` | **260 项通过** |
| Golden 评测 | `python scripts/eval.py` | 22 条记录：字段/operation/AR-AP 100%，幻觉率 0%，复核率 59.09%（合成 golden；13 条均为预期保守复核，见 [EVALUATION_NOTES.md](EVALUATION_NOTES.md)） |
| 端到端 fixture | `python scripts/build_output.py ...` | 6 个文件全部产出记录：CREATE/UPDATE/NO_CHANGE/PENDING_REVIEW 均有覆盖 |
| JSON Schema | `python scripts/generate_schema.py` | strict/full schema 重新生成成功 |
| fixtures | `python scripts/verify_fixtures.py` | 全部 PASS |
| Streamlit | 启动后请求 `/_stcore/health` | **200 ok**，端口已释放 |
| 手工 OCR fixture | `python scripts/run_manual_ocr.py` | 2 条 CREATE/AP/PASS（**不是真实 OCR**） |
| 真实 OCR | 4 个 OSS URL 探针（2026-11-12 18:16） | PDF1/PDF2/PNG 均 `data.list=[]`；`sample_carrier.pdf` 成功 |
| 真实 OCR → Agent | `run_ocr_url.py`（2026-11-13 重试） | **504**；原因是签名 URL 已过期，不是 agent 逻辑错误 |
| 视觉模型对比 | `python scripts/compare_models.py` | DeepSeek `deepseek-flash[1M]` 真实调用；3 份样本 **23/24（95.8%）** |
| LangChain 真实抽取 | `build_output.py --use-llm` | 平台 Anthropic 兼容 API 成功；`formal_invoice.pdf` 3 条 `NO_CHANGE` |
| 首次运行 AI 配置 | `scripts/configure_ai.py --show` | 首次运行询问：平台 API / 指定 DeepSeek/OpenAI/Anthropic / 不使用大模型；支持保存/清除 |
| DeepSeek 供应商 | `configure_ai.py --provider deepseek` + `test_ai_config.py` | 保存 `provider=deepseek`；LangChain `ChatOpenAI` 构建测试通过 |
| zip 源码一致性 | 逐文件 SHA-256 比较 `src/tests/app/scripts/config/schemas/data/docs` + 根文件（2026-11-19 复检） | **174 个文件，0 missing，0 different** |
| zip 内测试 | zip 解压到临时目录后 `pytest -q` | **260 项通过** |
| 一键启动/清理 | `start_app.bat --smoke-test`；并模拟强制结束 launcher | health 200；Job Object 终止 Streamlit；端口释放，无残留进程 |
| PNG 全流程 | `data/samples/sample_carrier_invoice.png` + `--ocr-mode mock`（视觉兜底默认开启） | Invoice / INV-DEMO-001 / 2 条费用 / USD / 合计 26.90 / posting null；2 条 `PENDING_REVIEW`（视觉兜底强制复核） |
| 首次运行 API 视觉兜底 | 清除平台 `ANTHROPIC_*`，仅使用保存的 DeepSeek `deepseek-chat`；`--ocr-mode api` 且无 OCR URL | OpenAI 兼容 `/chat/completions` 返回 2 条费用（5.00 / 21.90）；不再报 `OCR_URL_REQUIRED`，2 条 `PENDING_REVIEW` |
| 四份样本业务规则 | `tests/test_business_rules.py` | PDF1 B/L raw/normalized + UNPAID；PDF2 同名费用独立 + mapping_status；PRE-ALERT 币种符号推断；Statement candidate AP 不确认 |
| 问题清单回归 | `tests/test_checklist_fixes.py` | P/C 与 Terms 分离、发票号不混入箱号、日期 AMBIGUOUS、主题箱号、SHA/TAR、OCA17、未确认映射、摘要去重、无历史账单复核；ROE 不写入 QTY、BASE=C 不写入 P/C |
| LLM 输出与规则对齐 | `tests/test_llm_grounding.py` | LLM 的 reference/date/recipient/payer/payment instruction 由确定性规则校正；费用数值使用候选行，不再采用 LLM 数量/单价/金额 |
| 公网 URL 输入 | `tests/test_url_input.py` | 本地 HTTP server：下载、URL 校验、大小限制、404；多行 URL 拆分/去重；URL 图片/PDF 先提交 OCR API（默认每 URL 60s、单次尝试）；OCR 空/失败回退本地；图片/扫描 PDF OCR 失败回退视觉模型；`analyze_url`、`build_output --url` 均通过 |
| 公网 OSS URL 实测 | `build_output.py --url <OSS PDF1>` | `url_ocr_attempted=true`；OCR 返回空（另一次为 504）→ 本地 PDF 文字层；General Notice / OCA17 / 245 USD / PENDING_REVIEW |

---

## 3. 需求逐项完成度

### 3.1 输入格式

| 格式 | 状态 | 证据/限制 |
|---|---|---|
| EML | ✅ 已实现并验证 | 主题/发件人/收件人/正文/附件递归；`test_eml.py` |
| PDF（文字层） | ✅ 已实现并验证 | 坐标重建、表格检测；PDF1/PDF2 本地解析 8/8 字段 |
| PDF（扫描/图片型） | ✅ 已实现，部分真实验证 | 扫描页渲染后走 OCR；`sample_carrier.pdf` 真实 OCR 成功 |
| 图片（PNG/JPEG） | ⚠️ 部分 | 代码先转单页 PDF 再提交；直接 PNG 真实 OCR 返回空；`sample_carrier.pdf` 是图片型 PDF，间接证明路径可行 |
| Excel | ✅ 已实现并验证 | `.xlsx` 测试；`.xls` 代码路径存在但本轮未单独验证 |
| DOCX | ✅ 已实现并验证 | `statement.docx` |
| DOC | ✅ 已实现（内置 fallback） | LibreOffice 优先；无 LibreOffice 时用 Word 97 OLE piece table 提取文本/表格行；已在 Office 模板上验证；复杂表格需复核 |

### 3.2 核心业务

| 能力 | 状态 | 证据 |
|---|---|---|
| 指定 OCR API（`orderChange`/空 `callBack`/空 `taskType`/超时） | ✅ 已实现并真实调用 | `io/ocr_client.py`、`scripts/ocr_probe.py` |
| 单据类型/编号/日期 | ✅ 已实现 | `document_class.py`；PDF1/PDF2 本地 8/8 |
| 签发方/接收方 | ✅ 已实现（候选 + 状态） | `issuer_candidate`/`recipient_candidate` |
| 费用名/金额/币种/付款方式 | ✅ 已实现 | `charge_mapper.py`、`extract/rules.py`、`test_rule_extractor.py` |
| 费用名标准化 | ✅ 已实现 | `config/charge_mapping.yaml` 覆盖样本费用 |
| 币种三位代码 | ✅ 类型层强制 | `Currency` 校验；候选币种/文档币种解析 |
| PP/CC/COD 付款方式 | ✅ 已实现 | `_normalize_payment_term`；测试覆盖 |
| CREATE/UPDATE/NO_CHANGE/PENDING_REVIEW | ✅ 已实现 | `decision.py`、`test_pipeline.py` |
| 四级严格匹配 + enhanced | ✅ 已实现 | `matcher.py`、`test_matcher.py` |
| 逐费用行一对一匹配 | ✅ 已实现 | `used` 集、历史行 ID |
| AR/AP 四层判断 | ✅ 已实现 | `ar_ap.py`、`test_arap.py` |
| 重复检测/冲突/低置信度 | ✅ 已实现 | `duplicate.py`、`decision.py`、`validate/rules.py` |
| 数据校验（金额/币种/数量×单价/OCR 混淆/合计+税额） | ✅ 已实现 | `validate/rules.py`、`test_validation_integration.py` |
| 来源/原文/证据 | ✅ 已实现 | `SourceTrace`、`evidence_in_text`、`audit_trail` |
| 标准 JSON 数组 | ✅ 已实现 | strict/full schema；`test_output.py`、`test_schema.py` |
| Python + LangChain | ✅ 已实现并真实调用 | `extract/llm.py`、`langchain_extractor.py`；平台 Anthropic API 成功，首次运行可配置 |
| Streamlit UI | ✅ 健康检查通过 | `/_stcore/health` 200；`test_ui_service.py` |
| zip/Git 交付 | ✅ 已重建并核对 | `dist/shipping-bill-agent.zip` 已包含最新文档；2026-11-16 已做 162 文件哈希比较 |

---

## 4. OCR 与视觉模型的真实边界

### 4.1 OCR API（2026-11-12 18:16 实测）

| 文件 | 结果 |
|---|---|
| PDF1（文字型 General Notice） | 200 / 2.97s / `data.list=[]` |
| PDF2（文字型 Debit Note） | 200 / 3.44s / `data.list=[]` |
| PNG（直接图片） | 200 / 3.82s / `data.list=[]` |
| sample_carrier.pdf（图片型 PDF） | 200 / 11.51s / 成功返回发票号、BL、箱号、2 条费用 |

**结论**：该接口是**航运业务文档解析器**，不是通用 OCR；文字型 PDF 和直接 PNG 的“200 + 空列表”不能当作“没有费用”。

### 4.2 路由与兜底（本轮新增）

| 输入 | 顺序 |
|---|---|
| PDF | `api` 模式先按页 OCR；OCR 空/失败 → 本地文字层（`OCR_PDF_FIRST=1`） |
| 图片 | OCR（先转单页 PDF）；mock/local/api 均空 → 视觉模型最终兜底（默认开启，`VISION_FALLBACK=0` 可关闭）；支持 Anthropic 与 OpenAI 兼容端点（含首次运行保存的 DeepSeek）；结果强制 `PENDING_REVIEW` |
| EML / Excel / DOCX | 本地解析；EML 附件按实际格式递归 |
| DOC | LibreOffice 转 DOCX；无 LibreOffice → 内置 OLE/piece-table 文本解析 |
| 已有账单 JSON | `--existing-bills` 读取并匹配 |

### 4.3 首次运行 AI API 配置

- **首次运行主动询问**：平台当前 API / 指定 API / 不使用大模型（规则抽取）。
- 选择“不使用大模型”会保存 `provider=none`，后续只跑规则抽取，不再询问。
- CLI：`python scripts/configure_ai.py --show` / `--use-platform` / `--no-ai` / `--provider ... --model ... --base-url ... --api-key ...`。
- `--use-llm` 在无保存配置时会询问（TTY）；非交互终端直接规则抽取，不阻塞。
- Streamlit 首次运行先显示 AI API 选择页；之后侧边栏可修改。
- 配置保存在 `~/.shipping_agent/ai_config.json`（`AI_CONFIG_PATH` 可覆盖），不写入项目。
- 平台 Anthropic 兼容 API 已真实跑通 LangChain 结构化抽取；自定义 DeepSeek/OpenAI/Anthropic 已做构建测试。

### 4.2.1 视觉模型（2026-11-13 实测）

- 平台模型：`deepseek-flash[1M]`，通过 `https://api.deepseek.com/anthropic` 的 Anthropic 兼容接口；
- 首次运行保存的自定义 DeepSeek：`deepseek-chat`，通过 `https://api.deepseek.com/v1` 的 OpenAI 兼容 `/chat/completions`；2026-11-18 对 `data/samples/sample_carrier_invoice.png` 返回 2 条费用、合计 26.90；
- 输入：PDF 渲染图/PNG；
- 结果：PDF1 8/8、PDF2 8/8、PNG 7/8，总计 **23/24（95.8%）**；
- PNG 唯一不一致：视觉输出 `DEBIT INVOICE`，真值 `Invoice`——语义同义，不是金额/编号错误；
- 视觉模型补上了 OCR 缺失的日期、币种、合计、交易方等字段。

报告：[docs/COMPARISON.md](COMPARISON.md)

---

## 5. 主要缺口与风险（按优先级）

| 优先级 | 缺口 | 影响 | 建议 |
|---|---|---|---|
| P1 | `.doc` 复杂表格结构 | 内置解析能取文本/表格行，但复杂合并单元格仍需复核 | 用真实航运 DOC 增加回归样本 |
| P0 | 真实 OCR 只覆盖图片型 PDF；文字 PDF/直接 PNG 返回空 | 不能把 OCR 当通用解析器 | 文字 PDF 本地解析；图片先转 PDF；空结果进入复核 |
| P1 | 其他自定义 AI provider 未逐一真实验证 | 平台 Anthropic API 已验证；自定义 DeepSeek/OpenAI/Anthropic 只做了构建测试 | 用目标 provider 跑一次 `--use-llm` |
| P1 | golden/评测是合成数据 | 100% 指标不代表真实业务准确率 | 增加脱敏真实账单/人工标注集 |
| P2 | zip 与工作区的源码版本一致性 | 2026-11-16 已复核 162 文件、0 diff；后续改动仍需复核 | 交付前逐文件哈希比较 `src/tests/docs` 与 zip |
| P2 | 直接 PNG → 单页 PDF → 真实 OCR 未单独跑 | 图片路径只间接验证 | 用新签名 URL 跑一次转换后的 PDF |
| P2 | OCR 无 bbox/置信度 | 证据只能到文件/页级 | 在审计中明确限制，不伪造坐标 |
| P2 | 真实历史账单/记账主体数据少 | AR/AP 真实覆盖率有限 | 增加真实/脱敏历史账单 |
| P2 | OCR 签名 URL 会过期 | 真实复现失败（本次 504） | 使用长期对象存储/临时隧道 |

---

## 6. 结论与建议

**已经可以证明的：**

- 多格式解析、候选费用、规则抽取、匹配、AR/AP、operation、校验、JSON 输出链路完整；
- 260 项测试、golden 评测、端到端 fixture、Streamlit 健康检查均通过；
- 真实 OCR 对图片型 PDF 可用；真实视觉模型对 3 份样本达到 23/24 字段一致；
- 缺字段时不会伪造，真实 OCR 结果进入 `PENDING_REVIEW`。

**还不能证明的：**

- 在大量真实账单上的字段准确率；
- 其他自定义 AI provider 的真实端到端抽取；
- 复杂 `.doc` 表格结构/真实航运 DOC 的字段准确率；
- 直接 PNG 的真实 OCR（需先转 PDF 并重新托管）；
- 生产级托管、权限、审计与邮件交付。

**建议下一步（按顺序）：**

1. 用真实航运 `.doc` 补回归测试（内置 OLE 解析已可读文本）；
2. 用目标自定义 provider 跑一次 `scripts/extract_documents.py --use-llm`；
3. 用新签名 URL 重跑 `sample_carrier.pdf` 和“PNG→PDF”路径；
4. 增加真实/脱敏账单到 golden，重跑评测；
5. 发送邮件前逐文件比较 zip 与工作区源码，再发送。
