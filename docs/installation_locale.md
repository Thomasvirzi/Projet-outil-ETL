# Installation locale

Ce document décrit l'installation locale du projet ELT Commodities & Backtesting.

---

## 1. Prérequis

Installer :

```text
Python 3.12
pip
Terraform
gcloud CLI
dbt-bigquery
Streamlit
```

Le projet utilise aussi Google Cloud BigQuery. L'approche recommandée est :

```text
gcloud auth application-default login
```

plutôt qu'une clé JSON de service account.

---

## 2. Créer l'environnement Python

Depuis la racine du repo :

```bash
python3.12 -m venv .venv
source .venv/bin/activate
make install
```

Le projet doit utiliser Python 3.12. Si `.venv` a été créé avec Python 3.14, `dbt deps` peut échouer avec une erreur `mashumaro.exceptions.UnserializableField`. Dans ce cas :

```bash
deactivate
rm -rf .venv
python3.12 -m venv .venv
source .venv/bin/activate
make install
```

---

## 3. Configurer les variables locales

Créer le fichier local :

```bash
cp .env.example .env
```

Variables principales :

```text
GOOGLE_CLOUD_PROJECT
BIGQUERY_LOCATION
BIGQUERY_MARTS_DATASET
BIGQUERY_MART_DATASET
BIGQUERY_STAGING_DATASET
BIGQUERY_MAX_BYTES_BILLED
```

Exemple :

```bash
export GOOGLE_CLOUD_PROJECT=elt-commodities-backtesting
export BIGQUERY_LOCATION=EU
export BIGQUERY_MART_DATASET=mart
export BIGQUERY_MARTS_DATASET=mart
export BIGQUERY_STAGING_DATASET=dbt_finance
export BIGQUERY_MAX_BYTES_BILLED=1000000000
```

Important :

```text
.env est ignoré par Git.
credentials/ est ignoré par Git.
```

---

## 4. Authentifier Google Cloud

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project elt-commodities-backtesting
```

Vérifier :

```bash
gcloud auth application-default print-access-token
```

---

## 5. Préparer l'infrastructure

```bash
make infra-init
make infra-validate
make infra-plan
```

Puis, si le plan Terraform est correct :

```bash
make infra-apply
```

---

## 6. Lancer le pipeline

Dry-run sans exécuter les scripts :

```bash
python3 scripts/orchestrate.py --dry-run
```

Pipeline complet :

```bash
make orchestrate
```

Ingestion seule :

```bash
make ingest
```

---

## 7. Lancer dbt

```bash
make dbt-deps
make dbt-run
make dbt-test
```

Ou directement :

```bash
cd dbt_finance
dbt deps
dbt build
```

Important :

```text
Terraform crée les datasets BigQuery raw, dbt_finance et mart.
dbt crée ensuite les tables et vues à l'intérieur de ces datasets.
Si le dashboard affiche une erreur du type mart.mart_dashboard_overview introuvable,
cela signifie généralement que les marts dbt n'ont pas encore été construits.
```

---

## 8. Lancer le dashboard

```bash
make dashboard
```

ou :

```bash
streamlit run dashboard/app.py
```

---

## 9. Lancer la recette locale

```bash
pytest
python3 scripts/security_audit.py
```

Ces commandes vérifient la cohérence Python, dbt, dashboard, orchestration et sécurité locale.
