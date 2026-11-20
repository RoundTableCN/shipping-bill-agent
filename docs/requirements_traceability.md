# 需求追溯矩阵

> 对应笔试题《多格式文档解析的航运智能账单助手智能体》原文。
> 用途：逐条证明「要求 → 设计 → 代码模块 → 测试/产物」的对应关系。
> 状态说明：**已设计** = 方案已明确；**待实现** = 编码阶段完成；**已交付** = 文件已存在；**待验证** = 依赖外部接口或实测。

---

## 1. 项目目标（OBJ）

| ID | 原文要求 | 方案位置 | 实现模块 | 测试/产物 | 状态 |
|---|---|---|---|---|---|
| OBJ-01 | 支持 EML、PDF、图片、Excel、DOC/DOCX | §4.1–4.6 | `io/detect.py`、`io/*_parser.py`、`io/legacy_doc.py`、`io/url_fetcher.py` | `test_detect.py`、`test_eml.py`、`test_pdf.py`、`test_excel.py`、`test_word.py`、`test_legacy_doc.py`、`test_url_input.py` | 已实现；图片 OCR 部分真实验证；`.doc` 内置 OLE 解析；公网 URL 下载后走同一解析链路 |
| OBJ-02 | 自动解析 EML 正文、邮件头及附件 | §4.2 | `io/eml_parser.py` | `test_eml.py` | 已实现（P0-B） |
| OBJ-03 | PDF 或图片通过指定 OCR API 识别 | §5 | `io/ocr_client.py`、`io/ocr_factory.py`、`io/file_hosting.py` | `scripts/ocr_probe.py`、`test_ocr.py`、`test_ocr_wiring.py` | 真实探针已执行；图片型 PDF `chargeList` 已验证；文字 PDF/直接 PNG 返回空 |
| OBJ-04 | 从识别结果中提取航运账单和费用明细 | §4.8、§7 | `candidates/*`、`extract/*` | `test_rule_extractor.py` | 已实现（P1 规则抽取；LLM 可选） |
| OBJ-05 | 费用名称、币种、付款方式标准化 | §8.1、§8.2 | `business/charge_mapper.py`、`extract/rules.py` | `test_charge_mapping.py`、`test_rule_extractor.py` | 已实现（P1） |
| OBJ-06 | 根据输入信息新增或更新账单 | §8.3、§8.4、§8.6 | `business/matcher.py`、`business/decision.py`、`business/pipeline.py` | `test_matcher.py`、`test_decision.py` | 已实现（P2） |
| OBJ-07 | 根据记账主体和交易方向判断 AR/AP | §8.5 | `business/ar_ap.py` | `test_arap.py` | 已实现（P2） |
| OBJ-08 | 识别重复账单、冲突数据和低置信度结果 | §8.7、§8.9 | `business/duplicate.py`、`business/decision.py` | `test_duplicate.py`、`test_decision.py` | 已实现（P2） |
| OBJ-09 | 记录文件来源、原始文本和处理依据 | §6.3、§9 | `models/bundle.py`、`models/output.py`（`SourceTrace` / `audit_trail`） | `test_output.py` | 已实现（P0/P2） |
| OBJ-10 | 输出符合约定格式的 JSON | §6.2、§6.5、§6.6 | `models/output.py`、`output/serializer.py` | `test_output.py`、`test_schema.py` | 已实现（P0） |
| OBJ-11 | 必须使用 Python + LangChain | §7.4 | `extract/llm.py`、`extract/langchain_extractor.py`、`extract/orchestrator.py`、`ai_config.py` | `requirements.txt`、`test_llm.py`、`test_ai_config.py` | 已实现；平台 Anthropic API 真实调用成功 |
| OBJ-12 | 交付 zip 或 Git 仓库 | §14 | `dist/shipping-bill-agent.zip` | 交付包 | 已生成并包含最新文档（2026-11-18 重建） |

---

## 2. 核心功能（FUN）

| ID | 原文要求 | 方案位置 | 实现模块 | 测试/产物 | 状态 |
|---|---|---|---|---|---|
| FUN-01 | EML 主题、发件人、收件人、正文、附件 | §4.2 | `io/eml_parser.py` | `test_eml.py` | 已实现（P0-B） |
| FUN-02 | PDF/图片调用 OCR 提取文字和表格 | §5 | `io/ocr_client.py`、`io/ocr_factory.py`、`io/image_parser.py`、`io/pdf_parser.py`、`vision_extractor.py` | `test_ocr.py`、`test_ocr_wiring.py`、`test_vision_fallback.py`、`test_vision_extractor.py` | PDF 先 OCR 后本地兜底；图片型 PDF 已验证；直接 PNG 在所有 OCR 模式空后自动视觉兜底（Anthropic/OpenAI 兼容，含保存的 DeepSeek） |
| FUN-03 | Excel 工作表、表头、费用明细行 | §4.5 | `io/excel_parser.py` | `test_excel.py`、`charges.xlsx` | 已实现（P0-B） |
| FUN-04 | Word 正文和表格 | §4.6 | `io/word_parser.py` | `test_word.py`、`statement.docx` | 已实现（P0-B） |
| FUN-05 | EML 附件按实际格式递归解析 | §4.2 | `io/eml_parser.py`、`io/detect.py` | `test_eml.py` | 已实现（P0-B） |
| FUN-06 | 单据类型 | §4.3、§8.6 | `business/document_class.py`、`extract/models.py` | `test_document_class.py` | 已实现（P1） |
| FUN-07 | 单据编号及日期 | §4.3、§8.2 | `business/document_class.py` | `test_document_class.py` | 已实现（P1） |
| FUN-08 | 签发方和接收方 | §4.3、§8.5 | `business/document_class.py` | `test_document_class.py` | 已实现（P1 候选方） |
| FUN-09 | 费用名称 | §4.8、§8.1 | `candidates/*`、`business/charge_mapper.py` | `test_charge_mapping.py` | 已实现（P1） |
| FUN-10 | 数量、单价和金额 | §4.8、§6.3 | `models/candidate.py`、`extract/rules.py` | `test_rule_extractor.py` | 已实现（P1） |
| FUN-11 | 币种 | §8.2 | `models/types.py`、`extract/rules.py` | `test_rule_extractor.py` | 已实现（P1） |
| FUN-12 | PP/CC 等付款方式 | §8.2 | `extract/rules.py`（payment term） | `test_rule_extractor.py` | 已实现（P1） |
| FUN-13 | 小计、税额和总计 | §6.3、§8.8 | `models/output.py`、`business/totals.py`、`validate/rules.py` | `test_totals.py`、`test_validate_rules.py` | 已实现（P3） |
| FUN-14 | 费用名标准化，同时保存原始名与标准名 | §8.1 | `business/charge_mapper.py` | `test_charge_mapping.py` | 已实现（P1） |
| FUN-15 | CREATE：一费一条 | §8.6.4 | `business/decision.py`、`business/assembler.py`、`output/serializer.py` | `test_decision.py`、`test_pipeline.py` | 已实现（P2） |
| FUN-16 | UPDATE：四级匹配，只改明确字段，其余继承 | §8.3、§8.4 | `business/matcher.py`、`business/decision.py` | `test_matcher.py`、`test_decision.py` | 已实现（P2） |
| FUN-17 | AR/AP：结合签发方、接收方、记账主体、收费方向 | §8.5 | `business/ar_ap.py` | `test_arap.py` | 已实现（P2） |
| FUN-18 | 五项数据校验 | §8.8 | `validate/rules.py`、`business/totals.py`、`business/duplicate.py` | `test_validate_rules.py`、`test_totals.py`、`test_validation_integration.py` | 已实现（P3） |

---

## 3. 标准输出（OUT）

| ID | 原文要求 | 方案位置 | 实现模块 | 测试/产物 | 状态 |
|---|---|---|---|---|---|
| OUT-01 | 顶层为 JSON 数组 | §6.2 | `output/serializer.py` | `test_output.py` | 已实现（P0） |
| OUT-02 | `operation`：CREATE/UPDATE/NO_CHANGE/PENDING_REVIEW | §6.2、§8.9 | `models/output.py` | `test_output.py` | 已实现（P0） |
| OUT-03 | `document_info`：document_type/reference_no/document_date | §6.2 | `models/output.py` | `test_output.py` | 已实现（P0） |
| OUT-04 | `transaction_party`：issuer/recipient | §6.2 | `models/output.py` | `test_output.py` | 已实现（P0） |
| OUT-05 | `charge_details`：charge_item/amount/currency/payment_term | §6.2 | `models/output.py` | `test_output.py` | 已实现（P0） |
| OUT-06 | `financial_attributes`：accounting_entity/posting_type | §6.2 | `models/output.py` | `test_output.py` | 已实现（P0） |
| OUT-07 | `audit_trail.ai_reasoning` | §6.2、§6.3 | `models/output.py` | `test_output.py` | 已实现（P0） |
| OUT-08 | 合法 JSON；金额为数字；无法提取为 null | §6.1、§6.5 | `output/serializer.py` | `test_output.py`、`test_schema.py` | 已实现（P0） |

---

## 4. 处理要求（REQ）

| ID | 原文要求 | 方案位置 | 实现模块 | 测试/产物 | 状态 |
|---|---|---|---|---|---|
| REQ-01 | 不得虚构输入材料中不存在的数据 | §9 | `extract/evidence.py`、`validate/rules.py` | `test_evidence.py`、`test_validation_integration.py` | 已实现（P1/P3） |
| REQ-02 | 无法提取的字段使用 null | §6.2、§6.3 | `models/output.py` | `test_output.py` | 已实现（P0） |
| REQ-03 | 金额必须使用数字类型 | §6.1 | `models/types.py`、`output/serializer.py` | `test_types.py`、`test_output.py` | 已实现（P0） |
| REQ-04 | 币种统一三位代码 | §8.2 | `models/types.py`（类型）；`business/currency.py`（归一化待 P1） | `test_types.py` | 部分实现（类型已实现） |
| REQ-05 | 每个费用项目单独输出一条记录 | §8.6.4 | `business/assembler.py`、`business/decision.py` | `test_pipeline.py`、`test_output.py` | 已实现（P2） |
| REQ-06 | 更新时不得覆盖未明确要求修改的字段 | §8.4 | `business/decision.py` | `test_decision.py`、`test_pipeline.py` | 已实现（P2） |
| REQ-07 | OCR 结果不能未经校验直接入账 | §5.8 | `validate/rules.py`、`business/pipeline.py` | `test_validation_integration.py`、`test_real_ocr_fixture.py` | 已实现（P3） |
| REQ-08 | 最终结果必须是合法 JSON | §6.5 | `output/serializer.py` | `test_output.py`、`test_schema.py` | 已实现（P0） |

---

## 5. 验收标准（ACC）

| ID | 原文要求 | 方案位置 | 必须产物 | 状态 |
|---|---|---|---|---|
| ACC-01 | 正确解析 EML 正文及附件 | §4.2 | `test_eml.py` + EML 输出 | 已实现（P0-B） |
| ACC-02 | 调用 OCR API 识别 PDF 和图片 | §5 | `ocr_probe.py`、`io/ocr_client.py`、`io/ocr_factory.py`、`scripts/run_ocr_url.py`、`OCR_CAPABILITY.md` | 图片型 PDF 200，`chargeList` 2 条；直接 PNG/文字型 PDF 返回空；PDF 已改为 OCR-first + 本地兜底 |
| ACC-03 | 解析 Excel、Word 费用表格 | §4.5、§4.6 | `test_excel.py`、`test_word.py` + fixtures | 已实现（P0-B） |
| ACC-04 | 准确提取单据编号、费用、金额和币种 | §4.3、§4.8 | `test_document_class.py`、`test_rule_extractor.py`；`data/golden/` 22 条评测 | 已实现（P1/P3） |
| ACC-05 | 区分新增账单和更新账单 | §8.3、§8.4、§8.6 | `test_matcher.py`、`test_decision.py`、`test_pipeline.py` | 已实现（P2） |
| ACC-06 | 结合记账主体判断 AR/AP | §8.5 | `test_arap.py` | 已实现（P2） |
| ACC-07 | 检测重复账单和数据冲突 | §8.7、§8.9 | `test_duplicate.py`、`test_matcher.py` | 已实现（P2） |
| ACC-08 | 设计 harness 工程 | §9 | `validate/rules.py`、`tests/`、`data/golden/`、`scripts/eval.py` | 已实现（P3） |
| ACC-09 | 写出 5 点以上自己的思考 | `docs/DECISIONS.md` | 已交付 13 点（业务 6 + 技术 7） | **已交付** |
| ACC-10 | 基于 Python 和 LangChain 代码实现 | §7.4 | P0/P1 代码已实现；平台 Anthropic API 真实调用 | 已实现并验证 |

---

## 6. 交付（DLV）

| ID | 原文要求 | 方案位置 | 产物 | 状态 |
|---|---|---|---|---|
| DLV-01 | 打包 zip 或提供 Git 仓库链接 | §14 | `dist/shipping-bill-agent.zip` | 已生成并包含最新文档（2026-11-18 重建） |
| DLV-02 | 发送至 LUKA@PLTPLT.COM 及 pan@pltplt.com | §14.2 | 邮件记录 | 待发送（需本人操作） |
| DLV-03 | 邮件标题：应聘渠道+姓名+应聘岗位 | §14.2 | 邮件标题 | 待发送（需本人操作） |

---

## 7. 设计补充（DES）

| ID | 设计点 | 方案位置 | 测试/产物 | 状态 |
|---|---|---|---|---|
| DES-01 | 文档性质分层 | §8.6 | `test_document_class.py` | 已实现（P1） |
| DES-02 | 账单成熟度（含 void） | §6.3、§8.6 | `test_document_class.py` | 已实现（P1） |
| DES-03 | 费用行唯一标识 `line_id` / `source_position_id` | §4.8、§8.7 | `test_edge_cases.py`、`test_candidates.py` | 已实现（P1） |
| DES-04 | 资金流角色 payer/payee/beneficiary | §8.5 | `test_arap.py` | 已实现（P2） |
| DES-05 | 收费方向 `charge_direction` | §8.5 | `test_arap.py` | 已实现（P2） |
| DES-06 | 黄金数据坐标 + 渲染图双确认 | §4.3、§11 | `tests/test_pdf.py::test_general_notice_sample_and_label_pairs` | 已实现（测试在 test_pdf.py） |
| DES-07 | billing_status 内容判定 | §8.6.2 | `test_document_class.py` | 待实现 |
| DES-08 | 逐费用行 operation | §8.6.4 | `test_decision.py`、`test_pipeline.py` | 已实现（P2） |
| DES-09 | 历史费用行一对一匹配 | §8.3、§8.7 | `test_matcher.py` | 已实现（P2） |
| DES-10 | 三维置信度与门禁 | §8.9 | `test_decision.py` | 已实现（P2） |
| DES-11 | 候选方向 vs 确认方向、accounting_status | §6.3、§8.5 | `test_arap.py`、`test_business_rules.py` | 已实现 |
| DES-12 | 原始/规范化 B/L、多个日期、币种来源 | §4.3、§6.3 | `test_business_rules.py` | 已实现（full audit） |
| DES-13 | 费用 mapping_status / 原始标准双字段 | §8.1、§8.5 | `test_charge_mapping.py` | 已实现 |
| DES-14 | P/C 与单据 Payment Terms 分离 | 问题清单 2.1 | `test_checklist_fixes.py` | 已实现 |
| DES-15 | 容器号 ISO 6346 校验 + 邮件主题提取 | 问题清单 2.2、2.5 | `test_checklist_fixes.py` | 已实现 |
| DES-16 | 歧义日期 AMBIGUOUS / raw + candidates | 问题清单 2.3 | `test_checklist_fixes.py` | 已实现 |
| DES-17 | SHA/TAR、OCA17、PAY IMMEDIATELY、HOLD/Telex 独立字段 | 问题清单 2.6、3.3、3.6、4.3 | `test_checklist_fixes.py` | 已实现 |
| DES-18 | 未确认映射不写最终标准名 + 无历史账单复核 | 问题清单 3.1、9.7 | `test_checklist_fixes.py` | 已实现 |
| DES-19 | 公网 http/https URL 输入 | 输入适配 | `io/url_fetcher.py`、`test_url_input.py` | 已实现；CLI `--url` + Streamlit URL 输入；PDF/图片 OCR-first → 本地 → 视觉兜底 |

---

## 8. 状态汇总

| 状态 | 数量 | 说明 |
|---|---|---|
| 已交付 | 5 | `docs/DECISIONS.md`、`OCR_CAPABILITY.md`、`COMPARISON.md`、`OCR_vs_MANUAL.md`、`COMPLETION_AUDIT.md` |
| fixtures 已交付 | 7 | `data/fixtures/`：PDF×3、xlsx、docx、json、README |
| P0 已实现 | 8 项 OUT + 3 项 REQ | `models/`、`output/serializer.py`、`validate/schema.py` |
| P0-B 已实现 | 格式识别 / EML / PDF / Excel / Word / 候选行 / CLI | `io/*`、`candidates/*`、`cli.py`、57 项 pytest |
| P1 已实现 | 文档分类 / 费用语义 / 变更意图 / 证据校验 / LangChain 入口 | `business/*`、`extract/*`、94 项 pytest |
| P2 已实现 | 匹配 / 更新 / AR-AP / 去重 / operation / 最终 JSON | `business/*`、126 项 pytest |
| P3 已实现 | 金额/币种/数量×单价/OCR 混淆/合计+税额/缺失字段校验 + Golden + 评测 + 边界集 | `validate/rules.py`、`business/totals.py`、`data/golden/`、`scripts/eval.py`、176 项 pytest |
| P4 已实现 | Streamlit 上传 / 公网 URL / 结果 / full-strict-audit 下载 | `app/streamlit_app.py`、`ui_service.py`、`io/url_fetcher.py`、260 项 pytest |
| 已设计 | 全部 | `docs/PLAN.md` 已逐条覆盖 |
| 待实现 | 0 项（代码层） | P0–P4 已完成；剩余为真实外部验证与交付 |
| 待验证 | 自定义 AI provider / 直接 PNG / 真实历史账单 | 平台 LangChain 已真实验证；`.doc` 内置解析已验证 Office 模板；OCR 图片型 PDF 已验证 |
| 待交付 | 1 项 | 发送邮件 |

> 本矩阵的用途是防止"方案里写了、交付时漏了"。交付前应把「待实现 / 待验证 / 待交付」全部清零，或明确写出未完成原因。
