# Backlog priorisé

## Plateforme ELT et backtesting sur les matières premières

**Projet :** ELT Commodities & Backtesting

**Version :** 1.1

---

## 1. Cadrage et préparation

### Livrable

Projet initialisé et périmètre validé.

### Tâches

- valider les matières premières et leurs tickers ;
- choisir le benchmark global ;
- valider les sources RSS ;
- définir les stratégies du MVP ;
- créer le dépôt Git ;
- créer l’arborescence, le README et les fichiers de configuration ;
- préparer l’environnement Python.

---

## 2. Infrastructure Terraform

### Livrable

Infrastructure Google Cloud reproductible.

### Tâches

- configurer Terraform et le provider Google ;
- activer les API nécessaires ;
- créer les datasets BigQuery `raw`, `dbt_finance` et `mart` ;
- créer le service account ;
- configurer les permissions IAM ;
- tester `terraform validate`, `plan` et `apply` ;
- documenter le déploiement.

---

## 3. Ingestion des données de marché

### Livrable

Historique OHLCV disponible dans BigQuery.

### Tâches

- développer l’ingestion Yahoo Finance ;
- récupérer les données depuis 2015 ;
- normaliser les colonnes et les dates ;
- charger les données dans `raw.market_data_raw` ;
- gérer les doublons ;
- ajouter l’ingestion incrémentale ;
- ajouter les retries et les logs ;
- tester la réexécution sans doublon.

---

## 4. Ingestion des benchmarks

### Livrable

Benchmarks disponibles sur les mêmes périodes.

### Tâches

- configurer le benchmark global ;
- développer l’ingestion ;
- charger les données dans BigQuery ;
- aligner les dates avec les matières premières ;
- tester les mises à jour quotidiennes.

---

## 5. Ingestion des flux RSS

### Livrable

Articles financiers nettoyés dans BigQuery.

### Tâches

- configurer les sources RSS ;
- extraire les titres, dates, sources, URLs et résumés ;
- nettoyer le HTML ;
- normaliser les dates ;
- calculer les identifiants et hashes ;
- charger les articles dans `raw.news_raw` ;
- supprimer les doublons ;
- gérer les erreurs de flux.

---

## 6. Projet dbt et qualité des données

### Livrable

Couches Landing et Staging fonctionnelles.

### Tâches

- initialiser dbt ;
- déclarer les sources BigQuery ;
- créer les modèles Landing ;
- créer les modèles Staging ;
- typer et dédupliquer les données ;
- ajouter les tests `not_null`, `unique`, relations et fraîcheur ;
- générer la documentation dbt.

---

## 7. Indicateurs techniques

### Livrable

Indicateurs financiers disponibles par instrument et par date.

### Tâches

- calculer les rendements ;
- calculer SMA 20 et SMA 50 ;
- calculer RSI et Stochastic RSI ;
- calculer MACD, ATR et volatilité ;
- créer `int_technical_indicators` ;
- vérifier l’absence de look-ahead bias ;
- tester les résultats.

---

## 8. Embeddings et analyse des actualités

### Livrable

Articles vectorisés, classés et scorés.

### Tâches

- choisir le modèle d’embedding ;
- générer les embeddings ;
- créer les descriptions de référence des matières premières ;
- calculer la similarité article-instrument ;
- définir le seuil de pertinence ;
- calculer le sentiment ;
- calculer la nouveauté ;
- détecter les doublons sémantiques ;
- valider les résultats sur un échantillon.

---

## 9. Indicateurs textuels

### Livrable

Indicateurs RSS journaliers par matière première.

### Tâches

- définir la formule du `news_pressure_score` ;
- intégrer pertinence, sentiment, fraîcheur et nouveauté ;
- calculer `news_volume` ;
- calculer `news_surprise_20d` ;
- calculer la dispersion du sentiment ;
- créer `int_commodity_news_features` ;
- tester les jours sans article ;
- documenter les formules.

---

## 10. Moteur de backtesting

### Livrable

Moteur capable d’exécuter les stratégies du MVP.

### Tâches

- définir l’interface commune des stratégies ;
- gérer le portefeuille, le capital et les positions ;
- intégrer les frais et le slippage ;
- respecter l’exécution à J+1 ;
- implémenter Buy and Hold ;
- implémenter le croisement de moyennes mobiles ;
- implémenter SMA + Stochastic RSI ;
- implémenter le filtre RSS ;
- enregistrer les transactions et raisons de sortie ;
- ajouter les tests unitaires.

---

## 11. Métriques et comparaison

### Livrable

Performances calculées et comparables.

### Tâches

- calculer rendement, volatilité et drawdown ;
- calculer Sharpe, Sortino et Calmar ;
- calculer win rate, profit factor et frais ;
- comparer au Buy and Hold ;
- comparer au benchmark global ;
- comparer les stratégies avec et sans filtre RSS ;
- créer les tables Marts de backtesting.

---

## 12. Validation hors échantillon

### Livrable

Résultats méthodologiquement valides.

### Tâches

- utiliser 2020–2023 pour la calibration ;
- utiliser 2024 pour la validation ;
- utiliser 2025–J-1 pour le test final ;
- empêcher l’optimisation sur la période de test ;
- analyser la stabilité par instrument ;
- mesurer l’apport réel du filtre RSS ;
- documenter les limites.

---

## 13. Dashboard Streamlit

### Livrable

Application interactive reliée à BigQuery.

### Tâches

- créer la structure Streamlit ;
- connecter le dashboard aux tables Marts ;
- créer les pages Market Overview et Indicators ;
- créer la page News Indicators ;
- créer Strategy Explorer ;
- créer Backtest et Comparison ;
- créer Data Quality ;
- ajouter les filtres, graphiques et exports CSV ;
- ajouter le cache et la gestion des erreurs.

---

## 14. Orchestration

### Livrable

Pipeline quotidien automatisé.

### Tâches

- créer `orchestrate.py` ;
- enchaîner ingestion marché, benchmark et RSS ;
- lancer embeddings et indicateurs textuels ;
- lancer `dbt run` et `dbt test` ;
- mettre à jour les backtests ;
- créer les logs de pipeline ;
- planifier l’exécution quotidienne ;
- tester les erreurs et relances.

---

## 15. Tests et sécurité

### Livrable

Projet stable et sécurisé.

### Tâches

- finaliser les tests unitaires ;
- créer les tests d’intégration ;
- tester le pipeline de bout en bout ;
- vérifier les permissions IAM ;
- vérifier l’absence de secrets dans Git ;
- contrôler les coûts BigQuery ;
- corriger les anomalies bloquantes ;
- produire un rapport de recette.

---

## 16. Documentation et présentation

### Livrables

README final, documentation et soutenance.

### Tâches

- documenter l’installation et l’architecture ;
- documenter Terraform, dbt et le pipeline ;
- documenter les indicateurs et stratégies ;
- documenter les hypothèses et limites ;
- préparer les slides ;
- préparer la démonstration Streamlit ;
- créer un scénario de secours ;
- effectuer une répétition finale ;
- créer une version stable du dépôt.

---

## MVP obligatoire

Le MVP doit comprendre :

- Terraform et BigQuery ;
- ingestion Yahoo Finance et RSS ;
- projet dbt testé ;
- SMA, RSI et Stochastic RSI ;
- embeddings et sentiment ;
- `news_pressure_score` ;
- quatre stratégies ;
- moteur de backtesting avec frais et exécution à J+1 ;
- comparaison aux benchmarks ;
- dashboard Streamlit ;
- orchestration quotidienne ;
- tests critiques ;
- documentation finale.

---

## Ordre final des livrables

1. Cadrage et dépôt Git
2. Infrastructure Terraform
3. Ingestion marché et benchmarks
4. Ingestion RSS
5. Projet dbt
6. Indicateurs techniques
7. Embeddings et indicateurs textuels
8. Moteur de backtesting
9. Métriques et validation hors échantillon
10. Dashboard Streamlit
11. Orchestration
12. Tests et sécurité
13. Documentation et présentation

---

*Document de référence — Backlog synthétique — Version 1.1*