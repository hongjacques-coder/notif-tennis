# notif-tennis

Notification Discord à chaque nouvelle partie publiée sur :

- <https://www.partennis.com/proposition-de-partie>
- <https://www.tennis-contact.com/parties.php>

Tourne gratuitement sur GitHub Actions.

## Installation (une seule fois)

1. **Créer le webhook Discord**
   - Sur ton serveur Discord : clic droit sur un salon → *Modifier le salon* → *Intégrations* → *Webhooks* → *Nouveau webhook*.
   - *Copier l'URL du webhook*.
2. **Ajouter l'URL dans GitHub**
   - Repo → *Settings* → *Secrets and variables* → *Actions* → *New repository secret*.
   - Name : `DISCORD_WEBHOOK_URL` / Secret : l'URL copiée.
3. **Vérifier la branche par défaut**
   - GitHub ne lance les tâches planifiées que sur la branche par défaut : `main` (*Settings* → *General* → *Default branch*).
4. **Premier lancement**
   - Onglet *Actions* → *notif-tennis* → *Run workflow*.
   - Si `seen.json` n'existe pas, ce premier run enregistre les parties existantes **sans notifier**.
   - Ensuite, seules les nouvelles parties déclenchent une notif.

## ON / OFF

- **OFF** : *Actions* → *notif-tennis* → bouton `···` → **Disable workflow** (ou désactiver le job dans cron-job.org).
- **ON** : même endroit → **Enable workflow**.

Ça marche aussi depuis l'app mobile GitHub ou le navigateur du téléphone.

**Pause jusqu'à une date** : en haut de `notif_tennis.py`, `REPRISE_LE = "2026-10-16"`.
Avant cette date (heure de Paris), le script ne vérifie rien. Il reprend tout seul ce jour-là.
À la reprise, les parties publiées pendant la pause et encore en ligne sont notifiées.
`REPRISE_LE = ""` = pas de pause.

## Fréquence : toutes les 15 min, de 7h à 22h

Le planificateur de GitHub ne lance les runs que toutes les ~4-5 h sur ce repo.
Le vrai déclencheur est donc **cron-job.org** (gratuit), qui appelle GitHub à l'heure précise.

**Budget (repo privé = 2 000 min gratuites / mois, 1 min comptée par run) :**
4 runs/h × 15 h × 30 jours = 1 800 min + filet de sécurité GitHub (3/jour) ≈ 1 890 min ✅

### Mise en place de cron-job.org (une seule fois)

1. **Token GitHub** : <https://github.com/settings/personal-access-tokens/new>
   - Token name : `cron-notif-tennis`, Expiration : 1 an
   - Repository access : *Only select repositories* → `notif-tennis`
   - Repository permissions → **Actions : Read and write**
   - *Generate token* → copier (`github_pat_…`). Ne le partager avec personne.
2. **Compte gratuit** sur <https://cron-job.org> → *Create cronjob* :
   - URL : `https://api.github.com/repos/hongjacques-coder/notif-tennis/actions/workflows/notif-tennis.yml/dispatches`
   - Execution schedule → *Custom* :
     - Minutes : `0, 15, 30, 45`
     - Hours : `7` à `21`
     - Days / Months / Weekdays : tous
     - Time zone : **Europe/Paris**
3. Onglet **Advanced** :
   - Request method : `POST`
   - Headers :
     - `Accept` : `application/vnd.github+json`
     - `Authorization` : `Bearer github_pat_…`
     - `X-GitHub-Api-Version` : `2022-11-28`
     - `Content-Type` : `application/json`
   - Request body : `{"ref":"main"}`
4. *Save* → *Test run* : réponse attendue **204**, et un run apparaît dans l'onglet *Actions*.

### Changer la plage horaire ou la fréquence

- Plage horaire : `HEURE_DEBUT, HEURE_FIN` en haut de `notif_tennis.py` **et** les heures dans cron-job.org.
- Fréquence : les minutes dans cron-job.org. Attention au budget de 2 000 min / mois.

## Filtres (optionnels)

En haut de `notif_tennis.py` :

```python
DEPARTEMENTS = ["75", "77", "78", "91", "92", "93", "94", "95"]  # Île-de-France ([] = tous)
NIVEAU_MAX = "30/2"  # "" = pas de filtre
```

| Site | Comment le niveau est lu | 🎾 verte | ⚠️ orange (à toi de trancher) | Pas de notif |
|---|---|---|---|---|
| Partennis | Niveau min demandé + niveau du joueur | les 2 ≤ 30/2 | un seul ≤ 30/2 | les 2 > 30/2 |
| Tennis-Contact | Classements cités dans le texte libre (ex. « 30/3 mini à 30/2 ») | tous ≤ 30/2 | mélange, ou aucun niveau cité | tous > 30/2 |

Une annonce Tennis-Contact marquée « Partie réservée » est signalée par 🔒 dans la notif.

## Fonctionnement

1. Pour chaque site, le script lit **toutes** les pages (il suit la pagination jusqu'au bout).
2. Chaque partie a un identifiant :
   - Partennis : empreinte `pseudo + date + lieu + description` (le site n'a pas d'ID).
   - Tennis-Contact : l'ID de la partie donné par le site.
3. Un identifiant absent de `seen.json` déclenche une notif Discord, puis il est ajouté au fichier.
4. Premier passage sur un nouveau site : les parties existantes sont enregistrées **sans notifier**.
5. `seen.json` est recommité dans le repo après chaque run. Les parties passées depuis plus de 7 jours sont oubliées.
6. Un site en panne ne bloque pas l'autre.
7. Si un site renvoie 0 partie (ou moins que son compteur), tu reçois une alerte « structure changée », au maximum une fois par jour.

## Ajouter un site

Créer une classe sur le modèle de `TennisContact` dans `notif_tennis.py` (méthodes `scraper`, `parse`, `filtrer`) et l'ajouter à la liste `SOURCES`.

## Tester le webhook

*Actions* → *notif-tennis* → *Run workflow* → coche **Envoyer un message de test sur Discord** → *Run workflow*.

Ou en local :

```bash
pip install -r requirements.txt
DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..." python notif_tennis.py --test
```
