# 四份样本与账务规则落地说明

> 依据：四份样本与账务规则总结。原始面试资料未包含在公开仓库中，避免业务数据泄露。
> 目的：说明哪些业务规则已经进入代码，哪些仍需要业务确认。

## 1. 文档门禁

| 文档 | 处理 |
|---|---|
| Invoice / Debit Note / Credit Note | 可作为正式账单候选，但仍需 AR/AP 确认 |
| General Notice / Arrival Notice / PRE-ALERT | notice / tentative，不直接 CREATE/UPDATE |
| Statement | 汇总性文件，不直接 CREATE/UPDATE；审计 `E_DOC_STATEMENT_NOT_POSTABLE` |
| B/L / MBL / HBL | reference，不作为费用入账依据 |

**Debit Note 不自动等于 AP；Credit Note 不自动等于 AR。**

## 2. AR/AP：候选方向 vs 确认方向

- `posting_type`：只写**已确认**的 AR/AP；
- `candidate_posting_type`：弱证据候选，写入 full audit；
- `accounting_status`：`CONFIRMED` / `PENDING_CONFIRMATION`；
- 显式 payer/payee 匹配记账主体 → 确认；
- recipient/issuer 弱匹配 → 只作为 candidate，`posting_type=null`；
- `Debit Note`、`Credit Note`、`P/C`、`COD`、`PAY IMMEDIATELY`、`PAYMENT RECEIVED` 均不能单独决定 AR/AP；
- 费用行 `P/C=C` 保存在 `prepaid_collect_raw`，不再写入 `payment_term`；单据级 `Terms=COD` 才写入 `payment_term`；
- `PAY IMMEDIATELY` 保存在 `payment_due_instruction`，不进入 PP/CC/COD 枚举；
- 没有历史账单库时，CREATE/UPDATE 仍只是候选匹配结果，不代表真实数据库已查重。

Statement 示例：

```text
recipient = IMPORTER
→ candidate_posting_type = AP
→ posting_type = null
→ accounting_status = PENDING_CONFIRMATION
→ operation = PENDING_REVIEW
```

## 3. 同名费用与重复

- 两条同名/同额 HANDLING CHARGE 仍是两条独立费用；
- 只有同一 `source_position_id` 的重复解析才合并；
- 同值不同源行保留，并产生 `W_POSSIBLE_DUPLICATE` 提示。

## 4. 费用映射状态

`config/charge_mapping.yaml` 支持 `status` / `alias_status`：

| 原始名称 | 标准名称 | mapping_status |
|---|---|---|
| HANDLING CHARGE | Handling Charge | MATCHED |
| H/C | Handling Charge | CANDIDATE |
| 4 ADD'L DETENTION FREE TIME CHARGE | Detention Free Time Extension Charge | PENDING_CONFIRMATION |
| OCA17 / On Carriage Additional - US Em | On Carriage Additional | CANDIDATE |
| 未命中名称 | 保留原名 | UNMATCHED |

只有 `MATCHED` 才把标准名写入 `charge_item`。`CANDIDATE` / `PENDING_CONFIRMATION` 保留原始费用名作为 `charge_item`，候选标准名写入 `charge_values.candidate_standard_charge_name`，并产生 `E_MAPPING_NOT_CONFIRMED`，operation 进入 `PENDING_REVIEW`。这样未确认映射不会显示成最终标准费用。

## 5. 原始值与规范化值

full audit 增加：

- `document_identity`：document/invoice/reference/B/L/MBL/HBL/waybill/booking/seal 编号，container 来源，多个日期候选（label/raw/iso/source/status/candidates），`document_date_raw/status`；
- `charge_values`：费用代码、原始/候选/标准费用名、mapping_status、amount/rate/quantity 的 raw+normalized、ROE、Base、原币/结算金额、币种来源、payment term、P/C、payer/payee code、付款指令、付款到期日；
- `status`：operation_status、candidate/确认方向、accounting_status、payment_status、payment_received/scope、release_type/status、shipment_operation_status、business_instructions。

例如 PDF1：

```text
B/L raw        = BL-DEMO-001
B/L normalized = BL-DEMO-001
reference_no   = null（B/L 不冒充 document number）
PAYMENT RECEIVED = NO → payment_received = false, payment_status = UNPAID
OCA17 → charge_code_raw = OCA17, charge_item 保留原文,
        mapping_status = CANDIDATE, candidate_standard = On Carriage Additional
```

原始值不覆盖；OCR/vision 没有提供的 Base/ROE/结算字段保持 `null`，不猜测。

## 6. 四份样本的预期

| 样本 | 类型 | 关键结果 |
|---|---|---|
| PDF1 | General Notice | notice/tentative；posting null；B/L raw/normalized；reference null；OCA17 独立；payment_received=false |
| PDF2 | Debit Note | 3 条费用，两条 Handling 独立；Terms=COD；P/C=C 独立；4 ADD'L 保留原文；posting null；不自动 AP |
| PRE-ALERT | 通知 | 主题箱号 TGHU1234567；SHA/TAR 代码保留；TELEX RELEASE/HOLD 分离；posting null；不 CREATE |
| CARRIER Invoice | Invoice | 2 条费用；ORFR 为发票号不混入箱号；日期 AMBIGUOUS；Rate=2.85/Amount=21.90/ROE=1.0；posting null |

## 7. 仍未自动化的部分

- SHA/TAR 原始代码已保留（`payer_code_raw` / `payee_code_raw`），但尚未映射到具体公司；
- `4 ADD'L...`、H/C、OCA17 的标准名仍需业务确认，当前只作为候选，不进入最终标准名；
- Base / ROE / 结算金额依赖具体版式和 OCR/vision 返回，缺失时保持 null；CARRIER 样本已能提取 Rate=2.85、Amount=21.90、ROE=1.0；
- 真实历史账单库未接入；没有 `--existing-bills` 时不会声称 CREATE/UPDATE 已确认，而是 `PENDING_REVIEW + W_HISTORY_NOT_CHECKED`；
- 真实业务样本和人工标注仍需扩充。
