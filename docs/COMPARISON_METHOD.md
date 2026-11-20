# 视觉模型 23/24 对照的可复现说明

> 对应 [COMPARISON.md](COMPARISON.md) 的 `23/24（95.8%）`。
> 本文说明真值来源、模型配置、字段口径和限制。

## 1. 样本与真值来源

真值文件：[data/golden/human_verified.json](../data/golden/human_verified.json)

| 样本 | 真值来源 |
|---|---|
| PDF1 `sample_general_notice.pdf` | 本地文字层解析 + PDF 坐标重建 + 渲染图核对；`PAYMENT RECEIVED` 以渲染图为准，不用 `get_text()` 顺序推断 |
| PDF2 `sample_debit_note.pdf` | 本地文字层解析 + 费用行原文核对 |
| PNG `sample_carrier_invoice.png` | 人工对图读取；截图表格列：Base / Rate / Curr / Amount / R.O.E. / Curr / Amount |

真值文件只包含对照字段：`document_type`、`reference_no`、`document_date`、`currency`、`charges`、`total`。不是完整业务审计真值。

## 2. 模型运行配置

| 项目 | 值 |
|---|---|
| 模型 | `deepseek-flash[1M]` |
| 接口 | `https://api.deepseek.com/anthropic`（Anthropic 兼容） |
| 调用方式 | `src/shipping_agent/vision_extractor.py`，`temperature=0` |
| 输入 | PDF 最多前 3 页，120 dpi 转 JPEG；PNG 直接输入 |
| 输出 | 结构化 JSON，无法确定填 `null` |
| API key | 只从环境变量读取，**不写入仓库、不写入报告** |

运行命令：

```bash
python scripts/compare_models.py
```

运行时间：2026-11-13。原始结果：`out/comparison/report.json`。

## 3. 字段口径

每个样本比较 8 个字段：

```text
document_type
reference_no
document_date
currency
charge_count
charge_names（经 charge_mapping.yaml 标准化后比较）
charge_amounts
total
```

3 个样本 × 8 个字段 = **24 个字段**。

结果：

| 样本 | Vision | 不一致字段 |
|---|---:|---|
| PDF1 | 8/8 | 无 |
| PDF2 | 8/8 | 无 |
| PNG | 7/8 | `document_type`: 模型输出 `DEBIT INVOICE`，真值 `Invoice` |
| **合计** | **23/24 = 95.8%** | 仅 1 个语义同义差异 |

PNG 的 `DEBIT INVOICE` 与 `Invoice` 是同一类单据的不同写法，不是金额、编号或费用错误；如果按业务同义词归一，视觉模型为 24/24。为避免口径漂移，报告保留严格字符串比较，因此记为 23/24。

## 4. OCR / 本地解析的口径

- OCR 值来自已保存的真实探针响应（`out/ocr_probe/`、`out/ocr_probe_20261112/`）；
- PDF1/PDF2 的 OCR `data.list=[]`，记为缺失，不把空结果当作“无费用”；
- PNG 的 OCR 使用图片转单页 PDF 后的 `sample_carrier.pdf` 结果；
- 本地解析走项目 `parse_file + process_bundle`，OCR 模式 `local`；
- `charge_names` 比较前统一经过 `config/charge_mapping.yaml` 标准化。

## 5. 限制

1. **只有 3 个样本**，不足以证明泛化准确率；
2. 真值是人工/本地解析对照，不是双人独立标注；
3. 只运行了一次，没有重复性和温度方差统计；
4. OCR 探针 URL 为临时签名 URL，过期后不可复现，需重新托管文件；
5. 视觉模型输出可能受版式、截图清晰度、语言影响；
6. 该结果只说明“在这 3 份样本上视觉模型能补 OCR 缺失字段”，不能替代真实业务评测。
