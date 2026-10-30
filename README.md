# notif-tennis

Notification Discord à chaque nouvelle partie publiée sur :

- <https://www.partennis.com/proposition-de-partie>
- <https://www.tennis-contact.com/parties.php>
- <https://tennissables.com/parties-tennis/>

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

- **OFF** : *Actions* → *notif-tennis* → bouton `···` → **Disable workflow**.
  La boucle en cours le détecte et s'arrête en 5 min max.
- **ON** : même endroit → **Enable workflow**, puis **Run workflow** pour relancer la chaîne tout de suite
  (sinon le cron de secours la relance tout seul, parfois après quelques heures).

Ça marche aussi depuis l'app mobile GitHub ou le navigateur du téléphone.

**Pause jusqu'à une date** : en haut de `notif_tennis.py`, `REPRISE_LE = "2026-10-16"`.
Avant cette date (heure de Paris), le script ne vérifie rien. Il reprend tout seul ce jour-là.
À la reprise, les parties publiées pendant la pause et encore en ligne sont notifiées.
`REPRISE_LE = ""` = pas de pause.

## Fréquence : toutes les 5 min, 24 h/24

Le planificateur de GitHub n'est pas fiable (un run toutes les ~4-5 h). Le script tourne donc **en boucle** :

1. Un run vérifie les sites toutes les `INTERVALLE_MINUTES` (5) pendant `DUREE_RUN_MINUTES` (340, soit ~5h40).
2. À la fin, il relance automatiquement le run suivant (`gh workflow run`).
3. Le cron `*/15` du workflow sert de filet de sécurité pour redémarrer la chaîne si elle casse.
4. `seen.json` est sauvegardé (commit) dès qu'une nouvelle partie est vue.

⚠️ Le mode boucle ne s'active que si le **repo est public** (minutes GitHub Actions illimitées).
Si le repo redevient privé, le script ne fait qu'une vérification par run, pour ne pas vider le quota.

Changer la fréquence : `INTERVALLE_MINUTES` en haut de `notif_tennis.py` (1 min possible).

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
| Tennissables | Colonne « Niveau min » (« Non classé » = OK), sinon classements cités dans le texte | ≤ 30/2 | aucun niveau, ou mélange dans le texte | > 30/2 |

**Lieu Tennissables** (texte libre) : code postal, « Paris », arrondissement (« 19ème »), quelques lieux connus
(Lenglen, Elisabeth, Faluère…), sinon la ville est géolocalisée via l'API Adresse du gouvernement.
Lieu non reconnu → notif ⚠️ orange, à toi de trancher.

Une annonce Tennis-Contact marquée « Partie réservée » est signalée par 🔒 dans la notif.

## Fonctionnement

1. Pour chaque site, le script lit **toutes** les pages (il suit la pagination jusqu'au bout).
2. Chaque partie a un identifiant :
   - Partennis : empreinte `pseudo + date + lieu + description` (le site n'a pas d'ID).
   - Tennis-Contact : l'ID de la partie donné par le site.
   - Tennissables : empreinte `profil + date + heure + lieu + description`.
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
