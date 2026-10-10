"""Surveille les propositions de partie de tennis publiées sur plusieurs sites
et envoie une notification Discord pour chaque nouvelle partie.

Sources :
  - partennis.com/proposition-de-partie
  - tennis-contact.com/parties.php
"""

import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# --- Réglages -----------------------------------------------------------------

SEEN_FILE = Path(__file__).with_name("seen.json")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

# Départements acceptés (ici : Île-de-France). [] = tous.
DEPARTEMENTS: list[str] = ["75", "77", "78", "91", "92", "93", "94", "95"]
# Niveau max. "" = pas de filtre.
#   Partennis : vérifié sur le niveau minimum demandé ET sur le niveau du joueur.
#   Tennis-Contact : le niveau n'existe que dans le texte libre -> on lit les classements cités.
# Notif verte si tout est OK, notif ⚠️ orange si incohérent / non précisé (à toi de trancher),
# pas de notif si tout dépasse.
NIVEAU_MAX = "30/2"

MAX_PAGES = 200          # garde-fou contre une boucle infinie
PAUSE_ENTRE_PAGES = 1.5  # secondes, pour ne pas surcharger les sites
GARDER_JOURS = 7         # on oublie les parties passées depuis plus de N jours

# ------------------------------------------------------------------------------

HEADERS = {"User-Agent": "Mozilla/5.0 (notif-tennis; usage personnel)"}

MOIS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

# Classement du plus faible au plus fort
NIVEAUX = ["Débutant", "40", "30/5", "30/4", "30/3", "30/2", "30/1", "30",
           "15/5", "15/4", "15/3", "15/2", "15/1", "15", "5/6", "4/6", "3/6",
           "2/6", "1/6", "0", "-2/6", "-4/6", "-15", "-30"]

# Noms de départements (Tennis-Contact les écrit en toutes lettres)
DEPT_PAR_NOM = {
    "paris": "75", "seine et marne": "77", "yvelines": "78", "essonne": "91",
    "hauts de seine": "92", "seine saint denis": "93", "val de marne": "94",
    "val d oise": "95",
}


def log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def normaliser(texte: str) -> str:
    """'Val-d'Oise' -> 'val d oise'."""
    texte = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", texte.lower()).strip()


def fetch(url: str) -> BeautifulSoup:
    """Télécharge une page (3 essais) et gère l'encodage (UTF-8 ou ISO-8859-1)."""
    for essai in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            if "charset" not in r.headers.get("content-type", "").lower():
                m = re.search(rb'charset=["\']?([\w-]+)', r.content[:3000], re.I)
                r.encoding = m.group(1).decode() if m else "utf-8"
            return BeautifulSoup(r.text, "html.parser")
        except requests.RequestException as e:
            log(f"Erreur ({essai + 1}/3) sur {url} : {e}")
            time.sleep(5 * (essai + 1))
    raise RuntimeError(f"Impossible de charger {url}")


def niveau_ok(niveau: str) -> bool | None:
    """True si niveau <= NIVEAU_MAX, None si niveau inconnu."""
    niveau = niveau.split(" - ")[0].strip()
    if niveau not in NIVEAUX:
        return None
    return NIVEAUX.index(niveau) <= NIVEAUX.index(NIVEAU_MAX)


def dept_ok(code: str) -> bool:
    return not DEPARTEMENTS or code in DEPARTEMENTS


# --- Source 1 : Partennis -----------------------------------------------------

class Partennis:
    nom = "Partennis"
    cle = "partennis"
    url = "https://www.partennis.com/proposition-de-partie"

    def scraper(self) -> tuple[list[dict], int | None]:
        """Parcourt toutes les pages en suivant le lien 'Suivant' jusqu'au bout."""
        parties, attendu, page = [], None, 1
        url = self.url
        while page <= MAX_PAGES:
            soup = fetch(url)
            if attendu is None:
                badge = soup.select_one("#menu .badge")
                if badge and badge.get_text(strip=True).isdigit():
                    attendu = int(badge.get_text(strip=True))

            cards = soup.select("div.apercu_user")
            parties.extend(self.parse(c) for c in cards)

            m = re.search(r"Page\s+(\d+)\s*/\s*(\d+)", soup.get_text(" "))
            total = int(m.group(2)) if m else page
            log(f"[{self.nom}] Page {page}/{total} : {len(cards)} partie(s)")

            suivant = soup.select_one('a[rel="next"]')
            if page >= total or not suivant or "disabled" in suivant.get("class", []):
                break
            page += 1
            url = f"{self.url}?&page={page}"
            time.sleep(PAUSE_ENTRE_PAGES)
        return parties, attendu

    def parse(self, card) -> dict:
        profil = card.select_one("a.h4")
        joueur = profil.get_text(" ", strip=True) if profil else ""
        profil_url = profil["href"] if profil and profil.has_attr("href") else self.url
        pseudo = profil_url.rstrip("/").split("/")[-1] if profil else "?"

        champs = {}
        for li in card.select("ul.ul_no_style li"):
            label = li.find("b")
            if not label:
                continue
            cle = label.get_text(" ", strip=True).rstrip(" :").strip()
            label.extract()
            champs[cle] = li.get_text(" ", strip=True)

        m = re.search(r"Min:\s*(\S+)\s*Max:\s*(\S+)", champs.get("Niveau attendu", ""))
        niv_min, niv_max = (m.group(1), m.group(2)) if m else ("", "")

        badge = card.select_one("span.badge")
        niveau_joueur = ""
        if badge:
            niveau_joueur = re.sub(r"\s+", " ", badge.get_text(" ", strip=True)).replace("Niveau : ", "")

        club_a = card.select_one('a[href*="/club/"]')
        date_jeu, lieu, dept, infos = (champs.get("On joue quand ?", ""), champs.get("On joue ou ?", ""),
                                       champs.get("Cp/Dept", ""), champs.get("Des infos", ""))
        d = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", date_jeu)
        mois = MOIS.get(d.group(2).lower()) if d else None
        empreinte = hashlib.sha256("|".join([pseudo, date_jeu, lieu, infos]).encode()).hexdigest()[:16]

        return {
            "id": empreinte,
            "pseudo": pseudo,
            "url": profil_url,
            "date_jeu": date_jeu,
            "date_iso": date(int(d.group(3)), mois, int(d.group(1))).isoformat() if mois else None,
            "lieu": lieu,
            "dept": dept,
            "dept_code": dept.split(" ")[0],
            "niv_min": niv_min,
            "niveau_joueur": niveau_joueur,
            "reservee": False,
            "champs": [
                ("📅 Quand", date_jeu, True),
                ("📍 Où", f"{lieu or '?'} ({dept})", True),
                ("🏆 Niveau attendu", f"{niv_min} → {niv_max}", True),
                ("👤 Joueur", f"{joueur}\nNiveau : {niveau_joueur}", False),
                ("🎾 Club", club_a.get_text(" ", strip=True) if club_a else "", False),
                ("ℹ️ Infos", infos, False),
            ],
        }

    def filtrer(self, p: dict) -> tuple[bool, str]:
        """Renvoie (notifier ?, alerte)."""
        if not dept_ok(p["dept_code"]):
            return False, ""
        if not NIVEAU_MAX:
            return True, ""
        annonce, joueur = niveau_ok(p["niv_min"]), niveau_ok(p["niveau_joueur"])
        if annonce is False and joueur is False:
            return False, ""
        if annonce is False:
            return True, f"Niveau min demandé ({p['niv_min']}) > {NIVEAU_MAX}, mais le joueur est OK"
        if joueur is False:
            return True, f"Joueur ({p['niveau_joueur'].split(' - ')[0]}) > {NIVEAU_MAX}, mais l'annonce est OK"
        return True, ""


# --- Source 2 : Tennis-Contact ------------------------------------------------

class TennisContact:
    nom = "Tennis-Contact"
    cle = "tennis-contact"
    url = "https://www.tennis-contact.com/parties.php"

    def scraper(self) -> tuple[list[dict], int | None]:
        """Lit la liste ; si le site pagine, suit tous les liens de pagination trouvés."""
        parties, attendu, ids = [], None, set()
        a_visiter, visitees = [self.url], set()
        while a_visiter and len(visitees) < MAX_PAGES:
            url = a_visiter.pop(0)
            if url in visitees:
                continue
            visitees.add(url)
            soup = fetch(url)
            if attendu is None:
                m = re.search(r"(\d+)\s+propositions? de partie", soup.get_text(" "))
                attendu = int(m.group(1)) if m else None

            lignes = soup.select("table#proposition_parties tr")[1:]
            nouvelles = [p for p in (self.parse(tr) for tr in lignes) if p and p["id"] not in ids]
            ids.update(p["id"] for p in nouvelles)
            parties.extend(nouvelles)
            log(f"[{self.nom}] Page {len(visitees)} : {len(nouvelles)} partie(s)")

            # Liens de pagination éventuels (parties.php?...), sauf changement de langue
            for a in soup.select('a[href*="parties.php?"]'):
                lien = urljoin(url, a["href"])
                if "lang=" not in lien and lien not in visitees:
                    a_visiter.append(lien)
            if a_visiter:
                time.sleep(PAUSE_ENTRE_PAGES)
        return parties, attendu

    def parse(self, tr) -> dict | None:
        tds = {c: tr.select_one(f"td.{c}") for c in ("parties_date", "parties_qui", "parties_description")}
        lien = tr.select_one('a[href*="partie="]')
        if not all(tds.values()) or not lien:
            return None
        id_partie = re.search(r"partie=(\d+)", lien["href"]).group(1)

        date_txt = tds["parties_date"].get_text(" ", strip=True)
        d = re.search(r"(\d{2})/(\d{2})/(\d{4})", date_txt)
        qui = tds["parties_qui"].get_text(" ", strip=True)

        desc = tds["parties_description"]
        for br in desc.find_all("br"):
            br.replace_with("\n")
        morceaux = [m.strip() for m in desc.get_text().split("\n", 2)]
        lieu = morceaux[0] if morceaux else ""
        club = morceaux[1] if len(morceaux) > 1 else ""
        infos = morceaux[2] if len(morceaux) > 2 else ""

        # "Paris 15eme arrondissement (paris)" -> département "paris" -> 75
        m = re.search(r"\(([^()]*)\)\s*$", lieu)
        nom_dept = normaliser(m.group(1)) if m else ""

        # Classements cités dans le texte (ex : "30/3 mini à 30/2 maxi")
        texte = f"{club} {infos}"
        niveaux = [n for n in re.findall(r"(?<![\d/])(-?\d{1,2}/\d)(?![\d/])", texte) if n in NIVEAUX]

        return {
            "id": id_partie,
            "pseudo": qui,
            "url": urljoin(self.url, lien["href"]),
            "date_jeu": date_txt,
            "date_iso": f"{d.group(3)}-{d.group(2)}-{d.group(1)}" if d else None,
            "lieu": lieu,
            "dept_code": DEPT_PAR_NOM.get(nom_dept, ""),
            "niveaux_texte": list(dict.fromkeys(niveaux)),
            "reservee": "Réservée" in tr.get_text(),
            "champs": [
                ("📅 Quand", date_txt, True),
                ("📍 Où", lieu, True),
                ("🏆 Niveaux cités", ", ".join(dict.fromkeys(niveaux)) or "non précisé", True),
                ("👤 Joueur", qui, False),
                ("🎾 Club", "" if club.startswith("Salle/club indiff") else club, False),
                ("ℹ️ Infos", infos, False),
            ],
        }

    def filtrer(self, p: dict) -> tuple[bool, str]:
        if not dept_ok(p["dept_code"]):
            return False, ""
        if not NIVEAU_MAX:
            return True, ""
        resultats = [niveau_ok(n) for n in p["niveaux_texte"]]
        if not resultats:
            return True, "Niveau non précisé dans l'annonce"
        if not any(resultats):
            return False, ""
        if not all(resultats):
            return True, f"Niveaux cités : {', '.join(p['niveaux_texte'])} (certains > {NIVEAU_MAX})"
        return True, ""


SOURCES = [Partennis(), TennisContact()]


# --- Discord ------------------------------------------------------------------

def discord(payload: dict) -> None:
    if not DISCORD_WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL n'est pas défini")
    for _ in range(3):
        r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=30)
        if r.status_code == 429:  # rate limit Discord
            time.sleep(float(r.json().get("retry_after", 2)))
            continue
        r.raise_for_status()
        return
    raise RuntimeError("Discord : trop de rate limit")


def notifier(source, p: dict, alerte: str) -> None:
    description = []
    if alerte:
        description.append(f"⚠️ {alerte}")
    if p["reservee"]:
        description.append("🔒 Marquée « Partie réservée » sur le site")
    discord({
        "username": "notif-tennis",
        "embeds": [{
            "author": {"name": source.nom},
            "title": f"{'⚠️' if alerte else '🎾'} Nouvelle partie : {p['pseudo']} – {p['date_jeu']}"[:256],
            **({"description": "\n".join(description)} if description else {}),
            "url": p["url"],
            "color": 0xF39C12 if alerte else 0x2ECC71,
            "fields": [{"name": n, "value": v[:1024], "inline": i} for n, v, i in p["champs"] if v],
            "footer": {"text": source.url},
        }],
    })


# --- Mémoire (seen.json) ------------------------------------------------------

def charger_seen() -> dict:
    if not SEEN_FILE.exists():
        return {"sources": [], "alertes": {}, "parties": {}}
    data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
    if "parties" not in data:  # ancien format : uniquement Partennis
        data = {"sources": ["partennis"], "alertes": {},
                "parties": {f"partennis:{k}": v for k, v in data.items()}}
    data.setdefault("alertes", {})
    return data


def sauver_seen(seen: dict) -> None:
    limite = (date.today() - timedelta(days=GARDER_JOURS)).isoformat()
    seen["parties"] = {k: v for k, v in seen["parties"].items()
                       if not v.get("date_jeu_iso") or v["date_jeu_iso"] >= limite}
    SEEN_FILE.write_text(json.dumps(seen, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                         encoding="utf-8")


def alerter_une_fois_par_jour(seen: dict, cle: str, message: str) -> None:
    """Évite d'envoyer la même alerte technique toutes les 15 min."""
    if seen["alertes"].get(cle) == date.today().isoformat():
        return
    log(message)
    try:
        discord({"content": f"⚠️ notif-tennis : {message}"})
        seen["alertes"][cle] = date.today().isoformat()
    except Exception as e:
        log(f"Alerte non envoyée : {e}")


# --- Programme principal ------------------------------------------------------

def traiter_source(source, seen: dict) -> int:
    parties, attendu = source.scraper()
    log(f"[{source.nom}] {len(parties)} partie(s) trouvée(s) (compteur du site : {attendu})")

    if not parties and attendu:
        alerter_une_fois_par_jour(seen, f"{source.cle}:vide",
                                  f"{source.nom} : 0 partie lue alors que le site en annonce {attendu}. "
                                  "La structure de la page a peut-être changé.")
        return 0
    if attendu and len(parties) < attendu:
        alerter_une_fois_par_jour(seen, f"{source.cle}:incomplet",
                                  f"{source.nom} : {len(parties)} partie(s) lue(s) sur {attendu} annoncées. "
                                  "Certaines pages ne sont peut-être pas lues.")

    premier_lancement = source.cle not in seen["sources"]
    nouvelles = 0
    for p in parties:
        cle = f"{source.cle}:{p['id']}"
        if cle in seen["parties"]:
            continue
        if not premier_lancement:
            ok, alerte = source.filtrer(p)
            if ok:
                notifier(source, p, alerte)  # si ça plante : pas marquée vue -> réessai au prochain run
                nouvelles += 1
                time.sleep(1)
        seen["parties"][cle] = {
            "pseudo": p["pseudo"],
            "date_jeu": p["date_jeu"],
            "date_jeu_iso": p["date_iso"],
            "lieu": p["lieu"],
            "vu_le": datetime.now().isoformat(timespec="seconds"),
        }
        sauver_seen(seen)

    if premier_lancement:
        seen["sources"].append(source.cle)
        sauver_seen(seen)
        log(f"[{source.nom}] Premier lancement : {len(parties)} partie(s) enregistrée(s), aucune notification.")
    else:
        log(f"[{source.nom}] {nouvelles} nouvelle(s) partie(s) notifiée(s).")
    return nouvelles


def main() -> int:
    if "--test" in sys.argv:
        discord({"content": "✅ notif-tennis : le webhook Discord fonctionne !"})
        log("Notification de test envoyée.")
        return 0

    seen = charger_seen()
    erreurs = 0
    for source in SOURCES:
        try:
            traiter_source(source, seen)  # une source en panne ne bloque pas les autres
        except Exception as e:
            erreurs += 1
            log(f"[{source.nom}] ERREUR : {e}")
    sauver_seen(seen)
    return 1 if erreurs == len(SOURCES) else 0


if __name__ == "__main__":
    sys.exit(main())
