# 航运智能账单助手（Shipping Bill Agent）

多格式文档解析的航运智能账单助手智能体。

**定位**：这是一个**确定性账单流水线 + 可选 LangChain 语义抽取**的领域 Agent，不是会自主规划、自由调用工具的通用 Agent。解析、匹配、AR/AP、校验、operation 决策由代码控制；LangChain 只参与文档分类、费用语义和变更意图抽取。

**当前状态**：P0–P4 功能已实现；平台 LangChain API、图片型 PDF OCR、视觉模型对照、DOC 内置解析已验证。仍需补充真实业务样本、自定义 provider 实测和直接 PNG 的真实 OCR 路径。

## 当前能力（P0–P4）

- 统一输出模型：`operation` / `document_info` / `transaction_party` / `charge_details` / `financial_attributes` / `audit_trail`
- 两种输出模式：
  - `full`：完整审计轨迹（来源、原文、置信度、匹配过程等）
  - `strict`：只输出题目规定的字段，扩展审计信息写入独立 `audit.json`
- 金额类型 `Money = Decimal`，输出为 JSON number，不使用 float 中转
- 币种 `Currency` 强制三位大写代码；金额按 ISO 4217 币种小数位量化
- 输出 JSON Schema：`schemas/output.schema.json`（strict）与 `schemas/output.full.schema.json`（full）
- **格式识别**：魔数优先，支持 PDF / EML / XLSX / XLS / DOCX / DOC / PNG / JPEG / TIFF / HTML / CSV / TXT
- **EML**：主题/发件人/收件人/正文/附件递归；内嵌图片识别为 media；B/L 识别为 reference
- **PDF**：文字层解析 + 按坐标重建行 + 表头/费用表检测
- **Excel**：多 sheet、表头行检测、列映射、按币种合计行
- **Word**：正文段落 + 表格按 body 顺序提取
- **候选费用行**：表格行 + 文本行正则，带 `source_position_id`、`content_fingerprint`、evidence
- **OCR**：`api` 模式 PDF 页面优先 OCR，OCR 空/失败时回退本地文字层；图片先转单页 PDF；`mock` / `local` 可离线
- **图片最终兜底**：mock / local / api 都没有识别出图片内容时，自动调用已配置的视觉大模型（支持 Anthropic 兼容和 OpenAI 兼容端点，含 DeepSeek）；结果强制 `PENDING_REVIEW`。`VISION_FALLBACK=0` 可关闭
- **P1 文档分类**：document_type / document_class / billing_status / 编号 / 日期 / 交易方（规则基线）
- **P1 费用语义**：费用名标准化（YAML 映射）、金额/币种/付款方式、evidence 校验
- **P1 变更意图**：只提取明确的 `REVISED / CORRECTED / 改为` 证据，不推测
- **LangChain 抽取入口**：`ChatPromptTemplate` + `with_structured_output`；LLM 只做语义解释，编号/日期/金额/数量/P-C 等确定性字段由规则和候选行对齐；无 key / 调用失败自动回退规则
- **P2 已有账单**：适配层 + 索引（reference / BL / booking / container）
- **P2 匹配**：`strict` 原文四级 + `enhanced` 身份检索；逐费用行一对一
- **P2 更新**：只应用有明确证据的变更，未修改字段继承原账单
- **P2 AR/AP**：四层判断；区分 candidate direction 与 confirmed direction；弱证据只进 audit，不写 `posting_type`；无冲突时可继承历史 posting_type
- **业务规则审计**：`mapping_status`、原始/候选/标准费用名、Rate/ROE/Base、B/L raw/normalized、多个日期候选（含 AMBIGUOUS）、container 来源、SHA/TAR 代码、P/C、付款指令、Release/HOLD、币种来源、operation/accounting/payment status 进入 full audit
- **P0-P2 修复规则**：P/C 与单据 Terms 分开；发票号不得混入箱号；日期歧义保持 null；未确认映射保留原始费用名；B/L 不冒充 document number；没有历史账单时 `PENDING_REVIEW + W_HISTORY_NOT_CHECKED`
- **P2 去重**：同一 `source_position_id` 才合并；同值不同行保留
- **P2 最终输出**：CREATE / UPDATE / NO_CHANGE / PENDING_REVIEW + full/strict JSON
- **P3 数据校验**：金额/币种/数量×单价/OCR 混淆/合计+税额/缺失字段；错误进入 `PENDING_REVIEW`
- **P3 总计抽取**：subtotal / tax / total；多币种合计跳过并告警
- **P3 Golden 快照**：9 个核心样本 full JSON + 稳定字段回归
- **P3 评测指标**：字段准确率、operation、AR/AP、幻觉率、复核率；输出 JSON + Markdown
- **P3 边界场景**：Proforma、VOID、金额变更无证据、多页费用表、单部分 EML、同编号不同主体
- **P4 Streamlit**：多文件上传或公网 URL 输入；URL 的 PDF/图片先提交 OCR API，OCR 空/失败后本地解析，最后视觉兜底；分类/费用表/full-strict-audit 下载
- 完整本地工作区：260 项 pytest 全通过
- 本公开仓库已移除真实业务样例，样例相关测试自动 skip；当前结果：`129 passed, 131 skipped`
  （`data/fixtures/` 的合成数据测试仍会运行）
- 合成 fixtures：3 个 PDF、1 个 Excel、1 个 Word、1 个历史账单 JSON

## 验证状态（实现 ≠ 真实验证）

| 能力 | 已实现 | 已验证方式 | 尚未验证 |
|---|---|---|---|
| EML/PDF/Excel/Word 解析 | 是 | 单元测试 + fixtures | 真实复杂版式/扫描件 |
| OCR API | 是 | **OSS 图片型 PDF：200 / 11.96s，`chargeList` 2 条；真实 OCR→Agent 产出 2 条 PENDING_REVIEW**；直接 PNG 200 但空；文字型 PDF1/PDF2 200 但空 | 真实 currency/payer 字段（OCR 未返回） |
| LangChain / AI API | 是 | 平台 Anthropic 兼容 API 真实调用成功；`formal_invoice.pdf` 3 条 NO_CHANGE；首次运行可配置 | 其他自定义 provider 的真实调用 |
| 视觉模型对比 | 是 | DeepSeek `deepseek-flash[1M]` 真实调用；3 份样本 23/24 字段 | 更多真实账单/版式 |
| 匹配 / AR/AP / operation | 是 | synthetic golden + 边界集 | 真实历史账单数据 |
| Golden / 评测 | 是 | 9 个 golden、22 条记录、字段级指标；复核率 59% 为预期保守复核 | 真实/脱敏人工标注集；详见 [EVALUATION_NOTES.md](docs/EVALUATION_NOTES.md) |
| `.doc` | 是（LibreOffice 或内置 OLE 文本解析） | LibreOffice 转换优先；无 LibreOffice 时用 Word 97 piece table 提取文本/表格行 | 复杂 Word 表格结构仍需人工复核 |
| Streamlit | 是 | `/_stcore/health` 200 | 完整人工交互 |

> OCR 真实探针详见 [docs/OCR_CAPABILITY.md](docs/OCR_CAPABILITY.md)：接口是同步返回、`data.list[]` 业务字段结构，不是通用 text/tables；`chargeList` 已在 CARRIER 图片型 PDF 上确认（2 条费用），但仍缺 currency/date/total 字段。

## 一键启动（Windows，推荐）

**双击项目根目录的 [start_app.bat](start_app.bat)**。

它会：

1. 自动找到 Python；
2. 选择可用端口（默认 8501，被占用则自动换一个）；
3. 启动 Streamlit 并等待 `/_stcore/health` 返回 200；
4. 自动打开浏览器；
5. 关闭控制台窗口或按 `Ctrl+C` 时，通过 Windows Job Object 终止整个 Streamlit 进程树，不留后台进程；
6. 下次启动不受上一次影响。

日志：

```text
out/launcher/streamlit.log
```

也可以手动运行：

```powershell
python scripts/launch_streamlit.py
python scripts/launch_streamlit.py --no-browser
python scripts/launch_streamlit.py --port 8502
```

> 不要直接双击 `app/streamlit_app.py`。它不是独立应用，直接运行不会启动 Streamlit 服务；现在会提示你用 `start_app.bat` 或 `streamlit run`。
>
> 如果出现 `No module named streamlit`，说明选中了没有安装依赖的 Python。新版 `start_app.bat` 会先检查 `python -c "import streamlit"`，跳过不满足的 Python，再尝试常见安装路径。也可以在目标 Python 下运行：
> `"目标Python路径\python.exe" -m pip install -r requirements.txt`。

macOS / Linux：

```bash
python scripts/launch_streamlit.py
```

---

## 快速开始

```bash
python -m pip install -r requirements.txt

# 运行测试
python -m pytest -q

# 生成 JSON Schema
python scripts/generate_schema.py

# 生成 strict / full / audit 示例
python scripts/demo_output.py

# 解析文件或目录，输出 bundle + candidates
python scripts/parse_documents.py --input data/fixtures --out out/parse --ocr-mode mock
python scripts/parse_documents.py --input data/fixtures --out out/samples --ocr-mode mock

# 结构化抽取：文档分类 + 费用语义 + 变更意图
python scripts/extract_documents.py --input data/fixtures --out out/extract --existing-bills data/fixtures/existing_bills.json
python scripts/extract_documents.py --input data/fixtures --out out/extract_samples
# 有 LLM key 时启用 LangChain 抽取；失败自动回退规则
python scripts/extract_documents.py --input data/fixtures --out out/extract_llm --use-llm

# 生成最终标准 JSON（P2：匹配 + AR/AP + operation）
python scripts/build_output.py --input data/fixtures --out out/final \
  --existing-bills data/fixtures/existing_bills.json --output-mode full
python scripts/build_output.py --input data/fixtures --out out/final_strict \
  --existing-bills data/fixtures/existing_bills.json --output-mode strict

# 公网 URL 输入（URL 优先提交指定 OCR API，默认每个 URL 60s；失败/空再本地解析；最后视觉兜底）
# Streamlit 的 URL 文本框支持每行一个 URL，批量逐条处理
python scripts/parse_documents.py --url "https://example.com/invoice.pdf" --out out/url_parse
python scripts/extract_documents.py --url "https://example.com/invoice.pdf" --out out/url_extract
python scripts/build_output.py --url "https://example.com/invoice.pdf" --out out/url_final \
  --existing-bills data/fixtures/existing_bills.json --output-mode full


# 生成并回归 golden 快照
python scripts/generate_golden.py
python -m pytest tests/test_golden.py -q

# 评测指标（字段准确率 / operation / AR-AP / 幻觉率 / 复核率）
python scripts/eval.py

# 手工 OCR fixture：验证 OCR 之后的下游流程（不是真实 OCR）
python scripts/run_manual_ocr.py

# Streamlit 演示（Windows 推荐直接双击 start_app.bat）
python scripts/launch_streamlit.py
# 或：streamlit run app/streamlit_app.py
# 页面既支持上传文件，也支持输入公网 http/https 直链

# 重新生成并校验 fixtures
python scripts/make_fixtures.py
python scripts/verify_fixtures.py
```

## 题目合规性：DeepSeek + LangChain

题目只要求 **Python + LangChain**，没有限定必须使用 OpenAI 或某个固定模型。DeepSeek 作为模型供应商是合规的。

当前 DeepSeek 路径：

```text
provider=deepseek
  → LLMConfig(provider="deepseek", ...)
  → langchain_openai.ChatOpenAI(base_url="https://api.deepseek.com/v1")
  → ChatPromptTemplate
  → with_structured_output(...)
  → LangChainExtractor
```

也就是说，DeepSeek 是通过 **LangChain 的 `ChatOpenAI` 兼容层**调用的，不是绕过 LangChain 直接发 HTTP。DeepSeek 只负责语义抽取；匹配、AR/AP、校验和 operation 决策仍由确定性代码负责。

建议使用：

```text
provider = deepseek
model    = deepseek-chat
base_url = https://api.deepseek.com/v1
```

`deepseek-reasoner` 对 function calling / 结构化输出的支持可能有限，不建议作为默认抽取模型。

验收时建议用 `extract_documents.py --use-llm` 确认真实走了 LangChain：

```powershell
python scripts/extract_documents.py `
  --input data/fixtures/formal_invoice.pdf `
  --out out/deepseek_check `
  --use-llm
```

期望输出包含：

```text
source=llm
```

如果是 `source=rules_fallback`，说明 API/模型/结构化输出调用失败，系统自动回退了规则。

## AI API 配置（首次运行询问）

**首次运行会主动询问使用哪个大模型**，不会静默选择：

1. **使用平台当前 API**（默认项，若检测到 `DEEPSEEK_*`、`OPENAI_*` 或 `ANTHROPIC_*`）；
2. **指定 API**（DeepSeek / OpenAI / Anthropic 三种供应商）；
3. **不使用大模型（规则抽取）**。

选择结果会保存，后续启动不再询问。选择“不使用大模型”后，后续只运行规则抽取，不调用任何 AI API。

```bash
# 查看当前配置和平台检测结果
python scripts/configure_ai.py --show

# 保存平台当前 API
python scripts/configure_ai.py --use-platform

# 明确选择“不使用大模型（规则抽取）”
python scripts/configure_ai.py --no-ai

# 指定 DeepSeek
python scripts/configure_ai.py --provider deepseek \
  --model deepseek-chat \
  --base-url https://api.deepseek.com/v1 \
  --api-key sk-你的key

# 指定 OpenAI
python scripts/configure_ai.py --provider openai \
  --model gpt-4o-mini \
  --base-url https://api.openai.com/v1 \
  --api-key sk-你的key

# 或 Anthropic 兼容
python scripts/configure_ai.py --provider anthropic \
  --model claude-sonnet-5-5 \
  --base-url https://api.anthropic.com \
  --api-key sk-ant-...
```

Streamlit 的 Provider 选项：

```text
deepseek  → deepseek-chat / https://api.deepseek.com/v1
openai    → gpt-4o-mini / https://api.openai.com/v1
anthropic → claude-sonnet-5-5 / https://api.anthropic.com
```

- 配置文件保存在用户目录（`~/.shipping_agent/ai_config.json`，权限 0600），**不写入项目、不进入 zip**；
- `AI_CONFIG_PATH` 可覆盖路径；`python scripts/configure_ai.py --clear` 清除；
- 无交互终端下不会阻塞：未配置时直接使用规则抽取；
- 平台默认在当前环境为 `anthropic` / `deepseek-flash[1M]` / `https://api.deepseek.com/anthropic`，已真实跑通 LangChain 结构化抽取。

启用方式：

```bash
# CLI 抽取（默认读取平台 API）
python scripts/extract_documents.py --input data/fixtures --out out/extract_llm --use-llm

# 最终输出
python scripts/build_output.py --input data/fixtures --out out/final_llm \
  --existing-bills data/fixtures/existing_bills.json --use-llm

# Streamlit：首次运行先弹出 AI API 选择；之后侧边栏可修改
streamlit run app/streamlit_app.py
```

如果模型调用失败（无 key、网络、结构化输出不支持），会自动回退规则抽取，并在结果中写 `LLM_FALLBACK`。LLM 返回的费用名会自动走同一套标准化映射；未确认映射保留原始费用名，`P/C` 与单据级 `PP/CC/COD` 分开，不再把单个 `C` 归一为 `CC`。

## 配置 OCR（真实调用）

当前图片与扫描 PDF 已接入 OCR 链路；文本型 PDF 仍优先本地文字层。真实调用需要两步：

### 1. 探针：确认接口响应

```powershell
python scripts/ocr_probe.py --url https://公网可访问的账单.pdf
```

脚本会按题目给定的 payload 调用 `https://gateway.pltplt.com/ai/process`，保存原始 JSON 到 `out/ocr_probe/`。**先看真实响应结构，再依赖字段路径。**

### 2. 公网文件托管

OCR 服务端必须能下载文件。两种方式：

**A. 本地目录 + 隧道（演示）**

```powershell
python -m http.server 8765 --directory out/ocr_serve
cloudflared tunnel --url http://localhost:8765
# 把 cloudflared 给出的公网地址填入 OCR_FILE_BASE_URL
```

**B. OSS / S3**

把文件上传到对象存储，把公开基址填入 `OCR_FILE_BASE_URL`。

`.env` 示例：

```ini
OCR_ENDPOINT=https://gateway.pltplt.com/ai/process
OCR_TASK=orderChange
OCR_TASK_TYPE=
OCR_FILE_BASE_URL=https://你的隧道或对象存储地址
OCR_SERVE_DIR=out/ocr_serve
# 直接 PNG 实测 504；默认先把图片转成单页 PDF 再提交
OCR_IMAGE_AS_PDF=1
# api 模式下 PDF 先尝试 OCR；OCR 返回空/失败时回退本地文字层
OCR_PDF_FIRST=1
# 公网 URL 输入时，每个 URL 的 OCR 最长等待时间（秒），超时后本地/视觉兜底
URL_OCR_TIMEOUT=60
# mock/local/api 都没有识别出图片内容时，最后用视觉模型兜底（结果强制复核）
VISION_FALLBACK=1
# 可选：显式视觉模型。协议默认从 base_url 推断；
# Anthropic 兼容用 /v1/messages，OpenAI 兼容用 /chat/completions。
# VISION_BASE_URL=https://api.deepseek.com/anthropic
# VISION_MODEL=deepseek-flash[1M]
# VISION_API_KEY=
# VISION_PROTOCOL=anthropic
#
# 也可以复用首次运行保存的 API（Anthropic / OpenAI / DeepSeek）：
#   python scripts/configure_ai.py --show
```

> 实测：`task=orderChange` 对 PDF 返回 200，对直接 PNG 返回 504。因此 `api` 模式默认先把图片包成单页 PDF；如接口后续支持图片，可设 `OCR_IMAGE_AS_PDF=0`。

运行：

```powershell
python scripts/parse_documents.py --input 资料 --out out/ocr --ocr-mode api
python scripts/build_output.py --input 资料 --out out/ocr_final --ocr-mode api
```

- `--ocr-mode mock`：离线，不调用 API；
- `--ocr-mode local`：文本型 PDF 本地解析；
- `--ocr-mode api`：PDF 页面优先 OCR，OCR 空/失败时回退本地文字层；图片 OCR 缺少 `OCR_FILE_BASE_URL` 时，若视觉兜底已配置（`VISION_*`、平台 `ANTHROPIC_*` 或首次运行保存的 API）则跳过 OCR 直接用视觉模型，否则报 `OCR_URL_REQUIRED`，UI 会显示为可读错误而不是崩溃。mock / local / api 都没有识别出图片内容时，最后都会尝试视觉模型，结果强制复核。

## 目录

```
src/shipping_agent/
  models/
    types.py        # Money / Currency / ISODate / quantize_money
    base.py         # StrictModel (extra="forbid")
    bundle.py       # DocumentBundle 等解析中间表示
    candidate.py    # RawChargeLine / SourcePosition
    output.py       # 输出模型（full + strict）
  io/
    detect.py       # 魔数格式识别
    eml_parser.py   # EML 正文 + 递归附件
    pdf_parser.py   # 文字层 + 坐标行重建 + 表格检测
    excel_parser.py # 多 sheet / 表头 / 列映射
    word_parser.py  # 正文 + 表格
    image_parser.py # OCR（mock）
    text_parser.py  # HTML / CSV / TXT
    ocr_client.py   # OCR 客户端（mock / HTTP）
    dispatcher.py   # 按类型分发
  candidates/
    columns.py      # 表头 → 字段映射
    builder.py      # 表格行 / 文本行 → candidate
  business/
    charge_mapper.py    # 费用名标准化（YAML）
    document_class.py   # 文档类型 / billing_status / 交易方规则
    repository.py       # 已有账单适配 + 索引
    matcher.py          # strict 四级 + enhanced
    ar_ap.py            # 四层 AR/AP
    duplicate.py        # 安全去重
    decision.py         # CREATE / UPDATE / NO_CHANGE / PENDING_REVIEW
    assembler.py        # 组装最终 OutputRecord
    totals.py           # subtotal / tax / total 抽取
    pipeline.py         # 端到端 P2/P3 流水线
  extract/
    models.py           # 分类 / 费用 / 变更意图模型
    rules.py            # 规则抽取基线
    change_intent.py    # 明确变更意图
    evidence.py         # 证据 grounded 校验
    prompts.py          # LangChain 提示词
    llm.py              # ChatOpenAI 配置
    langchain_extractor.py
    orchestrator.py     # LLM 失败回退规则
    cli.py              # 抽取 CLI
  output/serializer.py   # full / strict 序列化
  validate/rules.py      # 金额/币种/合计/OCR 混淆校验
  validate/schema.py     # JSON Schema 生成与校验
  evaluation.py          # golden 评测指标
  golden_cases.py        # golden 样本映射
  examples.py            # 可复用的示例记录
  ui_service.py          # UI 服务层（无 streamlit 依赖）
  cli.py                 # 解析入口

app/streamlit_app.py     # Streamlit 演示
.streamlit/config.toml   # 上传大小 / 主题

tests/                   # P0 测试
schemas/                 # 生成的 JSON Schema
data/fixtures/           # 合成测试数据（PDF / Excel / Word / 历史账单）
data/samples/            # 原始样本副本（公开仓库已移除）
data/golden/expected/    # 9 个 full JSON 快照 + review_notes.md
scripts/                 # 生成/校验/演示脚本
docs/                    # 方案、决策、追溯矩阵、OCR 能力
```

## 输出示例（strict）

```json
[
  {
    "operation": "PENDING_REVIEW",
    "document_info": {
      "document_type": "PRE-ALERT",
      "reference_no": "PREALERT-DEMO-001",
      "document_date": "2026-10-20"
    },
    "transaction_party": {"issuer": null, "recipient": null},
    "charge_details": {
      "charge_item": "Handling Charge",
      "amount": 50.00,
      "currency": "USD",
      "payment_term": null
    },
    "financial_attributes": {
      "accounting_entity": "Importer Beta (Shanghai)",
      "posting_type": null
    },
    "audit_trail": {"ai_reasoning": ["..."]}
  }
]
```

## 设计要点

- **数字由代码负责**：金额、合计、匹配、AR/AP 由确定性代码完成；LLM 只做语义判断（P1+）。
- **strict / full 分离**：strict 逐字对齐题目标准输出；full 保留审计信息。
- **严格 schema**：业务对象 `extra="forbid"`；`AuditTrail` 也是显式字段模型，不允许运行时新增。
- **文档性质分层**：PRE-ALERT、General Notice、B/L 不会直接 CREATE；详见 `docs/PLAN.md` §8.6。
- **匹配双模式**：`strict` 逐字按原文四级；`enhanced` 在未命中时识别金额/费用名变更。

## 当前限制

- LangChain 抽取已用平台 Anthropic 兼容 API 真实跑通；也支持自定义 OpenAI/Anthropic API。默认仍使用规则抽取，除非勾选 `--use-llm`。
- 视觉兜底已用平台 `deepseek-flash[1M]`（Anthropic 兼容）和首次运行保存的 DeepSeek `deepseek-chat`（OpenAI 兼容）真实跑通；它走 HTTP 视觉接口，不是 LangChain 抽取入口。结果强制 `PENDING_REVIEW`。
- OCR 真实探针已执行：图片型 PDF `sample_carrier.pdf` 成功；文字型 PDF1/PDF2 和直接 PNG 返回 `data.list=[]`；图片需要先转单页 PDF。
- `.doc` 解析优先用 LibreOffice；没有 LibreOffice 时使用内置 Word 97 OLE/piece-table 文本解析。Word COM 仅在 `DOC_WORD_COM=1` 时启用（部分环境会弹窗阻塞）。
- `data/fixtures/` 为合成测试数据，不是真实业务单据。
- `data/samples/` 与 `data/fixtures/sample_prealert.eml` 属于真实/业务样例，公开仓库已移除；依赖它们的测试会自动 skip。
- `dist/shipping-bill-agent.zip` 已重建，包含最新的 `COMPARISON.md`、`OCR_vs_MANUAL.md`、`COMPLETION_AUDIT.md`、`EVALUATION_NOTES.md` 和 `COMPARISON_METHOD.md`。

## 文档

- [docs/PLAN.md](docs/PLAN.md)：完整实施方案
- [docs/DECISIONS.md](docs/DECISIONS.md)：业务与技术思考（12 点）
- [docs/requirements_traceability.md](docs/requirements_traceability.md)：需求追溯矩阵
- [docs/OCR_CAPABILITY.md](docs/OCR_CAPABILITY.md)：OCR 能力矩阵与真实探针记录
- [docs/BUSINESS_RULES.md](docs/BUSINESS_RULES.md)：四份样本与账务规则落地说明
- [docs/OCR_vs_MANUAL.md](docs/OCR_vs_MANUAL.md)：OCR 结果与人工/本地识别结果逐字段对比
- [docs/COMPARISON.md](docs/COMPARISON.md)：OCR / 本地解析 / 视觉模型三方对比
- [docs/COMPARISON_METHOD.md](docs/COMPARISON_METHOD.md)：23/24 的真值、模型配置、字段口径与限制
- [docs/EVALUATION_NOTES.md](docs/EVALUATION_NOTES.md)：100% 回归、59% 复核率的解释
- [docs/COMPLETION_AUDIT.md](docs/COMPLETION_AUDIT.md)：完成度审计与缺口

## 交付

- 交付包：`dist/shipping-bill-agent.zip`
- 一键验证：`powershell -File run_demo.ps1`（或按 Quick Start 逐条执行）
- 提交邮箱：`LUKA@PLTPLT.COM`、`pan@pltplt.com`
- 邮件标题：`应聘渠道+姓名+应聘岗位`
