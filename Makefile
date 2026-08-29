PYTHON ?= python

.PHONY: reset baseline tests gx dbt dashboard generate

reset:
	$(PYTHON) scripts/reset_lab.py

baseline:
	$(PYTHON) scripts/run_baseline.py

tests:
	pytest tests_public -q

gx:
	$(PYTHON) gx/validate_orders.py

dbt:
	$(PYTHON) scripts/sync_dbt_seeds.py
	$(PYTHON) -m dbt.cli.main build --project-dir dbt_project --profiles-dir dbt_project

dashboard:
	streamlit run dashboard/app.py

generate:
	$(PYTHON) scripts/generate_data.py --rows 600 --days 42 --seed 27
