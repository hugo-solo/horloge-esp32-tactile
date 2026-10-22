# Relais local Codex et Spotify

L'écran ESP32 ne conserve **aucun identifiant OpenAI ou Spotify**. Une petite VM Debian ou Ubuntu, allumée sur le même réseau local, lit les limites du compte connecté avec `codex app-server`. Le programme [`codex_quota_bridge.py`](codex_quota_bridge.py) transmet uniquement les pourcentages restants et les dates de remise à zéro. Quand il tourne sur macOS, il peut aussi lire le titre joué dans l'application Spotify locale.

Une clé de l'API OpenAI ne donne pas accès au quota de l'abonnement Codex : il faut connecter **Codex CLI avec le même compte ChatGPT** que celui utilisé dans l'application.

## Essai sur un Mac

Si Codex CLI est déjà connecté sur le Mac, lancez le relais dans un terminal :

```sh
codex login status
python3 bridge/codex_quota_bridge.py --bind IP_LOCALE_DU_MAC
```

Le relais crée `.codex-bridge/token`. Renseignez `codex_bridge_url` et `spotify_now_playing_url` dans `secrets.yaml` avec l'IP locale du Mac et ce jeton, puis flashez `horloge-codex.yaml`. La seconde URL utilise le chemin `/now-playing`. Quand Spotify joue sur le Mac, le titre apparaît au-dessus de l'heure ; il disparaît à la pause. macOS peut demander l'autorisation de lire l'état de Spotify la première fois. Le Mac doit rester allumé pendant cet essai. Plus tard, vous pourrez déplacer le relais Codex sur la VM et reflasher l'écran avec sa nouvelle URL. Pour continuer à afficher la lecture du Mac, laissez `spotify_now_playing_url` pointée vers celui-ci.

## Sur la VM Debian/Ubuntu

La VM doit avoir une adresse IP locale stable (ou une réservation DHCP), un accès Internet et SSH. Aucune redirection de port Internet n'est nécessaire.

```sh
sudo apt update
sudo apt install -y python3 nodejs npm git curl
sudo npm install -g @openai/codex
git clone https://github.com/hugo-solo/horloge-esp32-tactile.git
cd horloge-esp32-tactile
codex login --device-auth
```

Suivez les instructions de connexion affichées par Codex sur **votre propre navigateur**. Ne partagez ni code de connexion ni jeton. Vérifiez ensuite :

```sh
codex login status
python3 bridge/codex_quota_bridge.py
```

Au premier démarrage, le relais crée `.codex-bridge/token` avec des permissions privées. Gardez ce fichier sur la VM : il sert uniquement à empêcher les autres appareils du réseau local de lire vos pourcentages. La session du compte Codex reste, elle aussi, sur la VM.

Dans un second terminal sur la VM, vérifiez la réponse :

```sh
TOKEN=$(cat .codex-bridge/token)
curl --fail "http://127.0.0.1:8765/quota?token=$TOKEN"
```

La réponse doit contenir `remaining_5h`, `reset_5h` et, si disponibles, `remaining_week` et `reset_week`. Les valeurs de reset sont des secondes Unix ; l'écran calcule le temps restant.

## Démarrage automatique

Après avoir testé le relais, copiez l'unité systemd utilisateur fournie :

```sh
mkdir -p ~/.config/systemd/user
cp bridge/codex-quota.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now codex-quota.service
sudo loginctl enable-linger "$USER"
```

L'unité suppose que le dépôt est dans `~/horloge-esp32-tactile`. Pour vérifier son état :

```sh
systemctl --user status codex-quota.service
```

## Sur le Mac qui flashe l'écran

Ajoutez à `secrets.yaml` une URL qui pointe vers **l'adresse IP locale de la VM** et son jeton :

```yaml
codex_bridge_url: "http://IP_DE_LA_VM:8765/quota?token=JETON_DU_FICHIER"
```

Puis branchez l'écran et installez la variante à trois pages :

```sh
esphome run horloge-codex.yaml
```

Balayez deux fois de droite vers la gauche depuis l'horloge pour atteindre la page Codex. Les chiffres sont actualisés chaque minute. Si la VM est arrêtée ou inaccessible, la page affiche « SERVEUR HORS LIGNE » ; l'horloge et le chronomètre continuent de fonctionner.

Gardez le port `8765` accessible **uniquement sur le réseau local**. Le jeton du relais n'est pas une clé OpenAI et ne donne pas accès au compte, mais il permet de consulter vos pourcentages de quota.

Le petit [logo OpenAI](../assets/openai-white-monoblossom.svg) provient du [kit officiel OpenAI](https://cdn.openai.com/brand/OpenAI-Logos-2025.zip). Il désigne le service dont les quotas sont affichés ; ce projet indépendant n'est pas affilié à OpenAI.
