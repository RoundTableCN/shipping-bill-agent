# Fixtures（合成测试数据）

这些文件是为验证系统能力而**人工合成**的测试数据，不是真实业务单据。

## 文件与预期

| 文件 | 单据编号 | 用途 | 预期 operation |
|---|---|---|---|
| `formal_invoice.pdf` | INV-FIXTURE-001 | 与 `BILL-FIX-001` 完全一致 | `NO_CHANGE` |
| `formal_invoice_revised.pdf` | INV-FIXTURE-001 (R1) | Handling 65 → 80，并带明确更正说明 | `UPDATE` |
| `formal_invoice_create.pdf` | INV-FIXTURE-003 | 无历史匹配 | `CREATE` |
| `charges.xlsx` | STMT-FIXTURE-001 | Excel 表头/多币种/合计行 | `CREATE`（或按 statement 状态复核） |
| `statement.docx` | STMT-FIXTURE-002 | Word 正文 + 表格 + BALANCE DUE | `CREATE`（statement/confirmed） |
| `existing_bills.json` | — | 历史账单，供匹配/去重/AR-AP | 参考数据 |

## 关键字段

- Issuer：CARRIER ALPHA LIMITED
- Accounting entity / Payer：IMPORTER BETA (SHANGHAI)
- Payee / Beneficiary：CARRIER ALPHA LIMITED
- Master B/L：MAEU888777666
- House B/L：CGT260888888
- Booking：CGTSE260888888
- Containers：FIXU1234567, FIXU7654321
- `formal_invoice_create.pdf` 使用独立标识：MAEU999888777 / CGT260999999 / CGTSE260999999 / TGHU1234567

## 覆盖场景

1. **CREATE**：`formal_invoice_create.pdf`（INV-FIXTURE-003）
   - 使用独立的 B/L / booking / container：`MAEU999888777` / `CGTSE260999999` / `TGHU1234567`
   - 避免被 strict L2/L3/L4 误匹配到 `BILL-FIX-001`
2. **NO_CHANGE**：`formal_invoice.pdf` 对 `BILL-FIX-001`
3. **UPDATE**：`formal_invoice_revised.pdf` 对 `BILL-FIX-001`
   - 更正证据：`CORRECTION: HANDLING CHARGE AMOUNT REVISED FROM USD 65.00 TO USD 80.00`
4. **一对一匹配**：`BILL-FIX-002` 有两条同额同名 Handling 35
5. **Excel**：表头在第 4 行（第 3 行故意留空）、多币种、按币种合计
6. **Word**：正文 + 表格 + `BALANCE DUE`，用于 `billing_status=confirmed` 判定
7. **AR/AP**：Bill To/Payer 与 Payee/Beneficiary 明确，便于验证资金流判断

## 注意

- PDF 为**文字型**（非扫描件）。离线模式可用本地文本解析；真实 OCR 测试需把文件托管到公网 URL 后调用 OCR API。
- `formal_invoice_revised.pdf` 与 `formal_invoice.pdf` 使用同一 `reference_no`，靠 `REVISION` 和更正说明区分版本。
- `existing_bills.json` 的金额为 JSON number；适配层应转换为 `Decimal`。
