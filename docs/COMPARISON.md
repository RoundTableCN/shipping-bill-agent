# OCR vs Local Parser vs Vision Model

- Vision model: `deepseek-flash[1M]` via `https://api.deepseek.com/anthropic`
- OCR: 已保存的真实探针响应（lorem/OSS）
- Local: 项目本地解析 + 规则抽取
- Truth: `data/golden/human_verified.json`（人工/本地解析对照）
- 方法与限制: [COMPARISON_METHOD.md](COMPARISON_METHOD.md)
- 字段口径: 3 个样本 × 8 个字段 = 24；严格字符串比较

## PDF1

| Field | Truth | OCR API | Local parser | DeepSeek Vision |
|---|---|---|---|---|
| document_type | General Notice | null | General Notice | GENERAL NOTICE |
| reference_no | BL-DEMO-001 | null | BL-DEMO-001 | BL-DEMO-001 |
| document_date | 2026-10-19 | null | 2026-10-19 | 2026-10-19 |
| currency | USD | null | USD | USD |
| charges | On Carriage Additional 245.0 | — | On Carriage Additional 245.0000 | OCA17 On Carriage Additional - US Em 245.0 |
| charge_names | ONCARRIAGEADDITIONAL | — | ONCARRIAGEADDITIONAL | ONCARRIAGEADDITIONAL |
| total | 245.0 | null | 245.0000 | 245.0 |

| Match | OCR | Local | Vision |
|---|---|---|---|
| fields matched | 0/8 | 8/8 | 8/8 |

- OCR API: data.list=[]
- Local parser: ocr_mode=degraded_local
- Vision: model=deepseek-flash[1M]; 18.9s

## PDF2

| Field | Truth | OCR API | Local parser | DeepSeek Vision |
|---|---|---|---|---|
| document_type | Debit Note | null | Debit Note | DEBIT NOTE |
| reference_no | DN-DEMO-002 | null | DN-DEMO-002 | DN-DEMO-002 |
| document_date | 2026-10-24 | null | 2026-10-24 | 2026-10-24 |
| currency | USD | null | USD | USD |
| charges | Handling Charge 65.0; Detention Free Time Extension Charge 1310.4; Handling Charge 35.0 | — | Handling Charge 65.00; Detention Free Time Extension Charge 1310.40; Handling Charge 35.00 | HANDLING CHARGE 65.0; 4 ADD'L DETENTION FREE TIME CHARGE 1310.4; HANDLING CHARGE 35.0 |
| charge_names | DETENTIONFREETIMEEXTENSIONCHARGE; HANDLINGCHARGE; HANDLINGCHARGE | — | DETENTIONFREETIMEEXTENSIONCHARGE; HANDLINGCHARGE; HANDLINGCHARGE | DETENTIONFREETIMEEXTENSIONCHARGE; HANDLINGCHARGE; HANDLINGCHARGE |
| total | 1410.4 | null | 1410.40 | 1410.4 |

| Match | OCR | Local | Vision |
|---|---|---|---|
| fields matched | 0/8 | 8/8 | 8/8 |

- OCR API: data.list=[]
- Local parser: ocr_mode=degraded_local
- Vision: model=deepseek-flash[1M]; 16.0s

## PNG

| Field | Truth | OCR API | Local parser | DeepSeek Vision |
|---|---|---|---|---|
| document_type | Invoice | Invoice | null | DEBIT INVOICE |
| reference_no | INV-DEMO-001 | INV-DEMO-001 | null | INV-DEMO-001 |
| document_date | 2025-10-03 | null | null | 2025-10-03 |
| currency | USD | null | null | USD |
| charges | Wharfage Administration Fee 5.0; Wharfage 21.9 | WHARFAGE ADMINISTRATION FEE 5.00; WHARFAGE 21.90 | — | WHARFAGE ADMINISTRATION FEE 5.0; WHARFAGE 21.9 |
| charge_names | WHARFAGE; WHARFAGEADMINISTRATIONFEE | WHARFAGE; WHARFAGEADMINISTRATIONFEE | — | WHARFAGE; WHARFAGEADMINISTRATIONFEE |
| total | 26.9 | null | null | 26.9 |

| Match | OCR | Local | Vision |
|---|---|---|---|
| fields matched | 5/8 | 0/8 | 7/8 |

- OCR API: raw fileType=PAI-CARRIER-NOTICE
- Vision: model=deepseek-flash[1M]; 14.5s

## Summary

| Source | Fields matched | Total | Accuracy |
|---|---:|---:|---:|
| OCR API | 5 | 24 | 20.8% |
| Local parser | 16 | 24 | 66.7% |
| Vision | 23 | 24 | 95.8% |
