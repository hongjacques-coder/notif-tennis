# notif-tennis

Notification Discord à chaque nouvelle partie publiée sur
<https://www.partennis.com/proposition-de-partie>. Tourne gratuitement sur GitHub Actions.

## Installation (une seule fois)

1. **Créer le webhook Discord**
   - Sur ton serveur Discord : clic droit sur un salon → *Modifier le salon* → *Intégrations* → *Webhooks* → *Nouveau webhook*.
   - *Copier l'URL du webhook*.
2. **Ajouter l'URL dans GitHub**
   - Repo → *Settings* → *Secrets and variables* → *Actions* → *New repository secret*.
   - Name : `DISCORD_WEBHOOK_URL` / Secret : l'URL copiée.
3. **Vérifier la branche par défaut**
   - GitHub ne lance les tâches planifiées que sur la branche par défaut (*Settings* → *General* → *Default branch*).
   - Elle doit contenir ce code.
4. **Premier lancement**
   - Onglet *Actions* → *notif-tennis* → *Run workflow*.
   - Si `seen.json` n'existe pas, ce premier run enregistre les parties existantes **sans notifier**.
   - Ensuite, seules les nouvelles parties déclenchent une notif.

## ON / OFF

- **OFF** : *Actions* → *notif-tennis* → bouton `···` → **Disable workflow**.
- **ON** : même endroit → **Enable workflow**.

Ça marche aussi depuis l'app mobile GitHub ou le navigateur du téléphone.

## Changer la fréquence (X minutes)

Dans `.github/workflows/notif-tennis.yml`, ligne `cron` :

| Fréquence | Valeur |
|---|---|
| 5 min (minimum GitHub) | `"*/5 * * * *"` |
| 10 min | `"*/10 * * * *"` |
| 30 min | `"*/30 * * * *"` |

⚠️ GitHub peut retarder les runs planifiés de quelques minutes aux heures chargées.

## Filtres (optionnels)

En haut de `notif_tennis.py` :

```python
DEPARTEMENTS = ["75", "77", "78", "91", "92", "93", "94", "95"]  # Île-de-France ([] = tous)
NIVEAU_MAX = "30/2"  # vérifié sur le niveau min demandé ET le niveau du joueur ("" = tous)
# - les 2 OK          -> notif 🎾 (verte)
# - un seul OK        -> notif ⚠️ (orange), à toi de trancher
# - les 2 dépassent   -> pas de notif
```

## Fonctionnement

1. Le script lit **toutes** les pages (il suit le lien « Suivant » jusqu'à la dernière, quel que soit le nombre de pages).
2. Chaque partie reçoit une empreinte : `pseudo + date + lieu + description`.
3. Une empreinte absente de `seen.json` déclenche une notif Discord, puis elle est ajoutée au fichier.
4. `seen.json` est recommité dans le repo après chaque run. Les parties passées depuis plus de 7 jours sont oubliées.
5. Si 0 partie est lue alors que le site en annonce, tu reçois une alerte « structure changée ».

## Tester le webhook

*Actions* → *Run workflow* fonctionne, ou en local :

```bash
pip install -r requirements.txt
DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..." python notif_tennis.py --test
```
