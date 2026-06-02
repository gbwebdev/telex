# Telex

Un système de messagerie par imprimante thermique. Envoyez des messages depuis une interface web ; ils s'impriment automatiquement sur des Raspberry Pi distants.

```
[Interface web] ──→ [Serveur FastAPI] ←── polling ── [RPi Zero W + imprimante thermique]
```

## Fonctionnement

- L'admin envoie un message via l'interface web
- Chaque Raspberry Pi interroge le serveur toutes les minutes
- Le message s'imprime sur l'imprimante thermique
- L'interface affiche l'état de livraison en temps réel (⌛ en attente · ✓ reçu · ✓✓ imprimé · ✗ échec)
- Les messages envoyés hors-ligne sont imprimés dès la reconnexion
- Option de réimpression depuis l'interface

## Structure

```
telex/
├── server/                  # Serveur FastAPI (à déployer sur votre VPS)
│   ├── app/
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── database.py
│   │   ├── routers/
│   │   │   ├── admin.py     # API admin (envoi, gestion clients)
│   │   │   └── client.py    # API RPi (polling, ACK)
│   │   └── static/
│   │       └── index.html   # Interface web admin
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── requirements.txt
├── client/                  # Code Raspberry Pi
│   ├── telex_client.py      # Daemon principal (polling + impression)
│   ├── printer.py           # Détection automatique imprimante USB
│   ├── wifi_manager.py      # Gestion WiFi + hotspot de configuration
│   ├── config.py            # UUID et config persistants
│   ├── portal/              # Portail web de configuration WiFi
│   │   ├── portal.py
│   │   └── templates/
│   │       └── index.html
│   └── requirements.txt
└── deploy/
    ├── install.sh            # Script d'installation RPi
    ├── telex-client.service  # systemd
    ├── telex-wifi.service    # systemd
    └── telex-portal.service  # systemd
```

## Flux de mise en service

```
1. Admin crée un client dans l'interface (nom + identifiant)
   → Le serveur génère un mot de passe, affiché UNE SEULE FOIS
2. Le RPi démarre → imprime un ticket avec son IP et MAC
3. Admin ouvre http://<ip-du-rpi> dans le navigateur (même réseau)
   → Saisit l'URL du serveur, l'identifiant, le mot de passe
4. Le RPi se connecte au serveur et est opérationnel
```

Si le RPi n'est sur aucun réseau connu :
```
→ Crée un hotspot "Telex-XXXXXXXX" (mot de passe : telex1234)
→ Connectez-vous au hotspot, ouvrez http://192.168.4.1
→ Configurez le WiFi dans l'interface, puis saisissez les credentials Telex
```

Raccourci physique : courtcircuiter **GPIO17 (broche 11)** et **GND (broche 14)** avec un fil ou un trombone pour réimprimer le ticket de configuration à tout moment.

---

## Déploiement du serveur

### Prérequis
- Docker et Docker Compose installés
- Un nom de domaine pointant vers votre serveur
- (Recommandé) nginx + Let's Encrypt pour le HTTPS

### Installation

```bash
cd server/
cp ../.env.example .env
# Éditez .env et définissez ADMIN_API_KEY
nano .env

docker compose up -d
```

Le serveur écoute sur `127.0.0.1:8000`. Configurez nginx pour proxyfier le trafic HTTPS vers ce port.

**Exemple de config nginx :**
```nginx
server {
    listen 443 ssl;
    server_name telex.example.com;

    ssl_certificate     /etc/letsencrypt/live/telex.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/telex.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }
}
```

## Installation d'un client (Raspberry Pi Zero W) — sans écran

> Le RPi Zero W ne supporte que le WiFi **2.4 GHz**.

### Matériel supporté
- Raspberry Pi Zero W (ou tout RPi avec WiFi)
- Imprimante thermique USB 80mm compatible ESC/POS
  - Epson TM-T20II / TM-T20III / TM-T88V
  - PRP-250 et imprimantes génériques ESC/POS USB
  - Toute imprimante USB de classe 7 (détection automatique)

---

### Étape 1 — Préparer la carte SD

Téléchargez et installez **[Raspberry Pi Imager](https://www.raspberrypi.com/software/)**.

1. **OS** → *Raspberry Pi OS (other)* → **Raspberry Pi OS Lite (32-bit)**
   *(pas de bureau, plus léger, suffisant pour Telex)*
2. **Storage** → votre carte SD
3. Cliquez sur l'icône **⚙ (Edit Settings)** avant de flasher et renseignez :

| Champ | Valeur conseillée |
|-------|-------------------|
| Hostname | `telex-arthur` *(ou `telex-hugo`, etc.)* |
| SSH | ✓ Activer — authentification par mot de passe |
| Username | `pi` |
| Password | un mot de passe que vous retenez |
| WiFi SSID | votre réseau 2.4 GHz |
| WiFi password | votre mot de passe WiFi |
| WiFi country | FR |
| Timezone | Europe/Paris |

4. **Save** → **Write** → confirmez → attendez la fin du flash.

---

### Étape 2 — Premier démarrage

1. Insérez la carte SD dans le RPi et branchez l'alimentation
2. Attendez **~90 secondes** (premier démarrage, expansion du système de fichiers)
3. Trouvez l'adresse IP du RPi — trois options :
   - Via votre box/routeur (liste des appareils connectés)
   - `ping telex-arthur.local` (mDNS, fonctionne sur macOS/Linux sans config)
   - `arp -a | grep -i "b8:27:eb\|dc:a6:32\|e4:5f:01"` (préfixes MAC RPi)

---

### Étape 3 — Installer Telex

```bash
# Connexion SSH
ssh pi@telex-arthur.local
# (acceptez l'empreinte, entrez votre mot de passe)

# Installation
git clone https://github.com/VOTRE_COMPTE/telex.git
cd telex
sudo bash deploy/install.sh
```

L'installateur affiche l'adresse IP du portail à la fin.

---

### Étape 4 — Configurer le client

1. **Côté serveur** (interface admin → CLIENTS → + Nouveau) : créez le client avec son nom et son identifiant — **notez le mot de passe**, il n'est affiché qu'une fois
2. **Côté RPi** : ouvrez `http://<ip-du-rpi>` dans votre navigateur (même réseau)
3. Renseignez l'URL du serveur, l'identifiant et le mot de passe → **Enregistrer**
4. Le RPi imprime son ticket de confirmation et commence à surveiller les messages

---

### Sans WiFi connu au démarrage

Si la carte n'a pas été préconfigurée avec un réseau ou que vous changez de lieu :

- Le RPi crée automatiquement le hotspot **`Telex-XXXXXXXX`** (mot de passe : `telex1234`)
- Connectez-vous à ce hotspot depuis votre téléphone/ordinateur
- Ouvrez `http://192.168.4.1` et configurez le WiFi dans l'interface
- Le RPi se reconnecte, puis vous pouvez accéder à `http://<ip>` sur votre réseau habituel

---

### Réimprimer le ticket de configuration

- **Via l'interface** : `http://<ip-du-rpi>` → bouton "Réimprimer le ticket"
- **Physiquement** : courtcircuiter **GPIO17 (broche 11)** et **GND (broche 14)** avec un fil ou un trombone

## Utilisation

### Envoyer un message

**Mode admin** (accès complet) : `https://telex.example.com` → clé API → onglet ENVOYER

**Mode famille** (sans clé admin) : `https://telex.example.com/send` → identifiant du destinataire + son mot de passe → message. Ce lien peut être partagé avec des grands-parents, etc. sans leur donner les droits d'administration.

### Suivre les livraisons

Onglet **MESSAGES** :

| Icône | Signification |
|-------|---------------|
| ⌛    | En attente (client pas encore connecté) |
| ✓     | Reçu par le RPi |
| ✓✓   | Imprimé avec succès |
| ✗     | Échec d'impression (message d'erreur visible) |

Bouton **↺** sur une livraison échouée ou reçue pour réimprimer.

## Configuration du client

Le fichier `/etc/telex/config.json` sur le RPi :

```json
{
  "uuid": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "server_url": "https://telex.example.com",
  "poll_interval": 60
}
```

| Clé | Description | Défaut |
|-----|-------------|--------|
| `uuid` | Identifiant unique (généré automatiquement) | — |
| `server_url` | URL de votre serveur Telex | — |
| `poll_interval` | Intervalle de polling en secondes | `60` |

## Dépannage

### Le RPi ne se connecte pas

```bash
# Vérifier l'état du service
sudo journalctl -u telex-client -f

# Tester manuellement
sudo /opt/telex/venv/bin/python /opt/telex/client/telex_client.py
```

### L'imprimante n'est pas détectée

```bash
# Lister les périphériques USB
lsusb

# Vérifier les permissions
ls -la /dev/usb/
```

### Réinitialiser la configuration WiFi

```bash
# Supprimer la config et redémarrer pour relancer le hotspot
sudo rm /etc/NetworkManager/system-connections/*.nmconnection
sudo reboot
```

## Sécurité

- La clé API admin n'est jamais exposée côté client RPi
- Les RPi s'authentifient uniquement par leur UUID (adapté à un usage familial ; pour un usage public, ajoutez un secret partagé)
- Utilisez HTTPS en production (les tokens ne transitent pas en clair)

## Licence

MIT
