"""Tendance de franchissement des deux portes d'ATLAS — calcul rejouable par un tiers.

**Ce que ça mesure.** Les techniques d'ATLAS portent un grade : *envisageable*, *démontré*,
*réalisé*. Deux portes, donc : `Feasible → Demonstrated` et `Demonstrated → Realized`. La question
est de savoir si ces franchissements s'accélèrent, et si cette accélération n'est pas simplement
le tempo de l'équipe qui tient le catalogue.

**Ce que ça ne mesure pas, et qui doit accompagner le chiffre partout où il va** : nous ne savons
pas distinguer un monde qui accélère d'un catalogue mieux tenu. Le contrôle éditorial implémenté
ici ne retire que 5 à 11 % de la tendance, mais il **n'a aucun pouvoir de détection avant 2025** —
l'historique d'ATLAS a été réécrit le 27/05/2026 et les versions anciennes n'enregistrent presque
aucun changement éditorial. Voir README.md.

**Reproductibilité.** Les 37 versions publiées d'ATLAS sont épinglées par empreinte dans
`data/tendance-versions.json`, et le dépôt amont par son commit. Le module refuse de calculer
si une empreinte ne correspond pas : ATLAS **réécrit son historique**, et un écart silencieux
ferait comparer deux reconstructions différentes. Un tiers rejoue par :

    make tendance

qui clone le dépôt amont dans `data/cache/` au besoin, vérifie tout, puis calcule.

**Méthode.** Cox à risques proportionnels, codé ici (aucune dépendance de survie installée) :

- correction **d'Efron** pour les ex aequo — les dates sont celles de versions publiées, les
  simultanéités sont massives et Breslow les traiterait mal ;
- intervalles par **profil de vraisemblance**, jamais par Wald : avec 45 événements sur la seconde
  porte, la normalité asymptotique n'est pas acquise et le profil ne la suppose pas ;
- covariables de contrôle **dépendantes du temps**, au format (début, fin] — une valeur fixe par
  technique ne contrôlerait rien, puisqu'un sujet entré en 2022 traverse des périodes calmes puis
  agitées ;
- `maturity` et les relations `employs` sont **exclus** des covariables de contrôle : les inclure
  reviendrait à contrôler l'effet par lui-même.
"""

from __future__ import annotations

import glob
import json
import math
import os
import re
import statistics as st
import subprocess
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import yaml
from scipy.optimize import brentq, minimize, minimize_scalar
from scipy.stats import chi2

# --- autonome : les quatre fonctions reprises du dépôt privé, pour qu'il n'y ait aucun import ---
import hashlib as _hashlib


ROOT = Path(__file__).resolve().parent


def dumps(obj) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=True) + "\n"


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(obj), encoding="utf-8")


def sha256_file(path: Path) -> str:
    h = _hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


DERIVED = ROOT / "out"

AMONT = "https://github.com/mitre-atlas/atlas-data.git"
COMMIT = "3259f388d19cbcca11bacf12a0ef97f4198f711b"      # « Release v2026.09 », jamais une branche
CLONE = ROOT / "cache" / "atlas-data"
VERSIONS = ROOT / "data" / "tendance-versions.json"
SORTIE = DERIVED          # intermédiaires : reconstructibles, git-ignorés
# Livrables de publication : VERSIONNÉS. Ce qui part dans un article doit porter une empreinte,
# sinon on ne saura pas dans six mois quelle version de la figure a été publiée.
FIGURES = ROOT / "figures"

GRADES = {"Feasible": 0, "Demonstrated": 1, "Realized": 2}
PORTES = (("premiere", "Feasible", "feasible → demonstrated"),
          ("seconde", "Demonstrated", "demonstrated → realized"))
CHAMPS_NEUTRES = ("description", "references", "platforms", "name")   # jamais `maturity`
SEUIL = chi2.ppf(0.95, 1)
MENTION = ("It is difficult to tell a domain that is accelerating from a catalogue that is better "
           "kept; our hypothesis is that both effects are present. The editorial control removes "
           "only 5 to 11% of the trend, and has almost no detection power before 2025.")


LISEZMOI_FIGURES = """# Figures — publication outputs

**Do not edit by hand.** These files are produced by `make tendance` and kept under version
control, so that in six months we can say exactly which version was published. Intermediate
files (JSON, text summary) stay in `out/`, which is not version-controlled.

| File | Contents |
|---|---|
| `survie-deux-portes.{svg,pdf}` | Kaplan-Meier curves for both ATLAS gates |
| `facteurs-par-annee.{svg,pdf}` | Factors per year of entry, before and after editorial control, 95% CI |
| `parcours-fr.{svg,pdf}` | The overall path: grade at first sighting, the two gates, grade today (French) |
| `parcours-en.{svg,pdf}` | The same figure in English |

SVG for the web: real text, selectable and readable by a screen reader, colours as CSS variables
with an automatic dark theme. The font is the system font of whoever opens it, so rendering varies
slightly from one machine to the next. PDF for the paper: text as paths, identical everywhere.

**The figure never travels alone.** It is difficult to tell a domain that is accelerating from a
catalogue that is better kept; our hypothesis is that both effects are present. The editorial
control removes only 5 to 11% of the trend, and has almost no detection power before 2025.
"""


class TendanceError(RuntimeError):
    pass


# --- données : épinglées, vérifiées, jamais supposées -------------------------------------------
def preparer(clone: Path = CLONE) -> Path:
    """Clone au commit épinglé si absent, et vérifie que c'est bien celui-là."""
    if not (clone / ".git").exists():
        clone.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--quiet", AMONT, str(clone)], check=True)
    tete = subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    if tete != COMMIT:
        raise TendanceError(
            f"Le clone est à {tete[:12]}… et non au commit épinglé {COMMIT[:12]}… : "
            "ATLAS réécrit son historique, un écart silencieux comparerait deux reconstructions. "
            f"`git -C {clone} checkout {COMMIT}` ou supprimer le clone pour le refaire.")
    return clone


def charger(clone: Path = CLONE) -> list[tuple[date, dict]]:
    """[(date de publication, document)] pour les 37 versions, empreintes vérifiées."""
    attendu = json.loads(VERSIONS.read_text(encoding="utf-8"))
    trouves, ecarts = {}, []
    for p in glob.glob(str(clone / "dist" / "v6" / "ATLAS-20*.yaml")):
        tag = os.path.basename(p)[6:-5]
        if tag not in attendu:
            continue
        sha = sha256_file(Path(p))
        if sha != attendu[tag]["sha256"]:
            ecarts.append(f"{tag} : {sha[:12]}… ≠ {attendu[tag]['sha256'][:12]}…")
            continue
        trouves[tag] = p
    manquants = sorted(set(attendu) - set(trouves))
    if ecarts or manquants:
        raise TendanceError("Sources non conformes aux empreintes épinglées — "
                            + (f"écarts : {ecarts[:3]}. " if ecarts else "")
                            + (f"absentes : {manquants[:3]}." if manquants else ""))
    out = []
    for tag, p in trouves.items():
        with open(p, encoding="utf-8") as fh:
            out.append((date.fromisoformat(attendu[tag]["date"]), yaml.safe_load(fh)))
    return sorted(out, key=lambda x: x[0])


def _objets(doc: dict, cle: str) -> dict:
    o = doc.get(cle) or {}
    return o if isinstance(o, dict) else {x["id"]: x for x in o}


def trajectoires(serie: list[tuple[date, dict]]) -> dict[str, list[tuple[date, str]]]:
    """Grade de chaque technique à chaque changement, suivie par `uuid` (stable aux renommages)."""
    traj: dict[str, list[tuple[date, str]]] = defaultdict(list)
    for d0, doc in serie:
        for tid, t in _objets(doc, "techniques").items():
            u = t.get("uuid") or tid
            g = t.get("maturity")
            if g and (not traj[u] or traj[u][-1][1] != g):
                traj[u].append((d0, g))
    return traj


def mois(a: date, b: date) -> float:
    return (b - a).days / 30.44


# --- activité éditoriale : ce qui bouge dans le catalogue, hors grade ---------------------------
def volume_editorial(serie: list[tuple[date, dict]]) -> dict[str, dict]:
    """Changements par mois entre versions. `maturity` et `employs` exclus par construction."""
    out, prev = {}, None
    for d0, doc in serie:
        cur = {"date": d0, "T": _objets(doc, "techniques"), "M": _objets(doc, "mitigations"),
               "C": _objets(doc, "case-studies")}
        if prev is not None:
            dt = max(mois(prev["date"], d0), 0.1)
            neuf = len(set(cur["T"]) - set(prev["T"])) + len(set(cur["C"]) - set(prev["C"]))
            mit = len(set(cur["M"]) - set(prev["M"])) + sum(
                1 for k in set(cur["M"]) & set(prev["M"])
                if any(cur["M"][k].get(c) != prev["M"][k].get(c) for c in CHAMPS_NEUTRES))
            remanie = sum(1 for k in set(cur["T"]) & set(prev["T"])
                          if any(cur["T"][k].get(c) != prev["T"][k].get(c) for c in CHAMPS_NEUTRES))
            brut = neuf + mit + remanie
            out[d0.isoformat()] = {"mois_ecoules": round(dt, 2), "nouveaux_objets": neuf,
                                   "mitigations": mit, "champs_remanies": remanie,
                                   "brut": brut, "par_mois": round(brut / dt, 2)}
        prev = cur
    return out


def retouches_par_technique(serie: list[tuple[date, dict]]) -> dict[str, dict[str, int]]:
    """{date: {uuid: nb de champs neutres modifiés}} — l'attention portée à CETTE technique."""
    out, prev = {}, None
    for d0, doc in serie:
        par_uuid = {t.get("uuid") or k: t for k, t in _objets(doc, "techniques").items()}
        if prev is not None:
            out[d0.isoformat()] = {u: sum(1 for c in CHAMPS_NEUTRES if par_uuid[u].get(c) != prev[u].get(c))
                                   for u in set(par_uuid) & set(prev)}
        prev = par_uuid
    return out


# --- Cox : vraisemblance partielle, Efron, format (début, fin] ----------------------------------
def loglik(beta: list[float], lignes: list[dict]) -> float:
    total = 0.0
    for t in sorted({l["fin"] for l in lignes if l["evt"]}):
        risque = [l for l in lignes if l["debut"] < t <= l["fin"]]
        morts = [l for l in lignes if l["evt"] and l["fin"] == t]
        d = len(morts)
        lin = lambda l: sum(b * v for b, v in zip(beta, l["x"]))          # noqa: E731
        som_r = sum(math.exp(lin(l)) for l in risque)
        som_m = sum(math.exp(lin(l)) for l in morts)
        total += sum(lin(l) for l in morts)
        for k in range(d):
            reste = som_r - (k / d) * som_m
            if reste <= 0:
                return -1e12
            total -= math.log(reste)
    return total


def ajuster(lignes: list[dict], p: int) -> dict:
    """Estimation, et intervalle du PREMIER coefficient par profil de vraisemblance."""
    if p == 1:
        res = minimize_scalar(lambda b: -loglik([b], lignes), bounds=(-4, 4), method="bounded",
                              options={"xatol": 1e-8})
        beta, ll = [float(res.x)], -float(res.fun)
    else:
        res = minimize(lambda b: -loglik(list(b), lignes), [0.0] * p, method="Nelder-Mead",
                       options={"xatol": 1e-7, "fatol": 1e-7, "maxiter": 6000})
        beta, ll = list(res.x), -float(res.fun)

    def profil(v: float) -> float:
        if p == 1:
            return loglik([v], lignes)
        r = minimize(lambda rest: -loglik([v] + list(rest), lignes), beta[1:],
                     method="Nelder-Mead", options={"xatol": 1e-6, "fatol": 1e-6})
        return -float(r.fun)

    cible = ll - SEUIL / 2
    h = lambda v: profil(v) - cible                                        # noqa: E731
    lo = brentq(h, beta[0] - 4, beta[0], xtol=1e-5) if h(beta[0] - 4) < 0 else float("nan")
    hi = brentq(h, beta[0] + 4, beta[0], xtol=1e-5) if h(beta[0] + 4) < 0 else float("nan")
    ll0 = loglik([0.0] * p, lignes)
    return {"beta": beta, "hr": math.exp(beta[0]),
            "ic95": [math.exp(lo), math.exp(hi)],
            "loglik": ll, "p_valeur": float(chi2.sf(2 * (ll - ll0), p)),
            "n_lignes": len(lignes), "evenements": sum(l["evt"] for l in lignes)}


# --- population et panneau ----------------------------------------------------------------------
def sujets(traj: dict, depart: str, fin: date) -> list[dict]:
    out = []
    for u, pts in traj.items():
        t0 = next((d for d, g in pts if g == depart), None)
        if t0 is None:
            continue
        apres = [d for d, g in pts if d > t0 and GRADES.get(g, -1) > GRADES[depart]]
        out.append({"uuid": u, "t0": t0, "t_fin": apres[0] if apres else fin,
                    "duree": max(mois(t0, apres[0] if apres else fin), 0.1),
                    "evenement": int(bool(apres)),
                    "annee": t0.year + (t0.timetuple().tm_yday - 1) / 365.25})
    return out


def panel(S: list[dict], jalons: list[date], vol: dict, ret: dict, niveau: int) -> list[dict]:
    """niveau 1 = année seule · 2 = + volume global · 4 = + retouches de la technique (décalées)."""
    intens = [v["par_mois"] for v in vol.values()]
    moy, ec = st.mean(intens), st.pstdev(intens) or 1.0
    centre = st.mean([s["annee"] for s in S])
    brut = []
    for s in S:
        precedent, cumul, derniere = 0.0, 0, 0
        for b in [d for d in jalons if s["t0"] < d <= s["t_fin"]]:
            stop = mois(s["t0"], b)
            if stop <= precedent:
                continue
            v = vol.get(b.isoformat())
            brut.append({"debut": precedent, "fin": stop,
                         "evt": int(s["evenement"] and b == s["t_fin"]),
                         "annee": s["annee"] - centre,
                         "vol": ((v["par_mois"] if v else moy) - moy) / ec,
                         # état AVANT cette version : une promotion s'accompagne souvent d'une
                         # réécriture de la description, la retouche simultanée absorberait l'événement
                         "cumul": cumul, "recente": float(derniere)})
            cumul += (ret.get(b.isoformat()) or {}).get(s["uuid"], 0)
            derniere = 1 if (ret.get(b.isoformat()) or {}).get(s["uuid"], 0) else 0
            precedent = stop
    cums = [l["cumul"] for l in brut] or [0]
    mc, ecc = st.mean(cums), (st.pstdev(cums) or 1.0)
    colonnes = {1: ("annee",), 2: ("annee", "vol"), 4: ("annee", "vol", "cumul", "recente")}[niveau]
    return [{"debut": l["debut"], "fin": l["fin"], "evt": l["evt"],
             "x": [(l["cumul"] - mc) / ecc if c == "cumul" else l[c] for c in colonnes]}
            for l in brut]


def survie(S: list[dict]) -> dict:
    """Kaplan-Meier et variance de Greenwood — la courbe, pas seulement la médiane."""
    obs = sorted((s["duree"], s["evenement"]) for s in S)
    n = len(obs)
    prob, var, courbe = 1.0, 0.0, []
    for t in sorted({t for t, e in obs if e}):
        r = sum(1 for tt, _ in obs if tt >= t)
        d = sum(1 for tt, e in obs if tt == t and e)
        prob *= 1 - d / r
        var += d / (r * (r - d)) if r > d else 0
        se = prob * math.sqrt(var)
        courbe.append({"t": round(t, 2), "a_risque": r, "evts": d, "S": round(prob, 4),
                       "ic95": [round(max(0, prob - 1.96 * se), 4), round(min(1, prob + 1.96 * se), 4)]})
    med = next((c["t"] for c in courbe if c["S"] <= 0.5), None)
    borne_basse = next((c["t"] for c in courbe if c["ic95"][0] <= 0.5), None)
    borne_haute = next((c["t"] for c in courbe if c["ic95"][1] <= 0.5), None)
    return {"n": n, "evenements": sum(e for _, e in obs), "horizon": round(max(t for t, _ in obs), 1),
            "mediane": med, "ic95_mediane": [borne_basse, borne_haute],
            "S_fin": courbe[-1]["S"] if courbe else 1.0, "courbe": courbe}


def run(clone: Path = CLONE) -> dict:
    serie = charger(preparer(clone))
    fin = serie[-1][0]
    jalons = [d for d, _ in serie]
    traj = trajectoires(serie)
    vol, ret = volume_editorial(serie), retouches_par_technique(serie)
    res = {"mention": MENTION, "amont": {"depot": AMONT, "commit": COMMIT},
           "versions": len(serie), "de": jalons[0].isoformat(), "a": fin.isoformat(),
           "activite_editoriale": {"intervalles": len(vol),
                                   "mediane_par_mois": round(st.median([v["par_mois"] for v in vol.values()]), 2),
                                   "maximum_par_mois": max(v["par_mois"] for v in vol.values())},
           "portes": {}}
    for cle, depart, libelle in PORTES:
        S = sujets(traj, depart, fin)
        res["portes"][cle] = {
            "libelle": libelle, "grade_de_depart": depart, "n": len(S),
            "franchissements": sum(s["evenement"] for s in S),
            "annee_seule": ajuster(panel(S, jalons, vol, ret, 1), 1),
            "controle_volume_global": ajuster(panel(S, jalons, vol, ret, 2), 2),
            "controle_par_technique": ajuster(panel(S, jalons, vol, ret, 4), 4),
            "survie": survie(S),
        }
    res["parcours"] = parcours(serie)
    return res


# --- habillage web des SVG ----------------------------------------------------------------------
# Par défaut matplotlib VECTORISE le texte des SVG : plus un seul élément `<text>`, donc pas de
# texte sélectionnable, pas de lecture d'écran, pas de thème sombre, et 120 ko au lieu de 11. Pour
# le web on garde donc du vrai texte, et les couleurs passent par des variables CSS. Le PDF de
# l'article, lui, ne change pas : la fidélité de police y prime.
RC_WEB = {"svg.fonttype": "none",
          # pile système, « DejaVu Sans » en avant-dernier : c'est la police avec laquelle
          # matplotlib calcule les métriques de placement, autant que le lecteur l'ait aussi.
          "font.sans-serif": ["system-ui", "-apple-system", "Segoe UI", "DejaVu Sans", "sans-serif"]}

# Palette fermée : couleur claire -> (nom de variable, valeur sombre). Toute couleur absente d'ici
# resterait figée en clair sur fond sombre — l'habillage refuse donc d'en laisser passer une.
PALETTE_WEB = {
    "#ffffff": ("fond", "#14171a"),       "#000000": ("encre", "#e9ecef"),
    "#222222": ("encre-forte", "#e3e6ea"), "#333333": ("encre-moyenne", "#dadee3"),
    "#444444": ("encre-limite", "#cbd0d6"), "#555555": ("encre-titre", "#b9bfc6"),
    "#666666": ("encre-note", "#aab0b8"),  "#777777": ("encre-faible", "#9aa1a9"),
    "#808080": ("repere", "#8d949c"),      "#888888": ("intervalle", "#949aa2"),
    "#cccccc": ("trait-leger", "#3a4046"), "#e8e8e8": ("barre-fond", "#2b3137"),
    "#2a7d4f": ("franchi", "#4fb07c"),     "#c6762e": ("envisageable", "#e0a05c"),
    # le flux du parcours : franchit, bloqué, arrivé sans étape
    "#2a78d6": ("flux-franchit", "#5b9ae8"), "#eb6834": ("flux-bloque", "#f08a5f"),
    "#898781": ("flux-direct", "#9d9a93"),   "#b14a1c": ("texte-bloque", "#e09266"),
    "#1b5ea8": ("texte-franchit", "#7cb2ee"), "#6d6a64": ("texte-direct", "#a6a39c"),
    "#3f3d39": ("texte-sur-gris", "#1d1f22"), "#8a4a28": ("texte-reste", "#d79a72"),
    "#1f77b4": ("demontre", "#6aa9dd"),    "#b32d2d": ("realise", "#e07a7a"),
    "#d62728": ("seconde-porte", "#ef6f70"),
}
LEGENDE = ".legende.txt"          # le suffixe de la note qui accompagne un SVG
ANCRE_STYLE = '<style type="text/css">*{stroke-linejoin: round; stroke-linecap: butt}</style>'

# La réserve que toute part — 76 %, 35 %, 74/98 — emporte avec elle. Le portillon des chiffres la
# vérifie sur chaque SVG de `figures/`, parce qu'une figure circule seule, sans son article.
RESERVE_ATLAS = "What ATLAS measures: what has been documented — documentation is not the world."


def habiller_svg(chemin: Path, titre: str, description: str) -> str:
    """Rend un SVG matplotlib lisible sur le web : thème sombre, nom et description accessibles."""
    s = chemin.read_text(encoding="utf-8")
    if ANCRE_STYLE not in s or '<g id="figure_1">' not in s:
        raise TendanceError(f"{chemin.name} : SVG matplotlib non reconnu, habillage impossible")
    inconnues = {c for c in re.findall(r"(?:fill|stroke): (#[0-9a-f]{6})", s)} - set(PALETTE_WEB)
    if inconnues:
        raise TendanceError(f"{chemin.name} : couleurs hors palette, invisibles en thème sombre — "
                            + ", ".join(sorted(inconnues)))
    # La couleur claire est RÉPÉTÉE avant la variable : un lecteur SVG qui ignore `var()` jetterait
    # la déclaration entière et peindrait tout en noir, fond compris. La substitution passe AVANT
    # l'injection du bloc CSS, sinon elle se mordrait la queue sur ses propres déclarations.
    def _variable(m: re.Match) -> str:
        prop, hexa = m.group(1), m.group(2)
        return f"{prop}: {hexa}; {prop}: var(--airp-{PALETTE_WEB[hexa][0]}, {hexa})"

    s = re.sub(r"\b(fill|stroke): (#[0-9a-f]{6})", _variable, s)

    clair = " ".join(f"--airp-{n}:{c};" for c, (n, _) in PALETTE_WEB.items())
    sombre = " ".join(f"--airp-{n}:{d};" for _, (n, d) in PALETTE_WEB.items())
    # `.viz text` rattrape le texte laissé à la couleur par défaut : matplotlib n'écrit AUCUN
    # `fill` pour le noir, si bien que le titre serait resté noir sur fond sombre. Une règle de
    # feuille de style ne touche que ceux-là — un `style=` en ligne l'emporte toujours sur elle.
    bloc = (f'<style type="text/css">\n.viz {{ {clair} }}\n'
            f"@media (prefers-color-scheme: dark) {{ .viz {{ {sombre} }} }}\n"
            ".viz text { fill: #000000; fill: var(--airp-encre, #000000); }\n</style>")
    s = s.replace(ANCRE_STYLE, ANCRE_STYLE + "\n  " + bloc, 1)
    s = s.replace('<g id="figure_1">', '<g id="figure_1" class="viz">', 1)

    # `title` et `desc` nomment la figure pour une lecture d'écran, sans masquer le texte interne :
    # un `role="img"` le ferait, et c'est justement le texte qui porte les chiffres.
    def _ech(t: str) -> str:
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    s = s.replace("<metadata>", f"<title>{_ech(titre)}</title>\n  <desc>{_ech(description)}</desc>"
                                "\n  <metadata>", 1)
    chemin.write_text(s, encoding="utf-8")
    return s


# --- figures ------------------------------------------------------------------------------------
def figures(res: dict, dest: Path = FIGURES, formats: tuple[str, ...] = ("svg", "pdf")) -> list[Path]:
    """SVG pour le web (texte réel, thème sombre), PDF vectoriel pour l'article.

    Écrit dans `figures/`, sous git : seuls ces fichiers sont des livrables de publication.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    dest.mkdir(parents=True, exist_ok=True)
    sorties: list[Path] = []

    def enregistrer(fig, nom: str, titre: str, description: str) -> None:
        for ext in formats:
            f = dest / f"{nom}.{ext}"
            if ext == "svg":
                with plt.rc_context(RC_WEB):
                    fig.savefig(f)
                habiller_svg(f, titre, description)
            else:
                fig.savefig(f)
            sorties.append(f)
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for cle, couleur in (("premiere", "#1f77b4"), ("seconde", "#d62728")):
        p = res["portes"][cle]
        c = p["survie"]["courbe"]
        xs, ys = [0.0], [1.0]
        for pt in c:
            xs += [pt["t"], pt["t"]]
            ys += [ys[-1], pt["S"]]
        ax.step(xs, ys, where="post", color=couleur,
                label=f"{p['libelle']} — {p['franchissements']}/{p['n']}")
    ax.axhline(0.5, color="grey", lw=0.8, ls=":")
    ax.set_xlabel("months since entering the starting grade")
    ax.set_ylabel("share that has not crossed yet")
    ax.set_ylim(0, 1)
    ax.legend(fontsize=8)
    ax.set_title("Crossing the two ATLAS steps (Kaplan-Meier)", fontsize=10)
    # La légende affiche 74/98 et 45/130 : ce sont des parts, et elles portent la même réserve que
    # « 76 % ». Une figure circule seule, la réserve voyage donc avec elle.
    fig.text(0.5, 0.012, RESERVE_ATLAS, ha="center", fontsize=7.5, color="#555")
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    enregistrer(fig, "survie-deux-portes",
                "Crossing the two ATLAS steps (Kaplan-Meier)",
                "Two decreasing survival curves: "
                + "; ".join(f"{res['portes'][c]['libelle']}, {res['portes'][c]['franchissements']} "
                             f"crossings out of {res['portes'][c]['n']}"
                             for c, _, _ in PORTES) + ".")

    fig, ax = plt.subplots(figsize=(7.6, 3.8))
    etiquettes, valeurs, bas, hauts = [], [], [], []
    for cle, _, libelle in PORTES:
        p = res["portes"][cle]
        for champ, nom in (("annee_seule", "no control"),
                           ("controle_volume_global", "+ overall volume"),
                           ("controle_par_technique", "+ per technique")):
            etiquettes.append(f"{libelle.split(' → ')[0]} · {nom}")
            valeurs.append(p[champ]["hr"])
            bas.append(p[champ]["ic95"][0])
            hauts.append(p[champ]["ic95"][1])
    y = range(len(valeurs))
    ax.errorbar(valeurs, list(y), xerr=[[v - b for v, b in zip(valeurs, bas)],
                                        [h - v for v, h in zip(valeurs, hauts)]],
                fmt="o", color="#333", ecolor="#888", capsize=3)
    ax.axvline(1.0, color="grey", lw=0.8, ls=":")
    ax.set_yticks(list(y))
    ax.set_yticklabels(etiquettes, fontsize=8)
    ax.set_xlabel("crossing factor per year of entry\n(95% CI, profile likelihood)", fontsize=9)
    fig.tight_layout()
    enregistrer(fig, "facteurs-par-annee",
                "Crossing factors per year of entry, before and after editorial control",
                "Six points with their 95% confidence interval, three per step: no control, "
                "then overall editorial volume, then per-technique edits. All stay above 1."
                "")

    # Le parcours d'ensemble, dans les deux langues. Il sort du MÊME run que les deux figures
    # ci-dessus : une figure détaillée produite à part dérive dès le run suivant.
    for langue in ("fr", "en"):
        sorties += figure_parcours(res, res["parcours"], dest, langue, formats)
    return sorties



# --- parcours d'ensemble : d'où partent les techniques, et où elles en sont ---------------------
# --- parcours d'ensemble : un flux, de l'idée au réel -------------------------------------------
# Lu de GAUCHE À DROITE, un seul sens. La version précédente empilait les grades de bas en haut et
# les étapes de haut en bas : il fallait la relire trois fois pour faire le lien.
LIBELLES_PARCOURS = {
    "fr": {"titre": ("Technique d'attaque", "Le cheminement du laboratoire au réel"),
           "stades": (("Envisagée", "une idée"), ("Démontrée", "en laboratoire"),
                      ("Observée", "dans le réel")),
           "techniques": "{n} y sont passées",
           "franchissent": "{f} sur {n} franchissent · {p}",
           "delai": "en {med} mois", "intervalle": "entre {b} et {h}",
           "borne_basse": "à partir de {b}, pas de borne supérieure établie",
           "bloquees": "{n} bloquées",
           "restent": ("restent à l'idée", "restent au laboratoire"),
           "hors_etape1": ("{n} arrivées", "sans passer par l'étape 1"),
           "hors_etape": ("{n} arrivées", "sans passer par une étape"),
           "saut": "{n} ont sauté l'étape du laboratoire",
           "legende": ("{n} techniques suivies de {de} à {a}, dont {retirees} retirées du "
                       "catalogue depuis et {regressions} redescendues d'un stade. Délais médians "
                       "de Kaplan-Meier : première étape {m1} mois, {e1} ; seconde étape {m2} "
                       "mois, {e2}. Le "
                       "catalogue de référence du domaine, MITRE ATLAS, recense ce qui a été "
                       "documenté, pas tout ce qui existe."),
           "description": ("Un flux de gauche à droite en trois stades. Envisagée : {n1} techniques, "
                           "{f1} franchissent la première étape, soit {p1}, en {m1} mois ; {b1} "
                           "restent bloquées. Démontrée en laboratoire : {n2} techniques, dont {h2} "
                           "arrivées sans passer par la première étape ; {f2} franchissent la "
                           "seconde étape, soit {p2}, en {m2} mois ; {b2} restent bloquées. "
                           "Observée dans le réel : {n3} techniques.")},
    "en": {"titre": ("Attack technique", "The path from the lab to the real world"),
           "stades": (("Conceived", "an idea"), ("Demonstrated", "in the lab"),
                      ("Observed", "in the real world")),
           "techniques": "{n} went through",
           "franchissent": "{f} of {n} cross · {p}",
           "delai": "in {med} months", "intervalle": "between {b} and {h}",
           "borne_basse": "from {b} on, no upper bound established",
           "bloquees": "{n} held",
           "restent": ("stay an idea", "stay in the lab"),
           # tenus courts : écrits en entier, ils débordaient du ruban sur le nœud voisin
           "hors_etape1": ("{n} arrived", "without step 1"),
           "hors_etape": ("{n} arrived", "without any step"),
           "saut": "{n} skipped the lab step",
           "legende": ("{n} techniques tracked from {de} to {a}, {retirees} of them since removed "
                       "from the catalogue and {regressions} moved back a stage. Kaplan-Meier "
                       "median times: first step {m1} months, {e1}; second step {m2} months, "
                       "{e2}. The reference "
                       "catalogue of the field, MITRE ATLAS, records what has been documented, not "
                       "everything that exists."),
           "description": ("A left-to-right flow in three stages. Conceived: {n1} techniques, {f1} "
                           "cross the first step, that is {p1}, in {m1} months; {b1} are held. "
                           "Demonstrated in the lab: {n2} techniques, {h2} of them arrived without "
                           "going through the first step; {f2} cross the second step, that is {p2}, "
                           "in {m2} months; {b2} are held. Observed in the real world: {n3} "
                           "techniques.")},
}



def parcours(serie: list[tuple[date, dict]]) -> dict:
    """Effectifs d'ensemble : grade d'apparition, portes, grade actuel.

    **La population est celle du suivi — toute technique ayant porté un grade — et non le
    catalogue d'aujourd'hui.** Se restreindre aux techniques encore présentes donnerait des
    effectifs de portes différents de ceux du calcul publié : on réconcilierait une figure au prix
    de la cohérence avec la mesure.
    """
    from collections import Counter
    fin = serie[-1][0]
    traj = trajectoires(serie)
    actuelles = {t.get("uuid") or k for k, t in _objets(serie[-1][1], "techniques").items()}
    apparition = Counter(p[0][1] for p in traj.values())
    actuel = Counter(p[-1][1] for p in traj.values())
    sauts = 0
    for pts in traj.values():
        g = [x[1] for x in pts]
        if g[0] != "Feasible":
            continue
        for i in range(1, len(g)):
            if g[i] == "Realized" and "Demonstrated" not in g[1:i]:
                sauts += 1
                break
    regressions = sum(1 for pts in traj.values()
                      for a, b in zip(pts, pts[1:]) if GRADES.get(b[1], -1) < GRADES.get(a[1], -1))
    return {"suivies": len(traj), "retirees": len(traj) - len(actuelles & set(traj)),
            "apparition": dict(apparition), "actuel": dict(actuel),
            "sauts_premiere_porte": sauts, "regressions": regressions,
            "flux": flux(traj), "de": serie[0][0].isoformat(), "a": fin.isoformat()}


def flux(traj: dict[str, list[tuple[date, str]]]) -> dict:
    """Le diagramme de flux : combien franchissent, combien restent, combien arrivent sans étape.

    **Tout est compté du point de vue de la SORTIE d'un stade**, jamais de l'entrée dans le
    suivant. C'est la seule vue où un ruban a une largeur unique : le même passage compté à
    l'entrée donne un autre nombre, parce que dix techniques ont reculé d'un grade et repassent.
    Mélanger les deux vues, c'est ce qui donnait à l'ancienne figure sa note « non réconciliés à
    quatre unités près » — un aveu que la figure ne bouclait pas.

    Ce qui entre dans un stade sans venir du précédent n'est donc pas « apparu à ce stade », mais
    exactement **ce que les rubans ne couvrent pas** : la population moins ce qui y arrive. Les
    deux libellés disent cela, et rien de plus.
    """
    n = {"F": 0, "D": 0, "R": 0}
    e1 = {"vers_etape2": 0, "saut": 0, "bloquees": 0}
    e2 = {"franchissent": 0, "bloquees": 0}
    for pts in traj.values():
        g = [x[1] for x in pts]
        for cle, grade in (("F", "Feasible"), ("D", "Demonstrated"), ("R", "Realized")):
            n[cle] += grade in g
        if "Feasible" in g:
            apres = g[g.index("Feasible") + 1:]
            e1["vers_etape2" if "Demonstrated" in apres else
               "saut" if "Realized" in apres else "bloquees"] += 1
        if "Demonstrated" in g:
            iD = g.index("Demonstrated")
            e2["franchissent" if "Realized" in g[iD + 1:] else "bloquees"] += 1
    f = {"etape1": {"population": n["F"], "franchissent": e1["vers_etape2"] + e1["saut"], **e1},
         "etape2": {"population": n["D"], "entrees_etape1": e1["vers_etape2"],
                    "entrees_hors_etape": n["D"] - e1["vers_etape2"], **e2},
         "reel": {"population": n["R"], "entrees_etape2": e2["franchissent"],
                  "entrees_saut": e1["saut"],
                  "entrees_hors_etape": n["R"] - e2["franchissent"] - e1["saut"]}}
    boucler(f)
    return f


BOUCLES = (("etape1", ("vers_etape2", "saut", "bloquees")),
           ("etape2", ("entrees_etape1", "entrees_hors_etape")),
           ("etape2|sortie", ("franchissent", "bloquees")),
           ("reel", ("entrees_etape2", "entrees_saut", "entrees_hors_etape")))


def boucler(f: dict) -> None:
    """Un ruban qui ne boucle pas est un chiffre faux : le run s'arrête ici, pas à la relecture."""
    for cle, parts in BOUCLES:
        bloc = f[cle.split("|")[0]]
        if sum(bloc[p] for p in parts) != bloc["population"] or any(bloc[p] < 0 for p in parts):
            raise TendanceError(f"flux {cle} : {parts} ne totalisent pas {bloc['population']} — "
                                "la figure mentirait")


def plier(texte: str, largeur: int) -> list[str]:
    """Pliage à la main : `textwrap` ne connaît pas la largeur des axes, et `matplotlib` ne plie
    rien du tout. Les longueurs sont réglées pour la largeur de la figure, pas pour une colonne
    de terminal."""
    lignes, courante = [], ""
    for mot in texte.split():
        if len(courante) + len(mot) > largeur:
            lignes.append(courante)
            courante = mot
        else:
            courante = (courante + " " + mot).strip()
    lignes.append(courante)
    return lignes



def _ruban(ax, x0: float, yc0: float, x1: float, yc1: float, epaisseur: float,
           couleur: str, creux: float | None = None, alpha: float = 0.85) -> None:
    """Une bande lisse d'un bord à l'autre, d'épaisseur constante.

    L'épaisseur ne varie pas : un ruban qui s'amincit en route dirait qu'on perd des techniques en
    chemin. `creux` le fait plonger sous un nœud qu'il doit contourner.
    """
    import matplotlib.pyplot as plt
    from matplotlib.path import Path as Chemin
    if creux is None:
        c1, c2 = ((x0 + x1) / 2, yc0), ((x0 + x1) / 2, yc1)
    else:
        c1, c2 = (x0 + (x1 - x0) * 0.18, creux), (x0 + (x1 - x0) * 0.82, creux)
    e = epaisseur / 2
    sommets = [(x0, yc0 + e), (c1[0], c1[1] + e), (c2[0], c2[1] + e), (x1, yc1 + e),
               (x1, yc1 - e), (c2[0], c2[1] - e), (c1[0], c1[1] - e), (x0, yc0 - e)]
    codes = [Chemin.MOVETO, Chemin.CURVE4, Chemin.CURVE4, Chemin.CURVE4,
             Chemin.LINETO, Chemin.CURVE4, Chemin.CURVE4, Chemin.CURVE4]
    ax.add_patch(plt.matplotlib.patches.PathPatch(
        Chemin(sommets + [sommets[0]], codes + [Chemin.CLOSEPOLY]),
        facecolor=couleur, edgecolor="none", alpha=alpha))


def figure_parcours(res: dict, par: dict, dest: Path, langue: str,
                    formats: tuple[str, ...] = ("svg", "pdf")) -> list[Path]:
    """Le parcours d'une technique, en flux de gauche à droite : idée, laboratoire, réel."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    L = LIBELLES_PARCOURS[langue]
    virgule = "," if langue == "fr" else "."
    f = par["flux"]
    p1, p2 = res["portes"]["premiere"], res["portes"]["seconde"]
    # La figure dit ce que le calcul a mesuré, ou elle ne paraît pas : si le flux et le modèle de
    # Cox cessaient de compter la même chose, la figure illustrerait un autre chiffre que l'article.
    for bloc, porte in ((f["etape1"], p1), (f["etape2"], p2)):
        if (bloc["population"], bloc["franchissent"]) != (porte["n"], porte["franchissements"]):
            raise TendanceError(
                f"le flux ({bloc['franchissent']}/{bloc['population']}) ne dit pas la mesure "
                f"({porte['franchissements']}/{porte['n']}) — la figure illustrerait autre chose")

    def nb(v: float) -> str:                 # même arrondi que `resume()`, 7,85 donne 7,8
        return f"{v:.1f}".replace(".", virgule)

    def encadrement(s: dict) -> str:
        bas, haut_ic = s["ic95_mediane"]
        return (L["intervalle"].format(b=nb(bas), h=nb(haut_ic)) if haut_ic is not None
                else L["borne_basse"].format(b=nb(bas)))

    dest.mkdir(parents=True, exist_ok=True)
    # 6,6 pouces : la largeur de la colonne de l'article. Dessinée plus large, la figure y serait
    # réduite d'un tiers et ses petits textes deviendraient illisibles.
    fig, ax = plt.subplots(figsize=(6.6, 3.95))
    ax.set_xlim(0, 10)
    ax.set_ylim(3.55, 10)                    # le bas est vide : on ne le dessine pas
    ax.axis("off")
    BLEU, ORANGE, GRIS = "#2a78d6", "#eb6834", "#898781"
    # Pastille de fond sous les étiquettes qu'un ruban peut traverser : la convention de la
    # figure d'origine, et la seule qui tienne quelle que soit la courbe qui passe derrière.
    PASTILLE = {"facecolor": "#ffffff", "edgecolor": "none", "pad": 1.4}
    # L'arc passe SOUS les cases terminales des bloquées : au même niveau, son étiquette et
    # la leur se chevauchaient.
    CREUX = 3.15                             # point de contrôle du plongeon de l'arc
    for k, ligne in enumerate(L["titre"]):
        ax.text(5, 9.78 - k * 0.40, ligne, ha="center", fontsize=10.5 - k * 1.0,
                weight="bold" if k == 0 else "normal", color="#222222" if k == 0 else "#444444")

    h = 0.0150                               # unités de hauteur par technique
    haut = 7.88                              # les trois nœuds sont alignés par le haut
    xs = ((0.95, 1.35), (4.95, 5.35), (8.60, 9.00))
    e1, e2, reel = f["etape1"], f["etape2"], f["reel"]
    pops = (e1["population"], e2["population"], reel["population"])

    for (xg, xd), (nom, glose), n in zip(xs, L["stades"], pops):
        xc = (xg + xd) / 2
        ax.text(xc, 8.98, nom, ha="center", fontsize=9, weight="bold", color="#222222")
        ax.text(xc, 8.74, glose, ha="center", fontsize=7.5, color="#555555")
        ax.text(xc, 8.50, L["techniques"].format(n=n), ha="center", fontsize=7.5, color="#777777")

    # --- les tranches de chaque nœud, empilées de haut en bas --------------------------------
    def tranches(depart: float, parts: list[tuple[str, int]]) -> dict[str, tuple[float, float]]:
        out, y = {}, depart
        for cle, n in parts:
            out[cle] = (y, y - n * h)
            y -= n * h
        return out

    sortie1 = tranches(haut, [("vers", e1["vers_etape2"]), ("bloquees", e1["bloquees"]),
                              ("saut", e1["saut"])])
    entree2 = tranches(haut, [("etape1", e2["entrees_etape1"]),
                              ("hors", e2["entrees_hors_etape"])])
    sortie2 = tranches(haut, [("franchissent", e2["franchissent"]), ("bloquees", e2["bloquees"])])
    entree3 = tranches(haut, [("etape2", reel["entrees_etape2"]), ("saut", reel["entrees_saut"]),
                              ("hors", reel["entrees_hors_etape"])])

    def mi(b: tuple[float, float]) -> float:
        return (b[0] + b[1]) / 2

    def ep(b: tuple[float, float]) -> float:
        return b[0] - b[1]

    # ce qui franchit : le ruban principal, d'un nœud au suivant
    _ruban(ax, xs[0][1], mi(sortie1["vers"]), xs[1][0], mi(entree2["etape1"]),
           ep(sortie1["vers"]), BLEU)
    _ruban(ax, xs[1][1], mi(sortie2["franchissent"]), xs[2][0], mi(entree3["etape2"]),
           ep(sortie2["franchissent"]), BLEU)
    # le saut : il contourne le second nœud par en dessous, sinon il le traverserait
    _ruban(ax, xs[0][1], mi(sortie1["saut"]), xs[2][0], mi(entree3["saut"]),
           ep(sortie1["saut"]), BLEU, creux=CREUX, alpha=0.45)
    y_saut = (mi(sortie1["saut"]) + mi(entree3["saut"]) + 6 * CREUX) / 8
    ax.text(5.0, y_saut, L["saut"].format(n=e1["saut"]), ha="center", va="center", fontsize=7,
            color="#1b5ea8", bbox=PASTILLE)

    # Ce qui reste bloqué aboutit à une CASE TERMINALE : un ruban qui s'arrête net au milieu de
    # nulle part ne dit pas « ceux-là ne vont pas plus loin », il a l'air coupé.
    for xd, bornes, fin, bas, n, reste in (
            (xs[0][1], sortie1["bloquees"], 2.25, 5.55, e1["bloquees"], L["restent"][0]),
            (xs[1][1], sortie2["bloquees"], 6.10, 4.95, e2["bloquees"], L["restent"][1])):
        _ruban(ax, xd, mi(bornes), fin, bas, ep(bornes), ORANGE)
        ax.add_patch(plt.Rectangle((fin, bas - ep(bornes) / 2), 0.17, ep(bornes),
                                   facecolor="#b14a1c", edgecolor="none"))
        # l'étiquette APRÈS la case terminale : sous elle, elle tombait sur l'arc du saut
        ax.text(fin + 0.32, bas + 0.11, L["bloquees"].format(n=n), ha="left", va="center",
                fontsize=7.5, color="#b14a1c", weight="bold", bbox=PASTILLE)
        ax.text(fin + 0.32, bas - 0.19, reste, ha="left", va="center", fontsize=6.8,
                color="#8a4a28", bbox=PASTILLE)

    # Ce qui arrive sans avoir franchi d'étape part d'une SOURCE nommée, et s'y jette : posés en
    # bloc contre le nœud, ces effectifs avaient l'air de flotter sans venir de nulle part.
    for xg, bornes, lignes in ((xs[1][0], entree2["hors"],
                                [t.format(n=e2["entrees_hors_etape"]) for t in L["hors_etape1"]]),
                               (xs[2][0], entree3["hors"],
                                [t.format(n=reel["entrees_hors_etape"]) for t in L["hors_etape"]])):
        depart = xg - 2.05
        ax.add_patch(plt.Rectangle((depart, bornes[1]), 0.17, ep(bornes), facecolor="#6d6a64",
                                   edgecolor="none"))
        _ruban(ax, depart + 0.17, mi(bornes), xg, mi(bornes), ep(bornes), GRIS, alpha=0.6)
        for k, ligne in enumerate(lignes):       # l'étiquette DANS le ruban, pas en dessous
            ax.text((depart + 0.17 + xg) / 2, mi(bornes) + 0.14 - k * 0.26, ligne, ha="center",
                    va="center", fontsize=6.2, color="#3f3d39")

    # Les nœuds par-dessus les rubans : dessinés avant, le bleu les recouvrait et on ne voyait
    # plus où un stade finissait.
    for (xg, xd), n in zip(xs, pops):
        ax.add_patch(plt.Rectangle((xg, haut - n * h), xd - xg, n * h,
                                   facecolor="#444444", edgecolor="none"))

    # --- ce que chaque étape franchit, et en combien de temps --------------------------------
    for (xa, xb), porte, part in (((xs[0][1], xs[1][0]), p1, e1), ((xs[1][1], xs[2][0]), p2, e2)):
        xc = (xa + xb) / 2
        taux = part["franchissent"] / part["population"]
        ax.text(xc, 8.24, L["franchissent"].format(f=part["franchissent"], n=part["population"],
                                                   p=f"{taux:.0%}"),
                ha="center", fontsize=8.5, weight="bold", color="#1b5ea8")
        ax.text(xc, 8.00, L["delai"].format(med=round(porte["survie"]["mediane"])),
                ha="center", fontsize=7.5, color="#333333")

    # Ni réserve, ni note, ni limite DANS le dessin : elles vivent dans la légende qui
    # accompagne la figure, et le portillon contrôle les deux ensemble.
    fig.tight_layout()
    description = L["description"].format(
        n1=e1["population"], f1=e1["franchissent"], p1=f"{e1['franchissent']/e1['population']:.0%}",
        m1=nb(p1["survie"]["mediane"]), b1=e1["bloquees"],
        n2=e2["population"], h2=e2["entrees_hors_etape"], f2=e2["franchissent"],
        p2=f"{e2['franchissent']/e2['population']:.0%}", m2=nb(p2["survie"]["mediane"]),
        b2=e2["bloquees"], n3=reel["population"])
    out = []
    for ext in formats:
        chemin = dest / f"parcours-{langue}.{ext}"
        if ext == "svg":
            with plt.rc_context(RC_WEB):
                fig.savefig(chemin)
            habiller_svg(chemin, " — ".join(L["titre"]), description)
        else:
            fig.savefig(chemin)
        out.append(chemin)
    plt.close(fig)

    # LA LÉGENDE, à côté du SVG. Elle n'accompagne pas la figure par politesse : elle porte les
    # réserves que le dessin ne porte plus, et le portillon lit les deux comme UNE fenêtre. Une
    # figure publiée sans elle échoue au contrôle — c'est ce qui rend l'oubli impossible.
    legende = L["legende"].format(
        n=par["suivies"], de=par["de"][:4], a=par["a"][:4], retirees=par["retirees"],
        regressions=par["regressions"],
        m1=nb(p1["survie"]["mediane"]), e1=encadrement(p1["survie"]),
        m2=nb(p2["survie"]["mediane"]), e2=encadrement(p2["survie"]))
    f_legende = dest / f"parcours-{langue}{LEGENDE}"
    f_legende.write_text(legende + "\n", encoding="utf-8")
    out.append(f_legende)
    return out


def resume(res: dict) -> str:
    lignes = [f"Trend across both gates — {res['versions']} versions, {res['de']} → {res['a']}",
              f"  upstream: {res['amont']['commit'][:12]}… (37 version fingerprints verified)", ""]
    for cle, _, libelle in PORTES:
        p = res["portes"][cle]
        lignes.append(f"{libelle}: {p['franchissements']}/{p['n']} crossings")
        for champ, nom in (("annee_seule", "year alone .............."),
                           ("controle_volume_global", "+ editorial volume ....."),
                           ("controle_par_technique", "+ per-technique edits ..")):
            a = p[champ]
            lignes.append(f"   {nom} {a['hr']:.3f} ×/year  95% CI [{a['ic95'][0]:.2f} ; {a['ic95'][1]:.2f}]")
        s = p["survie"]
        med = f"{s['mediane']:.1f} months" if s["mediane"] else "not reached"
        ic = s["ic95_mediane"]
        lignes.append(f"   KM median ............... {med}  95% CI "
                      f"[{ic[0] if ic[0] else '—'} ; {'not reached' if ic[1] is None else ic[1]}]")
        lignes.append(f"   S at end of horizon ..... {s['S_fin']:.3f} at {s['horizon']} months")
        lignes.append("")
    lignes.append(f"LIMIT, to be published with the figure: {res['mention']}")
    return "\n".join(lignes)


def main(argv: list[str]) -> int:
    try:
        res = run(Path(os.environ["ATLAS_DATA"]) if os.environ.get("ATLAS_DATA") else CLONE)
    except (TendanceError, subprocess.CalledProcessError) as e:
        print(f"REFUSED: {e}")
        return 1
    SORTIE.mkdir(parents=True, exist_ok=True)
    write_json(SORTIE / "tendance.json", res)
    (SORTIE / "tendance.txt").write_text(resume(res) + "\n", encoding="utf-8")
    fs = figures(res)
    (FIGURES / "README.md").write_text(LISEZMOI_FIGURES, encoding="utf-8")
    print(resume(res))
    print(f"Written: {SORTIE.relative_to(ROOT)}/tendance.json, tendance.txt")
    print(f"Publication outputs (version-controlled): {FIGURES.relative_to(ROOT)}/ — "
          + ", ".join(f.name for f in fs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
