# OCR 能力矩阵与探针记录

> 对应方案 §5.4 / §5.5。
> 状态：**2026-11-12/13 已执行真实探针与路由复检**。接口连通、同步返回、`data.list[]` 业务字段结构已验证；CARRIER 图片型 PDF 已返回 2 条 `chargeList` 费用（发票号/箱号/B/L 可识别），但 currency/date/total/交易方仍缺失。文字型 PDF1/PDF2 和直接 PNG 返回 `data.list=[]`；PDF 已改为 OCR-first + 本地文字层回退。

## 0. 当前实现状态

- 探针脚本：[scripts/ocr_probe.py](../scripts/ocr_probe.py) 已实现并执行；
- HTTP client：[src/shipping_agent/io/ocr_client.py](../src/shipping_agent/io/ocr_client.py) 已实现重试、原始响应保留、业务字段读取；
- 公网托管：[src/shipping_agent/io/file_hosting.py](../src/shipping_agent/io/file_hosting.py) 的 `LocalHttpHosting` 支持"本地目录 + 隧道/对象存储"；
- 接线：图片与扫描 PDF 已接入 OCR；CLI / Streamlit 根据 `--ocr-mode api` 构建 client 与 hosting；
- 真实响应：`data.list[].chargeList` 会转成表格，`data.list[].fileType/mblNumber/...` 会转成文本；`data.list[].ctrList` 暂不建表；
- 图片兼容路径：OSS 直接 PNG 实测 200 但 `data.list=[]`；部分不可达/无后缀 URL 曾 504；图片在 `api` 模式下默认先转成单页 PDF 再提交（`OCR_IMAGE_AS_PDF=1`）。

---

## 1. 接口契约（题目原文）

```python
url = "https://gateway.pltplt.com/ai/process"
data = {
    "file": file_url,        # OCR 服务端可访问的 PDF/图片 URL
    "task": "orderChange",
    "callBack": "",
    "taskType": "",
}
response = requests.post(url, json=data, timeout=(10, 300))
response.raise_for_status()
ocr_result = response.json()
```

---

## 2. 能力矩阵

| # | 能力 | 状态 | 探针结论 | 影响 |
|---|---|---|---|---|
| 1 | `task="orderChange"` 适用于账单 | **已验证** | HTTP 200，`success=true`，`message=文档处理成功` | 请求参数可用 |
| 2 | `taskType=""` 合法 | **已验证** | 未报错，正常返回 | 可保持空值 |
| 3 | 同步直接返回结果 | **已验证** | 约 17.86s 返回；`task_id=null` | 不需要轮询 |
| 4 | 异步返回 `task_id` 时有轮询接口 | **不适用** | 本次为同步；未见轮询接口 | 暂不实现轮询 |
| 5 | 返回表格结构 | **已验证（业务表格）** | 不返回通用 `text/tables`；返回 `data.list[].chargeList`。图片型 PDF 成功返回 2 条费用：`chargeItem` / `amount` / `chargeCtr` | 字段名已确认；无 currency 字段 |
| 6 | 返回 bbox / 置信度 | **未返回** | 响应中无 bbox/confidence | 证据只能到文件/页级，不能到坐标 |
| 7 | PDF 支持多页 | **已验证** | 3 页 PDF 被接受；返回 `data.pages_split`、`data.list[].page_index` | 多页可处理 |
| 8 | 文件大小 / 页数限制 | **未验证** | 本次仅 3 页 | 仍需边界测试 |
| 9 | 直接图片（PNG）支持 | **不识别（200 但 list 空）** | 阿里云 OSS PNG：200 / 4.33s，`data.list=[]`；同一图片转 PDF 后识别成功 | 图片必须转单页 PDF 后提交 |
| 10 | 图片转 PDF 后 OCR | **已验证** | `sample_carrier.pdf`（图片型 PDF）→ 200 / 11.96s；`fileType=PAI-CARRIER-NOTICE`；2 条 `chargeList` | 推荐图片统一走此路径 |
| 11 | 文字型 PDF 识别 | **不识别（200 但 list 空）** | PDF1 General Notice 200 / 3.83s、PDF2 Debit Note 200 / 3.91s，均 `data.list=[]` | 文字型 PDF 用本地文字层解析 |

### 2.1 路由策略（`--ocr-mode api`）

| 输入 | 优先方式 | 回退 |
|---|---|---|
| PDF（有文字层） | 先按页调用 OCR（`OCR_PDF_FIRST=1`） | OCR 空/失败 → 本地文字层 |
| PDF（扫描/图片型） | OCR | OCR 失败 → 本地文字层（通常为空）+ 警告 |
| JPG/PNG/TIFF | OCR（先转单页 PDF） | mock/local/api 都没有识别出内容 → 自动用视觉模型最终兜底（默认开启，`VISION_FALLBACK=0` 可关闭），支持 Anthropic 兼容和 OpenAI 兼容端点（含首次运行保存的 DeepSeek），结果强制 `PENDING_REVIEW` |
| 公网 URL（PDF/图片） | OCR API 直接抓取原始 URL，每个 URL 默认 60s 超时 | OCR 空/失败/超时 → 本地 PDF 文字层 → 视觉模型兜底 |
| 公网 URL（EML/Excel/Word） | 下载后本地解析 | 这类文件不走 OCR API；解析失败进入复核/错误提示 |
| EML/Excel/DOCX | 本地解析 | 附件按实际格式递归解析 |
| DOC | LibreOffice 转 DOCX 后本地解析 | 无 LibreOffice → 内置 Word 97 OLE/piece-table 文本解析 |
| 已有账单 JSON | `--existing-bills` 适配 | — |

`OCR_PDF_FIRST=0` 可恢复“文字型 PDF 本地优先、仅扫描页走 OCR”的旧行为。

图片最终兜底的模型解析顺序：

1. 显式 `VISION_*`（可用 `VISION_PROTOCOL=anthropic|openai` 指定协议）；
2. 平台 `ANTHROPIC_*`；
3. 首次运行保存的 API（Anthropic / OpenAI / DeepSeek）；
4. 都没有 → 不调用大模型，报告 `OCR_URL_REQUIRED` 或 `VISION_FALLBACK_UNAVAILABLE`。

2026-11-18 实测：首次运行保存的 DeepSeek `deepseek-chat` 走 OpenAI 兼容 `/chat/completions`，对 `data/samples/sample_carrier_invoice.png` 返回 2 条费用、合计 26.90；结果 2 条 `PENDING_REVIEW`。

### 2.2 2026-11-10 图片对照实验

| URL | 类型 | 结果 |
|---|---|---|
| `https://img.remit.ee/i/IHLFss23qAvL` | PNG 92KB，服务端返回 `application/octet-stream` | **504 Gateway Time-out**；重试 300s 读超时 |
| `https://placehold.co/600x400.png` | 标准 PNG | **504 Gateway Time-out** |
| `https://loremfile.dev/pdf/a4-3pages.pdf` | 3 页 PDF，`application/pdf`，`.pdf` 后缀 | **200 success**，55.30s |
| `https://img.remit.ee/i/v77KEGbxVuTz` | Debit Note PDF，`application/octet-stream`，无 `.pdf` 后缀 | **504** |
| `https://img.remit.ee/i/joAepNNwbZvd` | General Notice PDF，`application/octet-stream`，无 `.pdf` 后缀 | **504** |
| `https://drive.usercontent.google.com/download?id=...&export=download` | PNG 91,964 字节，`image/png`（Google Drive `/view` 不是直链） | **504** |
| localtunnel 临时 URL → `sample_carrier.pdf` | 单页图片 PDF，1.57MB；本机 GET 200 `application/pdf` | **504** |
| localtunnel 临时 URL → `sample_debit_note.pdf` | 文字型 PDF2；本机 GET 200 | **504** |
| 阿里云 OSS 签名 URL → `PDF 示例账单2.pdf` | 文字型 Debit Note PDF；`application/pdf` | **200 / success / 3.91s，但 `data.list=[]`** |
| 阿里云 OSS 签名 URL → `sample_carrier.pdf` | 图片型单页 PDF，1.57MB | **200 / success / 11.96s；fileType=PAI-CARRIER-NOTICE；chargeList 2 条** |
| 阿里云 OSS 签名 URL → `图片示例.png` | PNG，91,964 字节，`image/png` | **200 / success / 4.33s，但 `data.list=[]`** |
| 阿里云 OSS 签名 URL → `PDF示例账单1.pdf` | 文字型 General Notice PDF；`application/pdf` | **200 / success / 3.83s，但 `data.list=[]`** |

结论：

1. 该 `task=orderChange` 对 PDF 可用；直接 PNG 在 OSS 上返回 200 但 `data.list=[]`，即**不识别直接图片**；同一图片转成 PDF 后识别成功；
2. `img.remit.ee` 上的 PDF 也 504，原因可能是 OCR 网关访问不到该域名，或该 URL 没有 `.pdf` 后缀、Content-Type 为 `application/octet-stream`；
3. **阿里云 OSS 已解决网络可达性**：签名 URL 返回 200 / success / 3.91s；但 Debit Note 的 `data.list=[]`，说明 `task=orderChange` 没有识别出这份单据（可能只支持特定单据类型/版式，或只支持扫描件/图片型 PDF）；
4. 图片必须转**图片型/扫描型 PDF**（如 `sample_carrier.pdf`）再提交；文字型 PDF2 服务端返回空列表；`taskType=DEBIT_NOTE` 也返回空；
4. 代码已默认把图片包成单页 PDF 再提交；如后续接口支持图片，可设 `OCR_IMAGE_AS_PDF=0`。

---

## 3. 探针执行步骤

```bash
python scripts/ocr_probe.py --url <public-pdf-or-image-url>
```

脚本会：

1. 发送题目给定的原始 payload；
2. 打印 HTTP 状态、响应头、耗时；
3. 保存原始 JSON 到 `out/ocr_probe/<timestamp>.json`；
4. 不截断、不重排、不做字段猜测。

---

## 4. 真实响应结构（2026-11-10）

顶层：

```json
{
  "data": {},
  "success": true,
  "message": "文档处理成功",
  "error_code": null,
  "task_id": null
}
```

`data`：

```json
{
  "createDate": "2026-11-10 17:31:37",
  "fileName": "",
  "list": [
    {
      "fileType": "PAI-COLOADER-NOTICE",
      "mblNumber": "",
      "shipper": "",
      "consignee": "",
      "invoiceNumber": "",
      "customsClearance": "",
      "ctrList": [],
      "chargeList": [],
      "page_index": [0, 3],
      "suspicious": "N",
      "isDetention": "N",
      "isDemurrage": "N"
    }
  ],
  "orderType": "None",
  "pages_split": [[0, 3]]
}
```

关键结论：

- **不是通用 OCR 的 `text/tables` 响应**，而是航运业务字段 JSON；
- `fileType` 是 OCR 服务自己的文档分类（本次 lorem 样本被归为 `PAI-COLOADER-NOTICE`）；
- 费用在 `data.list[].chargeList`，lorem 样本没有费用，所以为空；
- 箱号在 `data.list[].ctrList`；
- `page_index` / `pages_split` 可用于页级定位；
- 没有 bbox、置信度。

### 4.1 图片型 PDF 成功响应（2026-11-12）

`sample_carrier.pdf` → 200 / 11.96s：

```json
{
  "fileType": "PAI-CARRIER-NOTICE",
  "invoiceNumber": "INV-DEMO-001",
  "mblNumber": "CGTSE260888888",
  "ctrList": [
    {"ctrNumber": "FIXU7654321"}
  ],
  "chargeList": [
    {"chargeItem": "WHARFAGE ADMINISTRATION FEE", "amount": "5.00", "chargeCtr": ""},
    {"chargeItem": "WHARFAGE", "amount": "21.90", "chargeCtr": ""}
  ],
  "orderType": "ANR_LLM_CARRIER-INVOICE",
  "page_index": [0, 1]
}
```

重要限制：

- `chargeList` **没有 currency 字段**；
- 没有 payer / invoiceDate / total；
- 因此真实 OCR 结果进入 Agent 后：
  - 能生成 2 条候选费用（5.00 / 21.90）；
  - currency、payer 缺失；
  - 校验 `W_CURRENCY_MISSING`；
  - AR/AP 无法确认 → `PENDING_REVIEW`；
  - **不会伪造 USD 或付款义务**。

真实运行结果（`scripts/run_ocr_url.py`）：

```text
REAL OCR — fileType=PAI-CARRIER-NOTICE
structured=1 candidates=2
records=2
  PENDING_REVIEW 'Wharfage Administration Fee' 5.00 None posting=None validation=REVIEW
  PENDING_REVIEW 'Wharfage'                  21.90 None posting=None validation=REVIEW
output: out/real_ocr/sample_carrier_invoice.json
```

真实响应已保存为 [data/fixtures/ocr_real_CARRIER.json](../data/fixtures/ocr_real_CARRIER.json)，并由 [tests/test_real_ocr_fixture.py](../tests/test_real_ocr_fixture.py) 覆盖。

---

## 5. 当前实现门禁

已实现：

- `ocr_client.py`：请求 + 超时 + 3 次重试 + 原始响应保留；
- 已知 `data.text/tables` 路径；
- 真实业务字段路径：`data.list[].fileType/mblNumber/shipper/consignee/invoiceNumber` 转文本；
- `data.list[].chargeList`（字典列表）转 `TableBlock`，列名使用原始 key；
- mock 模式与离线测试。

**不实现**：

- 轮询任务（本次同步）；
- bbox/置信度依赖（响应未返回）；
- 对 `chargeList` 字段名的硬编码假设（等真实账单探针确认）。

---

## 6. 变更记录

| 日期 | 操作 | 结果 |
|---|---|---|
| 2026-11-05 | 创建文档 | 探针未执行 |
| 2026-11-10 | 首次真实探针：`https://loremfile.dev/pdf/a4-3pages.pdf` | 200 / success / 17.86s；返回 `data.list[]` 业务结构；`fileType=PAI-COLOADER-NOTICE`；`chargeList=[]` |
| 2026-11-10 | 直接 PNG 对照：`img.remit.ee/...`、`placehold.co/...` | 均 504 / 超时；确认直接图片不稳定 |
| 2026-11-10 | PDF 对照复测：lorem 3 页 PDF | 200 / success / 55.30s；服务本身正常 |
| 2026-11-10 | remit.ee 两份真实 PDF 探针 | 均 504；URL 无 `.pdf` 后缀且 Content-Type 为 octet-stream；需换可访问托管 |
| 2026-11-10 | Google Drive 直链 PNG 探针 | 504；直链为 `image/png`，仍不稳定；直接图片路径不可依赖 |
| 2026-11-10 | localtunnel 临时 PDF 探针 | 本机 GET 200；OCR 网关仍 504（图片 PDF 与文字 PDF 都失败）；隧道已关闭，端口已释放 |
| 2026-11-12 | 阿里云 OSS 签名 URL（Debit Note PDF2） | 200 / success / 3.91s；`data.list=[]`；网络可达，但该任务未识别此单据 |
| 2026-11-12 | 同一 OSS URL + `taskType=DEBIT_NOTE` | 200 / 3.06s；仍 `data.list=[]`；taskType 未改变结果 |
| 2026-11-12 | OSS 图片型 PDF `sample_carrier.pdf` | **200 / success / 11.96s**；`fileType=PAI-CARRIER-NOTICE`；`chargeList` 2 条；真实 OCR 成功 |
| 2026-11-12 | OSS 直接 PNG `图片示例.png` | 200 / success / 4.33s；`data.list=[]`；直接图片不识别，转 PDF 后才成功 |
| 2026-11-12 | OSS 文字型 PDF1 `PDF示例账单1.pdf` | 200 / success / 3.83s；`data.list=[]`；文字型 PDF 不识别 |
| 2026-11-12 | 真实 OCR → Agent（`scripts/run_ocr_url.py`） | 2 候选费用；2 条 `PENDING_REVIEW`；currency/payer 缺失，未伪造 |

---

## 7. 下一步验证

用更多**真实航运账单**的公网 URL 再跑探针，重点确认：

1. `chargeList` 是否始终只有 `chargeItem`/`amount`，还是部分单据返回 currency/paymentTerm；
2. `ctrList` 的结构；
3. 多页账单是否每页一个 `list` 元素，还是合并；
4. `fileType` 的完整枚举；
5. 日期、币种、合计、交易方是否有对应字段。

当前 `ocr_client.py` 已按“字典列表 → 表格 → 候选费用行”做了通用映射；CARRIER 图片型 PDF 的 `chargeItem`/`amount` 已确认，其他字段仍按缺失处理，不猜测。

---

## 8. 手工 OCR fixture（真实公网 URL 不可用时的替代）

- Fixture：[data/fixtures/ocr_mock_CARRIER.json](../data/fixtures/ocr_mock_CARRIER.json)
- 脚本：[scripts/run_manual_ocr.py](../scripts/run_manual_ocr.py)
- 内容：按 CARRIER 图片人工整理成 `data.list[].chargeList` 业务结构（不是真实 OCR 返回）
- 运行：

```powershell
python scripts/run_manual_ocr.py
```

- 结果：2 条费用，`CREATE` ×2，`AP`，`validation=PASS`，输出 [out/manual_ocr/sample_carrier_invoice.json](../out/manual_ocr/sample_carrier_invoice.json)
- 作用：验证 OCR **之后**的 `chargeList → 候选费用 → 抽取 → AR/AP → JSON` 链路；
- **限制**：不能证明真实 OCR 服务识别出了这些字段，真实账单探针仍待执行。
