# Facebook Car Monitor

Surveille les nouvelles annonces de voitures sur Facebook Marketplace (via un
Actor Apify) et envoie une notification Telegram pour chaque nouvelle annonce
qui correspond à vos critères.

MVP volontairement simple : Python + Apify + Telegram + fichiers JSON. Pas de
base de données, pas de Docker, pas de frontend.

## 1. Installer Python

Python 3.10+ est requis. Vérifiez avec :

```
python --version
```

## 2. Créer un environnement virtuel

Windows :

```
python -m venv .venv
.venv\Scripts\activate
```

## 3. Installer les dépendances

```
pip install -r requirements.txt
```

## 4. Créer le fichier `.env`

Copiez `.env.example` vers `.env` et remplissez les valeurs :

```
copy .env.example .env
```

- `APIFY_API_TOKEN` : votre token API Apify (voir étape 6)
- `TELEGRAM_BOT_TOKEN` : token du bot Telegram (voir étape 5)
- `TELEGRAM_CHAT_ID` : identifiant du chat qui recevra les notifications (voir étape 5)
- `DRY_RUN` : `true` pour tester sans envoyer de vrais messages Telegram, `false` pour les envoyer réellement

Ne committez jamais `.env` (déjà exclu via `.gitignore`).

## 5. Créer le bot Telegram et récupérer le Chat ID

1. Dans Telegram, parlez à [@BotFather](https://t.me/BotFather), envoyez `/newbot` et suivez les instructions. Vous obtenez un token du type `123456:ABC-DEF...`.
2. Envoyez un message quelconque à votre nouveau bot (pour qu'il ait un chat à vous répondre).
3. Ouvrez dans un navigateur :
   `https://api.telegram.org/bot<VOTRE_TOKEN>/getUpdates`
4. Repérez `"chat":{"id": ...}` dans la réponse JSON : c'est votre `TELEGRAM_CHAT_ID`.

## 6. Récupérer le token Apify

1. Créez un compte sur [apify.com](https://apify.com).
2. Allez dans **Settings > Integrations** pour récupérer votre token API personnel.
3. Mettez ce token dans `.env` sous `APIFY_API_TOKEN`.

## 7bis. Choisir le fournisseur de scraping (Apify ou Bright Data)

Le fournisseur utilisé pour récupérer les annonces est configurable dans
`config.json` via `scraper_provider` (`"apify"` par défaut, ou `"brightdata"`) :

```json
{
  "scraper_provider": "apify",
  "brightdata": {
    "dataset_id": "gd_lvt9iwuh6fbcwmx1a",
    "country": "BE",
    "results_limit": 40,
    "timeout_seconds": 180
  }
}
```

Les deux fournisseurs réutilisent la même URL Marketplace (`search.*` /
`custom_url`) et renvoient le même modèle `CarListing` : le reste du
programme (filtres, déduplication, `seen_listings.json`, Telegram) ne sait
pas d'où viennent les données. Pour utiliser Bright Data, ajoutez
`BRIGHTDATA_API_KEY` dans `.env` et passez `scraper_provider` à `"brightdata"`.

✅ **Validé par un run réel** (2026-09-23) : de vraies annonces belges près de
Liège ont été récupérées avec succès. Détails techniques importants :
- L'appel utilise `POST /datasets/v3/scrape` avec les paramètres
  `type=discover_new&discover_by=url` (pas l'endpoint `/trigger` habituel des
  gros jobs asynchrones - la découverte par URL fonctionne en synchrone pour
  un volume raisonnable).
- La réponse est en **NDJSON** (un objet JSON par ligne), pas un tableau JSON
  - géré automatiquement par `brightdata_client._parse_records()`.
- Un champ `country` (ex: `"BE"`) doit être envoyé avec l'URL pour un ciblage
  géographique correct.
- Le champ `car_miles`, quand Facebook l'expose, est utilisé directement pour
  le kilométrage (plus fiable que l'extraction par texte utilisée en repli).
- Si Bright Data bascule malgré tout sur un job asynchrone plus long (gros
  volume), le code retombe automatiquement sur le flux `progress`/`snapshot`.

## 7. Configurer l'Actor Apify

Ce projet utilise l'Actor officiel `apify/facebook-marketplace-scraper`.
Aucun abonnement n'est requis : il est facturé à l'usage (~quelques centimes
par run pour une dizaine d'annonces).

Le nom de l'Actor et tous les paramètres de recherche se trouvent dans
`config.json` :

```json
{
  "search": {
    "custom_url": "",
    "location_name": "Liege, Belgium",
    "location_id": "112128398804880",
    "category": "vehicles",
    "radius_km": 150,
    "days_since_listed": 1,
    "sort_by": "creation_time_descend",
    "exact": false
  },
  "apify": {
    "actor_id": "apify/facebook-marketplace-scraper",
    "results_limit": 40,
    "include_listing_details": true,
    "max_total_charge_usd": 0.5
  }
}
```

`location_id` est l'identifiant interne Facebook du lieu (pas un nom de ville
en texte libre : Facebook n'accepte que cet identifiant ou un slug de ville
canonique pour filtrer par localisation). Celui de Liège (`112128398804880`)
est déjà renseigné. Pour changer de ville, ouvrez Facebook Marketplace dans un
navigateur, filtrez par la localisation souhaitée, et copiez l'identifiant
numérique présent dans l'URL générée (juste après `/marketplace/`).

### Personnaliser l'URL de recherche Marketplace

Par défaut, l'URL est construite automatiquement à partir de `location_id`,
`category`, `radius_km`, `days_since_listed`, `sort_by` et `exact` :

```
https://www.facebook.com/marketplace/<location_id>/<category>?daysSinceListed=<...>&radius=<...>&sortBy=<...>&exact=<...>
```

Pour aller plus loin (mots-clés, autre catégorie, filtres non couverts par les
champs ci-dessus, etc.) sans toucher au code, renseignez `custom_url` avec une
URL Facebook Marketplace complète — elle sera utilisée telle quelle et tous
les autres champs `search.*` seront ignorés :

```json
{
  "search": {
    "custom_url": "https://www.facebook.com/marketplace/112128398804880/vehicles?daysSinceListed=1&radius=150&sortBy=price_ascend&exact=false"
  }
}
```

⚠️ Seule l'URL de **catégorie** (`/marketplace/<id>/vehicles`) a été validée
comme fonctionnant en anonyme avec l'Actor **Apify**. L'URL `/search?query=...`
retourne vide avec Apify (nécessite une session connectée).

### Recherche par mot-clé (`search.query`) — Bright Data uniquement

Contrairement à Apify, **Bright Data supporte `/search` en anonyme** — validé
avec des données réelles le 2026-09-24. Renseigner `search.query` (et
optionnellement `search.category_id`) fait basculer `build_search_url()` vers
`/marketplace/<id>/search/?query=...` au lieu de la page de catégorie :

```json
{
  "search": {
    "query": "Véhicules",
    "category_id": "546583916084032"
  }
}
```

**Pourquoi** : certaines annonces ne sont pas correctement rangées par
Facebook dans sa catégorie "Véhicules" et sont donc invisibles à la page de
catégorie stricte, même pour un utilisateur connecté qui filtrerait par
catégorie. La recherche par mot-clé les capture en plus.

**Combinaison des deux sources** : quand `search.query` est configuré,
`brightdata_client.fetch_marketplace_listings()` interroge **les deux URLs**
à chaque cycle (catégorie **et** recherche mot-clé), puis fusionne les
résultats — elles ne renvoient pas exactement les mêmes annonces. La
déduplication existante (`storage.dedupe_listings`, par id) gère les
recoupements entre les deux. **Coût doublé par cycle** (2 appels Bright Data
au lieu d'1) en échange d'une meilleure couverture. Voir
`apify_client.build_discovery_urls()`.

**Contrepartie** : étant une recherche texte libre et non un filtre de
catégorie strict, elle peut occasionnellement remonter des objets non liés
aux véhicules (ex. observé réellement : un nettoyeur haute pression). C'est
géré par `filters.exclude_non_vehicle_keywords` (voir plus bas), un filtre
volontairement conservateur qui ne rejette que les titres correspondant
clairement à une catégorie connue non-véhicule, jamais une vraie annonce
juste parce que son titre est inhabituel.

⚠️ Ne configurez `search.query` que si `scraper_provider` est `"brightdata"`.
Avec `"apify"`, `fetch_marketplace_listings()` affiche un `[WARN]` explicite
si `query` est défini, car l'Actor Apify renverrait silencieusement 0 résultat.

⚠️ **Limite fondamentale, quelle que soit l'URL utilisée** : un scraper
anonyme (sans connexion) verra toujours moins d'annonces qu'un compte
Facebook connecté (contenu personnalisé, algorithme, restrictions
anti-scraping). Ce n'est pas un bug corrigible côté code — voir la discussion
dans l'historique du projet. Se connecter avec un vrai compte pour scraper
violerait les CGU de Facebook et n'est pas une option supportée ici.

### Contrôle des coûts Apify

- `results_limit: null` (défaut actuel, pour Apify comme pour Bright Data) =
  **aucun plafond** : toutes les annonces disponibles sont récupérées, puis
  filtrées côté Python. Mettez un nombre (ex: `40`) pour replafonner si vous
  voulez limiter le coût par scan plutôt que de tout récupérer.
- `include_listing_details: true` (défaut actuel) active l'add-on payant
  "Listing details" (~2x le coût par annonce), nécessaire pour obtenir la
  date de publication (`timestamp`), utilisée pour le tri chronologique et le
  filtre "depuis le dernier scan". Passez à `false` pour diviser ce coût par
  ~2, au prix de la perte de cette date exacte (voir plus haut). Le parseur
  gère les deux formats de champs (avec/sans détails) — voir les tests dans
  `tests/test_apify_client.py`.
- `max_total_charge_usd` plafonne la dépense d'un run côté Apify (paramètre
  officiel de l'API), indépendamment de tout bug éventuel côté Actor.
- Le prix n'est **pas** filtrable directement dans l'input de l'Actor (son
  schéma n'accepte que `startUrls`/`resultsLimit`/`includeListingDetails`).
  Un filtre `minPrice`/`maxPrice` dans l'URL Facebook n'a été vu fonctionner
  que sur l'endpoint `/search` (qui retourne vide en anonyme) ; sur la page
  de catégorie `/vehicles` réellement utilisée, ce n'est **pas validé** — le
  filtrage de prix reste donc fait côté Python (`filters.py`).

## 8. Ajuster votre filtre de prix

Toujours dans `config.json`, section `filters`. Le prix est le **seul filtre
métier** : une annonce est gardée si `min_price <= prix <= max_price`, quels
que soient son année ou son kilométrage (affichés dans Telegram s'ils sont
connus, mais jamais utilisés pour rejeter une annonce) :

```json
{
  "filters": {
    "min_price": 100,
    "max_price": 4000,
    "exclude_non_vehicle_keywords": true
  }
}
```

`exclude_non_vehicle_keywords` (défaut `true`) : filtre anti-bruit conservateur
utile surtout avec `search.query` (voir plus haut) — rejette un titre s'il
correspond clairement à une catégorie connue non-véhicule (nettoyeur,
aspirateur, meuble, électroménager...). Ne rejette jamais une vraie annonce
juste parce que son titre est inhabituel ou ne contient aucun mot-clé
reconnu. Passez à `false` pour désactiver entièrement. Voir
`filters.is_likely_non_vehicle()` et `tests/test_filters.py`.

Si le prix d'une annonce est absent ou impossible à parser, elle est toujours
rejetée (on ne devine jamais un prix).

## 9. Lancer le programme

```
python main.py
```

Le programme tourne en continu : il scanne, filtre, notifie, puis attend
`monitoring.interval_minutes` avant de recommencer. Arrêtez-le avec `Ctrl+C`.

### Mode "un seul cycle" (`RUN_ONCE`) — préparation pour GitHub Actions

Pour un hébergement gratuit futur via GitHub Actions (scheduled workflow), le
programme doit pouvoir exécuter **un seul scan puis se terminer** plutôt que
tourner en boucle indéfiniment :

- En local, sans rien configurer : comportement inchangé (boucle infinie).
- `RUN_ONCE=true` dans `.env` : exécute exactement un scan puis quitte.
- Sous GitHub Actions, c'est **automatique** : la variable `GITHUB_ACTIONS`
  (positionnée par GitHub lui-même) déclenche le mode "un seul cycle" sans
  rien configurer.
- Code de sortie du processus : `0` si le scan a réussi, `1` s'il a échoué
  (erreur du provider, Telegram, etc.) — un workflow GitHub Actions peut donc
  détecter un échec directement via le statut du job.

### Hébergement gratuit avec GitHub Actions

Le workflow `.github/workflows/monitor.yml` exécute un scan planifié (par
défaut toutes les heures - modifiable en éditant la ligne `cron:` du
fichier) sans que vous n'ayez de machine à faire tourner en continu.

**Mise en place :**

1. Sur GitHub : **Settings → Secrets and variables → Actions → New repository
   secret**, ajoutez : `APIFY_API_TOKEN`, `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_CHAT_ID`, `BRIGHTDATA_API_KEY`, `DRY_RUN` (mettez `false` une
   fois que vous êtes prêt à recevoir de vraies notifications).
2. Poussez `.github/workflows/monitor.yml` sur GitHub (`git add`, `commit`,
   `push`).
3. Le workflow se déclenche automatiquement selon le planning défini, ou
   manuellement via l'onglet **Actions → Facebook Marketplace Monitor → Run
   workflow**.

Chaque exécution fait exactement **un scan** (le mode `RUN_ONCE` s'active
automatiquement sous GitHub Actions), puis **recommit automatiquement**
`seen_listings.json` et `last_scan.json` dans le dépôt pour que l'état soit
conservé d'une exécution à l'autre - sans ça, chaque run repartirait de zéro
et vous recevriez les mêmes annonces en boucle.

Tant que `DRY_RUN=true` dans `.env`, les annonces qui seraient envoyées sont
seulement affichées dans le terminal (aucun message Telegram réel). Passez à
`DRY_RUN=false` une fois que vous avez vérifié que tout fonctionne comme prévu.

## 10. Lancer les tests

```
python -m unittest discover -s tests -t .
```

Les tests utilisent des données mockées : aucune requête réelle n'est faite à
Facebook ou à Apify.

## Structure du projet

| Fichier | Rôle |
|---|---|
| `main.py` | Boucle de monitoring (scan / filtre / notifie / attend) |
| `apify_client.py` | Appel de l'Actor Apify + conversion en `CarListing` |
| `filters.py` | Parsing de prix/km/année + logique de filtrage |
| `notifier.py` | Envoi des notifications Telegram |
| `storage.py` | Détection des doublons (`seen_listings.json`) + curseur du dernier scan (`last_scan.json`) |
| `models.py` | Modèle `CarListing` |
| `config.py` | Chargement de `config.json` et `.env` |

### Fraîcheur des annonces : `last_scan.json`

Facebook ne propose que des paliers larges pour `daysSinceListed` (ex: "dernières 24h"),
donc une annonce publiée il y a plusieurs heures peut être "nouvelle pour nous" sans
être réellement fraîche. Pour éviter ça, chaque scan réussi (hors `DRY_RUN`) enregistre
son heure de démarrage dans `last_scan.json`, et le scan suivant ne notifie que les
annonces publiées **depuis ce curseur** (en plus de la vérification par ID via
`seen_listings.json`). Les notifications sont aussi triées par ordre chronologique
(plus ancienne d'abord). Comme `seen_listings.json`, ce fichier n'est jamais modifié
en `DRY_RUN=true`.

## Limites connues du MVP

- L'Actor Apify ne renvoie pas de champ `year` ni `mileage` structuré : ces
  valeurs sont extraites par recherche de motif dans le titre et la
  description (FR/NL), uniquement pour affichage dans Telegram. Elles ne sont
  **jamais** utilisées pour filtrer une annonce : seul le prix compte.
- Le paramètre `daysSinceListed` de Facebook est appliqué côté Apify, puis
  revérifié côté Python à partir du champ `timestamp` retourné par l'Actor
  (nécessite `include_listing_details: true`, qui double approximativement le
  coût Apify par scan par rapport au mode sans détails).
- Le coût Apify affiché dans les logs (`Apify cost: $...`) est une estimation
  best-effort basée sur le dernier run du compte ; il peut être absent si
  l'API ne le retourne pas encore au moment de la lecture.
