# IKA COMPTEUR

Application web de compteur de visite. Ce dépôt contient le socle : authentification (avec double
authentification), gestion des utilisateurs, historique des actions, tableau de bord et pages d'erreur.

- **Backend** : FastAPI, SQLAlchemy 2.0 (async, asyncpg), Alembic (psycopg2), Pydantic v2, Pydantic Settings
- **Sécurité** : python-jose (JWT), bcrypt, itsdangerous (sessions signées), pyotp + qrcode (OTP), cryptography (Fernet)
- **Exports** : reportlab (PDF), openpyxl (Excel)
- **Frontend** : Jinja2, Bootstrap 5.3 et Bootstrap Icons, servis en local (aucun CDN)
- **Tests** : pytest, pytest-asyncio, httpx

## Prérequis

- Python 3.12 ou plus récent
- PostgreSQL 14 ou plus récent

## Installation

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # puis renseigner les valeurs (voir ci-dessous)
```

## Configuration (.env)

Toutes les variables sont décrites dans `.env.example`. Le fichier `.env` n'est jamais versionné.
Les variables d'environnement du système l'emportent sur le fichier `.env`.

| Variable | Rôle |
| --- | --- |
| `APP_ENV` | `development`, `test` ou `production` (valeur par défaut : `production`). |
| `APP_DEBUG` | Doit valoir `false` en production (vérifié au démarrage). |
| `APP_BASE_URL` | Adresse publique de l'application. Elle sert aux liens envoyés par e-mail et, par défaut, à CORS. |
| `SECRET_KEY` | Clé longue et aléatoire, 32 caractères minimum. Voir l'encadré ci-dessous. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Durée de validité du JWT (60 par défaut). |
| `SESSION_EXPIRE_MINUTES` | Durée de vie du cookie de session (480 par défaut). |
| `PASSWORD_RESET_EXPIRE_MINUTES` | Durée de validité d'un lien de réinitialisation (30 par défaut). |
| `COOKIE_SECURE` | Attribut `Secure` des cookies. Voir la section Sécurité. |
| `ALLOWED_HOSTS` | Hôtes acceptés, séparés par des virgules (par défaut `127.0.0.1,localhost`). |
| `CORS_ORIGINS` | Origines CORS autorisées, séparées par des virgules. Vide = `APP_BASE_URL`. |
| `DATABASE_URL` | URL asyncpg (`postgresql+asyncpg://…`). Alembic la convertit automatiquement vers psycopg2. |
| `TEST_DATABASE_URL` | Tests uniquement, facultatif. Vide = base de `DATABASE_URL` suffixée par `_test`. |
| `SMTP_*`, `MAIL_FROM*` | Serveur d'envoi des e-mails. Voir l'encadré ci-dessous. |
| `FIRST_ADMIN_*` | Adresse, mot de passe et nom du premier administrateur (voir plus bas). |

**`SECRET_KEY`** signe les JWT et les sessions, et chiffre les secrets OTP. Si elle change,
les secrets OTP enregistrés deviennent illisibles. En production, la valeur d'exemple est refusée.
Pour générer une clé :

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

**`SMTP_*`** : si `SMTP_HOST` est vide en développement, le contenu des e-mails, liens compris, est
écrit dans les journaux (logger `app.mail`). En production, un SMTP est obligatoire pour envoyer les
liens de réinitialisation.

## Base de données et migrations

```bash
createdb ika_compteur               # base de l'application
alembic upgrade head                # crée ou met à jour les tables
```

Après une modification des modèles, créez une nouvelle migration et relisez-la avant de l'appliquer :

```bash
alembic revision --autogenerate -m "description du changement"
alembic upgrade head
```

La migration initiale (`alembic/versions/…_initiale.py`) crée quatre tables : `utilisateurs`, `historique`,
`jetons_revoques` et `jetons_reinitialisation`.

## Premier administrateur

Renseignez `FIRST_ADMIN_EMAIL`, `FIRST_ADMIN_PASSWORD` et `FIRST_ADMIN_NAME` dans `.env`, puis lancez :

```bash
python scripts/creer_premier_admin.py
```

- Le mot de passe doit respecter la politique de l'application (voir Sécurité). Sinon, rien n'est créé
  et le script liste les règles non respectées.
- Le script est **idempotent** et ne modifie jamais un compte existant. Rien n'est créé si l'adresse
  est déjà utilisée ou si un administrateur existe déjà.
- La création est enregistrée dans l'historique.
- Après la première connexion, changez ce mot de passe depuis la page « Mon profil ».

## Lancement

Développement :

```bash
uvicorn app.main:app --reload --port 8000
```

- Application : http://127.0.0.1:8000
- Documentation de l'API : http://127.0.0.1:8000/docs et http://127.0.0.1:8000/redoc

En production, derrière un proxy HTTPS (Nginx par exemple) :

- `APP_ENV=production` et `APP_DEBUG=false` ;
- `SECRET_KEY` aléatoire ;
- `ALLOWED_HOSTS` et `APP_BASE_URL` renseignés avec le vrai domaine ;
- uvicorn lancé avec `--proxy-headers --forwarded-allow-ips=<adresse du proxy>`, pour que l'adresse IP
  réelle du client soit utilisée par la limitation de débit et l'historique.

## Tests

```bash
createdb ika_compteur_test          # base dédiée aux tests
pytest
```

- Les tests utilisent `TEST_DATABASE_URL` ou, à défaut, la base de `DATABASE_URL` suffixée par `_test`.
  Par sécurité, le nom de la base doit se terminer par `_test` : la base de développement n'est jamais touchée.
- Les tables sont créées au début de la session, vidées avant chaque test et supprimées à la fin.
- Aucun e-mail n'est envoyé : `SMTP_HOST` est forcé à vide.
- Les tests couvrent :
  - les en-têtes de sécurité et la CSP ;
  - le CSRF, les cookies, les hôtes autorisés et CORS ;
  - la connexion, le verrouillage, la limitation de débit (429) et la déconnexion avec révocation du jeton ;
  - la politique de mot de passe, l'inscription, le mot de passe oublié et la réinitialisation ;
  - l'OTP ;
  - le CRUD des utilisateurs et les permissions par rôle ;
  - l'historique en lecture seule ;
  - les listes (pagination, numéros, tri, recherche), les exports et les pages d'erreur.

## Rôles

| Rôle | Accès |
| --- | --- |
| Administrateur (`ADMIN`) | Tout : gestion des utilisateurs (création, modification, suppression, déverrouillage, réinitialisation OTP), historique, exports. |
| Manager (`MANAGER`) | Lecture des utilisateurs et de l'historique, exports PDF / Excel. |
| Utilisateur (`UTILISATEUR`) | Tableau de bord et profil (mot de passe, double authentification). |

L'inscription publique crée un compte `UTILISATEUR` actif. Un administrateur ne peut pas supprimer son
propre compte, et le dernier administrateur actif ne peut être ni supprimé, ni désactivé, ni rétrogradé.

## Sécurité

- **En-têtes HTTP** sur toutes les réponses :
  - CSP stricte, sans `unsafe-inline` ni `unsafe-eval` : aucun CSS ni JS dans le HTML, tout est dans
    `app/static/css/style.css` et `app/static/js/app.js` ;
  - HSTS, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
    `Referrer-Policy: strict-origin-when-cross-origin`.
  - Seules `/docs` et `/redoc`, qui chargent Swagger UI et ReDoc depuis jsdelivr, reçoivent une CSP
    assouplie limitée à ces deux chemins.
- **Hôtes et CORS** : `TrustedHostMiddleware` (`ALLOWED_HOSTS`) et CORS restreint (`CORS_ORIGINS`, avec
  méthodes et en-têtes explicites).
- **Cookies** : le JWT (`ika_jeton`) et la session (`ika_session`) sont `HttpOnly` et `SameSite=Lax`.
  L'attribut `Secure` est piloté par `COOKIE_SECURE` :
  - vide : automatique, vrai en production et faux sinon ;
  - le développement tourne en `http://127.0.0.1`, où un cookie `Secure` ne serait pas renvoyé par le
    navigateur ;
  - **en production, l'application doit être servie en HTTPS et `COOKIE_SECURE` ne doit pas valoir `false`.**
- **CSRF** : jeton en session, présent dans tous les formulaires et vérifié sur toutes les requêtes POST
  (erreur 403 sinon).
- **Session** : à la connexion, la session est régénérée (nouveau jeton CSRF) et un nouveau JWT est émis
  (nouveau `jti`). À la déconnexion, le `jti` est ajouté à la liste de révocation : le jeton est refusé
  ensuite.
- **Mots de passe** :
  - politique : 10 à 72 caractères, au moins une majuscule, une minuscule, un chiffre et un caractère
    spécial ;
  - hachage bcrypt ; le mot de passe n'est jamais réaffiché ni journalisé.
- **Verrouillage** : après 5 échecs consécutifs, le compte est verrouillé pendant 15 minutes. Le message
  indique la durée restante. Le compteur est remis à zéro après une connexion réussie.
- **Limitation de débit** sur la connexion (par IP et par e-mail) et sur la vérification OTP (par IP et par
  utilisateur). Au-delà, une page 429 s'affiche avec l'en-tête `Retry-After`.
- **Double authentification (TOTP)** :
  - le secret est chiffré en base (Fernet, clé dérivée de `SECRET_KEY`) ;
  - l'OTP n'est activé qu'après la saisie d'un code valide ;
  - si l'OTP est actif, aucun JWT n'est émis avant le code.
- **Mot de passe oublié** :
  - même message, que l'adresse existe ou non ;
  - le jeton est stocké haché (SHA-256), il est à usage unique et expire.
- **Historique** :
  - toutes les actions (CRUD, connexion, déconnexion, échecs, OTP, mots de passe) sont journalisées
    par un service unique ;
  - aucun mot de passe, hash, jeton ni secret n'y est enregistré ;
  - le module est en lecture seule (routes GET uniquement).
- **Exports Excel** : toute valeur texte commençant par `=`, `+`, `-`, `@`, une tabulation ou un retour
  chariot est préfixée par une apostrophe (anti-injection de formules).
- **Erreurs** :
  - pages personnalisées 400, 401, 403, 404, 429, 500 et 503 ;
  - les erreurs 500 sont journalisées avec leur trace, qui n'est jamais affichée à l'utilisateur.

### Limitations connues

- **Limitation de débit en mémoire.** Les compteurs de tentatives (connexion et OTP) sont gardés en
  mémoire, dans chaque processus :
  - avec plusieurs workers uvicorn ou plusieurs serveurs, chaque processus compte ses propres tentatives ;
  - les compteurs sont remis à zéro à chaque redémarrage.

  Le verrouillage de compte, enregistré en base, reste global. Pour une limitation partagée, il faudrait
  un stockage commun (Redis, par exemple).
- Après un changement ou une réinitialisation du mot de passe, les JWT déjà émis restent valides jusqu'à
  leur expiration (`ACCESS_TOKEN_EXPIRE_MINUTES`). Seule la déconnexion révoque un jeton.
- Un code OTP valide reste utilisable pendant sa fenêtre de validité (± 30 secondes).
- Les dates sont affichées et exportées en UTC.

## Structure

```
├── .env.example            # modèle de configuration
├── requirements.txt
├── alembic.ini, alembic/   # migrations (env.py : conversion asyncpg → psycopg2)
├── pytest.ini              # configuration des tests
├── app/
│   ├── main.py             # middlewares, fichiers statiques, gestionnaires d'erreurs, routers
│   ├── core/               # configuration, base de données, sécurité, e-mail, erreurs,
│   │                       # dépendances, rendu, validation, listes, exports communs
│   ├── auth/               # connexion, OTP, inscription, mot de passe, profil
│   ├── utilisateur/        # gestion des comptes (CRUD, permissions, exports)
│   ├── historique/         # journal des actions (lecture seule, exports)
│   ├── tableau_de_bord/    # indicateurs et dernières activités
│   ├── templates/          # base.html, composants/, un dossier par module, erreurs/
│   └── static/             # css/style.css, js/app.js, img/logo.png, vendor/ (Bootstrap)
├── scripts/
│   └── creer_premier_admin.py
└── tests/                  # conftest.py et tests par thème
```

Chaque module métier contient : `__init__.py`, `model.py`, `schemas.py`, `services.py`, `permissions.py`,
`export_pdf.py`, `export_excel.py` et `routes.py`. Ses templates sont dans `app/templates/<module>/`
(`ajoute.html`, `liste.html`, `detail.html`).
