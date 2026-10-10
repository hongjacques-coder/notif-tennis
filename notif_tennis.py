"""Surveille les propositions de partie publiques de partennis.com
et envoie une notification Discord pour chaque nouvelle partie."""

import hashlib
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# --- Réglages -----------------------------------------------------------------

BASE_URL = "https://www.partennis.com/proposition-de-partie"
SEEN_FILE = Path(__file__).with_name("seen.json")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

# Filtres optionnels (laisser vide = toutes les parties).
# Ex : DEPARTEMENTS = ["75", "92", "94"]
DEPARTEMENTS: list[str] = []
# Ex : MON_NIVEAU = "30/2" -> notifie seulement si ton niveau est dans la fourchette demandée
MON_NIVEAU = ""

MAX_PAGES = 200          # garde-fou contre une boucle infinie
PAUSE_ENTRE_PAGES = 1.5  # secondes, pour ne pas surcharger le site
GARDER_JOURS = 7         # on oublie les parties passées depuis plus de N jours

# ------------------------------------------------------------------------------

HEADERS = {"User-Agent": "Mozilla/5.0 (notif-tennis; usage personnel)"}

MOIS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

# Classement du plus faible au plus fort (même ordre que sur le site)
NIVEAUX = ["Débutant", "40", "30/5", "30/4", "30/3", "30/2", "30/1", "30",
           "15/5", "15/4", "15/3", "15/2", "15/1", "15", "5/6", "4/6", "3/6",
           "2/6", "1/6", "0", "-2/6", "-4/6", "-15", "-30"]


def log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def parse_date_fr(texte: str) -> date | None:
    m = re.search(r"(\d{1,2})\s+([A-Za-zéèûôÉ]+)\s+(\d{4})", texte)
    if not m:
        return None
    mois = MOIS.get(m.group(2).lower())
    return date(int(m.group(3)), mois, int(m.group(1))) if mois else None


def fetch(url: str) -> str:
    """Télécharge une page, avec 3 essais."""
    for essai in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            log(f"Erreur ({essai + 1}/3) sur {url} : {e}")
            time.sleep(5 * (essai + 1))
    raise RuntimeError(f"Impossible de charger {url}")


def parse_partie(card) -> dict:
    """Extrait les infos d'une carte 'apercu_user'."""
    profil = card.select_one("a.h4")
    lignes = profil.get_text(" ", strip=True) if profil else ""
    pseudo = profil["href"].rstrip("/").split("/")[-1] if profil and profil.has_attr("href") else "?"

    champs = {}
    for li in card.select("ul.ul_no_style li"):
        label = li.find("b")
        if not label:
            continue
        cle = label.get_text(" ", strip=True).rstrip(" :").strip()
        label.extract()
        champs[cle] = li.get_text(" ", strip=True)

    niveau_attendu = champs.get("Niveau attendu", "")
    m = re.search(r"Min:\s*(\S+)\s*Max:\s*(\S+)", niveau_attendu)
    niv_min, niv_max = (m.group(1), m.group(2)) if m else ("", "")

    niveau_joueur = ""
    badge = card.select_one("span.badge")
    if badge:
        niveau_joueur = re.sub(r"\s+", " ", badge.get_text(" ", strip=True)).replace("Niveau : ", "")

    club = ""
    club_a = card.select_one('a[href*="/club/"]')
    if club_a:
        club = club_a.get_text(" ", strip=True)

    return {
        "pseudo": pseudo,
        "profil_url": profil["href"] if profil and profil.has_attr("href") else BASE_URL,
        "joueur": lignes,
        "niveau_joueur": niveau_joueur,
        "club": club,
        "date_jeu": champs.get("On joue quand ?", ""),
        "lieu": champs.get("On joue ou ?", ""),
        "dept": champs.get("Cp/Dept", ""),
        "niv_min": niv_min,
        "niv_max": niv_max,
        "infos": champs.get("Des infos", ""),
    }


def empreinte(p: dict) -> str:
    """ID stable : pseudo + date + lieu + description (pas la 'dernière connexion')."""
    cle = "|".join([p["pseudo"], p["date_jeu"], p["lieu"], p["infos"]])
    return hashlib.sha256(cle.encode("utf-8")).hexdigest()[:16]


def scrape_toutes_les_pages() -> tuple[list[dict], int | None]:
    """Parcourt toutes les pages en suivant le lien 'Suivant' jusqu'au bout."""
    parties, attendu = [], None
    url, page = BASE_URL, 1
    while url and page <= MAX_PAGES:
        soup = BeautifulSoup(fetch(url), "html.parser")
        if attendu is None:
            badge = soup.select_one("#menu .badge")
            if badge and badge.get_text(strip=True).isdigit():
                attendu = int(badge.get_text(strip=True))

        cards = soup.select("div.apercu_user")
        parties.extend(parse_partie(c) for c in cards)

        m = re.search(r"Page\s+(\d+)\s*/\s*(\d+)", soup.get_text(" "))
        total = int(m.group(2)) if m else page
        log(f"Page {page}/{total} : {len(cards)} partie(s)")

        suivant = soup.select_one('a[rel="next"]')
        if page >= total or not suivant or "disabled" in suivant.get("class", []):
            break
        page += 1
        url = f"{BASE_URL}?&page={page}"
        time.sleep(PAUSE_ENTRE_PAGES)
    return parties, attendu


def passe_filtres(p: dict) -> bool:
    if DEPARTEMENTS and not any(p["dept"].startswith(d) for d in DEPARTEMENTS):
        return False
    if MON_NIVEAU and p["niv_min"] in NIVEAUX and p["niv_max"] in NIVEAUX:
        i = NIVEAUX.index(MON_NIVEAU)
        if not NIVEAUX.index(p["niv_min"]) <= i <= NIVEAUX.index(p["niv_max"]):
            return False
    return True


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


def notifier(p: dict) -> None:
    champs = [
        {"name": "📅 Quand", "value": p["date_jeu"] or "?", "inline": True},
        {"name": "📍 Où", "value": f"{p['lieu'] or '?'} ({p['dept']})", "inline": True},
        {"name": "🏆 Niveau attendu", "value": f"{p['niv_min']} → {p['niv_max']}", "inline": True},
        {"name": "👤 Joueur", "value": f"{p['joueur']}\nNiveau : {p['niveau_joueur']}"[:1024], "inline": False},
    ]
    if p["club"]:
        champs.append({"name": "🎾 Club", "value": p["club"][:1024], "inline": False})
    if p["infos"]:
        champs.append({"name": "ℹ️ Infos", "value": p["infos"][:1024], "inline": False})
    discord({
        "username": "Partennis",
        "embeds": [{
            "title": f"🎾 Nouvelle partie : {p['pseudo']} – {p['date_jeu']}",
            "url": p["profil_url"],
            "color": 0x2ECC71,
            "fields": champs,
            "footer": {"text": "partennis.com/proposition-de-partie"},
        }],
    })


def charger_seen() -> dict | None:
    if not SEEN_FILE.exists():
        return None
    return json.loads(SEEN_FILE.read_text(encoding="utf-8"))


def sauver_seen(seen: dict) -> None:
    limite = date.today() - timedelta(days=GARDER_JOURS)
    seen = {k: v for k, v in seen.items()
            if not v.get("date_jeu_iso") or date.fromisoformat(v["date_jeu_iso"]) >= limite}
    SEEN_FILE.write_text(json.dumps(seen, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                         encoding="utf-8")


def main() -> int:
    if "--test" in sys.argv:
        discord({"content": "✅ notif-tennis : le webhook Discord fonctionne !"})
        log("Notification de test envoyée.")
        return 0

    parties, attendu = scrape_toutes_les_pages()
    log(f"{len(parties)} partie(s) trouvée(s) (compteur du site : {attendu})")

    if not parties and attendu:
        discord({"content": f"⚠️ notif-tennis : 0 partie lue alors que le site en annonce {attendu}. "
                            "La structure de la page a peut-être changé."})
        return 1

    seen = charger_seen()
    premier_lancement = seen is None
    seen = seen or {}

    nouvelles = 0
    for p in parties:
        cle = empreinte(p)
        if cle in seen:
            continue
        if not premier_lancement and passe_filtres(p):
            notifier(p)  # si ça plante, la partie n'est pas marquée vue -> réessai au prochain run
            nouvelles += 1
            time.sleep(1)
        d = parse_date_fr(p["date_jeu"])
        seen[cle] = {
            "pseudo": p["pseudo"],
            "date_jeu": p["date_jeu"],
            "date_jeu_iso": d.isoformat() if d else None,
            "lieu": p["lieu"],
            "vu_le": datetime.now().isoformat(timespec="seconds"),
        }
        sauver_seen(seen)

    if premier_lancement:
        sauver_seen(seen)
        log(f"Premier lancement : {len(seen)} partie(s) enregistrée(s), aucune notification envoyée.")
    else:
        log(f"{nouvelles} nouvelle(s) partie(s) notifiée(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
