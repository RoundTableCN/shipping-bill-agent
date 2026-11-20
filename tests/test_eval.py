from shipping_agent.evaluation import evaluate, render_markdown


def test_eval_matches_golden():
    report = evaluate()

    for field in (
        "document_type",
        "reference_no",
        "document_date",
        "charge_item",
        "amount",
        "currency",
        "payment_term",
    ):
        assert report["fields"][field]["accuracy"] == 1.0
        assert report["fields"][field]["total"] == 22

    assert report["operation"]["accuracy"] == 1.0
    assert report["arap"]["accuracy"] == 1.0
    assert report["hallucination"]["rate"] == 0.0
    assert report["review"]["total"] == 22
    assert report["review"]["pending"] == 13
    assert len(report["per_case"]) == 9


def test_eval_markdown_renders():
    markdown = render_markdown(evaluate())
    assert "# Evaluation Report" in markdown
    assert "Hallucination rate" in markdown
    assert "sample_debit_note" in markdown
