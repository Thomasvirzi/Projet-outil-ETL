PYTHON ?= python3
PIP ?= pip
DBT_DIR := dbt_finance
TF_DIR := infrastructure

.PHONY: install infra-init infra-validate infra-plan infra-apply infra-destroy ingest dbt-run dbt-test backtest dashboard test

install:
	$(PIP) install -r requirements/requirements.txt

infra-init:
	terraform -chdir=$(TF_DIR) init

infra-validate:
	terraform -chdir=$(TF_DIR) validate

infra-plan:
	terraform -chdir=$(TF_DIR) plan -var-file=environments/dev.tfvars

infra-apply:
	terraform -chdir=$(TF_DIR) apply -var-file=environments/dev.tfvars

infra-destroy:
	terraform -chdir=$(TF_DIR) destroy -var-file=environments/dev.tfvars

ingest:
	$(PYTHON) scripts/orchestrate.py --only ingest

dbt-run:
	cd $(DBT_DIR) && dbt run

dbt-test:
	cd $(DBT_DIR) && dbt test

backtest:
	$(PYTHON) -m backtesting.engine

dashboard:
	streamlit run dashboard/app.py

test:
	pytest
