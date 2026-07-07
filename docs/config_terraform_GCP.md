# Tuto — Configurer Terraform avec Google Cloud BigQuery

Ce document explique, étape par étape, comment utiliser Terraform pour créer l'infrastructure Google Cloud du projet.

L'objectif est de provisionner automatiquement :

- les APIs Google Cloud nécessaires ;
- les datasets BigQuery `raw`, `dbt_finance` et `mart` ;
- un service account pour le pipeline ELT ;
- les droits IAM minimaux pour écrire et lire les données ;
- éventuellement un bucket Cloud Storage optionnel.

---

## 1. À quoi sert Terraform dans ce projet ?

Terraform permet de décrire l'infrastructure dans des fichiers de code.

Au lieu de créer les datasets BigQuery à la main dans la console Google Cloud, on écrit :

```hcl
resource "google_bigquery_dataset" "raw" {
  dataset_id = "raw"
  location   = "EU"
}
```

Puis Terraform applique cette configuration dans Google Cloud.

Dans ce projet, Terraform sert à garantir que l'environnement BigQuery est :

- reproductible ;
- documenté ;
- versionné ;
- recréable si besoin ;
- cohérent entre les membres du projet.

---

## 2. Architecture créée par Terraform

```text
Google Cloud Project
├── APIs activées
│   ├── BigQuery API
│   ├── BigQuery Storage API
│   ├── IAM API
│   ├── Service Usage API
│   └── Cloud Resource Manager API
├── BigQuery
│   ├── dataset raw
│   ├── dataset dbt_finance
│   └── dataset mart
├── IAM
│   └── service account du pipeline
└── Cloud Storage optionnel
    └── bucket temporaire ou artefacts
```

---

## 3. Rôle des trois datasets BigQuery

### `raw`

Zone de données brutes.

Elle contient ce qui arrive depuis les scripts Python :

```text
raw.market_data_raw
raw.benchmarks_raw
raw.news_raw
raw.news_embeddings_raw
raw.news_sentiment_raw
raw.article_commodity_relevance_raw
raw.news_features_raw
raw.pipeline_logs_raw
```

On y met les données proches de la source, avec peu de logique métier.

---

### `dbt_finance`

Zone de transformation dbt.

Elle contient les modèles intermédiaires :

```text
landing
staging
warehouse
```

Exemples :

```text
dbt_finance.stg_commodity_prices
dbt_finance.stg_news
dbt_finance.int_technical_indicators
dbt_finance.int_commodity_news_features
```

Cette zone sert à nettoyer, typer, dédupliquer, joindre et enrichir les données.

---

### `mart`

Zone finale pour l'analyse.

Elle contient les tables propres utilisées par :

- le moteur de backtesting ;
- le dashboard Streamlit ;
- les comparaisons de stratégies.

Exemples :

```text
mart.mart_strategy_signals
mart.mart_backtest_trades
mart.mart_backtest_daily
mart.mart_strategy_metrics
mart.mart_dashboard_overview
```

---

## 4. Fichiers Terraform du projet

Les fichiers sont placés dans :

```text
infrastructure/
```

Structure :

```text
infrastructure/
├── providers.tf
├── variables.tf
├── main.tf
├── bigquery.tf
├── iam.tf
├── storage.tf
├── outputs.tf
└── environments/
    └── example.tfvars
```

### `providers.tf`

Déclare Terraform et le provider Google.

Le provider est le plugin qui permet à Terraform de parler à Google Cloud.

---

### `variables.tf`

Déclare les paramètres du déploiement.

Exemples :

```text
project_id
region
location
raw_dataset_id
dbt_dataset_id
mart_dataset_id
service_account_id
```

Ces variables évitent d'écrire les valeurs en dur dans les ressources.

---

### `main.tf`

Active les APIs Google Cloud nécessaires.

Exemple :

```text
bigquery.googleapis.com
iam.googleapis.com
serviceusage.googleapis.com
```

Sans ces APIs, Terraform ne peut pas créer les ressources correspondantes.

---

### `bigquery.tf`

Crée les datasets BigQuery :

```text
raw
dbt_finance
mart
```

Tous utilisent la même localisation, par exemple `EU`.

Important : BigQuery impose de faire attention à la localisation. Si les datasets sont en `EU`, les jobs dbt et les requêtes doivent aussi respecter cette localisation.

---

### `iam.tf`

Crée le service account du pipeline.

Ce compte sera utilisé par les scripts Python, dbt et éventuellement Streamlit pour accéder à BigQuery.

Le service account reçoit :

- `roles/bigquery.jobUser` au niveau projet, pour lancer des requêtes BigQuery ;
- `roles/bigquery.dataEditor` sur les datasets du projet, pour créer et modifier les tables nécessaires.

On évite volontairement de donner des rôles trop larges comme `Owner` ou `Editor`.

---

### `storage.tf`

Crée un bucket Cloud Storage optionnel.

Dans le MVP, il peut rester désactivé.

Il pourra servir plus tard à stocker :

- exports temporaires ;
- artefacts ;
- fichiers intermédiaires volumineux ;
- sauvegardes ponctuelles.

---

### `outputs.tf`

Affiche les informations utiles après le déploiement.

Exemples :

```text
raw_dataset_id
dbt_dataset_id
mart_dataset_id
pipeline_service_account_email
```

Ces outputs aident à configurer ensuite `.env`, dbt ou les scripts Python.

---

## 5. Pré-requis locaux

Avant d'utiliser Terraform, il faut installer :

- Terraform ;
- Google Cloud CLI ;
- un compte Google Cloud avec accès au projet ;
- un projet Google Cloud avec facturation activée.

Vérifier Terraform :

```bash
terraform version
```

Vérifier Google Cloud CLI :

```bash
gcloud version
```

---

## 6. Préparer le projet dans l'interface web GCP

Avant de lancer Terraform, il faut préparer quelques éléments dans la console web Google Cloud.

Console :

```text
https://console.cloud.google.com/
```

L'objectif de cette partie est de vérifier que le projet GCP existe, que la facturation est active et que ton compte a les droits nécessaires.

---

### 6.1 Créer ou sélectionner un projet Google Cloud

Dans l'interface web :

```text
Console Google Cloud
→ Sélecteur de projet en haut de l'écran
→ Nouveau projet
```

Renseigner :

```text
Nom du projet : elt-commodities-backtesting
Organisation : aucune ou celle de ton école/compte
Emplacement : valeur par défaut
```

Après création, Google Cloud génère un `project_id`.

Exemple :

```text
elt-commodities-123456
```

Important : le `project_id` n'est pas toujours identique au nom affiché du projet.

C'est cette valeur qu'il faudra mettre dans :

```text
infrastructure/environments/dev.tfvars
```

Ligne concernée :

```hcl
project_id = "elt-commodities-123456"
```

---

### 6.2 Vérifier ou activer la facturation

BigQuery nécessite généralement un compte de facturation actif, même si le projet reste dans les limites gratuites.

Dans l'interface web :

```text
Menu ☰
→ Billing / Facturation
→ Vérifier que le projet est lié à un compte de facturation
```

Si le projet n'est pas lié :

```text
Billing
→ Link a billing account / Associer un compte de facturation
→ Sélectionner le compte
→ Confirmer
```

Sans facturation active, Terraform peut échouer au moment d'activer les APIs ou de créer les ressources.

---

### 6.3 Vérifier tes droits IAM

Terraform va créer des ressources. Ton compte utilisateur doit donc avoir assez de droits sur le projet.

Dans l'interface web :

```text
Menu ☰
→ IAM & Admin
→ IAM
```

Chercher ton adresse Google.

Pour un projet académique, le plus simple est d'avoir temporairement :

```text
Owner
```

Ou, en plus strict :

```text
Service Usage Admin
BigQuery Admin
Service Account Admin
Project IAM Admin
Storage Admin si bucket activé
```

À retenir :

- `Owner` est pratique pour initialiser un projet étudiant ;
- en entreprise, on éviterait `Owner` et on donnerait des rôles plus précis ;
- le service account créé par Terraform aura ensuite des droits plus limités.

---

### 6.4 Ne pas créer les datasets à la main

Dans la console BigQuery, il est possible de créer les datasets manuellement.

Mais pour ce projet, il vaut mieux ne pas le faire.

Terraform doit créer :

```text
raw
dbt_finance
mart
```

Pourquoi ?

- pour garder l'infrastructure reproductible ;
- pour éviter les différences entre ce qui est dans GCP et ce qui est dans le code ;
- pour pouvoir refaire le projet proprement sur un autre compte.

Dans l'interface web, BigQuery servira surtout à vérifier après coup que Terraform a bien créé les datasets.

---

### 6.5 Vérifier les APIs dans la console

Terraform active les APIs automatiquement, mais tu peux vérifier leur statut dans l'interface.

Dans l'interface web :

```text
Menu ☰
→ APIs & Services
→ Enabled APIs & services
```

APIs attendues après `terraform apply` :

```text
BigQuery API
BigQuery Storage API
Cloud Resource Manager API
IAM Service Account Credentials API ou IAM API
Service Usage API
Cloud Storage API
```

Avant `terraform apply`, certaines peuvent ne pas être encore actives. C'est normal.

---

### 6.6 Où vérifier les ressources après Terraform ?

Après `terraform apply`, les ressources seront visibles dans plusieurs menus.

| Ressource | Où la voir dans GCP |
| --- | --- |
| Datasets BigQuery | `BigQuery` → projet → datasets |
| Service account | `IAM & Admin` → `Service Accounts` |
| Rôles IAM | `IAM & Admin` → `IAM` |
| APIs activées | `APIs & Services` → `Enabled APIs & services` |
| Bucket optionnel | `Cloud Storage` → `Buckets` |

---

### 6.7 Résumé de ce qu'il faut faire dans le web

```text
1. Aller sur https://console.cloud.google.com/
2. Créer ou sélectionner le projet GCP
3. Copier le project_id
4. Vérifier que la facturation est active
5. Vérifier que ton compte a les bons rôles IAM
6. Ne pas créer les datasets BigQuery à la main
7. Laisser Terraform créer l'infrastructure
8. Revenir dans la console pour vérifier les ressources créées
```

---

## 7. Se connecter à Google Cloud

Connexion utilisateur :

```bash
gcloud auth login
```

Connexion pour les identifiants applicatifs locaux :

```bash
gcloud auth application-default login
```

Définir le projet par défaut :

```bash
gcloud config set project TON_PROJECT_ID
```

Vérifier le projet actif :

```bash
gcloud config get-value project
```

---

## 8. Préparer le fichier de variables

Un exemple est fourni ici :

```text
infrastructure/environments/example.tfvars
```

Il ne faut pas mettre de secrets dedans.

Créer un fichier local `dev.tfvars` :

```bash
cp infrastructure/environments/example.tfvars infrastructure/environments/dev.tfvars
```

Modifier :

```hcl
project_id  = "ton-id-projet-gcp"
region      = "europe-west1"
location    = "EU"
environment = "dev"

raw_dataset_id = "raw"
dbt_dataset_id = "dbt_finance"
mart_dataset_id = "mart"

service_account_id           = "etl-commodities-pipeline"
service_account_display_name = "ELT Commodities Pipeline"

create_storage_bucket = false
storage_bucket_name   = null
```

Si tu actives le bucket :

```hcl
create_storage_bucket = true
storage_bucket_name   = "ton-project-id-elt-commodities-artifacts"
```

Si `storage_bucket_name` reste à `null`, Terraform génère un nom par défaut avec le `project_id`.

Le nom d'un bucket Cloud Storage doit être globalement unique dans Google Cloud.

---

## 9. Initialiser Terraform

Depuis la racine du projet :

```bash
make infra-init
```

Ou directement :

```bash
terraform -chdir=infrastructure init
```

Cette commande télécharge le provider Google et prépare le dossier `.terraform/`.

Le dossier `.terraform/` est ignoré par Git.

---

## 10. Formater et valider

Formater les fichiers Terraform :

```bash
terraform -chdir=infrastructure fmt
```

Valider la syntaxe :

```bash
terraform -chdir=infrastructure validate
```

Si `validate` échoue, il faut corriger les fichiers `.tf` avant de continuer.

---

## 11. Prévisualiser avec `terraform plan`

La commande `plan` montre ce que Terraform va créer, modifier ou supprimer.

```bash
terraform -chdir=infrastructure plan -var-file=environments/dev.tfvars
```

Ou via Makefile :

```bash
make infra-plan
```

À cette étape, rien n'est encore créé.

Il faut lire le plan et vérifier :

- le bon `project_id` ;
- la localisation BigQuery ;
- les datasets ;
- le service account ;
- les rôles IAM ;
- l'absence de ressource inattendue.

---

## 12. Déployer avec `terraform apply`

Quand le plan est correct :

```bash
terraform -chdir=infrastructure apply -var-file=environments/dev.tfvars
```

Ou :

```bash
make infra-apply
```

Terraform affiche à nouveau le plan, puis demande confirmation.

Répondre :

```text
yes
```

Après le déploiement, Terraform affiche les outputs.

---

## 13. Vérifier dans Google Cloud

Après `terraform apply`, on vérifie à deux endroits :

- dans le terminal, avec `gcloud` et `bq` ;
- dans l'interface web GCP, pour confirmer visuellement.

---

### 13.1 Vérifier les datasets BigQuery en ligne de commande

Vérifier les datasets BigQuery :

```bash
bq ls --project_id TON_PROJECT_ID
```

Tu dois voir :

```text
raw
dbt_finance
mart
```

---

### 13.2 Vérifier les datasets dans l'interface web

Dans la console :

```text
Menu ☰
→ BigQuery
→ Explorer
→ Sélectionner ton projet
```

Tu dois voir les datasets :

```text
raw
dbt_finance
mart
```

Cliquer sur chaque dataset et vérifier :

```text
Dataset ID : raw / dbt_finance / mart
Location : EU
```

Au début, ces datasets peuvent être vides. C'est normal : Terraform crée les zones BigQuery, mais les tables seront créées plus tard par les scripts Python et dbt.

---

### 13.3 Vérifier le service account en ligne de commande

Vérifier le service account :

```bash
gcloud iam service-accounts list --project TON_PROJECT_ID
```

Tu dois voir un compte proche de :

```text
etl-commodities-pipeline@TON_PROJECT_ID.iam.gserviceaccount.com
```

---

### 13.4 Vérifier le service account dans l'interface web

Dans la console :

```text
Menu ☰
→ IAM & Admin
→ Service Accounts
```

Tu dois voir :

```text
ELT Commodities Pipeline
etl-commodities-pipeline@TON_PROJECT_ID.iam.gserviceaccount.com
```

Ce compte sera utilisé par :

- les scripts Python d'ingestion ;
- dbt ;
- éventuellement Streamlit si le dashboard lit BigQuery directement.

---

### 13.5 Vérifier les droits IAM dans l'interface web

Dans la console :

```text
Menu ☰
→ IAM & Admin
→ IAM
```

Chercher le service account :

```text
etl-commodities-pipeline@TON_PROJECT_ID.iam.gserviceaccount.com
```

Il doit avoir au minimum :

```text
BigQuery Job User
```

Les droits `BigQuery Data Editor` sont appliqués au niveau des datasets. Ils peuvent donc être visibles dans les permissions des datasets BigQuery plutôt que dans la liste IAM globale.

Pour vérifier les droits dataset :

```text
BigQuery
→ Explorer
→ Cliquer sur le dataset raw
→ Sharing / Permissions
```

Faire la même chose pour :

```text
dbt_finance
mart
```

---

### 13.6 Vérifier les APIs activées dans l'interface web

Dans la console :

```text
Menu ☰
→ APIs & Services
→ Enabled APIs & services
```

Vérifier que les APIs nécessaires apparaissent, notamment :

```text
BigQuery API
BigQuery Storage API
Cloud Resource Manager API
IAM API
Service Usage API
Cloud Storage API
```

---

### 13.7 Vérifier le bucket optionnel

Seulement si `create_storage_bucket = true`.

Dans la console :

```text
Menu ☰
→ Cloud Storage
→ Buckets
```

Tu dois voir le bucket configuré dans :

```text
infrastructure/environments/dev.tfvars
```

Si `create_storage_bucket = false`, aucun bucket n'est attendu.

---

## 14. Configurer l'authentification locale sans clé JSON

Pour exécuter les scripts Python localement, il faudra une authentification.

La bonne approche pour ce projet est d'utiliser les **Application Default Credentials** de Google Cloud.

Cela évite de créer un fichier de clé JSON pour le service account.

Cette approche est recommandée parce que certains projets Google Cloud bloquent volontairement la création de clés avec la contrainte :

```text
constraints/iam.disableServiceAccountKeyCreation
```

Si tu vois cette erreur :

```text
Key creation is not allowed on this service account.
```

Ce n'est pas une erreur de commande. C'est une règle de sécurité du projet GCP.

---

### 14.1 Connexion recommandée pour le développement local

Se connecter avec son compte Google :

```bash
gcloud auth login
```

Créer les credentials applicatifs locaux :

```bash
gcloud auth application-default login
```

Définir le projet actif :

```bash
gcloud config set project TON_PROJECT_ID
```

Vérifier :

```bash
gcloud auth list
gcloud auth application-default print-access-token
gcloud config get-value project
```

Avec cette méthode, les bibliothèques Python Google utilisent automatiquement les credentials locaux.

Il n'y a pas besoin de créer :

```text
./credentials/pipeline-sa.json
```

---

### 14.2 Configurer `.env`

Créer ensuite `.env` depuis `.env.example` :

```bash
cp .env.example .env
```

Puis renseigner :

```text
GOOGLE_CLOUD_PROJECT=TON_PROJECT_ID
BIGQUERY_LOCATION=EU
GOOGLE_APPLICATION_CREDENTIALS=
```

`GOOGLE_APPLICATION_CREDENTIALS` reste vide parce qu'on utilise `gcloud auth application-default login`.

Le fichier `.env` sert donc surtout à donner au code :

- le projet GCP ;
- la localisation BigQuery ;
- les paramètres applicatifs du projet.

---

### 14.3 Option avancée : impersonation du service account

Si tu veux exécuter localement les commandes en te faisant passer temporairement pour le service account, tu peux utiliser l'impersonation.

Dans ce cas, ton utilisateur doit avoir le rôle suivant sur le service account :

```text
Service Account Token Creator
```

Commande :

```bash
gcloud auth application-default login \
  --impersonate-service-account=etl-commodities-pipeline@TON_PROJECT_ID.iam.gserviceaccount.com
```

Cette méthode reste sans clé JSON.

Elle est plus propre qu'un fichier de clé, mais elle demande une configuration IAM supplémentaire.

Pour le projet actuel, l'approche simple avec `gcloud auth application-default login` suffit.

---

## 15. Comment les scripts Python utilisent cette infra

Le fichier `.env` indique au code Python :

```text
GOOGLE_CLOUD_PROJECT
BIGQUERY_LOCATION
```

Si `GOOGLE_APPLICATION_CREDENTIALS` est vide, les bibliothèques Google utilisent automatiquement les Application Default Credentials créés par :

```bash
gcloud auth application-default login
```

Le fichier `config/settings.yml` indique :

```text
raw_dataset: raw
dbt_dataset: dbt_finance
mart_dataset: mart
```

Le flux devient :

```text
scripts Python
→ lisent .env + config/settings.yml
→ se connectent à BigQuery avec les credentials locaux gcloud
→ écrivent dans raw
→ dbt transforme dans dbt_finance
→ dbt expose dans mart
```

---

## 16. Comment dbt utilise cette infra

dbt devra être configuré pour écrire dans BigQuery.

Le projet dbt utilisera :

```text
project_id = TON_PROJECT_ID
dataset    = dbt_finance
location   = EU
method     = oauth
```

Avec `method = oauth`, dbt utilise les credentials créés par :

```bash
gcloud auth application-default login
```

dbt lira les sources dans `raw`, puis produira :

```text
dbt_finance.stg_*
dbt_finance.int_*
mart.mart_*
```

La configuration précise de dbt sera faite lors de l'étape dédiée au projet dbt.

---

## 17. Détruire l'infrastructure

Pour supprimer les ressources Terraform :

```bash
terraform -chdir=infrastructure destroy -var-file=environments/dev.tfvars
```

Attention :

- `destroy` supprime les ressources gérées par Terraform ;
- les datasets BigQuery peuvent contenir des données importantes ;
- dans ce projet, `delete_contents_on_destroy = false` protège contre la suppression automatique de datasets non vides ;
- il faut exporter ou sauvegarder les données avant toute suppression volontaire.

Ne jamais lancer `destroy` sans être sûr du projet GCP actif.

---

## 18. Fichiers à ne jamais commiter

Ne pas commiter :

```text
.env
*.tfstate
*.tfstate.*
.terraform/
credentials/*.json
service-account*.json
infrastructure/environments/dev.tfvars
```

Ces fichiers peuvent contenir :

- des chemins locaux ;
- des identifiants ;
- l'état réel de l'infrastructure ;
- des informations sensibles.

Même si l'approche recommandée évite les clés JSON, ces règles restent utiles pour empêcher un accident si un fichier de credentials est créé plus tard.

---

## 19. Résumé du flux Terraform

```text
1. Installer Terraform et gcloud
2. Préparer ou sélectionner le projet dans la console web GCP
3. Vérifier la facturation dans la console web GCP
4. Vérifier les droits IAM dans la console web GCP
5. Se connecter avec gcloud auth login
6. Se connecter avec gcloud auth application-default login
7. Copier example.tfvars vers dev.tfvars
8. Renseigner project_id
9. Lancer terraform init
10. Lancer terraform validate
11. Lancer terraform plan
12. Lire le plan
13. Lancer terraform apply
14. Vérifier les ressources dans la console web GCP
15. Configurer .env pour les scripts Python
```

---

## 20. Commandes rapides

Depuis la racine du projet :

```bash
make infra-init
make infra-validate
make infra-plan
make infra-apply
```

Commandes directes équivalentes :

```bash
terraform -chdir=infrastructure init
terraform -chdir=infrastructure validate
terraform -chdir=infrastructure plan -var-file=environments/dev.tfvars
terraform -chdir=infrastructure apply -var-file=environments/dev.tfvars
```

---

## 21. Ce que Terraform ne fait pas encore

Terraform crée l'infrastructure, mais il ne fait pas tout.

Il ne fait pas encore :

- l'ingestion Yahoo Finance ;
- l'ingestion RSS ;
- la création des tables BigQuery détaillées ;
- les modèles dbt ;
- les backtests ;
- le dashboard Streamlit.

Ces éléments seront développés dans les étapes suivantes du projet.
