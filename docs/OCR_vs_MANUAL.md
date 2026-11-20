# OCR 结果 vs《识别结果_样例账单.md》对比

> 对比对象：
> - 人工/本地解析结果：[识别结果_样例账单.md](../识别结果_样例账单.md)
> - OCR 真实调用结果：2026-11-12 18:16 对用户提供的 4 个 OSS URL 重新探针
>
> 结论先行：**两份结果不是同一种识别方式**。`识别结果_样例账单.md` 的 PDF 数据来自本地文字层解析，CARRIER 截图字段来自人工读图；OCR 只对 `sample_carrier.pdf`（图片型 PDF）返回了业务字段，对两份文字型 PDF 和直接 PNG 都返回了 `data.list=[]`。

---

## 1. 本次 OCR 探针结果

| 文件 | URL 对应 | HTTP | 耗时 | `data.list` | 关键返回 |
|---|---|---:|---:|---|---|
| PDF示例账单1.pdf | 用户提供的 OSS URL | 200 | 2.97s | `[]` | `orderType=None`，`pages_split=[]` |
| PDF 示例账单2.pdf | 用户提供的 OSS URL | 200 | 3.44s | `[]` | `orderType=None`，`pages_split=[]` |
| 图片示例.png | 用户提供的 OSS URL | 200 | 3.82s | `[]` | 直接 PNG 不识别 |
| sample_carrier.pdf | 用户提供的 OSS URL | 200 | 11.51s | 1 条 | `fileType=PAI-CARRIER-NOTICE`，`chargeList` 2 条 |

原始响应已保存：

```text
out/ocr_probe_20261112/probe-20261112-181631.json   # PDF1
out/ocr_probe_20261112/probe-20261112-181635.json   # PDF2
out/ocr_probe_20261112/probe-20261112-181639.json   # PNG
out/ocr_probe_20261112/probe-20261112-181651.json   # sample_carrier.pdf
```

---

## 2. 文件 1：PDF 示例账单2.pdf

### 人工/本地解析结果

- 单据类型：Debit Note
- 编号：DN-DEMO-002
- 日期：2026-10-24
- 提单号：MAEU275752922
- 箱号：TGHU1234567、FIXU7654321
- 币种：USD
- 付款方式：CC
- 合计：1,410.40
- 费用：HANDLING CHARGE 65.00 / 4 ADD'L DETENTION FREE TIME CHARGE 1,310.40 / HANDLING CHARGE 35.00
- 操作：PENDING_REVIEW

### OCR 结果

```json
{
  "data": {
    "list": [],
    "orderType": "None",
    "pages_split": []
  },
  "success": true,
  "message": "文档处理成功"
}
```

### 差异

| 字段 | 人工/本地解析 | OCR | 差异 |
|---|---|---|---|
| 单据类型 | Debit Note | 空 | OCR 未识别 |
| 编号 | DN-DEMO-002 | 空 | OCR 未识别 |
| 日期 | 2026-10-24 | 空 | OCR 未识别 |
| 费用 | 3 条 | 0 条 | OCR 未识别 |
| 币种/合计 | USD / 1,410.40 | 空 | OCR 未识别 |

**结论**：这份文字型 PDF 的字段完全来自本地文字层解析，OCR 没有提供任何可对比字段。不能把这份结果说成“OCR 识别成功”。

---

## 3. 文件 2：PDF示例账单1.pdf

### 人工/本地解析结果

- 单据类型：General Notice
- 编号：BL-DEMO-001
- 日期：2026-10-19
- 箱号：MSCU1234564
- 币种：USD
- 费用：On Carriage Additional 245.00
- 操作：PENDING_REVIEW

### OCR 结果

```json
{
  "data": {
    "list": [],
    "orderType": "None",
    "pages_split": []
  },
  "success": true,
  "message": "文档处理成功"
}
```

### 差异

| 字段 | 人工/本地解析 | OCR | 差异 |
|---|---|---|---|
| 单据类型 | General Notice | 空 | OCR 未识别 |
| 编号 | BL-DEMO-001 | 空 | OCR 未识别 |
| 日期 | 2026-10-19 | 空 | OCR 未识别 |
| 费用 | 1 条 245.00 | 0 条 | OCR 未识别 |

**结论**：与 PDF2 相同，OCR 对这份文字型 PDF 返回空列表；所有字段来自本地解析。

---

## 4. 文件 3：CARRIER 账单截图

### 4.1 OCR 对直接 PNG 的结果

`图片示例.png`：HTTP 200，3.82s，`data.list=[]`。

**直接 PNG 不被该 OCR 接口识别。**

### 4.2 OCR 对 sample_carrier.pdf（图片型 PDF）的结果

```json
{
  "fileType": "PAI-CARRIER-NOTICE",
  "invoiceNumber": "INV-DEMO-001",
  "mblNumber": "CGTSE260888888",
  "ctrList": [{"ctrNumber": "FIXU7654321"}],
  "chargeList": [
    {"chargeItem": "WHARFAGE ADMINISTRATION FEE", "amount": "5.00", "chargeCtr": ""},
    {"chargeItem": "WHARFAGE", "amount": "21.90", "chargeCtr": ""}
  ],
  "orderType": "ANR_LLM_CARRIER-INVOICE",
  "page_index": [0, 1]
}
```

### 4.3 与人工读图结果的逐字段对比

| 字段 | 人工读图 | OCR（sample_carrier.pdf） | 一致性 |
|---|---|---|---|
| 单据类型 | Invoice / Debit Invoice | `PAI-CARRIER-NOTICE` | 原始分类不同；需映射，不能直接相等 |
| 发票编号 | INV-DEMO-001 | INV-DEMO-001 | **一致** |
| 发票日期 | 2025-10-03（旁边另有 10/09/2025） | 未返回 | OCR 缺失 |
| 币种 | USD | 未返回 | OCR 缺失 |
| 合计 | 26.90 | 未返回 | OCR 缺失 |
| 费用 1 | WHARFAGE ADMINISTRATION FEE / 5.00 | 同名 / 5.00 | **一致** |
| 费用 2 | WHARFAGE / 21.90 | 同名 / 21.90 | **一致** |
| 箱号 | FIXU7654321 | FIXU7654321 | **一致** |
| B/L / 订舱号 | CGTSE260888888 | `mblNumber=CGTSE260888888` | **一致** |
| 签发方 | CARRIER American Integrated Shipping Services Co., LLC | 空 | OCR 缺失 |
| 收件方 | EXAMPLE FORWARDING INC. | `consignee=""` | OCR 缺失 |
| 付款人标签 | PAYER-DEMO-01 | 未返回 | OCR 缺失 |
| 付款条件 | PAY IMMEDIATELY | 未返回 | OCR 缺失 |
| 数量/单价 | Rate 5.00 / 2.85；数量未明示 | 未返回 | OCR 缺失 |
| PP/CC | 未明确 | 未返回 | OCR 缺失 |
| 起运地/目的地 | NINGBO (ZJ) / PORT EVERGLADES (FL) | 未返回 | OCR 缺失 |

**一致项（逐字段计数）**：
- 发票号 1 个字段；
- B/L 1 个字段；
- 箱号 1 个字段；
- 费用 1 的名称 + 金额 2 个字段；
- 费用 2 的名称 + 金额 2 个字段。

合计 **7 个标量字段**；若按业务项计，则是 **5 项**（发票号、B/L、箱号、费用 1、费用 2）。不再使用与表格不一致的笼统计数。
**OCR 独有**：`fileType`、`orderType`、`page_index`、`ctrList` 结构。
**人工独有**：日期、币种、合计、签发方/收件方、付款人、付款条件、起运地/目的地、数量/单价。

---

## 5. 关键差异总结

### 5.1 识别方式不同

| 项目 | 《识别结果_样例账单.md》 | OCR API |
|---|---|---|
| PDF1/PDF2 | 本地文字层解析 | 返回空 |
| PNG | 人工读图 | 直接 PNG 返回空 |
| sample_carrier.pdf | 人工读图 | 返回业务字段 |
| 费用标准化 | 已有标准名/映射 | 只有原始 `chargeItem` |
| 证据粒度 | 行级文本/人工观察 | 文件级 + `page_index`，无 bbox/confidence |

### 5.2 OCR 的强项

- 对 **图片型/扫描型 PDF** 可以识别出：
  - 发票号；
  - MBL/B/L；
  - 箱号；
  - 费用名与金额；
  - 业务单据类型 `fileType`；
  - `orderType` 和页码。
- 对 CARRIER 这份单据，OCR 的费用金额与人工读图**完全一致**。

### 5.3 OCR 的缺口

- 不返回日期、币种、合计；
- 不返回签发方/收件方、付款人、付款条件；
- 不返回数量/单价；
- 不返回 bbox/置信度；
- 两份文字型 PDF 和直接 PNG 均返回空；
- `fileType` 是 OCR 自己的业务分类（`PAI-CARRIER-NOTICE`），不等于题目要求的 `document_type`，需要映射。

### 5.4 对 Agent 的影响

- **不能把 OCR 空结果当成“没有费用”**：它只说明该接口没识别这份单据。
- 文字型 PDF 应走本地解析；图片型 PDF 走 OCR；直接图片先转单页 PDF。
- OCR 缺币种/日期/交易方时，Agent 不能补猜，应保持 `null` 并进入 `PENDING_REVIEW`。
- 人工读图结果可以作为对照真值，但必须标注“人工/本地解析”，不能标注为 OCR 成功。

---

## 6. 结论

1. **PDF1、PDF2**：OCR 返回空，人工/本地解析结果无法被 OCR 验证；这两份的准确来源是本地文字层解析。
2. **CARRIER 直接 PNG**：OCR 返回空；直接图片不可用。
3. **CARRIER 图片型 PDF**：OCR 成功识别 **5 个业务项 / 7 个标量字段**（发票号、B/L、箱号、费用 1 名称+金额、费用 2 名称+金额），但缺少日期、币种、合计、交易方和付款条件。
4. **两边都一致的地方**：CARRIER 的 `INV-DEMO-001`、`CGTSE260888888`、`FIXU7654321`、`5.00`、`21.90`。
5. **两边不一致/OCR 缺失的地方**：PDF1/PDF2 全部字段、CARRIER 的日期/币种/合计/交易方/付款条件。
6. 因此，当前 Agent 的正确策略是：**多来源合并 + 缺失字段进入复核**，而不是把 OCR 或人工结果单方面当成完整账单。
