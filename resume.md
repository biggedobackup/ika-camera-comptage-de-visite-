# IKA COMPTEUR — Plateforme Intelligente de Comptage de Visiteurs & Gestion des Caméras 3D

Ce document constitue la référence complète du projet **IKA COMPTEUR** : sa description, son architecture, ses modes de fonctionnement (en réseau local et en ligne sur VPS), ainsi que son guide de configuration et de déploiement.

---

## 1. Description du projet

**IKA COMPTEUR** est une solution web et IoT d'analyse de fréquentation et de comptage de personnes en temps réel, conçue pour les points de vente, centres commerciaux, agences et établissements recevant du public.

Le système s'interface directement avec des **caméras stéréoscopiques 3D binoculaires HX-CCD21** (caméras intelligentes avec processeur de vision embarqué et algorithmes de détection IA). Il ingère les flux de comptage minute par minute, filtre les passages non pertinents (personnel avec badge, livreurs), élimine les doublons grâce à la reconnaissance des clients récurrents, et restitue ces données sur des tableaux de bord interactifs actualisés en direct via WebSocket.

### Objectifs principaux :
1. **Souveraineté des données :** Rapatrier les données issues des caméras sur une infrastructure propre (serveur local ou VPS privé) plutôt que de dépendre d'un cloud tiers propriétaire à l'étranger (`op.foorir.com`).
2. **Temps réel :** Diffuser instantanément chaque passage détecté vers les écrans des gestionnaires sans rafraîchissement de page.
3. **Précision analytique IA :** Exploiter les statistiques avancées fournies par les caméras 3D (flux bruts, clients uniques réels dédoublés, taux de revisite, durée moyenne de séjour, exclusion du personnel).
4. **Facilité d'exploitation :** Offrir un CRUD complet pour gérer les caméras, générer des rapports personnalisés et exporter les données sous formats Excel et PDF.

---

## 2. Résumé exécutif

* **Backend :** FastAPI (Python 3.12+ / 3.14) entièrement asynchrone (`asyncio`, SQLAlchemy 2.0 async, asyncpg).
* **Base de données :** PostgreSQL avec extensions JSONB pour le stockage des ventilations IA (tranches d'âge, genre, taille, durées de présence).
* **Communication IoT :** Endpoints HTTP POST RESTful non-bloquants, tolérants aux pannes, idempotents (clé unique `(SN, date, timestamp_debut)`) avec gestion des révisions temporelles.
* **Diffusion Live :** WebSocket bidirectionnel `/ws/comptage` notifiant instantanément les clients connectés.
* **Frontend :** HTML5 / CSS3 / JavaScript vanilla conforme aux standards d'accessibilité (aucun style inline, respect strict de la charte IKA COMPTEUR, conformité CSP stricte `connect-src 'self' ws: wss:`).
* **Sécurité & Droits :** Authentification par session sécurisée (cookies HttpOnly, SameSite), CSRF token sur tous les formulaires d'administration, isolation des endpoints IoT sans CSRF, double authentification TOTP (2FA/OTP), contrôle d'accès basé sur les rôles (`ADMIN`, `MANAGER`, `UTILISATEUR`).

---

## 3. Architecture globale du système

```
                          SITE PHYSIQUE (Magasin / Bâtiment)
┌────────────────────────────────────────────────────────────────────────┐
│                                                                        │
│   [Caméra 1 - Entrée 1] (HX-CCD21) ──┐                                 │
│   [Caméra 2 - Entrée 2] (HX-CCD21) ──┼───► Switch / Box Internet       │
│   [Caméra 3 - Entrée 3] (HX-CCD21) ──┤        (DHCP ou IP fixe)        │
│   [Caméra 4 - Entrée 4] (HX-CCD21) ──┘                │                │
└───────────────────────────────────────────────────────┼────────────────┘
                                                        │
                      Requêtes montantes HTTP POST       │
                      (Intervalle minute & Heartbeat)   │
                                                        ▼
                        ┌───────────────────────────────────────────────┐
                        │      Réseau Local (LAN) OU Internet (WAN)     │
                        └───────────────────────────────────────────────┘
                                                        │
                                                        ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│                       SERVEUR IKA COMPTEUR (Local ou VPS)                     │
│                                                                                │
│   ┌────────────────────────────────────────────────────────────────────────┐   │
│   │ Reverse Proxy (Nginx) - SSL/TLS (HTTPS :443 / WSS)                     │   │
│   └───────────────────────────────────┬────────────────────────────────────┘   │
│                                       │ Proxy pass :8000                       │
│   ┌───────────────────────────────────▼────────────────────────────────────┐   │
│   │                      Application FastAPI (Python)                      │   │
│   │                                                                        │   │
│   │  • Endpoints IoT Caméras (Sans CSRF) :                                 │   │
│   │    - POST /api/passenger-flow/interval-aggregate (V1.0)               │   │
│   │    - POST /api/passenger-flow/device-status      (Heartbeat V1.0)      │   │
│   │    - POST /api/camera/dataUpload                 (V2.5 de secours)     │   │
│   │    - POST /api/camera/heartBeat                  (Heartbeat V2.5)      │   │
│   │                                                                        │   │
│   │  • Passerelle Temps Réel :                                             │   │
│   │    - WebSocket /ws/comptage (Diffusion instantanée aux navigateurs)    │   │
│   │                                                                        │   │
│   │  • Espace Web Administrateur & Managers (Avec CSRF & Sessions) :       │   │
│   │    - /cameras              : Liste et surveillance des appareils       │   │
│   │    - /cameras/ajouter      : Formulaire d'ajout matériel (CRUD)        │   │
│   │    - /cameras/{id}         : Fiche technique et modification           │   │
│   │    - /cameras/passages     : Flux en direct et historique              │   │
│   │    - /cameras/rapport/...  : Synthèse, graphiques horaires, KPIs       │   │
│   │    - /cameras/export/...   : Génération Excel (.xlsx) et PDF (.pdf)    │   │
│   └───────────────────────────────────┬────────────────────────────────────┘   │
│                                       │                                        │
│   ┌───────────────────────────────────▼────────────────────────────────────┐   │
│   │           Base de données PostgreSQL (Schéma ika_compteur)             │   │
│   │  • cameras             • passages_comptage     • camera_heartbeats     │   │
│   │  • utilisateurs        • historique_actions    • sessions              │   │
│   └────────────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────────────┘
                                        ▲
                                        │ WebSocket Live & Requêtes Web HTTPS
                                        │
┌───────────────────────────────────────┴────────────────────────────────────────┐
│                        POSTES & TERMINAUX DE CONSULTATION                      │
│     Navigateurs web (Ordinateurs bureau, Portables, Tablettes, Smartphones)    │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Modes de fonctionnement : Local vs Ligne (VPS)

### Mode 1 : Fonctionnement en Réseau Local (LAN privé sans Internet)

Ce mode est idéal lorsque le serveur physique est situé dans le même bâtiment que les caméras ou sur un réseau d'entreprise isolé.

* **Principe :** Les caméras et le serveur sont sur la même plage d'adresses IP privées (ex : `192.168.1.0/24`).
* **Adresse cible dans les caméras :** `<IP_LOCALE_DU_SERVEUR>:8000` (ex : `192.168.1.50:8000`).
* **Avantages :** 
  * Fonctionne à 100% même en cas de coupure totale d'Internet.
  * Confidentialité maximale (les données ne quittent jamais le bâtiment).
* **Consultation :** Les utilisateurs se connectent en tapant `http://192.168.1.50:8000` depuis un ordinateur connecté au Wi-Fi ou au câble du réseau local.

---

### Mode 2 : Fonctionnement en Ligne (Serveur distant / VPS Cloud)

Ce mode est idéal pour centraliser un ou plusieurs points de vente et pouvoir consulter les données de n'importe où dans le monde.

* **Principe :**
  1. Le serveur FastAPI et PostgreSQL sont installés sur un VPS (OVH, Hetzner, AWS, Scaleway, DigitalOcean...).
  2. Le VPS dispose d'une adresse IP publique fixe et d'un nom de domaine avec certificat HTTPS (ex : `https://compteur.mon-entreprise.com`).
  3. Sur le site physique, les caméras sont simplement branchées sur la box Internet locale (fibre, ADSL ou routeur 4G/5G).
* **Pourquoi aucune configuration n'est nécessaire sur la box locale ?**
  * Les caméras HX-CCD21 fonctionnent en **client HTTP sortant** : elles envoient des requêtes POST vers l'extérieur exactement comme un smartphone ou un PC qui ouvre une page web.
  * Il n'y a **aucun port à ouvrir** et aucune redirection NAT à configurer sur la box Internet du magasin.
* **Adresse cible dans les caméras :**
  * Host / Nom de domaine : `compteur.mon-entreprise.com` (ou IP publique du VPS).
  * Port : `443` (HTTPS) ou `80` (HTTP standard).
  * Chemins : `/api/passenger-flow/interval-aggregate` et `/api/passenger-flow/device-status`.
* **Consultation :** Les dirigeants, managers et équipes se connectent en tout lieu sur `https://compteur.mon-entreprise.com` depuis leur téléphone ou leur ordinateur.

---

## 5. Intégration IoT des caméras HX-CCD21

### Protocoles supportés :

1. **Protocole Uplink V1.0 (Natif & Recommandé) :**
   * Données de passage (par minute) : `POST /api/passenger-flow/interval-aggregate`
   * État de santé matériel : `POST /api/passenger-flow/device-status`
   * Structure : JSON hiérarchisé avec `event_counts` (flux bruts), `final_stats` (clients réels dédoublés), `non_customer` (personnel exclu), `dwell_stats` (temps de présence), et ventilations sociodémographiques (tranches d'âge, genre, hauteur).
2. **Protocole Uplink V2.5 (Secours & Rétrocompatibilité) :**
   * Données de passage : `POST /api/camera/dataUpload`
   * État de santé matériel : `POST /api/camera/heartBeat`

### Règles critiques constructeur respectées :
* **Réponse 200 obligatoire et NON-VIDE :** Si le serveur renvoie une réponse vide (`204 No Content`) ou une erreur, le firmware de la caméra considère que le paquet a échoué et le renvoie en boucle. Le backend renvoie systématiquement `{"ok": true, "code": 0, "msg": "success"}`.
* **Idempotence et révisions :** La caméra peut réémettre un intervalle de temps après recalcul IA local avec un numéro de révision plus élevé. Le backend compare `revision` avec la base existante : si la révision est plus récente, il met à jour le créneau sans créer de doublon ; si elle est égale ou antérieure, il valide sans duplication.
* **Résilience aux coupures réseau :** En cas d'interruption du lien réseau, la caméra stocke ses historiques en mémoire cache locale et les transmet en rafale dès le rétablissement du lien.

---

## 6. Fonctionnalités de l'application

### A. Surveillance et CRUD complet des caméras (`/cameras`)
* **Détection véridique de l'état réseau :** Une caméra est affichée **« En ligne »** uniquement si elle a émis un signal (heartbeat ou rapport) dans les **3 dernières minutes (180 secondes)**. Dans le cas contraire, elle apparaît en **« Hors ligne »** avec l'horodatage de son dernier contact.
* **Ajout d'une caméra (`/cameras/ajouter`) :** Enregistrement complet avec numéro de série unique, nom convivial, emplacement physique, adresse IP, adresse MAC, modèle, rôle réseau (Master/Slave/Client) et version logicielle.
* **Modification (`/cameras/{id}`) :** Mise à jour en temps réel des libellés et métadonnées techniques.
* **Suppression (`/cameras/{id}/supprimer`) :** Suppression définitive avec fenêtre modale de confirmation.

### B. Flux & Passages en temps réel (`/cameras/passages`)
* Écoute en continu du canal WebSocket `/ws/comptage`.
* Dès qu'un paquet minute arrive, une nouvelle ligne apparaît instantanément en haut de l'historique avec une animation douce, sans rechargement de page.
* Les compteurs du jour (entrées, sorties, visiteurs uniques, personnel filtré) sont mis à jour en direct.

### C. Rapport d'analyse & Statistiques (`/cameras/rapport/statistiques`)
* **Cartes d'indicateurs visuelles (Charte IKA) :**
  * **Total Entrées :** Comptage physique brut des franchissements de porte.
  * **Clients uniques (IA) :** Visiteurs réels dédoublés par vision artificielle.
  * **Taux de revisite :** Pourcentage et nombre de personnes revenues au cours de la journée.
  * **Personnel filtré :** Employés, agents de sécurité et livreurs écartés des statistiques.
* **Répartition horaire :** Histogramme dynamique montrant l'affluence heure par heure (de 8h à 21h).
* **Performance par porte / caméra :** Tableau ventilant les flux par entrée.
* **Filtres avancés :** Filtrage sur une période libre (date de début, date de fin) et par caméra/entrée spécifique.

### D. Exports conformes et sécurisés
* **Export Excel (`.xlsx`) :** Tableaux structurés avec totaux automatiques et protection contre les injections de formules CSV/Excel (neutralisation des caractères `=`, `+`, `-`, `@`).
* **Export PDF (`.pdf`) :** Documents imprimables haute fidélité générés via ReportLab avec mise en page tabulaire soignée.

### E. Sécurité & Gestion des utilisateurs
* Gestion des rôles : `ADMIN` (contrôle total), `MANAGER` (consultation et exports), `UTILISATEUR` (accès limité).
* Double authentification TOTP (2FA par application comme Google Authenticator).
* Journal d'audit complet de toutes les actions système dans `/historique`.

---

## 7. Guide de configuration des caméras physiques (HX-CCD21)

Pour diriger vos 4 caméras vers votre serveur IKA COMPTEUR :

1. Ouvrez un navigateur web et connectez-vous à l'adresse IP locale de la caméra (ex: `http://192.168.1.142`).
2. Allez dans le menu : **Configuration** ➔ **Data Upload / Report Settings** (ou **Cloud / Platform Settings**).
3. Renseignez les paramètres suivants :
   * **Protocol :** `HTTP POST`
   * **Server Address / Host :**
     * En local : `<IP_DE_VOTRE_PC_OU_SERVEUR>` *(ex : `192.168.1.50`)*
     * En ligne : `<VOTRE_NOM_DE_DOMAINE_OU_IP_VPS>` *(ex : `compteur.domaine.com`)*
   * **Port :** `8000` (en local direct) ou `80` / `443` (en ligne avec Nginx).
   * **Interval Upload Path :** `/api/passenger-flow/interval-aggregate`
   * **Heartbeat Path :** `/api/passenger-flow/device-status`
   * **Upload Interval :** `60` secondes (1 minute).
4. Cliquez sur **Save / Apply**.
5. Observez sur l'interface IKA COMPTEUR (`/cameras`) : la caméra passe immédiatement en vert **« En ligne »** dès son premier signal.

---

## 8. Guide de démarrage et déploiement

### A. Lancement en Local (Développement / Test)

```bash
# 1. Cloner ou ouvrir le projet
cd "compteur de visite"

# 2. Configurer les variables d'environnement dans .env
# (DATABASE_URL=postgresql+asyncpg://utilisateur:motdepasse@localhost:5432/ika_compteur)

# 3. Appliquer les migrations de base de données
alembic upgrade head

# 4. Lancer le serveur avec rechargement automatique
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

* Accès à l'application : `http://127.0.0.1:8000`
* Accès sur le réseau local : `http://<IP_DE_VOTRE_MACHINE>:8000`

---

### B. Déploiement en Production sur un VPS (Linux Ubuntu/Debian)

#### 1. Configuration de l'environnement sur le VPS :
```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv postgresql nginx certbot python3-certbot-nginx
```

#### 2. Configuration du service systemd (`/etc/systemd/system/ikacompteur.service`) :
```ini
[Unit]
Description=IKA Compteur - Backend FastAPI
After=network.target postgresql.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/ikacompteur
ExecStart=/var/www/ikacompteur/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4
Restart=always
RestartSec=5
EnvironmentFile=/var/www/ikacompteur/.env

[Install]
WantedBy=multi-user.target
```

#### 3. Configuration Nginx avec Reverse Proxy et WebSocket (`/etc/nginx/sites-available/ikacompteur`) :
```nginx
server {
    server_name compteur.votre-entreprise.com;

    client_max_body_size 20M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Support complet WebSocket
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }
}
```

#### 4. Activation du certificat HTTPS (SSL gratuit Let's Encrypt) :
```bash
sudo ln -s /etc/nginx/sites-available/ikacompteur /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d compteur.votre-entreprise.com
sudo systemctl enable --now ikacompteur
```

---

## 9. Identifiants d'accès d'administration

Lors du déploiement initial, le compte administrateur configuré est :

* **URL de connexion :** `/connexion`
* **Identifiant (Email) :** `admin@admin.com`
* **Mot de passe :** `gedeonr9`
* **Rôle :** `ADMIN` (accès illimité, gestion du matériel, exports, utilisateurs et audits).

*(Compte de secours préconfiguré : `admin@ikacompteur.com` / `Admin@2026`)*.

---

## 10. Synthèse technique des tests automatisés

Le projet dispose d'une couverture de tests rigoureuse exécutée via `pytest` (12 tests dédiés à la partie caméra et plus de 170 tests pour la sécurité globale de l'application) garantissant :
* L'ingestion conforme des données d'intervalles V1.0 et V2.5.
* L'idempotence stricte et l'écrasement des révisions sans doublon.
* Le calcul véridique du statut en ligne/hors ligne (expiration à 180 s).
* Le cycle complet du CRUD des caméras (Création, Lecture, Modification, Suppression).
* La diffusion temps réel par WebSocket.
* La génération intègre des rapports et des exports Excel / PDF.
