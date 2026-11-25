"""Analyse de sensibilité : calcule tout ou partie de la grille déclarée de 80 cas."""

import argparse
import json
from pathlib import Path
from time import perf_counter

import pandas as pd

from hospital_planning.config.loader import load_hospital_config, load_profiles, with_profile, with_solver_settings
from hospital_planning.domain.contracts import DEFAULT_PROFILE_ID, HospitalConfig
from hospital_planning.experiments.runner import METHODS, run_experiment
from hospital_planning.experiments.scenarios import ScenarioDefinition, sensitivity_definitions
from hospital_planning.optimization.availability import project_planning_availability

RESULTS_FILE = "sensitivity_results.csv"
KEY = ["scenario_id", "profile_id", "method_name"]


def run_sensitivity(
    definitions: list[ScenarioDefinition],
    demand: pd.DataFrame,
    beds: pd.DataFrame,
    staff: pd.DataFrame,
    planning_availability: pd.DataFrame,
    metadata: dict[str, object],
    config: HospitalConfig,
    *,
    methods: tuple[str, ...],
    profile_id: str = DEFAULT_PROFILE_ID,
) -> pd.DataFrame:
    """Calcule les KPI de chaque cas ; les plans détaillés ne sont pas conservés."""
    frames: list[pd.DataFrame] = []
    for definition in definitions:
        experiment, outputs = run_experiment(
            definition,
            demand,
            beds,
            staff,
            planning_availability,
            planning_availability,
            metadata,
            config,
            methods=methods,
            profile_id=profile_id,
        )
        frame = experiment.metrics.drop(columns="experiment_id")
        frame["absence_rate"] = definition.absence_rate
        frame["demand_multiplier"] = definition.demand_multiplier
        frame["capacity_reduction"] = definition.capacity_reduction
        frame["seed"] = experiment.scenario.seed
        frame["created_at"] = experiment.created_at.isoformat()
        frame["staff_coverage_rate"] = [
            _coverage_rate(outputs[method].staff_coverage) if method in outputs else None
            for method in frame["method_name"]
        ]
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def merge_results(previous: pd.DataFrame | None, new: pd.DataFrame) -> pd.DataFrame:
    """Remplace les cas recalculés et conserve les autres, si l'instance est la même.

    Un cas calculé sur d'autres données (empreinte différente pour le même
    identifiant) est retiré : des résultats d'instances différentes ne se mélangent pas.
    """
    if previous is not None and not previous.empty:
        new_hashes = new.drop_duplicates("scenario_id").set_index("scenario_id")["scenario_input_hash"]
        expected = previous["scenario_id"].map(new_hashes)
        previous = previous[expected.isna() | (previous["scenario_input_hash"] == expected)]
        replaced = pd.MultiIndex.from_frame(previous[KEY]).isin(pd.MultiIndex.from_frame(new[KEY]))
        kept = previous[~replaced]
        new = new if kept.empty else pd.concat([kept, new], ignore_index=True)
    rank = {name: index for index, name in enumerate(METHODS)}
    ordered = new.assign(_rank=new["method_name"].map(rank)).sort_values(["profile_id", "scenario_id", "_rank"])
    return ordered.drop(columns="_rank").reset_index(drop=True)


def _coverage_rate(coverage: pd.DataFrame) -> float | None:
    if coverage.empty or not int(coverage["target_staff"].sum()):
        return None
    return 1 - int(coverage["target_shortage"].sum()) / int(coverage["target_staff"].sum())


def main() -> None:
    """Calcule la grille, entière par défaut, et fusionne avec les résultats existants."""
    parser = argparse.ArgumentParser(description="Calcule l'analyse de sensibilité (80 cas).")
    parser.add_argument("--config", type=Path, default=Path("configs/hospital.json"))
    parser.add_argument("--profiles-file", type=Path, default=Path("configs/profiles.json"))
    parser.add_argument("--profile", default=DEFAULT_PROFILE_ID)
    parser.add_argument("--instance", type=Path, default=Path("results/operational_instances/S0"))
    parser.add_argument("--staff", type=Path, default=Path("data/synthetic/staff.csv"))
    parser.add_argument("--availability", type=Path, default=Path("data/synthetic/staff_availability.csv"))
    parser.add_argument("--output", type=Path, default=Path("results/experiments"))
    parser.add_argument("--methods", nargs="+", choices=METHODS, default=["naive", "greedy"])
    parser.add_argument("--cases", nargs="+", help="Identifiants SENS_… ; toute la grille par défaut.")
    parser.add_argument("--time-limit", type=int)
    parser.add_argument("--workers", type=int)
    arguments = parser.parse_args()
    config = with_solver_settings(load_hospital_config(arguments.config), arguments.time_limit, arguments.workers)
    profiles = {profile.profile_id: profile for profile in load_profiles(arguments.profiles_file, config)}
    if arguments.profile not in profiles:
        parser.error(f"profil inconnu : {arguments.profile}")
    definitions = sensitivity_definitions()
    if arguments.cases:
        unknown = sorted(set(arguments.cases) - {item.scenario_id for item in definitions})
        if unknown:
            parser.error(f"cas inconnus : {unknown}")
        definitions = [item for item in definitions if item.scenario_id in set(arguments.cases)]
    demand = pd.read_csv(arguments.instance / "demand_requirements.csv", parse_dates=["date"])
    beds = pd.read_csv(arguments.instance / "bed_requirements.csv", parse_dates=["date"])
    staff = pd.read_csv(arguments.staff)
    availability = pd.read_csv(arguments.availability, parse_dates=["date"])
    metadata = json.loads((arguments.instance / "operational_instance.json").read_text(encoding="utf-8"))
    planning = project_planning_availability(staff, availability, demand["date"], config)
    started = perf_counter()
    results = run_sensitivity(
        definitions,
        demand,
        beds,
        staff,
        planning,
        metadata,
        with_profile(config, profiles[arguments.profile]),
        methods=tuple(arguments.methods),
        profile_id=arguments.profile,
    )
    path = arguments.output / RESULTS_FILE
    arguments.output.mkdir(parents=True, exist_ok=True)
    merged = merge_results(pd.read_csv(path) if path.is_file() else None, results)
    merged.to_csv(path, index=False)
    print(
        f"{len(definitions)} cas x {len(arguments.methods)} méthode(s) en {perf_counter() - started:.0f} s ; "
        f"{len(merged)} lignes au total"
    )


if __name__ == "__main__":
    main()
