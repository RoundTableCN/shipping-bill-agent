# 评测说明：100% 是回归集通过，不是真实业务准确率

> 对应 `python scripts/eval.py` 的 `out/eval/report.json` / `report.md`。
> 生成日期：2026-11-13。

## 1. 数据集边界

当前评测集是 **9 个样本、22 条费用记录**：

| 样本 | 类型 | 记录数 |
|---|---|---:|
| sample_prealert | EML / PRE-ALERT | 1 |
| sample_general_notice | PDF / General Notice | 1 |
| sample_debit_note | PDF / Debit Note | 3 |
| sample_carrier_invoice | PNG / OCR mock | 0 |
| formal_invoice | PDF / Invoice | 3 |
| formal_invoice_revised | PDF / Invoice revision | 3 |
| formal_invoice_create | PDF / Invoice | 3 |
| statement | DOCX / Statement | 3 |
| charges | XLSX / Statement | 5 |
| **合计** | | **22** |

这些是**合成/样例数据**，用于回归验证解析、匹配、AR/AP、校验和输出稳定性，不代表真实业务分布。

## 2. 100% 指标的含义

| 指标 | 结果 | 含义 |
|---|---:|---|
| document_type / reference_no / document_date | 22/22 | 与 golden 快照一致 |
| charge_item / amount / currency / payment_term | 22/22 | 与 golden 快照一致 |
| operation | 22/22 | 与人工预期的 operation 一致 |
| AR/AP | 22/22 | 与人工预期一致 |
| hallucination rate | 0/22 | 所有输出费用都能在原文找到证据 |
| review rate | 13/22 = 59.09% | **保守策略产生的预期复核**，不是字段错误率 |

**结论**：100% 表示“回归集没有退化”，不表示“真实账单准确率 100%”。

## 3. 13 条 PENDING_REVIEW 的分类

| 来源 | 条数 | 原因 | 性质 |
|---|---:|---|---|
| sample_prealert | 1 | PRE-ALERT / notice / tentative | 预期保守 |
| sample_general_notice | 1 | General Notice，不是确认账单 | 预期保守 |
| sample_debit_note | 3 | 无 payer / 付款义务证据，`E_ARAP_UNDETERMINED` | 预期保守 |
| statement | 3 | Statement 不允许 CREATE/UPDATE；payload 只有 recipient 弱证据，candidate AP 不确认 | 预期保守（门禁） |
| charges | 5 | Statement / notice / tentative；多币种合计不强行合并 | 预期保守 |
| **合计** | **13** | | **没有一条是字段抽取错误** |

因此 59.09% 应理解为：

```text
预期复核率 = 13 / 22
```

而不是：

```text
识别错误率 = 59.09%
```

## 4. 为什么保留这些复核

- 题目要求“不得虚构”和“低置信度进入复核”；
- `PRE-ALERT`、`General Notice`、`Statement` 不直接当作正式账单；
- 没有 payer/payee/收费方向的 Debit Note 不猜测 AR/AP；
- AR/AP 置信度低于 0.85 时进入人工复核；
- 多币种合计无法用一个 `total` 表达时保留 `null` 并告警。

## 5. 后续评测建议

1. 增加真实/脱敏航运账单，按单据类型分层统计；
2. 将“预期复核”和“错误复核”分开统计，避免把保守策略误读为错误；
3. 增加字段级混淆矩阵（尤其 document_type、charge_item、currency、posting_type）；
4. 记录每个样本的人工真值来源（坐标/渲染图/原文行）；
5. 对 OCR 和视觉模型分别做可复现的独立评测集。
