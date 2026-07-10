PYTHON := $(shell command -v python 2>/dev/null || command -v python3)
PIP := $(PYTHON) -m pip
DBT_DIR := dbt_finance
DBT_PROFILES_DIR := .
TF_DIR := infrastructure
STREAMLIT_ADDRESS ?= localhost
STREAMLIT_PORT ?= 8501

.PHONY: check-python install infra-init infra-validate infra-plan infra-apply infra-destroy ingest nlp nlp-mock orchestrate schedule dbt-deps dbt-ensure-raw dbt-run dbt-build dbt-test backtest equities dashboard security-audit test

check-python:
	$(PYTHON) scripts/check_python_version.py

install: check-python
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

ingest: check-python
	$(PYTHON) scripts/orchestrate.py --only ingest

nlp: check-python
	$(PYTHON) scripts/orchestrate.py --only nlp

nlp-mock: check-python
	$(PYTHON) scripts/nlp/create_embeddings.py --mock-embeddings
	$(PYTHON) scripts/nlp/compute_sentiment.py --mock-sentiment
	$(PYTHON) scripts/nlp/compute_relevance.py --mock-embeddings
	$(PYTHON) scripts/nlp/compute_news_indicators.py

orchestrate: check-python
	$(PYTHON) scripts/orchestrate.py

schedule: check-python
	$(PYTHON) scripts/orchestrate.py --schedule

dbt-deps: check-python
	cd $(DBT_DIR) && dbt deps --profiles-dir $(DBT_PROFILES_DIR)

dbt-ensure-raw: check-python
	$(PYTHON) scripts/extract_load/ensure_raw_tables.py

dbt-run: check-python
	$(PYTHON) scripts/extract_load/ensure_raw_tables.py
	cd $(DBT_DIR) && dbt run --profiles-dir $(DBT_PROFILES_DIR)

dbt-build: check-python
	$(PYTHON) scripts/extract_load/ensure_raw_tables.py
	cd $(DBT_DIR) && dbt build --profiles-dir $(DBT_PROFILES_DIR)

dbt-test: check-python
	$(PYTHON) scripts/extract_load/ensure_raw_tables.py
	cd $(DBT_DIR) && dbt test --profiles-dir $(DBT_PROFILES_DIR)

backtest: check-python
	$(PYTHON) -m backtesting.engine

equities: check-python
	$(PYTHON) scripts/extract_load/equities_trading.py

dashboard: check-python
	@echo "Dashboard URL: http://$(STREAMLIT_ADDRESS):$(STREAMLIT_PORT)"
	PYTHONPATH=$(CURDIR) streamlit run dashboard/app.py --server.address=$(STREAMLIT_ADDRESS) --server.port=$(STREAMLIT_PORT) --server.headless=false --browser.serverAddress=$(STREAMLIT_ADDRESS)

security-audit: check-python
	$(PYTHON) scripts/security_audit.py

test: check-python
	pytest
