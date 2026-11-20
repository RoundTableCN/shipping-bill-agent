$ErrorActionPreference = "Stop"

Write-Host "== verify fixtures =="
python scripts\verify_fixtures.py

Write-Host "== pytest =="
python -m pytest -q

Write-Host "== generate schema =="
python scripts\generate_schema.py

Write-Host "== generate golden =="
python scripts\generate_golden.py

Write-Host "== eval =="
python scripts\eval.py

Write-Host "== final output (fixtures) =="
python scripts\build_output.py --input data\fixtures --out out\final `
  --existing-bills data\fixtures\existing_bills.json --output-mode full

Write-Host "== final output (original samples) =="
python scripts\build_output.py --input data\samples --out out\final_samples `
  --existing-bills data\fixtures\existing_bills.json --output-mode full

Write-Host ""
Write-Host "Done. Streamlit: streamlit run app/streamlit_app.py"
