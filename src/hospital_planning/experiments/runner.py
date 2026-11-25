"""Exécution et stockage d'expériences comparables, y compris la sensibilité."""

import argparse
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import pandas as pd

from hospital_planning.config.loader import load_hospital_config, with_solver_settings
from hospital_planning.domain.contracts import HospitalConfig, MethodResult
from hospital_planning.domain.enums import MethodStatus
from hospital_planning.experiments.scenarios import (
    ScenarioDefinition,
    ScenarioInstance,
    apply_scenario,
    load_scenarios,
    sensitivity_definitions,
)
from hospital_planning.optimization.exact import ExactResult, run_cp_sat, run_milp, save_exact_result
from hospital_planning.optimization.greedy import GreedyResult, run_greedy, save_greedy_result


@dataclass(frozen=True)
class ExperimentResult:
    """Résultats d'une même instance scénario exécutée par plusieurs méthodes."""

    experiment_id: str
    scenario: ScenarioInstance
    method_results: tuple[MethodResult, ...]
    metrics: pd.DataFrame
    created_at: datetime


def run_experiment(
    definition: ScenarioDefinition,
    demand_requirements: pd.DataFrame,
    bed_requirements: pd.DataFrame,
    staff: pd.DataFrame,
    historical_availability: pd.DataFrame,
    baseline_planning_availability: pd.DataFrame,
    instance_metadata: dict[str, object],
    config: HospitalConfig,
    *,
    methods: tuple[str, ...] = ("greedy", "milp", "cp_sat"),
    seed: int | None = None,
) -> tuple[ExperimentResult, dict[str, GreedyResult | ExactResult]]:
    """Exécute chaque méthode sur une unique copie scénario identifiée."""
    if not methods or set(methods) - {"greedy", "milp", "cp_sat"}:
        raise ValueError("methods doit contenir une ou plusieurs méthodes connues.")
    scenario_seed = config.random_seed if seed is None else seed
    scenario = apply_scenario(
        definition,
        demand_requirements,
        bed_requirements,
        baseline_planning_availability,
        config,
        seed=scenario_seed,
    )
    metadata = _scenario_metadata(instance_metadata, scenario)
    results: dict[str, GreedyResult | ExactResult] = {}
    method_results: list[MethodResult] = []
    runners = {
        "greedy": run_greedy,
        "milp": run_milp,
        "cp_sat": run_cp_sat,
    }
    for method_name in methods:
        try:
            output = runners[method_name](
                scenario.demand_requirements,
                scenario.bed_requirements,
                staff,
                historical_availability,
                metadata,
                config,
                scenario.planning_availability,
            )
        except Exception as error:  # Les autres méthodes doivent rester exploitables.
            method_results.append(_error_result(method_name, metadata, config, error))
        else:
            results[method_name] = output
            method_results.append(output.method_result)
    experiment_id = f"experiment-{definition.scenario_id.lower()}-{scenario.input_hash[:12]}"
    result_tuple = tuple(method_results)
    metrics = _metrics_frame(experiment_id, definition, scenario, result_tuple)
    return ExperimentResult(experiment_id, scenario, result_tuple, metrics, datetime.now(UTC)), results


def save_experiment(
    experiment: ExperimentResult,
    outputs: dict[str, GreedyResult | ExactResult],
    output_directory: Path,
) -> dict[str, Path]:
    """Conserve les entrées scénario, sorties par méthode et KPI tabulaires."""
    output_directory.mkdir(parents=True, exist_ok=True)
    scenario_directory = output_directory / "scenario_inputs"
    scenario_directory.mkdir(exist_ok=True)
    paths = {
        "demand": scenario_directory / "demand_requirements.csv",
        "beds": scenario_directory / "bed_requirements.csv",
        "availability": scenario_directory / "planning_availability.csv",
        "metrics": output_directory / "metrics.csv",
        "metadata": output_directory / "experiment.json",
    }
    experiment.scenario.demand_requirements.to_csv(paths["demand"], index=False)
    experiment.scenario.bed_requirements.to_csv(paths["beds"], index=False)
    experiment.scenario.planning_availability.to_csv(paths["availability"], index=False)
    previous = _previous_metadata(paths["metadata"], experiment.scenario.input_hash)
    metrics = experiment.metrics
    if previous is not None and paths["metrics"].is_file():
        # Une méthode lancée seule (ex. depuis le dashboard) ne doit pas effacer
        # les méthodes déjà exécutées sur la même instance : on fusionne.
        old_metrics = pd.read_csv(paths["metrics"])
        old_metrics = old_metrics[~old_metrics["method_name"].isin(metrics["method_name"])]
        metrics = pd.concat([old_metrics, metrics], ignore_index=True)
        metrics["_order"] = metrics["method_name"].map({"greedy": 0, "milp": 1, "cp_sat": 2}).fillna(9)
        metrics = metrics.sort_values("_order").drop(columns="_order").reset_index(drop=True)
    metrics.to_csv(paths["metrics"], index=False)
    method_paths: dict[str, dict[str, Path]] = {}
    for method_name, output in outputs.items():
        method_directory = output_directory / method_name
        method_paths[method_name] = (
            save_greedy_result(output, method_directory)
            if method_name == "greedy"
            else save_exact_result(output, method_directory)
        )
    metadata = {
        "experiment_id": experiment.experiment_id,
        "created_at": experiment.created_at.isoformat(),
        "scenario": experiment.scenario.definition.model_dump(),
        "seed": experiment.scenario.seed,
        "scenario_input_hash": experiment.scenario.input_hash,
        "methods": list(metrics["method_name"]),
        "method_artifacts": {
            **(previous or {}).get("method_artifacts", {}),
            **{
                # Chemins relatifs au dossier de l'expérience, en notation POSIX :
                # le dépôt reste lisible sous Windows, Linux et macOS.
                method_name: {name: path.relative_to(output_directory).as_posix() for name, path in paths_.items()}
                for method_name, paths_ in method_paths.items()
            },
        },
    }
    paths["metadata"].write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return paths


def _previous_metadata(metadata_path: Path, input_hash: str) -> dict[str, object] | None:
    """Relit une expérience existante seulement si elle porte sur la même instance."""
    if not metadata_path.is_file():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if metadata.get("scenario_input_hash") != input_hash:
        return None
    # Normalise les anciens chemins (absolus ou « results\\... ») en « <méthode>/<fichier> ».
    metadata["method_artifacts"] = {
        name: {key: f"{name}/{PurePosixPath(str(value).replace(chr(92), '/')).name}" for key, value in paths.items()}
        for name, paths in metadata.get("method_artifacts", {}).items()
    }
    return metadata


def sensitivity_manifest(config: HospitalConfig, *, seed: int | None = None) -> pd.DataFrame:
    """Construit le manifeste des 80 expériences sans déclencher de solveur."""
    scenario_seed = config.random_seed if seed is None else seed
    return pd.DataFrame(
        [
            {
                "scenario_id": definition.scenario_id,
                "absence_rate": definition.absence_rate,
                "demand_multiplier": definition.demand_multiplier,
                "capacity_reduction": definition.capacity_reduction,
                "seed": scenario_seed,
                "exact_calls": 2,
            }
            for definition in sensitivity_definitions()
        ]
    )


def _scenario_metadata(metadata: dict[str, object], scenario: ScenarioInstance) -> dict[str, object]:
    scenario_metadata = deepcopy(metadata)
    instance = scenario_metadata["instance"]
    assert isinstance(instance, dict)
    instance["scenario_id"] = scenario.definition.scenario_id
    instance["instance_id"] = f"{instance['instance_id']}-{scenario.definition.scenario_id.lower()}"
    instance["input_hash"] = scenario.input_hash
    return scenario_metadata


def _error_result(
    method_name: str,
    metadata: dict[str, object],
    config: HospitalConfig,
    error: Exception,
) -> MethodResult:
    instance = metadata["instance"]
    assert isinstance(instance, dict)
    return MethodResult(
        experiment_id=f"{method_name}-{instance['instance_id']}",
        scenario_id=str(instance["scenario_id"]),
        method_name=method_name,
        status=MethodStatus.ERROR,
        runtime_seconds=0.0,
        seed=config.random_seed,
        config_hash=str(instance["forecast"]["config_hash"]),
        native_status="EXCEPTION",
        error_message=str(error),
    )


def _metrics_frame(
    experiment_id: str,
    definition: ScenarioDefinition,
    scenario: ScenarioInstance,
    results: tuple[MethodResult, ...],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for result in results:
        components = result.objective_components
        validation = result.validation
        rows.append(
            {
                "experiment_id": experiment_id,
                "scenario_id": definition.scenario_id,
                "scenario_input_hash": scenario.input_hash,
                "method_name": result.method_name,
                "status": result.status.value,
                "native_status": result.native_status,
                "runtime_seconds": result.runtime_seconds,
                "objective_value": result.objective_value,
                "best_bound": result.best_bound,
                "optimality_gap": result.optimality_gap,
                "solver_time_limit_seconds": result.solver_time_limit_seconds,
                "solver_num_workers": result.solver_num_workers,
                "unmet_demand_patient_days": result.unmet_demand_patient_days,
                "rejected_admissions": result.rejected_admissions,
                "staff_shortage_total": result.staff_shortage_total,
                "coverage_rate": result.coverage_rate,
                "beds_opened_total": result.beds_opened_total,
                "fairness_metric": result.fairness_metric,
                "hard_constraint_violations": validation.hard_constraint_violations if validation else None,
                "validation_passed": validation.valid if validation else None,
                "opened_bed_cost": components.opened_bed_cost if components else None,
                "unmet_patient_day_cost": components.unmet_patient_day_cost if components else None,
                "staff_target_shortage_cost": components.staff_target_shortage_cost if components else None,
                "workload_imbalance_cost": components.workload_imbalance_cost if components else None,
            }
        )
    return pd.DataFrame.from_records(rows)


def main() -> None:
    """Exécute les scénarios déclarés, sans lancer la grille exhaustive par défaut."""
    parser = argparse.ArgumentParser(description="Exécute les expériences de scénarios hospitaliers.")
    parser.add_argument("--config", type=Path, default=Path("configs/hospital.json"))
    parser.add_argument("--scenarios", type=Path, default=Path("configs/scenarios.json"))
    parser.add_argument("--instance", type=Path, default=Path("results/operational_instances/S0"))
    parser.add_argument("--staff", type=Path, default=Path("data/synthetic/staff.csv"))
    parser.add_argument("--availability", type=Path, default=Path("data/synthetic/staff_availability.csv"))
    parser.add_argument("--output", type=Path, default=Path("results/experiments"))
    parser.add_argument("--methods", nargs="+", choices=("greedy", "milp", "cp_sat"), default=["greedy"])
    parser.add_argument("--time-limit", type=int, help="Limite en secondes par solveur exact (défaut : configuration).")
    parser.add_argument("--workers", type=int, help="Threads par solveur exact (défaut : configuration).")
    parser.add_argument("--sensitivity-manifest", action="store_true")
    arguments = parser.parse_args()
    config = with_solver_settings(load_hospital_config(arguments.config), arguments.time_limit, arguments.workers)
    if arguments.sensitivity_manifest:
        arguments.output.mkdir(parents=True, exist_ok=True)
        sensitivity_manifest(config).to_csv(arguments.output / "sensitivity_manifest.csv", index=False)
        return
    instance = arguments.instance
    demand = pd.read_csv(instance / "demand_requirements.csv", parse_dates=["date"])
    beds = pd.read_csv(instance / "bed_requirements.csv", parse_dates=["date"])
    staff = pd.read_csv(arguments.staff)
    availability = pd.read_csv(arguments.availability, parse_dates=["date"])
    metadata = json.loads((instance / "operational_instance.json").read_text(encoding="utf-8"))
    from hospital_planning.optimization.availability import project_planning_availability

    planning_availability = project_planning_availability(staff, availability, demand["date"], config)
    all_metrics: list[pd.DataFrame] = []
    for definition in load_scenarios(arguments.scenarios, config):
        experiment, outputs = run_experiment(
            definition,
            demand,
            beds,
            staff,
            availability,
            planning_availability,
            metadata,
            config,
            methods=tuple(arguments.methods),
        )
        save_experiment(experiment, outputs, arguments.output / experiment.experiment_id)
        all_metrics.append(experiment.metrics)
    pd.concat(all_metrics, ignore_index=True).to_csv(arguments.output / "scenario_summary.csv", index=False)


if __name__ == "__main__":
    main()
