"""Player-name matching + course-code lookup — shared by the CLI importers
(import_udisc.py / import_pdga.py) and the Cloudflare Worker.

Pure functions; no I/O. Caller hands in a player name and a roster (list of
known names) or a layout string; gets back the matched roster entry / course
code.
"""

from __future__ import annotations

import unicodedata
from difflib import get_close_matches


# Display name for every course code used in the sheet.
COURSE_NAMES: dict[str, str] = {
    "epw":  "Ettyville MVP White",
    "epb":  "Ettyville MVP Blue",
    "epy":  "Ettyville MVP Yellow",
    "eiw":  "Ettyville Axiom White",
    "eib":  "Ettyville Axiom Blue",
    "eiy":  "Ettyville Axiom Yellow",
    "lmb":  "Larrimac Blue",
    "lmy":  "Larrimac Yellow",
    "alm":  "Almonte",
    "alb":  "Almonte Blue",
    "aly":  "Almonte Yellow",
    "alr":  "Almonte Red",
    "alm0": "Almonte (old)",
    "kan":  "Kanata",
    "mtn":  "Mountain",
    "cur":  "Currie",
    "shr":  "The Shire",
    "upi":  "UPI",
    "ffw":  "Franktown",
    "kvb":  "Ferguson Blue",
    "kvy":  "Ferguson Yellow",
    "kvr":  "Ferguson Red",
    "kpv":  "Kemptville (old)",
    "cf":   "Camp Fortune",
    "rhl":  "Rockhill",
    "ctp":  "Centrepointe",
    "sr":   "Sandy Row Blue",
    "sro":  "Sandy Row Orange",
    "unq":  "One-off layout",
    "jeu":  "(unused)",
}

# Common first-name shortenings the master sheet uses.
FIRST_NAME_ALIASES = {
    "Christopher": "Chris", "Matthew": "Matt", "Jonathan": "Jon",
    "Michael": "Mike", "Robert": "Rob", "William": "Will",
    "Daniel": "Dan", "Nicholas": "Nick", "Andrew": "Andy",
    "Joshua": "Josh", "Anthony": "Tony", "Maximilian": "Max",
    "Maxime": "Max",
}


def strip_accents(s: str) -> str:
    """é → e, ñ → n, ç → c, etc. — for matching only, never for writing."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def to_lastname_first(udisc_name: str) -> str:
    """'Jacob Mainville' → 'Mainville_Jacob'. Multi-word last names join with _.

    'Pier-luc Gyre' → 'Gyre_Pier-luc' (hyphens preserved, case preserved).
    """
    parts = udisc_name.strip().split()
    if len(parts) < 2:
        return udisc_name.strip()
    return f"{'_'.join(parts[1:])}_{parts[0]}"


def match_player(udisc_name: str, roster: list[str]) -> tuple[str | None, str]:
    """Return (matched_roster_name, reason) or (None, why_not).

    Matching cascade (highest confidence first):
        1. Exact match after Last_First flip
        2. Same after stripping accents from both sides
        3. Case-insensitive
        4. Unique surname (one Last_* in roster) + first-name initial agrees
        5. First-name shortening (Christopher → Chris, etc.)
        6. Fuzzy (difflib, ≥0.75 similarity)
    """
    candidate = to_lastname_first(udisc_name)

    # 1 — exact
    if candidate in roster:
        return candidate, "exact"

    # 2 — accent-stripped exact
    stripped = {strip_accents(n).lower(): n for n in roster}
    key = strip_accents(candidate).lower()
    if key in stripped:
        return stripped[key], "accent-normalized"

    # 3 — case-insensitive
    ci = {n.lower(): n for n in roster}
    if candidate.lower() in ci:
        return ci[candidate.lower()], "case-insensitive"

    # 4 — unique surname, BUT only if the first name's first letter also
    #     agrees. Without that check, an unfamiliar player ("Amber Correia")
    #     would get auto-matched to a roster member ("Correia_Justin") just
    #     because they share a last name. First-name shortenings (Chris/
    #     Christopher, Dave/David, Max/Maxime) still share initial letters,
    #     so this filter doesn't reject legitimate matches.
    parts = udisc_name.strip().split()
    udisc_first_initial = parts[0][0].lower() if parts else ""
    last = candidate.split("_")[0]
    last_stripped = strip_accents(last).lower()
    surname_matches = [
        n for n in roster
        if strip_accents(n).lower().startswith(last_stripped + "_")
    ]
    if len(surname_matches) == 1:
        roster_first = (
            surname_matches[0].split("_", 1)[1] if "_" in surname_matches[0] else ""
        )
        if roster_first and udisc_first_initial == roster_first[0].lower():
            return surname_matches[0], "unique surname + first-initial"
        return None, (
            f"surname matches {surname_matches[0]!r} but first names "
            f"differ ({parts[0] if parts else '?'} vs {roster_first})"
        )
    if len(surname_matches) > 1:
        return None, f"ambiguous surname → {surname_matches}"

    # 5 — first-name shortening
    if len(parts) >= 2:
        short = FIRST_NAME_ALIASES.get(parts[0])
        if short:
            alt = f"{'_'.join(parts[1:])}_{short}"
            if alt in roster:
                return alt, f"first-name shortening ({parts[0]}→{short})"

    # 6 — fuzzy
    close = get_close_matches(candidate, roster, n=1, cutoff=0.75)
    if close:
        return close[0], "fuzzy"

    return None, "no match"


def guess_course_from_layout(text: str) -> str | None:
    """Map a layout/event string (UDisc or PDGA) to one of our course codes.

    Context-aware: looks for the COURSE name first, then a tee color
    modifier within the same text. Handles both compact UDisc names
    ("Almonte Blues") and verbose PDGA strings ("Larrimac Disc Golf
    Course - YELLOWS; 18 holes").
    """
    s = text.lower()

    def has(*tokens):
        return any(t in s for t in tokens)

    # Larrimac
    if has("larrimac", "lmac"):
        if has("yellow"):
            return "lmy"
        if has("blue"):
            return "lmb"
        return "lmb"
    # Sandy Row. PDGA uses "ORANGE Sandy Row" / "BLUE Sandy Row"; UDisc
    # sometimes drops the color ("Sandy Row Golf Club"). User convention
    # in active2025: sro = ORANGE, sr = BLUE (BLUE is the default when no
    # color modifier is present).
    if has("sandy row"):
        return "sro" if has("orange") else "sr"
    # Almonte
    if has("almonte"):
        if has("yellow"):
            return "aly"
        if has("blue"):
            return "alb"
        if has("red"):
            return "alr"
        return "alm"
    # Ferguson Forest (Kemptville). UDisc: "Ferguson Forest Blues",
    # "Ferguson Forest Wonderbread", etc. User maps all of these to
    # kvb/kvy/kvr (the Kemptville tee codes), NOT the older `kpv` slot.
    # Check this before the general "kemptville" rule so Ferguson always
    # lands on the right code.
    if has("ferguson"):
        if has("yellow"):
            return "kvy"
        if has("red"):
            return "kvr"
        return "kvb"
    # Kemptville (other layouts, if any)
    if has("kemptville"):
        if has("yellow"):
            return "kvy"
        if has("blue"):
            return "kvb"
        if has("red"):
            return "kvr"
        return "kvb"
    # Ettyville Phase MVP. UDisc uses "Ettyville MVP <tee>". Also Pdgy aliases.
    if has("ettyville mvp", "phase mvp", "pdgy", "mvp tee", "mvp"):
        if has("white"):
            return "epw"
        if has("yellow"):
            return "epy"
        if has("blue"):
            return "epb"
    # Ettyville Phase Axiom. UDisc uses "Ettyville Axiom [Dunes] <tee>".
    if has("axiom", "inva"):
        if has("white"):
            return "eiw"
        if has("yellow"):
            return "eiy"
        if has("blue"):
            return "eib"
    # Single-layout courses
    if has("the shire", "shire"):
        return "shr"
    if has("camp fortune"):
        return "cf"
    if has("franktown"):
        return "rhl"
    if has("centrepointe", "centerpointe"):
        return "ctp"
    # Mountain — UDisc lists this as "Philips Screw Driver" (yes, that
    # spelling); user catalogs it as Phillips_Screwdriver → mtn.
    if has("philips screw driver", "phillips screw driver", "phillips screwdriver",
           "screwdriver", "mountain"):
        return "mtn"
    if has("kanata"):
        return "kan"
    if has("upi"):
        return "upi"
    return None
