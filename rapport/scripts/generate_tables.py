"""Génère les tableaux LaTeX et les chiffres du rapport depuis configs/, data/ et results/.

Aucun calcul d'optimisation n'est lancé : le script lit les résultats publiés, compte
les variables du modèle et interroge la description de l'API. À relancer après toute
modification des résultats, depuis la racine du projet :

    $env:PYTHONPATH = "src"
    .\\.venv\\Scripts\\python.exe rapport/scripts/generate_tables.py

Sorties : rapport/tables/*.tex (tableaux complets) et rapport/tables/chiffres.tex
(une macro par valeur citée dans le texte).
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "rapport" / "tables"
RESULTS = ROOT / "results" / "experiments"
sys.path.insert(0, str(ROOT / "src"))

SERVICES = ["URG", "MED", "REA", "CHI"]
SERVICE_NAMES = {"URG": "Urgences", "MED": "Médecine", "REA": "Réanimation", "CHI": "Chirurgie"}
METHODS = ["naive", "greedy", "milp", "cp_sat"]
METHOD_NAMES = {"naive": "Naïve", "greedy": "Greedy", "milp": "MILP/CBC", "cp_sat": "CP-SAT"}
PROFILES = ["equilibre", "priorite_accueil", "priorite_personnel"]
PROFILE_NAMES = {
    "equilibre": "Équilibré",
    "priorite_accueil": "Priorité accueil",
    "priorite_personnel": "Priorité personnel",
}
SCENARIOS = ["S0", "S1", "S2", "S3", "S4", "S5"]
SCENARIO_NAMES = {
    "S0": "Nominal",
    "S1": "Pic aux urgences",
    "S2": "Hausse générale",
    "S3": "Absences",
    "S4": "Crise combinée",
    "S5": "Fermeture de lits",
}
MODELS = {
    "naive": "Naïf",
    "seasonal_naive": "Naïf saisonnier",
    "moving_average": "Moyenne mobile",
    "exponential_smoothing": "Lissage exponentiel",
    "lagged_regression": "Régression à retards",
}
ROLE_NAMES = {"PHYSICIAN": "Médecins", "NURSE": "Infirmiers", "CARE_ASSISTANT": "Aides-soignants"}
SHIFT_NAMES = {"MORNING": "Matin", "EVENING": "Soir", "NIGHT": "Nuit"}


# --- mise en forme ------------------------------------------------------------
def integer(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", r"\,")


def decimal(value: float, digits: int = 1, sign: bool = False) -> str:
    text = f"{value:+.{digits}f}" if sign else f"{value:.{digits}f}"
    return text.replace(".", "{,}").replace("-", "$-$").replace("+", "$+$")


def percent(value: float, digits: int = 1, sign: bool = False) -> str:
    return decimal(value * 100, digits, sign) + r"\,\%"


def escape(text: str) -> str:
    for old, new in (("&", r"\&"), ("%", r"\%"), ("_", r"\_"), ("#", r"\#"), ("{", r"\{"), ("}", r"\}")):
        text = text.replace(old, new)
    return text


def bold(text: str) -> str:
    return r"\textbf{" + text + "}"


def sid(scenario: str) -> str:
    return f"$S_{scenario[1]}$"


def write_table(
    name: str, caption: str, spec: str, header: list[str], rows: list[list[str] | str], wide: bool = False, note: str = ""
) -> None:
    """Écrit un tableau au style du rapport (booktabs, légende au-dessus)."""
    body = []
    for row in rows:
        body.append("        " + (row if isinstance(row, str) else " & ".join(row) + r" \\"))
    tabular = [
        rf"\begin{{tabular}}{{{spec}}}",
        r"        \toprule",
        "        " + " & ".join(bold(item) if item else "" for item in header) + r" \\",
        r"        \midrule",
        *body,
        r"        \bottomrule",
        r"    \end{tabular}",
    ]
    inner = "\n".join(tabular)
    content = rf"    \resizebox{{\textwidth}}{{!}}{{{inner}}}" if wide else "    \\small\n    " + inner
    lines = [
        "% Généré par rapport/scripts/generate_tables.py : ne pas modifier à la main.",
        r"\begin{table}[H]",
        r"    \centering",
        rf"    \caption{{{caption}}}",
        rf"    \label{{tab:{name}}}",
        content,
    ]
    if note:
        lines += [r"    \par\vspace{3pt}", rf"    {{\footnotesize {note}}}"]
    lines.append(r"\end{table}")
    (OUT / f"{name}.tex").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


MACROS: dict[str, str] = {}


def macro(name: str, value: str) -> None:
    assert re.fullmatch(r"[A-Za-z]+", name), name
    assert name not in MACROS, name
    MACROS[name] = value


# --- données ------------------------------------------------------------------
hospital = json.loads((ROOT / "configs/hospital.json").read_text(encoding="utf-8"))
scenarios = json.loads((ROOT / "configs/scenarios.json").read_text(encoding="utf-8"))["scenarios"]
profiles = json.loads((ROOT / "configs/profiles.json").read_text(encoding="utf-8"))["profiles"]
summary = pd.read_csv(RESULTS / "scenario_summary.csv")
summary["s"] = summary["scenario_id"].str[:2]
kpi = summary.set_index(["profile_id", "s", "method_name"])
assert len(summary) == len(PROFILES) * len(SCENARIOS) * len(METHODS)


def experiment_directory(profile: str, scenario: str) -> Path:
    """Dossier d'une expérience de référence (les simulations personnalisées sont exclues)."""
    for path in sorted(RESULTS.glob("experiment-s*/experiment.json")):
        metadata = json.loads(path.read_text(encoding="utf-8"))
        if metadata["profile_id"] == profile and metadata["scenario"]["scenario_id"][:2] == scenario:
            return path.parent
    raise FileNotFoundError((profile, scenario))


def coverage(profile: str, scenario: str, method: str) -> pd.DataFrame:
    return pd.read_csv(experiment_directory(profile, scenario) / method / "staff_coverage.csv")


def covered(frame: pd.DataFrame) -> float:
    return 1 - frame["target_shortage"].sum() / frame["target_staff"].sum()


# --- configuration ------------------------------------------------------------
def configuration_tables() -> None:
    services = hospital["services"]
    write_table(
        "services",
        r"Services de l'hôpital synthétique (\texttt{configs/hospital.json}).",
        "lcccccc",
        ["Service", "Code", "Lits", "Admissions de base / jour", "DMS (jours)", "Effet d'événement", "Rang Greedy"],
        [
            [
                SERVICE_NAMES[code],
                rf"\texttt{{{code}}}",
                str(services[code]["beds_total"]),
                str(services[code]["base_daily_admissions"]),
                str(services[code]["length_of_stay_days"]),
                f"+{services[code]['special_event_effect']}",
                str(services[code]["priority"]),
            ]
            for code in SERVICES
        ]
        + [
            r"\midrule",
            [bold("Total"), "", bold(str(sum(services[c]["beds_total"] for c in SERVICES))), "", "", "", ""],
        ],
        wide=True,
        note="Rang Greedy : ordre de traitement du personnel par l'heuristique (0 = premier servi).",
    )
    data = hospital["synthetic_data"]
    write_table(
        "effectifs",
        r"Effectifs et cibles de personnel (\texttt{configs/hospital.json}).",
        "lccc",
        ["Corps professionnel", "Agents", "Cible pour dix lits ouverts et par poste", "Minimum par poste"],
        [
            [
                ROLE_NAMES[role],
                str(data["staff_by_role"][role]),
                str(data["staff_per_ten_beds"][role]),
                str(data["minimum_staff_by_role"][role]),
            ]
            for role in hospital["roles"]
        ]
        + [r"\midrule", [bold("Total"), bold(str(sum(data["staff_by_role"].values()))), "", ""]],
        note="La cible est identique pour tous les services et pour les trois postes ; le minimum ne s'applique qu'à un service ouvert.",
    )
    macro("NbLits", str(sum(services[c]["beds_total"] for c in SERVICES)))
    macro("NbAgents", str(sum(data["staff_by_role"].values())))
    for role, name in (("PHYSICIAN", "Medecins"), ("NURSE", "Infirmiers"), ("CARE_ASSISTANT", "Aides")):
        macro(f"Nb{name}", str(data["staff_by_role"][role]))
    macro("NbJours", integer(hospital["historical_days"]))
    macro("TempsSolveur", str(hospital["planning_policy"]["solver_time_limit_seconds"]))
    macro("ThreadsSolveur", str(hospital["planning_policy"]["solver_num_workers"]))
    macro("ReposMin", str(hospital["planning_policy"]["min_rest_hours"]))
    macro("NuitsMax", str(hospital["planning_policy"]["max_consecutive_nights"]))
    macro("PostesMax", str(data["max_shifts"]))

    rows = []
    for item in scenarios:
        code = item["scenario_id"][:2]
        peak = ", ".join(f"{s} ×{m:.2f}".replace(".", "{,}") for s, m in item.get("service_multipliers", {}).items())
        demand = f"{peak}, {item['peak_days']} premiers jours" if peak else f"×{item['demand_multiplier']:.2f}".replace(
            ".", "{,}"
        ) + ", tous services"
        rows.append(
            [
                sid(code),
                rf"\texttt{{{escape(item['scenario_id'])}}}",
                demand.replace("×", r"$\times$"),
                percent(item["absence_rate"], 0),
                percent(item["capacity_reduction"], 0),
            ]
        )
    write_table(
        "scenarios",
        r"Définition des six scénarios (\texttt{configs/scenarios.json}).",
        "llp{5.2cm}cc",
        ["", "Identifiant", "Admissions demandées", "Absences ajoutées", "Lits fermés"],
        rows,
        wide=True,
        note="Absences : part des professionnels disponibles rendus indisponibles sur tout l'horizon (tirage fixé par la graine). Lits fermés : réduction de la capacité de chaque service, arrondie à l'entier inférieur.",
    )

    weights = {p["profile_id"]: p.get("objective_weights") or hospital["objective_weights"] for p in profiles}

    def multiplied(weight: dict[str, object], key: str, field: str) -> str:
        factors = weight.get(field) or {}
        suffix = "".join(rf" ({s} $\times${m})" for s, m in factors.items())
        value = int(weight.get(key, 0))
        return integer(value) + (suffix if value else "")

    write_table(
        "profils",
        r"Poids de l'objectif selon le profil (\texttt{configs/profiles.json}).",
        "llccc",
        ["Coefficient", "Champ", *(PROFILE_NAMES[p] for p in PROFILES)],
        [
            [
                r"$c_{\text{lit}}$, lit-jour ouvert",
                r"\texttt{opened\_bed}",
                *(integer(weights[p]["opened_bed"]) for p in PROFILES),
            ],
            [
                r"$c_{\text{dem}}$, journée-patient non soutenue",
                r"\texttt{unmet\_patient\_day}",
                *(multiplied(weights[p], "unmet_patient_day", "demand_multipliers") for p in PROFILES),
            ],
            [
                r"$c_{\text{ref}}$, admission refusée",
                r"\texttt{rejected\_admission}",
                *(multiplied(weights[p], "rejected_admission", "demand_multipliers") for p in PROFILES),
            ],
            [
                r"$c_{\text{rh}}$, poste cible non couvert",
                r"\texttt{staff\_target\_shortage}",
                *(multiplied(weights[p], "staff_target_shortage", "staff_multipliers") for p in PROFILES),
            ],
            [
                r"$c_{\text{eq}}$, poste d'étendue de charge",
                r"\texttt{workload\_imbalance}",
                *(integer(weights[p]["workload_imbalance"]) for p in PROFILES),
            ],
        ],
        wide=True,
    )

    quality = json.loads((ROOT / "data/synthetic/quality_report.json").read_text(encoding="utf-8"))
    notes = {
        "historical_demand": r"\texttt{emergency\_arrivals} vide hors URG",
        "staff_availability": r"\texttt{absence\_type} vide si disponible",
    }
    write_table(
        "qualite",
        r"Rapport de qualité des données synthétiques (\texttt{data/synthetic/quality\_report.json}).",
        "lrrrl",
        ["Table", "Lignes", "Valeurs vides", "Doublons", "Explication"],
        [
            [
                rf"\texttt{{{escape(name)}}}",
                integer(count),
                integer(quality["missing_values"][name]),
                integer(quality["duplicate_rows"][name]),
                notes.get(name, "--"),
            ]
            for name, count in quality["row_counts"].items()
        ],
        note=f"Période couverte : {quality['date_min']} au {quality['date_max']}. Valeurs invalides : {quality['invalid_value_count']}. Verdict : {'conforme' if quality['valid'] else 'non conforme'}.",
    )
    macro("DateDebut", quality["date_min"])
    macro("DateFin", quality["date_max"])
    macro("LignesDispo", integer(quality["row_counts"]["staff_availability"]))


# --- prévisions -----------------------------------------------------------------
def forecasting_tables() -> None:
    metrics = pd.read_csv(ROOT / "results/forecasts/metrics_summary.csv")
    horizon = pd.read_csv(ROOT / "results/forecasts/metrics_by_horizon.csv")
    selection = pd.read_csv(ROOT / "results/forecasts/model_selection.csv").set_index("service")["selected_model"]
    table = metrics.set_index(["partition", "service", "model_name"])
    rows: list[list[str] | str] = []
    for service in SERVICES:
        if rows:
            rows.append(r"\midrule")
        for index, model in enumerate(MODELS):
            row = table.loc[("validation", service, model)]
            kept = selection[service] == model
            cells = [
                MODELS[model],
                decimal(row["mae"], 2),
                decimal(row["rmse"], 2),
                decimal(row["wape"], 2) + r"\,\%",
                decimal(row["bias"], 2, True),
                "Retenu" if kept else "--",
            ]
            cells = [bold(c) for c in cells] if kept else cells
            rows.append(
                [rf"\multirow{{5}}{{*}}{{{SERVICE_NAMES[service]} (\texttt{{{service}}})}}" if index == 0 else "", *cells]
            )
    count = int(metrics.loc[metrics["partition"] == "validation", "observations"].iloc[0])
    test_count = int(metrics.loc[metrics["partition"] == "test_final", "observations"].iloc[0])
    write_table(
        "previsions_validation",
        f"Erreurs de validation des cinq modèles ({count} prévisions par service et par modèle).",
        "llccccc",
        ["Service", "Modèle", "MAE", "RMSE", "WAPE", "Biais", "Décision"],
        rows,
        wide=True,
    )
    rows = []
    for service in SERVICES:
        values = {model: table.loc[("test_final", service, model), "wape"] for model in MODELS}
        best = min(values, key=values.get)
        rows.append(
            [
                f"{SERVICE_NAMES[service]}",
                *(
                    (bold if model == best else str)(decimal(values[model], 1) + r"\,\%")
                    + (r"$^{\ast}$" if model == selection[service] else "")
                    for model in MODELS
                ),
            ]
        )
    write_table(
        "previsions_test",
        f"WAPE sur le test final réservé ({test_count} prévisions par service), jamais utilisé pour choisir le modèle.",
        "lccccc",
        ["Service", *MODELS.values()],
        rows,
        wide=True,
        note=r"$^{\ast}$ modèle retenu en validation ; en gras, meilleure valeur du test.",
    )
    kept = horizon[(horizon["partition"] == "validation") & (horizon["model_name"] == "lagged_regression")]
    pivot = kept.pivot(index="service", columns="horizon", values="mae")
    write_table(
        "previsions_horizon",
        "MAE de la régression à retards selon l'horizon (validation, 12 origines).",
        "lccccccc",
        ["Service", *(f"$J+{h}$" for h in pivot.columns)],
        [[SERVICE_NAMES[s], *(decimal(pivot.loc[s, h], 2) for h in pivot.columns)] for s in SERVICES],
    )
    assert int(kept["observations"].iloc[0]) == 12
    for service, name in zip(SERVICES, ("Urg", "Med", "Rea", "Chi"), strict=True):
        macro(f"WapeVal{name}", decimal(table.loc[("validation", service, "lagged_regression"), "wape"], 2) + r"\,\%")
        macro(f"WapeTest{name}", decimal(table.loc[("test_final", service, "lagged_regression"), "wape"], 1) + r"\,\%")
    macro("MaeValUrg", decimal(table.loc[("validation", "URG", "lagged_regression"), "mae"], 2))
    macro("NbPrevVal", str(count))
    macro("NbPrevTest", str(test_count))


# --- résultats -------------------------------------------------------------------
def result_tables() -> None:
    for profile in PROFILES:
        rows: list[list[str] | str] = []
        for scenario in SCENARIOS:
            if rows:
                rows.append(r"\midrule")
            block = kpi.loc[(profile, scenario)]
            best, reference = block["objective_value"].min(), block.loc["greedy", "objective_value"]
            for index, method in enumerate(METHODS):
                r = block.loc[method]
                value = integer(r["objective_value"])
                rows.append(
                    [
                        rf"\multirow{{4}}{{*}}{{{sid(scenario)} {SCENARIO_NAMES[scenario]}}}" if index == 0 else "",
                        METHOD_NAMES[method],
                        bold(value) if r["objective_value"] == best else value,
                        "--" if method == "greedy" else percent(r["objective_value"] / reference - 1, 1, True),
                        "--" if pd.isna(r["optimality_gap"]) else percent(r["optimality_gap"], 1),
                        integer(r["rejected_admissions"]),
                        percent(r["coverage_rate"], 1),
                        integer(r["staff_shortage_total"]),
                        percent(covered(coverage(profile, scenario, method)), 1),
                        integer(r["fairness_metric"]),
                    ]
                )
        write_table(
            f"resultats_{profile}",
            f"Résultats des quatre méthodes, profil « {PROFILE_NAMES[profile]} ».",
            "llrrrrrrrr",
            [
                "Scénario",
                "Méthode",
                r"Objectif $\mathcal{Z}$",
                "vs Greedy",
                "Gap",
                "Refus",
                "Couv. demande",
                "Déficit RH",
                "Postes couverts",
                "Équité",
            ],
            rows,
            wide=True,
            note="En gras : meilleur objectif du scénario. Les 24 plans respectent toutes les contraintes dures.",
        )
        assert bool(kpi.loc[profile]["validation_passed"].all())

    rows = []
    for profile in PROFILES:
        if rows:
            rows.append(r"\midrule")
        for index, scenario in enumerate(SCENARIOS):
            block = kpi.loc[(profile, scenario)]
            best, greedy = block["objective_value"].min(), block.loc["greedy"]
            winners = [m for m in METHODS if block.loc[m, "objective_value"] == best]
            w = block.loc[winners[0]]
            rows.append(
                [
                    rf"\multirow{{6}}{{*}}{{{PROFILE_NAMES[profile]}}}" if index == 0 else "",
                    sid(scenario),
                    " = ".join(METHOD_NAMES[m] for m in winners),
                    percent(best / greedy["objective_value"] - 1, 1, True),
                    f"{integer(w['rejected_admissions'])} ({integer(greedy['rejected_admissions'])})",
                    f"{integer(w['staff_shortage_total'])} ({integer(greedy['staff_shortage_total'])})",
                ]
            )
    write_table(
        "meilleures_methodes",
        "Meilleure méthode par profil et par scénario.",
        "lclccc",
        ["Profil", "", "Meilleure méthode", "Gain vs Greedy", "Refus (Greedy)", "Déficit RH (Greedy)"],
        rows,
        note="Les objectifs de deux profils ne sont pas comparables entre eux.",
    )

    rows = []
    for scenario in SCENARIOS:
        cells = [f"{sid(scenario)} {SCENARIO_NAMES[scenario]}"]
        greedy = kpi.loc[("equilibre", scenario, "greedy")]
        cells += [integer(greedy["rejected_admissions"]), integer(greedy["staff_shortage_total"])]
        for profile in PROFILES:
            r = kpi.loc[(profile, scenario, "cp_sat")]
            cells += [integer(r["rejected_admissions"]), integer(r["staff_shortage_total"])]
        rows.append(cells)
    write_table(
        "arbitrage",
        "Arbitrage accueil / personnel : refus et déficit RH de CP-SAT selon le profil.",
        "lcccccccc",
        [
            "Scénario",
            "Greedy refus",
            "déficit",
            "Équilibré refus",
            "déficit",
            "Accueil refus",
            "déficit",
            "Personnel refus",
            "déficit",
        ],
        rows,
        wide=True,
        note="Le plan Greedy est identique pour les trois profils.",
    )

    rows = []
    for method in METHODS:
        frame = coverage("equilibre", "S0", method)
        rows.append(
            [
                METHOD_NAMES[method],
                *(percent(covered(frame[frame["service"] == s]), 0) for s in SERVICES),
                *(percent(covered(frame[frame["shift"] == s]), 0) for s in SHIFT_NAMES),
                bold(percent(covered(frame), 1)),
            ]
        )
    write_table(
        "couverture_s0",
        r"Postes cibles couverts en $S_0$ par service et par poste, profil équilibré.",
        "lcccc|ccc|c",
        ["Méthode", *SERVICES, *SHIFT_NAMES.values(), "Total"],
        rows,
    )

    rows = []
    for profile in PROFILES:
        block = kpi.loc[profile]
        shares = {
            key: block[key] / block["objective_value"]
            for key in (
                "staff_target_shortage_cost",
                "unmet_patient_day_cost",
                "rejected_admission_cost",
                "opened_bed_cost",
            )
        }
        rows.append(
            [PROFILE_NAMES[profile], *(f"{percent(v.min(), 1)} à {percent(v.max(), 1)}" for v in shares.values())]
        )
    write_table(
        "parts_objectif",
        "Part de chaque composante dans l'objectif (24 plans par profil).",
        "lcccc",
        ["Profil", "Déficit RH", "Demande non soutenue", "Refus", "Lits ouverts"],
        rows,
        wide=True,
    )

    rows = []
    for method in METHODS:
        block = summary[summary["method_name"] == method]
        gaps = block["optimality_gap"].dropna()
        rows.append(
            [
                METHOD_NAMES[method],
                decimal(block["runtime_seconds"].min(), 1),
                decimal(block["runtime_seconds"].mean(), 1),
                decimal(block["runtime_seconds"].max(), 1),
                "--" if gaps.empty else f"{percent(gaps.min(), 1)} à {percent(gaps.max(), 1)}",
                str(int((block["status"] == "OPTIMAL").sum())),
                f"{int(block['validation_passed'].sum())} / {len(block)}",
            ]
        )
    write_table(
        "performances",
        "Temps de calcul, gap déclaré et respect des contraintes (18 plans par méthode).",
        "lcccccc",
        ["Méthode", "Min (s)", "Moyenne (s)", "Max (s)", "Gap", "Optimal prouvé", "Contraintes respectées"],
        rows,
        wide=True,
    )
    result_macros()


def result_macros() -> None:
    greedy0 = coverage("equilibre", "S0", "greedy")
    target = int(greedy0["target_staff"].sum())
    staff = pd.read_csv(ROOT / "data/synthetic/staff.csv")
    capacity = int(staff["max_shifts"].sum())
    macro("CibleSz", integer(target))
    macro("CapacitePostes", integer(capacity))
    macro("PlafondSz", percent(capacity / target, 1))
    macro("AgentsCent", str(round(target / hospital["synthetic_data"]["max_shifts"])))
    for method, name in (("naive", "Naive"), ("greedy", "Greedy"), ("milp", "Milp"), ("cp_sat", "Cp")):
        frame = coverage("equilibre", "S0", method)
        row = kpi.loc[("equilibre", "S0", method)]
        macro(f"CouvSz{name}", percent(covered(frame), 1))
        macro(f"RefusSz{name}", integer(row["rejected_admissions"]))
        macro(f"DeficitSz{name}", integer(row["staff_shortage_total"]))
        macro(f"ObjSz{name}", integer(row["objective_value"]))
        for service, short in zip(SERVICES, ("Urg", "Med", "Rea", "Chi"), strict=True):
            macro(f"CouvSz{name}{short}", percent(covered(frame[frame["service"] == service]), 0))
    accueil = coverage("priorite_accueil", "S0", "milp")
    macro("CouvSzMilpUrgAccueil", percent(covered(accueil[accueil["service"] == "URG"]), 0))
    macro("CouvNuitInfUrgCp", percent(covered(coverage("equilibre", "S0", "cp_sat").query("service == 'URG' and shift == 'NIGHT' and role == 'NURSE'")), 0))
    macro("CouvDemSzGreedy", percent(kpi.loc[("equilibre", "S0", "greedy"), "coverage_rate"], 1))
    macro("CouvDemSqGreedy", percent(kpi.loc[("equilibre", "S4", "greedy"), "coverage_rate"], 1))
    every = [covered(coverage(p, s, m)) for p in PROFILES for s in SCENARIOS for m in METHODS]
    macro("CouvMinTous", percent(min(every), 0))
    macro("CouvMaxTous", percent(max(every), 0))
    winners = 0
    for profile, short in zip(PROFILES, ("Eq", "Acc", "Per"), strict=True):
        gains, deficits = [], []
        for scenario in SCENARIOS:
            block = kpi.loc[(profile, scenario)]
            best = block["objective_value"].min()
            winners += int(block.loc["cp_sat", "objective_value"] == best)
            gains.append(1 - best / block.loc["greedy", "objective_value"])
            deficits.append(1 - block.loc["cp_sat", "staff_shortage_total"] / block.loc["greedy", "staff_shortage_total"])
        macro(f"GainMin{short}", percent(min(gains), 1))
        macro(f"GainMax{short}", percent(max(gains), 1))
        macro(f"DeficitCpMin{short}", percent(min(deficits), 0))
        macro(f"DeficitCpMax{short}", percent(max(deficits), 0))
    macro("NbCpMeilleur", str(winners))
    ratio = kpi["objective_value"].xs("naive", level=2) / kpi["objective_value"].xs("greedy", level=2) - 1
    macro("NaiveMin", percent(ratio.min(), 1))
    macro("NaiveMax", percent(ratio.max(), 1))
    for scenario in ("S0", "S3"):
        block = kpi.loc[("priorite_personnel", scenario)]
        name = {"S0": "Sz", "S3": "St"}[scenario]
        macro(f"MilpPer{name}", percent(block.loc["milp", "objective_value"] / block.loc["greedy", "objective_value"] - 1, 1, True))
        macro(f"GapMilpPer{name}", percent(block.loc["milp", "optimality_gap"], 1))
        macro(f"RefusMilpPer{name}", integer(block.loc["milp", "rejected_admissions"]))
    for profile, short in zip(PROFILES, ("Eq", "Acc", "Per"), strict=True):
        for scenario, name in (("S0", "Sz"), ("S4", "Sq")):
            macro(f"RefusCp{short}{name}", integer(kpi.loc[(profile, scenario, "cp_sat"), "rejected_admissions"]))
            macro(f"DeficitCp{short}{name}", integer(kpi.loc[(profile, scenario, "cp_sat"), "staff_shortage_total"]))
    for scenario, name in zip(SCENARIOS, ("Sz", "Su", "Sd", "St", "Sq", "Sc"), strict=True):
        if scenario != "S0":
            macro(f"RefusGreedy{name}", integer(kpi.loc[("equilibre", scenario, "greedy"), "rejected_admissions"]))
            macro(f"DeficitGreedy{name}", integer(kpi.loc[("equilibre", scenario, "greedy"), "staff_shortage_total"]))
        macro(f"CouvGreedy{name}", percent(covered(coverage("equilibre", scenario, "greedy")), 1))
    saturated = pd.read_csv(experiment_directory("equilibre", "S4") / "greedy" / "bed_allocations.csv")
    macro("SaturesSq", f"{int((saturated['occupancy_end'] >= saturated['capacity_available']).sum())} sur {len(saturated)}")
    absents = pd.read_csv(experiment_directory("equilibre", "S3") / "scenario_inputs" / "planning_availability.csv")
    macro("AbsentsSt", str(absents.loc[absents["scenario_absence"], "staff_id"].nunique()))
    for scenario, name in (("S3", "St"), ("S4", "Sq")):
        macro(f"EquiteGreedy{name}", integer(kpi.loc[("equilibre", scenario, "greedy"), "fairness_metric"]))
    share = kpi.loc["equilibre"]["staff_target_shortage_cost"] / kpi.loc["equilibre"]["objective_value"]
    macro("PartRhMin", percent(share.min(), 0))
    macro("PartRhMax", percent(share.max(), 0))
    gap = kpi.loc["priorite_accueil"]["optimality_gap"]
    macro("GapMaxAccueilMilp", percent(gap.xs("milp", level=1).max(), 1))
    macro("GapMaxAccueilCp", percent(gap.xs("cp_sat", level=1).max(), 1))
    unmet = kpi.loc["equilibre"]["unmet_patient_day_cost"] / kpi.loc["equilibre"]["objective_value"]
    macro("PartDemMin", percent(unmet.min(), 0))
    macro("PartDemMax", percent(unmet.max(), 0))
    qualified = staff["qualified_services"].map(json.loads)
    for service, name in zip(SERVICES, ("Urg", "Med", "Rea", "Chi"), strict=True):
        macro(f"Qualif{name}", percent(float(qualified.map(lambda q, s=service: s in q).mean()), 0))
        macro(f"PartCible{name}", percent(greedy0.loc[greedy0["service"] == service, "target_staff"].sum() / target, 0))
    macro("VivierA", str(int(qualified.map(lambda q: set(q) <= {"URG", "CHI"}).sum())))
    macro("VivierB", str(int(qualified.map(lambda q: set(q) <= {"REA", "MED"}).sum())))
    seeds = [
        json.loads(p.read_text(encoding="utf-8"))["solver_seed"]
        for p in sorted(RESULTS.glob("experiment-s*/milp/method_result.json"))
    ]
    macro("NbReprisesCbc", str(sum(seed != hospital["random_seed"] for seed in seeds)))
    # Effet de palier : jours où CP-SAT n'ouvre pas le même nombre de lits que Greedy en S0.
    for profile, short in (("equilibre", "Eq"), ("priorite_personnel", "Per")):
        directory = experiment_directory(profile, "S0")
        tables = [pd.read_csv(directory / name / "bed_allocations.csv") for name in ("greedy", "cp_sat")]
        merged = tables[0].merge(tables[1], on=["date", "service"], suffixes=("_greedy", "_cp"))
        different = merged[merged["opened_beds_greedy"] != merged["opened_beds_cp"]]
        macro(f"PaliersDiff{short}", str(len(different)))
        macro(f"PaliersCinq{short}", str(int((different["opened_beds_cp"] % 5 == 0).sum())))


# --- sensibilité ------------------------------------------------------------------
def sensitivity_tables() -> None:
    data = pd.read_csv(RESULTS / "sensitivity_results.csv")
    greedy = data[data["method_name"] == "greedy"]
    absences, demands = sorted(greedy["absence_rate"].unique()), sorted(greedy["demand_multiplier"].unique())
    closures = sorted(greedy["capacity_reduction"].unique())
    label = {d: rf"$\times${d:.2f}".replace(".", "{,}") for d in demands}

    def cell(method: str, absence: float, demand: float, closure: float) -> pd.Series:
        rows = data[
            (data["method_name"] == method)
            & (data["absence_rate"] == absence)
            & (data["demand_multiplier"] == demand)
            & (data["capacity_reduction"] == closure)
        ]
        assert len(rows) == 1
        return rows.iloc[0]

    write_table(
        "sensibilite_couverture",
        "Postes cibles couverts par Greedy selon les absences et la demande (aucune fermeture de lits).",
        "lcccc",
        ["Absences", *(f"Demande {label[d]}" for d in demands)],
        [
            [percent(a, 0), *(percent(cell("greedy", a, d, 0.0)["staff_coverage_rate"], 1) for d in demands)]
            for a in absences
        ],
    )
    write_table(
        "sensibilite_refus",
        "Admissions refusées par Greedy selon la demande et les fermetures (aucune absence ajoutée).",
        "lcccc",
        ["Lits fermés", *(f"Demande {label[d]}" for d in demands)],
        [
            [
                percent(c, 0),
                *(
                    integer(row["rejected_admissions"]) + ("" if row["validation_passed"] else r"$^{\dagger}$")
                    for row in (cell("greedy", 0.0, d, c) for d in demands)
                ),
            ]
            for c in closures
        ],
        note=r"$^{\dagger}$ contraintes non respectées : les patients déjà présents dépassent les lits restants ; la valeur ne décrit pas un plan réalisable.",
    )
    write_table(
        "sensibilite_methodes",
        r"Postes cibles couverts par Naïve et Greedy selon les absences (demande $\times$1, aucune fermeture).",
        "lccccc",
        ["Méthode", *(percent(a, 0) for a in absences)],
        [
            [METHOD_NAMES[m], *(percent(cell(m, a, 1.0, 0.0)["staff_coverage_rate"], 1) for a in absences)]
            for m in ("naive", "greedy")
        ],
    )
    lines = [
        "% Généré par rapport/scripts/generate_tables.py : ne pas modifier à la main.",
        r"{\footnotesize",
        r"\begin{longtable}{lcccrrrrc}",
        r"\caption{Les 80 cas de la grille de sensibilité, heuristique Greedy, profil équilibré.}\label{tab:sensibilite_complete}\\",
        r"\toprule",
        r"\textbf{Cas} & \textbf{Abs.} & \textbf{Dem.} & \textbf{Lits} & \textbf{Objectif} & \textbf{Refus} & \textbf{Déficit RH} & \textbf{Postes couv.} & \textbf{Contraintes} \\",
        r"\midrule\endfirsthead",
        r"\toprule",
        r"\textbf{Cas} & \textbf{Abs.} & \textbf{Dem.} & \textbf{Lits} & \textbf{Objectif} & \textbf{Refus} & \textbf{Déficit RH} & \textbf{Postes couv.} & \textbf{Contraintes} \\",
        r"\midrule\endhead",
        r"\bottomrule\endfoot",
    ]
    for row in greedy.sort_values("scenario_id").itertuples():
        lines.append(
            " & ".join(
                [
                    rf"\texttt{{{escape(row.scenario_id[5:])}}}",
                    percent(row.absence_rate, 0),
                    label[row.demand_multiplier],
                    f"$-${percent(row.capacity_reduction, 0)}" if row.capacity_reduction else "--",
                    integer(row.objective_value),
                    integer(row.rejected_admissions),
                    integer(row.staff_shortage_total),
                    percent(row.staff_coverage_rate, 1),
                    "respectées" if row.validation_passed else "non",
                ]
            )
            + r" \\"
        )
    lines += [r"\end{longtable}", "}"]
    (OUT / "sensibilite_complete.tex").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    macro("NbCas", str(greedy["scenario_id"].nunique()))
    macro("NbResSens", str(len(data)))
    macro("NbResSensOk", str(int(data["validation_passed"].sum())))
    macro("NbResSensKo", str(int((~data["validation_passed"]).sum())))
    macro("SensCouvBase", percent(cell("greedy", 0.0, 1.0, 0.0)["staff_coverage_rate"], 1))
    macro("SensCouvAbs", percent(cell("greedy", 0.2, 1.0, 0.0)["staff_coverage_rate"], 1))
    macro("SensCouvPire", percent(cell("greedy", 0.2, 2.0, 0.0)["staff_coverage_rate"], 1))
    macro("SensRefusBase", integer(cell("greedy", 0.0, 1.0, 0.0)["rejected_admissions"]))
    for demand, name in ((1.25, "Vc"), (1.5, "Cq"), (2.0, "Dx")):
        macro(f"SensRefus{name}", integer(cell("greedy", 0.0, demand, 0.0)["rejected_admissions"]))
    macro("SensCouvFermee", percent(cell("greedy", 0.0, 1.0, 0.1)["staff_coverage_rate"], 1))
    macro("SensRefusFermee", integer(cell("greedy", 0.0, 1.0, 0.1)["rejected_admissions"]))
    macro("SensNaiveBase", percent(cell("naive", 0.0, 1.0, 0.0)["staff_coverage_rate"], 1))
    macro("SensNaiveAbs", percent(cell("naive", 0.2, 1.0, 0.0)["staff_coverage_rate"], 1))
    beds = pd.read_csv(ROOT / "results/operational_instances/S0/bed_requirements.csv")
    first = beds[beds["date"] == beds["date"].min()].set_index("service")
    limit = 1 - (first["occupancy_start"] - first["expected_discharges"]) / first["capacity_available"]
    macro("LimiteMed", percent(limit["MED"], 0))
    assert limit.idxmin() == "MED"
    macro("RecensementMed", str(int(first.loc["MED", "occupancy_start"])))


# --- logiciel ----------------------------------------------------------------------
def software_tables() -> None:
    from hospital_planning.api.app import app
    from hospital_planning.config.loader import load_hospital_config
    from hospital_planning.optimization import exact

    paths = app.openapi()["paths"]
    rows = []
    for path, operations in paths.items():
        for verb, operation in operations.items():
            text = (operation.get("description") or "").split("\n")[0].split(";")[0].strip()
            rows.append(
                [
                    rf"\texttt{{{verb.upper()}}}",
                    r"\texttt{" + escape(path).replace("/", r"/\allowbreak ") + "}",
                    escape(text.rstrip(".")) + ".",
                ]
            )
    write_table(
        "endpoints",
        f"Les {len(rows)} points d'accès de l'API, extraits de sa description OpenAPI.",
        "lp{8.2cm}p{8.4cm}",
        ["Verbe", "Route", "Rôle"],
        rows,
        wide=True,
    )
    macro("NbEndpoints", str(len(rows)))

    import pulp

    config = load_hospital_config(ROOT / "configs/hospital.json")
    inputs_dir = experiment_directory("equilibre", "S0") / "scenario_inputs"
    demand, beds, planning = (
        pd.read_csv(inputs_dir / f"{name}.csv", parse_dates=["date"])
        for name in ("demand_requirements", "bed_requirements", "planning_availability")
    )
    staff = pd.read_csv(ROOT / "data/synthetic/staff.csv")
    inputs, _ = exact._build_inputs(demand, beds, staff, planning, config, planning)
    model = pulp.LpProblem("taille", pulp.LpMinimize)
    variables = exact._create_pulp_variables(model, inputs, config)
    exact._add_pulp_constraints(model, variables, inputs, config)
    constraints = model.constraints() if callable(model.constraints) else model.constraints
    macro("NbVariables", integer(sum(len(group) for group in variables.values())))
    macro("NbAffectations", integer(len(variables["assignment"])))
    macro("NbContraintes", integer(len(constraints)))
    macro("NbDeficits", integer(len(variables["shortage"])))

    listing = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout
    counts: dict[str, int] = {}
    for line in listing.splitlines():
        if "::" in line:
            name = line.split("::")[0].replace("\\", "/").split("/")[-1]
            counts[name] = counts.get(name, 0) + 1
    subjects = {
        "test_api_contract.py": "Contrat de l'API, lecture des artefacts, traversée de chemin",
        "test_config_contracts.py": "Validation de la configuration",
        "test_data_validation.py": "Contrôles de qualité des données",
        "test_forecasting.py": "Prévisions chronologiques, métriques, absence de fuite",
        "test_generator.py": "Reproductibilité du générateur",
        "test_greedy_and_validator.py": "Greedy, validateur, occupation du premier jour",
        "test_occupancy.py": "Conservation des patients",
        "test_operational_requirements.py": "Instance opérationnelle et empreinte de demande",
        "test_portability.py": "Chemins relatifs, empreinte indépendante du système",
        "test_profiles_and_naive.py": "Stratégie naïve, profils, équité sans les absents",
        "test_scenario_comparison.py": "Comparaison par graine et par profil",
        "test_scenarios.py": "Transformations des scénarios",
        "test_sensitivity.py": "Grille de sensibilité et fusion des résultats",
        "test_simulator.py": "Scénarios personnalisés, isolement de S0--S5",
        "test_solver_settings.py": "Budget, borne, gap et statut prouvé des solveurs",
        "test_solver_smoke.py": "Disponibilité des solveurs",
    }
    assert set(counts) == set(subjects), set(counts) ^ set(subjects)
    specs = {
        "dashboard.spec.ts": "Ouverture des dix vues, sans calcul automatique",
        "simulator.spec.ts": "Simulateur, cas irréalisable, comparaison et profils",
    }
    browser = {
        name: len(re.findall(r"^test\(", (ROOT / "frontend/tests" / name).read_text(encoding="utf-8"), re.M))
        for name in specs
    }
    write_table(
        "tests",
        "Tests automatisés du projet.",
        "lcl",
        ["Fichier", "Tests", "Objet"],
        [[rf"\texttt{{{escape(n)}}}", str(counts[n]), subjects[n]] for n in sorted(counts)]
        + [r"\midrule", [bold("Total Python (pytest)"), bold(str(sum(counts.values()))), ""], r"\midrule"]
        + [[rf"\texttt{{{escape(n)}}}", str(browser[n]), specs[n]] for n in specs]
        + [r"\midrule", [bold("Total navigateur (Playwright)"), bold(str(sum(browser.values()))), ""]],
        wide=True,
    )
    macro("NbTestsPython", str(sum(counts.values())))
    macro("NbTestsNavigateur", str(sum(browser.values())))

    columns = {
        "date": ("Date ISO", "Jour observé"),
        "service": ("Texte", "Code du service : URG, MED, REA ou CHI"),
        "admissions": ("Entier", "Admissions du jour"),
        "discharges": ("Entier", "Sorties issues de la dynamique des séjours"),
        "emergency_arrivals": ("Entier ou vide", "Arrivées aux urgences, renseignées pour URG seulement"),
        "is_holiday": ("Booléen", "Jour férié synthétique"),
        "is_special_event": ("Booléen", "Événement exceptionnel tiré au hasard"),
        "data_source": ("Texte", "Toujours synthetic"),
    }
    header = pd.read_csv(ROOT / "data/synthetic/historical_demand.csv", nrows=0).columns.tolist()
    assert header == list(columns), header
    write_table(
        "dictionnaire",
        r"Colonnes de \texttt{historical\_demand.csv}.",
        "lll",
        ["Colonne", "Type", "Description"],
        [[rf"\texttt{{{escape(c)}}}", *columns[c]] for c in header],
    )
    excerpt = {
        "planning_horizon_days": hospital["planning_horizon_days"],
        "random_seed": hospital["random_seed"],
        "services": {
            code: {
                key: hospital["services"][code][key]
                for key in ("beds_total", "base_daily_admissions", "priority", "length_of_stay_days")
            }
            for code in hospital["services"]
        },
        "shifts": hospital["shifts"],
        "staff_by_role": hospital["synthetic_data"]["staff_by_role"],
        "staff_per_ten_beds": hospital["synthetic_data"]["staff_per_ten_beds"],
        "planning_policy": hospital["planning_policy"],
        "objective_weights": hospital["objective_weights"],
    }
    text = json.dumps(excerpt, indent=2)
    text = re.sub(r"\{\s+([^{}]*?)\s+\}", lambda m: "{" + re.sub(r"\s+", " ", m.group(1)) + "}", text)
    assert text.isascii()
    (OUT / "hospital_extrait.json").write_text(text + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    configuration_tables()
    forecasting_tables()
    result_tables()
    sensitivity_tables()
    software_tables()
    lines = ["% Généré par rapport/scripts/generate_tables.py : ne pas modifier à la main."]
    lines += [rf"\newcommand{{\{name}}}{{{value}}}" for name, value in sorted(MACROS.items())]
    (OUT / "chiffres.tex").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(list(OUT.glob('*.tex')))} fichiers LaTeX, {len(MACROS)} chiffres")


if __name__ == "__main__":
    main()
