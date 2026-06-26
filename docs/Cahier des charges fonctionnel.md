# Cahier des charges fonctionnel

# Cahier des charges fonctionnel synthétique

## Plateforme ELT et backtesting sur les matières premières

**Projet :** ELT Commodities & Backtesting

**Cadre :** M1 Ynov Data & IA — 2025-2026

**Présentation finale :** 7 juillet 2026

**Version :** 1.1

---

## 1. Objectif

Développer une plateforme permettant de :

- collecter des données de marché et des actualités financières ;
- calculer des indicateurs techniques et textuels ;
- tester plusieurs stratégies de trading ;
- comparer les résultats à des benchmarks ;
- visualiser les performances dans un dashboard Streamlit.

L’intelligence artificielle sera utilisée pour transformer les articles en indicateurs, et non pour prédire directement les prix.

---

## 2. Utilisateurs

### Analyste

Il consulte les marchés, les indicateurs, les signaux et les résultats des stratégies.

### Étudiant ou chercheur

Il teste différentes règles de trading et mesure l’apport des actualités financières.

### Administrateur technique

Il contrôle la fraîcheur des données, le statut du pipeline et les erreurs.

---

## 3. Périmètre

### Inclus

- 10 à 15 matières premières ;
- données journalières depuis le 1er janvier 2020 ;
- données OHLCV ;
- flux RSS financiers ;
- embeddings et sentiment ;
- indicateurs techniques ;
- backtests ;
- benchmarks ;
- dashboard Streamlit ;
- infrastructure Google Cloud avec Terraform.

### Exclu

- trading réel ;
- données en temps réel ;
- prédiction directe des prix par IA ;
- connexion à un broker ;
- recommandations d’investissement.

---

## 4. Fonctions principales

### F1 — Collecter les données de marché

Le système doit récupérer quotidiennement :

- open ;
- high ;
- low ;
- close ;
- volume ;
- symbole ;
- date.

Les données doivent être stockées dans BigQuery, sans doublon.

---

### F2 — Collecter les actualités

Le système doit récupérer les articles issus de flux RSS financiers.

Chaque article doit contenir :

- titre ;
- source ;
- date ;
- URL ;
- texte ou résumé.

Les articles doivent être nettoyés et dédupliqués.

---

### F3 — Associer les articles aux matières premières

Chaque article doit être transformé en embedding et comparé à chaque matière première.

Le système doit produire :

- un score de pertinence ;
- un score de sentiment ;
- un score de nouveauté.

Un article peut être associé à plusieurs matières premières.

---

### F4 — Calculer les indicateurs textuels

Le système doit produire quotidiennement :

- `news_pressure_score` ;
- `news_surprise_20d` ;
- `news_volume` ;
- `novelty_score` ;
- `sentiment_dispersion`.

Ces indicateurs doivent être calculés par matière première.

---

### F5 — Calculer les indicateurs techniques

Le système doit calculer au minimum :

- SMA 20 ;
- SMA 50 ;
- RSI 14 ;
- Stochastic RSI ;
- MACD ;
- ATR ;
- volatilité ;
- rendements journaliers.

---

### F6 — Exécuter des stratégies

Le système doit proposer au minimum :

1. Buy and Hold ;
2. croisement de moyennes mobiles ;
3. moyennes mobiles avec Stochastic RSI ;
4. stratégie technique avec filtre RSS.

Les paramètres doivent être configurables.

---

### F7 — Exécuter un backtest

L’utilisateur doit pouvoir choisir :

- une matière première ;
- une stratégie ;
- une période ;
- un capital initial ;
- des frais ;
- un slippage ;
- un benchmark.

Les signaux calculés à J doivent être exécutés au plus tôt à J+1.

---

### F8 — Calculer les performances

Le système doit calculer :

- rendement cumulé ;
- rendement annualisé ;
- volatilité ;
- ratio de Sharpe ;
- ratio de Sortino ;
- maximum drawdown ;
- win rate ;
- nombre de transactions ;
- frais cumulés ;
- performance par rapport au benchmark.

---

### F9 — Comparer les stratégies

L’utilisateur doit pouvoir comparer :

- stratégie technique seule ;
- stratégie technique avec filtre RSS ;
- Buy and Hold ;
- benchmark global.

Les comparaisons doivent utiliser la même période, le même capital et les mêmes frais.

---

### F10 — Superviser le pipeline

Le système doit afficher :

- date du dernier run ;
- statut du pipeline ;
- nombre de lignes chargées ;
- erreurs rencontrées ;
- données manquantes ;
- tests dbt en échec.

---

## 5. Dashboard Streamlit

Le dashboard comprendra les pages suivantes :

| Page | Contenu |
| --- | --- |
| Market Overview | Prix, variations, tendance et volatilité |
| Indicators | Indicateurs techniques et signaux |
| News Indicators | Pression des actualités, surprise et volume |
| Strategy Explorer | Choix des paramètres et de la stratégie |
| Backtest | Equity curve, drawdown et transactions |
| Comparison | Comparaison des stratégies et benchmarks |
| Data Quality | Statut du pipeline et qualité des données |

---

## 6. Règles métier

- aucune donnée future ne doit être utilisée ;
- un signal produit à J est exécuté à J+1 ;
- les frais doivent être intégrés ;
- les données marché doivent être uniques par symbole et par date ;
- un article ne doit contribuer à un indicateur que s’il dépasse un seuil de pertinence ;
- les paramètres du test final ne doivent pas être calibrés sur la période hors échantillon ;
- chaque backtest doit conserver ses paramètres et sa date d’exécution.

---

## 7. Découpage temporel

| Période | Usage |
| --- | --- |
| 2020–2023 | Calibration |
| 2024 | Validation |
| 2025–J-1 | Test final hors échantillon |

---

## 8. Infrastructure

Terraform devra permettre de créer et configurer :

- les datasets BigQuery ;
- les comptes de service ;
- les permissions IAM ;
- les API Google Cloud nécessaires ;
- éventuellement un bucket Cloud Storage.

BigQuery contiendra trois zones :

| Dataset | Contenu |
| --- | --- |
| `raw` | Données brutes |
| `dbt_finance` | Transformations intermédiaires |
| `mart` | Données destinées aux backtests et au dashboard |

---

## 9. Critères d’acceptation

Le projet sera accepté si :

- au moins 10 matières premières sont disponibles ;
- les données couvrent la période 2020 à J-1 ;
- les flux RSS sont ingérés et dédupliqués ;
- les embeddings et scores textuels sont calculés ;
- au moins quatre stratégies sont disponibles ;
- les backtests prennent en compte les frais ;
- les signaux respectent l’exécution à J+1 ;
- les performances sont comparées à un benchmark ;
- le dashboard permet de consulter les résultats ;
- l’infrastructure peut être déployée avec Terraform ;
- les traitements et limites sont documentés.

---

## 10. Livrables

- infrastructure Terraform ;
- pipeline ELT Python ;
- projet dbt ;
- indicateurs techniques ;
- indicateurs textuels ;
- moteur de backtesting ;
- dashboard Streamlit ;
- notebooks d’analyse ;
- README ;
- présentation finale.

---

*Document de référence — Cahier des charges fonctionnel synthétique — Version 1.1*