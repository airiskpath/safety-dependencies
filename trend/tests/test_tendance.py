"""Tendance des deux portes — le solveur est validé avant d'être cru.

Un calcul rejouable par un tiers ne vaut que si l'implémentation est vérifiée. Trois niveaux :
un cas dont la solution se calcule à la main, une simulation où le vrai coefficient est connu,
et les garde-fous qui refusent une source non conforme.
"""

from __future__ import annotations

import json
import math
import random
from datetime import date

import pytest

import tendance as T


# --- 1. le solveur, sur un cas résolu à la main -------------------------------------------------
def test_efron_cas_symetrique_donne_exactement_zero():
    """Deux sujets ex aequo, covariables 1 et 0 : le maximum est β = 0, démontrable.

    Vraisemblance d'Efron : L(β) = β − log(e^β+1) − log(½(e^β+1)).
    Dérivée : 1 − 2e^β/(e^β+1), nulle si e^β = 1, donc β = 0. Par symétrie c'est le seul point.
    """
    lignes = [{"debut": 0.0, "fin": 1.0, "evt": 1, "x": [1.0]},
              {"debut": 0.0, "fin": 1.0, "evt": 1, "x": [0.0]}]
    a = T.ajuster(lignes, 1)
    assert a["beta"][0] == pytest.approx(0.0, abs=1e-5)
    assert a["hr"] == pytest.approx(1.0, abs=1e-5)
    # la valeur de la log-vraisemblance en 0 est elle aussi calculable : −log2 − log1 = −log 2
    assert T.loglik([0.0], lignes) == pytest.approx(-math.log(2) - math.log(1.0), abs=1e-12)


def test_efron_diffère_de_breslow_sur_les_ex_aequo():
    """Sans correction d'Efron, le second terme serait log(e^β+1) : la valeur diffère.

    Ce test fixe le choix de méthode : si quelqu'un remplaçait Efron par Breslow, il casserait.
    """
    lignes = [{"debut": 0.0, "fin": 1.0, "evt": 1, "x": [1.0]},
              {"debut": 0.0, "fin": 1.0, "evt": 1, "x": [0.0]}]
    b = 0.7
    efron = T.loglik([b], lignes)
    breslow = b - 2 * math.log(math.exp(b) + 1)
    assert efron != pytest.approx(breslow, abs=1e-6)
    assert efron == pytest.approx(b - math.log(math.exp(b) + 1) - math.log(0.5 * (math.exp(b) + 1)), abs=1e-12)


# --- 2. le solveur, sur des données simulées au coefficient connu -------------------------------
def test_estime_le_vrai_coefficient_sur_donnees_simulees():
    """Survie exponentielle à risques proportionnels, β = 0,5, graine fixe : l'estimation le retrouve."""
    rng = random.Random(20260926)
    beta_vrai, lignes = 0.5, []
    for _ in range(400):
        x = rng.uniform(-1, 1)
        t = rng.expovariate(0.1 * math.exp(beta_vrai * x))     # taux de base 0,1
        fin = min(t, 20.0)                                      # censure administrative
        lignes.append({"debut": 0.0, "fin": max(fin, 1e-6), "evt": int(t <= 20.0), "x": [x]})
    a = T.ajuster(lignes, 1)
    assert a["evenements"] > 200
    assert a["beta"][0] == pytest.approx(beta_vrai, abs=0.15)
    assert a["ic95"][0] < math.exp(beta_vrai) < a["ic95"][1]     # l'intervalle couvre la vérité
    assert a["p_valeur"] < 0.01


def test_sans_effet_l_intervalle_contient_1():
    rng = random.Random(7)
    lignes = []
    for _ in range(300):
        x = rng.uniform(-1, 1)
        t = rng.expovariate(0.1)                                # aucun effet de x
        lignes.append({"debut": 0.0, "fin": max(min(t, 20.0), 1e-6), "evt": int(t <= 20.0), "x": [x]})
    a = T.ajuster(lignes, 1)
    assert a["ic95"][0] < 1.0 < a["ic95"][1] and a["p_valeur"] > 0.05


# --- 3. Kaplan-Meier, calculé à la main ---------------------------------------------------------
def test_kaplan_meier_sur_un_exemple_calculable():
    """Durées 1(évt), 2(censuré), 3(évt), 4(évt) → S = 0,75 ; 0,375 ; 0."""
    S = [{"duree": 1.0, "evenement": 1}, {"duree": 2.0, "evenement": 0},
         {"duree": 3.0, "evenement": 1}, {"duree": 4.0, "evenement": 1}]
    s = T.survie(S)
    assert [c["S"] for c in s["courbe"]] == [0.75, 0.375, 0.0]
    assert s["mediane"] == 3.0 and s["n"] == 4 and s["evenements"] == 3


def test_mediane_absente_si_la_courbe_ne_croise_pas():
    S = [{"duree": 5.0, "evenement": 1}] + [{"duree": 9.0, "evenement": 0} for _ in range(9)]
    s = T.survie(S)
    assert s["mediane"] is None and s["S_fin"] == 0.9


# --- 4. les garde-fous sur les sources ----------------------------------------------------------
def test_refuse_une_empreinte_non_conforme(tmp_path, monkeypatch):
    faux = tmp_path / "versions.json"
    faux.write_text(json.dumps({"2026.09": {"date": "2026-09-15", "sha256": "00" * 32}}), encoding="utf-8")
    monkeypatch.setattr(T, "VERSIONS", faux)
    with pytest.raises(T.TendanceError, match="empreintes épinglées"):
        T.charger(T.CLONE)


def test_refuse_un_clone_hors_du_commit_epingle(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "COMMIT", "0" * 40)
    with pytest.raises(T.TendanceError, match="commit épinglé"):
        T.preparer(T.CLONE)


def test_les_37_versions_sont_epinglees():
    attendu = json.loads(T.VERSIONS.read_text(encoding="utf-8"))
    assert len(attendu) == 37
    assert all(len(v["sha256"]) == 64 and v["date"] for v in attendu.values())
    assert attendu["2026.09"]["sha256"] == (
        "935efa93e28294432d3e2f537eb94991ef8d1f8c58341cd360ea3321ddb66688")   # = le pin ATLAS


# --- 5. les covariables ne contiennent rien du grade -------------------------------------------
def _doc(techniques: dict) -> dict:
    return {"techniques": techniques, "mitigations": {}, "case-studies": {}}


def test_le_volume_editorial_ignore_le_grade():
    """Changer `maturity` seul ne doit produire AUCUN changement éditorial : sinon on
    contrôlerait l'effet mesuré par lui-même."""
    a = _doc({"AML.T1": {"uuid": "u1", "maturity": "Feasible", "description": "texte", "name": "n"}})
    b = _doc({"AML.T1": {"uuid": "u1", "maturity": "Realized", "description": "texte", "name": "n"}})
    vol = T.volume_editorial([(date(2026, 1, 1), a), (date(2026, 2, 1), b)])
    assert vol["2026-02-01"]["brut"] == 0
    assert T.retouches_par_technique([(date(2026, 1, 1), a), (date(2026, 2, 1), b)])["2026-02-01"]["u1"] == 0
    # en revanche une description remaniée compte
    c = _doc({"AML.T1": {"uuid": "u1", "maturity": "Realized", "description": "autre", "name": "n"}})
    vol2 = T.volume_editorial([(date(2026, 1, 1), a), (date(2026, 2, 1), c)])
    assert vol2["2026-02-01"]["champs_remanies"] == 1


def test_la_retouche_simultanee_n_entre_pas_dans_la_ligne_courante():
    """Le décalage d'une version est ce qui empêche la covariable d'absorber l'événement."""
    jalons = [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]
    S = [{"uuid": "u1", "t0": jalons[0], "t_fin": jalons[2], "duree": 2.0,
          "evenement": 1, "annee": 2026.0}]
    vol = {d.isoformat(): {"par_mois": 1.0} for d in jalons}
    ret = {jalons[1].isoformat(): {"u1": 5}, jalons[2].isoformat(): {"u1": 0}}
    lignes = T.panel(S, jalons, vol, ret, 4)
    assert len(lignes) == 2
    # la ligne qui couvre la version où la retouche a lieu ne la voit pas encore
    assert lignes[0]["x"][3] == 0.0
    assert lignes[1]["x"][3] == 1.0            # elle apparaît à la ligne SUIVANTE


# --- 6. le résultat réel, tel qu'il sera cité --------------------------------------------------
@pytest.mark.skipif(not (T.CLONE / ".git").exists(), reason="clone amont absent")
def test_resultat_reel_reproduit_les_chiffres_publies():
    """Portillon : le calcul rapatrié doit redonner les facteurs annoncés, sinon c'est le résultat."""
    res = T.run()
    assert res["versions"] == 37
    p1, p2 = res["portes"]["premiere"], res["portes"]["seconde"]
    assert (p1["n"], p1["franchissements"]) == (98, 74)
    assert (p2["n"], p2["franchissements"]) == (130, 45)
    assert p1["annee_seule"]["hr"] == pytest.approx(1.66, abs=0.02)
    assert p2["annee_seule"]["hr"] == pytest.approx(2.52, abs=0.02)
    assert p1["controle_par_technique"]["hr"] == pytest.approx(1.55, abs=0.03)
    assert p2["controle_par_technique"]["hr"] == pytest.approx(2.23, abs=0.03)
    assert p2["survie"]["mediane"] == pytest.approx(54.9, abs=0.2)
    assert p2["survie"]["ic95_mediane"][1] is None          # borne haute non atteinte
    assert "catalogue that is better kept" in res["mention"]


# --- 7. les livrables de publication sont versionnés -------------------------------------------
def test_les_figures_sortent_dans_figures_versionne(tmp_path):
    """`figures/` est sous git : ce qui part dans un article doit porter une empreinte."""
    ROOT = T.ROOT
    assert T.FIGURES == ROOT / "figures"
    assert T.SORTIE != T.FIGURES                       # les intermédiaires restent ailleurs
    res = {"portes": {cle: {"libelle": lib, "n": 2, "franchissements": 1,
                            "survie": {"courbe": [{"t": 1.0, "S": 0.5}],
                                       "mediane": 1.0, "ic95_mediane": [0.5, None]},
                            "annee_seule": {"hr": 1.5, "ic95": [1.1, 2.0]},
                            "controle_volume_global": {"hr": 1.4, "ic95": [1.0, 1.9]},
                            "controle_par_technique": {"hr": 1.3, "ic95": [1.0, 1.8]}}
                      for cle, _, lib in T.PORTES},
           "parcours": {"suivies": 4, "retirees": 1, "sauts_premiere_porte": 1, "regressions": 0,
                        "apparition": {"Feasible": 2, "Demonstrated": 1, "Realized": 1},
                        "actuel": {"Feasible": 1, "Demonstrated": 1, "Realized": 2},
                        "flux": {"etape1": {"population": 2, "franchissent": 1, "vers_etape2": 1,
                                            "saut": 0, "bloquees": 1},
                                 "etape2": {"population": 2, "franchissent": 1, "bloquees": 1,
                                            "entrees_etape1": 1, "entrees_hors_etape": 1},
                                 "reel": {"population": 2, "entrees_etape2": 1, "entrees_saut": 0,
                                          "entrees_hors_etape": 1}},
                        "de": "2021-05-13", "a": "2026-09-15"}}
    produits = T.figures(res, tmp_path, formats=("svg",))
    assert {p.name for p in produits} == {"survie-deux-portes.svg", "facteurs-par-annee.svg",
                                          "parcours-fr.svg", "parcours-en.svg",
                                          "parcours-fr.legende.txt", "parcours-en.legende.txt"}
    assert all(p.parent == tmp_path and p.stat().st_size > 0 for p in produits)


@pytest.mark.skipif(not (T.CLONE / ".git").exists(), reason="clone amont absent")
def test_le_parcours_porte_la_population_du_suivi_et_non_le_catalogue():
    """La figure du parcours compte les techniques SUIVIES, pas celles encore au catalogue.

    Se restreindre aux 208 d'aujourd'hui changerait les effectifs des portes (98 et 130 dans le
    calcul publié) : on réconcilierait la figure au prix d'un écart avec la mesure.
    """
    par = T.parcours(T.charger(T.preparer()))
    assert par["suivies"] == 212 and par["retirees"] == 4
    assert sum(par["apparition"].values()) == par["suivies"]      # les colonnes se totalisent
    assert sum(par["actuel"].values()) == par["suivies"]
    assert par["sauts_premiere_porte"] == 12 and par["regressions"] == 10


@pytest.mark.skipif(not (T.CLONE / ".git").exists(), reason="clone amont absent")
def test_les_rubans_du_flux_bouclent_et_disent_la_mesure():
    """Un ruban qui ne boucle pas est un chiffre faux. Et le flux doit dire CE QUE Cox a mesuré :
    sinon la figure illustrerait un autre chiffre que celui de l'article."""
    f = T.parcours(T.charger(T.preparer()))["flux"]
    assert (f["etape1"]["population"], f["etape1"]["franchissent"]) == (98, 74)
    assert (f["etape2"]["population"], f["etape2"]["franchissent"]) == (130, 45)
    e1, e2, reel = f["etape1"], f["etape2"], f["reel"]
    assert e1["vers_etape2"] + e1["saut"] + e1["bloquees"] == 98
    assert e2["entrees_etape1"] + e2["entrees_hors_etape"] == 130 == e2["franchissent"] + e2["bloquees"]
    assert reel["entrees_etape2"] + reel["entrees_saut"] + reel["entrees_hors_etape"] == 103


def test_le_flux_refuse_de_ne_pas_boucler():
    """Le garde-fou doit casser. Aucune donnée ne peut le déclencher aujourd'hui — les restes sont
    calculés par soustraction — mais il tient l'invariant contre une retouche future du calcul."""
    bon = {"etape1": {"population": 3, "vers_etape2": 1, "saut": 1, "bloquees": 1},
           "etape2": {"population": 2, "entrees_etape1": 1, "entrees_hors_etape": 1,
                      "franchissent": 1, "bloquees": 1},
           "reel": {"population": 2, "entrees_etape2": 1, "entrees_saut": 1,
                    "entrees_hors_etape": 0}}
    T.boucler(bon)                                   # silencieux quand tout tombe juste
    casse = {**bon, "reel": {**bon["reel"], "entrees_hors_etape": -1}}
    with pytest.raises(T.TendanceError, match="ne totalisent pas"):
        T.boucler(casse)


def test_le_lisezmoi_des_figures_porte_la_limite():
    assert "catalogue that is better kept" in T.LISEZMOI_FIGURES
    assert "Do not edit by hand" in T.LISEZMOI_FIGURES


# --- 8. l'habillage web des SVG ----------------------------------------------------------------
def _svg_de_demo(tmp_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(2, 1))
    ax.axis("off")
    ax.text(0.5, 0.5, "titre sans couleur", ha="center")        # noir par défaut, sans `fill`
    ax.text(0.5, 0.2, "en vert", color="#2a7d4f")
    f = tmp_path / "demo.svg"
    with plt.rc_context(T.RC_WEB):
        fig.savefig(f)
    plt.close(fig)
    return f


def test_le_svg_garde_du_vrai_texte_et_bascule_en_theme_sombre(tmp_path):
    """Par défaut matplotlib vectorise le texte : plus de lecture d'écran ni de thème sombre."""
    f = _svg_de_demo(tmp_path)
    s = T.habiller_svg(f, "Un titre", "Une description")
    assert "<text" in s and "titre sans couleur" in s          # du texte, pas des tracés
    assert "<title>Un titre</title>" in s and "<desc>Une description</desc>" in s
    assert "@media (prefers-color-scheme: dark)" in s and 'class="viz"' in s
    assert "fill: #2a7d4f; fill: var(--airp-franchi, #2a7d4f)" in s
    # le texte laissé en noir par matplotlib n'a AUCUN `fill` : seule la règle de feuille de
    # style le rattrape, sinon le titre resterait noir sur fond sombre.
    assert ".viz text { fill: #000000; fill: var(--airp-encre, #000000); }" in s


def test_l_habillage_refuse_une_couleur_hors_palette(tmp_path):
    """Une couleur ajoutée sans valeur sombre resterait figée en clair : le run doit casser."""
    f = _svg_de_demo(tmp_path)
    f.write_text(f.read_text(encoding="utf-8").replace("#2a7d4f", "#ff00ff"), encoding="utf-8")
    with pytest.raises(T.TendanceError, match="#ff00ff"):
        T.habiller_svg(f, "t", "d")


def test_chaque_couleur_de_la_palette_change_bien_en_sombre():
    assert all(clair != sombre for clair, (_, sombre) in T.PALETTE_WEB.items())
    noms = [n for n, _ in T.PALETTE_WEB.values()]
    assert len(set(noms)) == len(noms)                  # deux couleurs, deux variables
