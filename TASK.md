# TASK.md — Plan de tâches projet

## Projet

**ELT Commodities & Backtesting**  
Plateforme ELT pour matières premières avec ingestion marché/RSS, transformations dbt, indicateurs techniques et textuels, moteur de backtesting, dashboard Streamlit et infrastructure Google Cloud/Terraform.

**Échéance finale :** 7 juillet 2026  
**Objectif MVP :** livrer un pipeline reproductible, testé, documenté et démontrable.

---

## Légende

- `[ ]` à faire
- `[~]` en cours
- `[x]` terminé
- `P0` obligatoire pour le MVP
- `P1` important après MVP
- `P2` amélioration optionnelle

---

## 0. Décisions de cadrage

- [ ] `P0` Valider la liste finale de 10 à 15 matières premières.
- [ ] `P0` Associer chaque matière première à son ticker Yahoo Finance.
- [ ] `P0` Choisir le benchmark global représentatif du marché des commodities.
- [ ] `P0` Valider les sources RSS financières à utiliser.
- [ ] `P0` Trancher la période d’historique cible : les documents mentionnent 2020–J-1, mais le backlog indique aussi une récupération depuis 2015.
- [ ] `P0` Définir les paramètres par défaut : capital initial, frais, slippage, seuil RSS, fenêtres SMA/RSI.
- [ ] `P0` Documenter les limites liées aux futures : roulement, liquidité, différence spot/futures.

---

## 1. Initialisation du dépôt

- [x] `P0` Créer l’arborescence cible du projet.
- [x] `P0` Ajouter `.gitignore` avec exclusion de `.env`, credentials et artefacts locaux.
- [x] `P0` Créer `.env.example` sans secrets.
- [x] `P0` Créer `requirements/requirements.txt`.
- [x] `P0` Ajouter un `Makefile` ou documenter les commandes équivalentes.
- [x] `P0` Mettre à jour `README.md` avec installation, architecture et commandes de base.
- [x] `P1` Ajouter des notebooks d’exploration et de validation.

Arborescence attendue :

```text
infrastructure/
config/
scripts/
  extract_load/
  nlp/
dbt_finance/
backtesting/
dashboard/
notebooks/
tests/
requirements/
```

---

## 2. Configuration projet

- [x] `P0` Créer `config/commodities.yml`.
- [x] `P0` Créer `config/benchmarks.yml`.
- [x] `P0` Créer `config/rss_sources.yml`.
- [x] `P0` Créer `config/strategies.yml`.
- [x] `P0` Créer `config/settings.yml`.
- [x] `P0` Centraliser la lecture de configuration dans `scripts/extract_load/config.py`.
- [x] `P0` Gérer les variables d’environnement et les chemins de credentials Google Cloud.
- [x] `P0` Vérifier qu’aucun secret n’est versionné.

---

## 3. Infrastructure Terraform et Google Cloud

- [x] `P0` Configurer le provider Google Cloud.
- [x] `P0` Activer les API Google Cloud nécessaires.
- [x] `P0` Créer les datasets BigQuery `raw`, `dbt_finance` et `mart`.
- [x] `P0` Créer le service account du pipeline.
- [x] `P0` Configurer les rôles IAM selon le principe du moindre privilège.
- [x] `P0` Définir la localisation unique des datasets.
- [x] `P0` Ajouter les outputs utiles au déploiement.
- [x] `P0` Tester `terraform validate`.
- [ ] `P0` Tester `terraform plan`.
- [ ] `P0` Tester `terraform apply`.
- [x] `P1` Ajouter un bucket Cloud Storage si nécessaire.
- [x] `P1` Documenter `terraform destroy` et les précautions associées.

Fichiers attendus :

```text
infrastructure/main.tf
infrastructure/providers.tf
infrastructure/variables.tf
infrastructure/outputs.tf
infrastructure/bigquery.tf
infrastructure/iam.tf
infrastructure/environments/dev.tfvars
```

---

## 4. Ingestion des données de marché

- [ ] `P0` Développer `scripts/extract_load/ingest_commodities.py`.
- [ ] `P0` Récupérer les données OHLCV via `yfinance`.
- [ ] `P0` Charger l’historique depuis la date retenue jusqu’à J-1.
- [ ] `P0` Normaliser les colonnes, dates et types.
- [ ] `P0` Ajouter `source` et `ingested_at`.
- [ ] `P0` Charger les données dans `raw.market_data_raw`.
- [ ] `P0` Dédupliquer sur le couple `symbol` + `date`.
- [ ] `P0` Implémenter l’ingestion incrémentale.
- [ ] `P0` Ajouter retries, backoff exponentiel et logs d’erreur.
- [ ] `P0` Tester la relance sans doublon.
- [ ] `P1` Conserver le dernier état valide en cas d’échec source.

Schéma minimal attendu :

```text
symbol
date
open
high
low
close
adjusted_close
volume
source
ingested_at
```

---

## 5. Ingestion des benchmarks

- [ ] `P0` Développer `scripts/extract_load/ingest_benchmarks.py`.
- [ ] `P0` Ingest un Buy and Hold de référence par instrument.
- [ ] `P0` Ingest le benchmark global.
- [ ] `P0` Aligner fréquence, dates et champs avec les matières premières.
- [ ] `P0` Charger les données benchmark dans BigQuery.
- [ ] `P0` Tester les mises à jour quotidiennes.
- [ ] `P1` Ajouter des contrôles de couverture temporelle par benchmark.

---

## 6. Ingestion RSS

- [ ] `P0` Développer `scripts/extract_load/ingest_rss.py`.
- [ ] `P0` Lire les URLs depuis `config/rss_sources.yml`.
- [ ] `P0` Extraire titre, source, URL, date et résumé/contenu disponible.
- [ ] `P0` Nettoyer le HTML avec BeautifulSoup.
- [ ] `P0` Normaliser l’encodage et les dates.
- [ ] `P0` Calculer `article_id` et `content_hash`.
- [ ] `P0` Charger les articles dans `raw.news_raw`.
- [ ] `P0` Supprimer les doublons exacts.
- [ ] `P0` Gérer les erreurs par flux.
- [ ] `P1` Ajouter une déduplication sémantique entre articles proches.

Schéma minimal attendu :

```text
article_id
title
source
url
published_at
clean_text
content_hash
ingested_at
```

---

## 7. Pipeline NLP et embeddings

- [ ] `P0` Développer `scripts/nlp/create_embeddings.py`.
- [ ] `P0` Choisir un modèle Sentence Transformers léger.
- [ ] `P0` Générer un embedding pour chaque article.
- [ ] `P0` Historiser le nom et la version du modèle.
- [ ] `P0` Éviter de recalculer les embeddings existants.
- [ ] `P0` Développer `scripts/nlp/compute_relevance.py`.
- [ ] `P0` Créer une description de référence par matière première.
- [ ] `P0` Calculer la similarité cosinus article–matière première.
- [ ] `P0` Appliquer un seuil configurable de pertinence.
- [ ] `P0` Autoriser plusieurs associations par article.
- [ ] `P0` Développer `scripts/nlp/compute_sentiment.py`.
- [ ] `P0` Calculer `positive_probability`, `negative_probability`, `neutral_probability` et `sentiment_score`.
- [ ] `P0` Calculer `novelty_score`.
- [ ] `P1` Détecter les doublons sémantiques sur fenêtre récente.
- [ ] `P2` Ajouter des scores thématiques : géopolitique, offre, météo.

Formule de sentiment attendue :

```text
sentiment_score = positive_probability - negative_probability
```

---

## 8. Indicateurs textuels

- [ ] `P0` Développer `scripts/nlp/compute_news_indicators.py`.
- [ ] `P0` Définir la formule du `news_pressure_score`.
- [ ] `P0` Intégrer pertinence, sentiment, nouveauté, fraîcheur et poids source.
- [ ] `P0` Calculer `news_volume` par matière première et par jour.
- [ ] `P0` Calculer `news_surprise_20d`.
- [ ] `P0` Calculer `novelty_score` agrégé.
- [ ] `P0` Calculer `sentiment_dispersion`.
- [ ] `P0` Gérer les jours sans article.
- [ ] `P0` Créer ou alimenter `int_commodity_news_features`.
- [ ] `P0` Documenter les formules.
- [ ] `P1` Calculer `news_acceleration`.
- [ ] `P2` Calculer `geopolitical_risk_score`, `supply_shock_score` et `weather_risk_score`.

---

## 9. Projet dbt

- [ ] `P0` Initialiser `dbt_finance`.
- [ ] `P0` Configurer `dbt_project.yml`.
- [ ] `P0` Configurer `packages.yml` si nécessaire.
- [ ] `P0` Déclarer les sources BigQuery.
- [ ] `P0` Créer les modèles Landing en vues.
- [ ] `P0` Créer `stg_commodity_prices`.
- [ ] `P0` Créer `stg_benchmarks`.
- [ ] `P0` Créer `stg_news`.
- [ ] `P0` Créer `stg_pipeline_logs`.
- [ ] `P0` Créer `int_technical_indicators`.
- [ ] `P0` Créer `int_article_commodity_relevance`.
- [ ] `P0` Créer `int_commodity_news_features`.
- [ ] `P0` Créer `int_strategy_signals`.
- [ ] `P0` Créer `int_daily_returns`.
- [ ] `P0` Créer `mart_strategy_signals`.
- [ ] `P0` Créer `mart_backtest_trades`.
- [ ] `P0` Créer `mart_backtest_daily`.
- [ ] `P0` Créer `mart_strategy_metrics`.
- [ ] `P0` Créer `mart_dashboard_overview`.
- [ ] `P0` Ajouter les tests dbt critiques.
- [ ] `P0` Générer la documentation dbt.

Tests dbt attendus :

- [ ] `P0` `not_null` sur les champs critiques.
- [ ] `P0` `unique` sur les identifiants.
- [ ] `P0` Unicité du couple `symbol` + `date`.
- [ ] `P0` Cohérence OHLC.
- [ ] `P0` Absence de dates futures.
- [ ] `P0` Fraîcheur des données.
- [ ] `P0` Validité des signaux.
- [ ] `P0` Absence de doublons articles.
- [ ] `P1` Tests de relations entre tables.

---

## 10. Indicateurs techniques

- [ ] `P0` Calculer les rendements simples.
- [ ] `P0` Calculer les rendements logarithmiques.
- [ ] `P0` Calculer SMA 20.
- [ ] `P0` Calculer SMA 50.
- [ ] `P0` Calculer RSI 14.
- [ ] `P0` Calculer Stochastic RSI K.
- [ ] `P0` Calculer Stochastic RSI D.
- [ ] `P0` Calculer MACD.
- [ ] `P0` Calculer le signal MACD.
- [ ] `P0` Calculer ATR 14.
- [ ] `P0` Calculer la volatilité historique.
- [ ] `P0` Vérifier l’absence de look-ahead bias.
- [ ] `P0` Tester les résultats sur un échantillon.
- [ ] `P1` Calculer SMA 100 ou SMA 200.
- [ ] `P1` Calculer les bandes de Bollinger.
- [ ] `P1` Calculer le ratio de volume.

---

## 11. Moteur de backtesting

- [ ] `P0` Créer `backtesting/engine.py`.
- [ ] `P0` Créer `backtesting/portfolio.py`.
- [ ] `P0` Créer `backtesting/costs.py`.
- [ ] `P0` Créer `backtesting/metrics.py`.
- [ ] `P0` Créer `backtesting/models.py`.
- [ ] `P0` Définir une interface commune de stratégie.
- [ ] `P0` Implémenter Buy and Hold.
- [ ] `P0` Implémenter le croisement de moyennes mobiles.
- [ ] `P0` Implémenter SMA + Stochastic RSI.
- [ ] `P0` Implémenter la stratégie technique avec filtre RSS.
- [ ] `P0` Gérer capital, cash, positions et exposition.
- [ ] `P0` Intégrer les frais.
- [ ] `P0` Intégrer le slippage configurable.
- [ ] `P0` Respecter l’exécution à J+1.
- [ ] `P0` Interdire la vente à découvert dans le MVP.
- [ ] `P0` Enregistrer les transactions.
- [ ] `P0` Enregistrer les raisons de sortie.
- [ ] `P0` Enregistrer les paramètres et la date d’exécution de chaque backtest.
- [ ] `P0` Produire le portefeuille journalier.
- [ ] `P1` Ajouter une stratégie breakout ou mean reversion si le planning le permet.

---

## 12. Métriques et comparaison

- [ ] `P0` Calculer le rendement cumulé.
- [ ] `P0` Calculer le rendement annualisé.
- [ ] `P0` Calculer la volatilité annualisée.
- [ ] `P0` Calculer le ratio de Sharpe.
- [ ] `P0` Calculer le ratio de Sortino.
- [ ] `P0` Calculer le maximum drawdown.
- [ ] `P0` Calculer le ratio de Calmar.
- [ ] `P0` Calculer le win rate.
- [ ] `P0` Calculer le profit factor.
- [ ] `P0` Calculer le nombre de transactions.
- [ ] `P0` Calculer la durée moyenne des positions.
- [ ] `P0` Calculer les frais cumulés.
- [ ] `P0` Calculer la surperformance par rapport au benchmark.
- [ ] `P0` Comparer stratégie technique seule, stratégie avec filtre RSS, Buy and Hold et benchmark global.
- [ ] `P0` Créer les tables Marts de backtesting.

---

## 13. Validation hors échantillon

- [ ] `P0` Utiliser 2020–2023 pour calibration.
- [ ] `P0` Utiliser 2024 pour validation.
- [ ] `P0` Utiliser 2025–J-1 pour test final.
- [ ] `P0` Empêcher l’optimisation sur la période de test.
- [ ] `P0` Analyser la stabilité par instrument.
- [ ] `P0` Mesurer l’apport réel du filtre RSS.
- [ ] `P0` Ne pas sélectionner uniquement sur le rendement brut.
- [ ] `P0` Documenter les limites méthodologiques.

---

## 14. Dashboard Streamlit

- [ ] `P0` Créer `dashboard/app.py`.
- [ ] `P0` Créer `dashboard/services/bigquery_client.py`.
- [ ] `P0` Créer `dashboard/services/data_loader.py`.
- [ ] `P0` Connecter Streamlit aux tables Marts BigQuery.
- [ ] `P0` Ajouter cache de chargement.
- [ ] `P0` Ajouter gestion claire des erreurs.
- [ ] `P0` Créer la page `Market Overview`.
- [ ] `P0` Créer la page `Indicators` ou `Signals`.
- [ ] `P0` Créer la page `News Indicators`.
- [ ] `P0` Créer la page `Strategy Explorer`.
- [ ] `P0` Créer la page `Backtest`.
- [ ] `P0` Créer la page `Comparison`.
- [ ] `P0` Créer la page `Data Quality`.
- [ ] `P0` Ajouter filtres instrument, catégorie, période et stratégie.
- [ ] `P0` Afficher equity curve, drawdown, transactions et métriques.
- [ ] `P0` Afficher statut pipeline, erreurs et fraîcheur des données.
- [ ] `P0` Ajouter exports CSV.
- [ ] `P0` Afficher un avertissement de risque financier.
- [ ] `P1` Rendre l’interface responsive.

---

## 15. Orchestration quotidienne

- [ ] `P0` Créer `scripts/orchestrate.py`.
- [ ] `P0` Enchaîner ingestion marché, benchmarks et RSS.
- [ ] `P0` Lancer embeddings et scores textuels.
- [ ] `P0` Lancer `dbt run`.
- [ ] `P0` Lancer `dbt test`.
- [ ] `P0` Mettre à jour les backtests.
- [ ] `P0` Écrire le statut final du run.
- [ ] `P0` Journaliser chaque tâche avec `run_id`, `task_name`, dates, statut, lignes traitées et erreur.
- [ ] `P0` Planifier l’exécution quotidienne avec APScheduler.
- [ ] `P0` Tester les relances après erreur.

Ordre attendu :

```text
1. ingestion marché
2. ingestion benchmarks
3. ingestion RSS
4. génération embeddings
5. calcul scores textuels
6. dbt run
7. dbt test
8. mise à jour backtests
9. écriture statut final
```

---

## 16. Tests et qualité

- [ ] `P0` Ajouter tests unitaires pour calculs d’indicateurs.
- [ ] `P0` Ajouter tests unitaires pour règles de signaux.
- [ ] `P0` Ajouter tests unitaires pour frais et slippage.
- [ ] `P0` Ajouter tests unitaires pour métriques de performance.
- [ ] `P0` Ajouter tests unitaires pour déduplication.
- [ ] `P0` Ajouter tests unitaires pour sentiment.
- [ ] `P0` Ajouter tests unitaires pour similarité article–matière première.
- [ ] `P0` Ajouter tests d’intégration ingestion vers BigQuery.
- [ ] `P0` Ajouter tests d’intégration dbt.
- [ ] `P0` Ajouter tests d’intégration Streamlit vers Marts.
- [ ] `P0` Ajouter test complet d’un backtest.
- [ ] `P0` Ajouter scénario end-to-end source → ingestion → raw → dbt → signaux → backtest → dashboard.
- [ ] `P0` Produire un rapport de recette.
- [ ] `P1` Ajouter CI si possible.

---

## 17. Sécurité, coûts et performance

- [ ] `P0` Vérifier l’absence de secrets dans Git.
- [ ] `P0` Vérifier les permissions IAM.
- [ ] `P0` Utiliser les variables d’environnement ou `.env` ignoré par Git.
- [ ] `P0` Partitionner les tables par date lorsque pertinent.
- [ ] `P0` Clusteriser par symbole lorsque pertinent.
- [ ] `P0` Limiter les requêtes aux colonnes utiles.
- [ ] `P0` Contrôler les coûts BigQuery.
- [ ] `P0` Suivre les temps d’exécution des traitements.
- [ ] `P1` Documenter les objectifs de performance : ingestion < 10 min, embeddings < 30 min, dbt < 15 min, backtest < 10 s, page Streamlit < 5 s avec cache.

---

## 18. Documentation et soutenance

- [ ] `P0` Documenter l’installation locale.
- [ ] `P0` Documenter l’architecture globale.
- [ ] `P0` Documenter Terraform et le déploiement GCP.
- [ ] `P0` Documenter le pipeline ELT.
- [ ] `P0` Documenter les modèles dbt et le schéma des données.
- [ ] `P0` Documenter les indicateurs techniques.
- [ ] `P0` Documenter les indicateurs textuels.
- [ ] `P0` Documenter les stratégies de backtesting.
- [ ] `P0` Documenter les hypothèses, limites et biais évités.
- [ ] `P0` Préparer les slides de soutenance.
- [ ] `P0` Préparer la démonstration Streamlit.
- [ ] `P0` Préparer un scénario de secours.
- [ ] `P0` Effectuer une répétition finale.
- [ ] `P0` Créer une version stable du dépôt.

---

## MVP obligatoire

- [ ] `P0` Infrastructure Terraform et BigQuery fonctionnelle.
- [ ] `P0` Ingestion Yahoo Finance fonctionnelle.
- [ ] `P0` Ingestion RSS fonctionnelle.
- [ ] `P0` Projet dbt avec tests critiques.
- [ ] `P0` Indicateurs SMA, RSI et Stochastic RSI.
- [ ] `P0` Embeddings et sentiment.
- [ ] `P0` `news_pressure_score`.
- [ ] `P0` Quatre stratégies de backtesting.
- [ ] `P0` Moteur de backtesting avec frais et J+1.
- [ ] `P0` Comparaison aux benchmarks.
- [ ] `P0` Dashboard Streamlit.
- [ ] `P0` Orchestration quotidienne.
- [ ] `P0` Tests critiques.
- [ ] `P0` Documentation finale.

---

## Commandes attendues

- [ ] `P0` `make infra-plan`
- [ ] `P0` `make infra-apply`
- [ ] `P0` `make ingest`
- [ ] `P0` `make dbt-run`
- [ ] `P0` `make dbt-test`
- [ ] `P0` `make backtest`
- [ ] `P0` `make dashboard`
- [ ] `P0` `make test`

---

## Critères d’acceptation finaux

- [ ] L’infrastructure se déploie avec Terraform.
- [ ] Les données marché couvrent au moins 10 matières premières.
- [ ] Les données couvrent la période retenue jusqu’à J-1.
- [ ] Les données sont chargées dans BigQuery sans doublons.
- [ ] Les flux RSS sont ingérés, nettoyés et dédupliqués.
- [ ] Les embeddings et scores textuels sont calculés.
- [ ] Les modèles dbt s’exécutent avec succès.
- [ ] Les tests critiques passent.
- [ ] Les indicateurs techniques et textuels sont reproductibles.
- [ ] Les backtests respectent l’absence de données futures.
- [ ] Les signaux à J sont exécutés au plus tôt à J+1.
- [ ] Les frais sont intégrés.
- [ ] Les résultats sont comparés au Buy and Hold et au benchmark global.
- [ ] Le dashboard permet d’explorer les marchés, signaux, actualités, backtests et métriques.
- [ ] Les erreurs du pipeline sont journalisées.
- [ ] Le projet peut être installé et lancé depuis le README.
- [ ] Aucun secret n’est présent dans le dépôt.
- [ ] Les limites du projet sont clairement documentées.
