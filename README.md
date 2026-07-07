# Projet-outil-ETL

Plateforme ELT et de backtesting dédiée aux matières premières.

Le projet vise à collecter des données de marché et des actualités financières, les stocker dans BigQuery, les transformer avec dbt, calculer des indicateurs techniques et textuels, exécuter des stratégies de backtesting, puis visualiser les résultats dans un dashboard Streamlit.

## Objectifs

- Ingestion quotidienne de données OHLCV via Yahoo Finance.
- Ingestion, nettoyage et déduplication de flux RSS financiers.
- Stockage des données brutes et transformées dans Google BigQuery.
- Transformation des données avec dbt.
- Génération d'embeddings, sentiment et indicateurs textuels.
- Calcul d'indicateurs techniques.
- Backtesting de stratégies explicables.
- Comparaison avec Buy and Hold et benchmark global.
- Visualisation interactive avec Streamlit.
- Déploiement reproductible via Terraform.

## Stack technique

| Domaine | Outils |
| --- | --- |
| Langage | Python |
| Cloud | Google Cloud Platform |
| Data warehouse | BigQuery |
| Infrastructure | Terraform |
| Transformations | dbt Core + dbt-bigquery |
| Ingestion marché | yfinance |
| Ingestion RSS | feedparser, BeautifulSoup |
| NLP | sentence-transformers, transformers |
| Backtesting | moteur Python interne |
| Dashboard | Streamlit |
| Orchestration | APScheduler |
| Tests | pytest, tests dbt |

## Arborescence

```text
.
├── infrastructure/          # Terraform et environnements
├── config/                  # Fichiers YAML de configuration
├── scripts/
│   ├── extract_load/        # Ingestion marché, benchmarks et RSS
│   └── nlp/                 # Embeddings, pertinence et indicateurs textuels
├── dbt_finance/             # Projet dbt
│   └── models/
│       ├── landing/
│       ├── staging/
│       ├── warehouse/
│       └── marts/
├── backtesting/             # Moteur, métriques, coûts et stratégies
├── data/                    # Zone locale runtime, contenu ignoré par Git
├── dashboard/               # Application Streamlit
├── docs/                    # Documentation projet
├── logs/                    # Logs runtime, contenu ignoré par Git
├── notebooks/               # Exploration et validation
├── tests/                   # Tests Python
├── requirements/            # Dépendances Python
├── TASK.md                  # Backlog projet détaillé
├── Makefile                 # Commandes projet
└── .env.example             # Exemple de configuration locale
```

## Installation locale

Créer un environnement virtuel avec Python 3.12 :

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

Installer les dépendances :

```bash
make install
```

Créer la configuration locale :

```bash
cp .env.example .env
```

Puis renseigner les variables nécessaires dans `.env`, notamment le projet Google Cloud et le chemin vers le service account.

## Configuration

Les secrets ne doivent jamais être commités.

La configuration locale passe par :

- `.env` pour les variables d'environnement et chemins de credentials ;
- `config/*.yml` pour les paramètres fonctionnels du pipeline ;
- `infrastructure/environments/*.tfvars` pour Terraform.

Un fichier d'exemple Terraform est disponible dans `infrastructure/environments/example.tfvars`.

## Commandes utiles

```bash
make install
make infra-init
make infra-validate
make infra-plan
make infra-apply
make ingest
make dbt-run
make dbt-test
make backtest
make dashboard
make test
```

Certaines commandes pointent vers des modules qui seront développés dans les prochaines étapes du backlog.

## Pipeline cible

```text
Yahoo Finance + flux RSS
        │
        ▼
Scripts Python d'ingestion
        │
        ▼
BigQuery raw
        │
        ▼
NLP + dbt
        │
        ▼
BigQuery dbt_finance / mart
        │
        ├── Backtesting
        └── Streamlit
```

## Règles importantes

- Aucune donnée future ne doit être utilisée dans les signaux.
- Un signal produit à J est exécuté au plus tôt à J+1.
- Les frais doivent être intégrés aux backtests.
- Les données marché doivent être uniques par `symbol` et `date`.
- Les articles RSS doivent être nettoyés et dédupliqués.
- Les paramètres du test final ne doivent pas être calibrés sur la période hors échantillon.
- Aucun secret ne doit être présent dans le dépôt Git.

## Documentation projet

- `TASK.md` contient le backlog opérationnel.
- `docs/documentation_finale.md` sert d'index final pour la soutenance.
- `docs/installation_locale.md` explique l'installation locale.
- `docs/architecture_globale.md` synthétise l'architecture.
- `docs/flux_donnee.md` explique le trajet de la donnée, des APIs jusqu'au dashboard.
- `docs/pedagogie.md` explique comment configurer Terraform avec Google Cloud BigQuery.
- `docs/rapport_recette.md` synthétise la recette locale.
- `docs/soutenance_slides.md` propose le plan des slides.
- `docs/demo_streamlit.md` décrit le scénario de démonstration.
- `docs/scenario_secours.md` prépare la démo de secours.
- `Note de cadrage.md` décrit le périmètre et la méthodologie.
- `Cahier des charges.md` décrit les exigences techniques.
- `Cahier des charges fonctionnel.md` décrit les fonctions attendues.
- `Backlog priorise.md` fournit le découpage initial des livrables.

## Version stable

La version stable MVP est indiquée dans `VERSION`.

Les notes de version sont disponibles dans `RELEASE_NOTES.md`.
