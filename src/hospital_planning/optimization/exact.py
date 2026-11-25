"""Solveurs MILP/CBC et CP-SAT équivalents pour l'instance canonique."""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

import pandas as pd

from hospital_planning.config.loader import load_hospital_config
from hospital_planning.domain.contracts import DEFAULT_PROFILE_ID, HospitalConfig, MethodResult
from hospital_planning.domain.enums import MethodStatus
from hospital_planning.optimization.availability import project_planning_availability
from hospital_planning.optimization.greedy import GreedyResult, run_greedy
from hospital_planning.optimization.objective import (
    calculate_objective_components,
    calculate_workload_range,
    sum_by_service,
)
from hospital_planning.optimization.validator import validate_solution


@dataclass(frozen=True)
class ExactResult:
    """Sorties normalisées d'un solveur exact."""

    method_result: MethodResult
    bed_allocations: pd.DataFrame
    staff_assignments: pd.DataFrame
    staff_coverage: pd.DataFrame
    planning_availability: pd.DataFrame


@dataclass(frozen=True)
class ExactInputs:
    """Vue indexée, immuable et commune des entrées d'optimisation."""

    dates: list[pd.Timestamp]
    services: list[str]
    shifts: list[str]
    roles: list[str]
    staff_ids: list[str]
    requested: dict[tuple[str, int], int]
    initial_occupancy: dict[str, int]
    occupancy_required: dict[tuple[str, int], int]
    capacity: dict[tuple[str, int], int]
    staff_role: dict[str, str]
    staff_max_shifts: dict[str, int]
    qualified_services: dict[str, set[str]]
    available: set[tuple[str, int, str]]


def run_milp(
    demand_requirements: pd.DataFrame,
    bed_requirements: pd.DataFrame,
    staff: pd.DataFrame,
    historical_availability: pd.DataFrame,
    instance_metadata: dict[str, object],
    config: HospitalConfig,
    planning_availability: pd.DataFrame | None = None,
) -> ExactResult:
    """Résout la formulation canonique avec PuLP/CBC."""
    import pulp

    started_at = datetime.now(UTC)
    started_perf = perf_counter()
    inputs, planning_availability = _build_inputs(
        demand_requirements, bed_requirements, staff, historical_availability, config, planning_availability
    )
    model = pulp.LpProblem("hospital_planning_milp", pulp.LpMinimize)
    variables = _create_pulp_variables(model, inputs, config)
    _add_pulp_constraints(model, variables, inputs, config)
    objective = _pulp_objective(variables, inputs, config)
    model += objective
    # Pas de solution initiale Greedy : CBC restait bloqué dessus et rendait
    # exactement la baseline, ce qui rendait la comparaison sans objet.
    stats, log, solver_seed = _solve_with_cbc(model, config)
    native_status = stats.status_str
    if not stats.has_solution:
        return _empty_result("milp", native_status, perf_counter() - started_perf, instance_metadata, config)
    proven = native_status == "Optimal" and _cbc_search_completed(log)
    if native_status == "Optimal" and not proven:
        native_status = "OptimalNotProven"
    objective_value = float(pulp.value(objective))
    if proven:
        best_bound = objective_value
    else:
        # CBC raisonne sans le terme constant de l'objectif : on le réintègre.
        cbc_bound = _cbc_best_bound(log)
        best_bound = None if cbc_bound is None else cbc_bound + float(objective.constant)
    bed_allocations, assignments = _extract_pulp_solution(variables, inputs, config)
    return _finalize_result(
        "milp",
        MethodStatus.OPTIMAL if proven else MethodStatus.FEASIBLE,
        native_status,
        perf_counter() - started_perf,
        started_at,
        bed_allocations,
        assignments,
        planning_availability,
        staff,
        instance_metadata,
        config,
        best_bound,
        bed_requirements,
        solver_seed,
    )


def run_cp_sat(
    demand_requirements: pd.DataFrame,
    bed_requirements: pd.DataFrame,
    staff: pd.DataFrame,
    historical_availability: pd.DataFrame,
    instance_metadata: dict[str, object],
    config: HospitalConfig,
    planning_availability: pd.DataFrame | None = None,
) -> ExactResult:
    """Résout la formulation canonique avec OR-Tools CP-SAT."""
    from ortools.sat.python import cp_model

    started_at = datetime.now(UTC)
    started_perf = perf_counter()
    inputs, planning_availability = _build_inputs(
        demand_requirements, bed_requirements, staff, historical_availability, config, planning_availability
    )
    greedy_hint = run_greedy(
        demand_requirements,
        bed_requirements,
        staff,
        historical_availability,
        instance_metadata,
        config,
        planning_availability,
    )
    model = cp_model.CpModel()
    variables = _create_cp_sat_variables(model, inputs, config)
    _add_cp_sat_constraints(model, variables, inputs, config)
    _set_cp_sat_hint(model, variables, inputs, greedy_hint, staff)
    model.minimize(_cp_sat_objective(variables, inputs, config))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = config.planning_policy.solver_time_limit_seconds
    solver.parameters.num_search_workers = config.planning_policy.solver_num_workers
    solver.parameters.random_seed = config.random_seed
    status_code = solver.solve(model)
    native_status = solver.status_name(status_code)
    if status_code not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
        return _empty_result("cp_sat", native_status, perf_counter() - started_perf, instance_metadata, config)
    status = MethodStatus.OPTIMAL if status_code == cp_model.OPTIMAL else MethodStatus.FEASIBLE
    bed_allocations, assignments = _extract_cp_sat_solution(solver, variables, inputs, config)
    return _finalize_result(
        "cp_sat",
        status,
        native_status,
        perf_counter() - started_perf,
        started_at,
        bed_allocations,
        assignments,
        planning_availability,
        staff,
        instance_metadata,
        config,
        float(solver.best_objective_bound),
        bed_requirements,
        config.random_seed,
    )


def save_exact_result(result: ExactResult, output_directory: Path) -> dict[str, Path]:
    """Enregistre les mêmes artefacts que Greedy pour une comparaison équitable."""
    output_directory.mkdir(parents=True, exist_ok=True)
    tables = {
        "bed_allocations": result.bed_allocations,
        "staff_assignments": result.staff_assignments,
        "staff_coverage": result.staff_coverage,
        "planning_availability": result.planning_availability,
    }
    paths: dict[str, Path] = {}
    for name, table in tables.items():
        path = output_directory / f"{name}.csv"
        table.to_csv(path, index=False)
        paths[name] = path
    result_path = output_directory / "method_result.json"
    serialized = result.method_result.model_copy(
        update={
            # Relatifs au dossier de ce method_result.json : portables et sans chemin personnel.
            "assignments_artifact_path": paths["staff_assignments"].relative_to(output_directory).as_posix(),
            "allocations_artifact_path": paths["bed_allocations"].relative_to(output_directory).as_posix(),
        }
    )
    result_path.write_text(serialized.model_dump_json(indent=2), encoding="utf-8")
    paths["method_result"] = result_path
    return paths


def _build_inputs(
    demand_requirements: pd.DataFrame,
    bed_requirements: pd.DataFrame,
    staff: pd.DataFrame,
    historical_availability: pd.DataFrame,
    config: HospitalConfig,
    planning_availability: pd.DataFrame | None = None,
) -> tuple[ExactInputs, pd.DataFrame]:
    demand = demand_requirements.copy()
    beds = bed_requirements.copy()
    demand["date"] = pd.to_datetime(demand["date"])
    beds["date"] = pd.to_datetime(beds["date"])
    dates = sorted(pd.Timestamp(value) for value in demand["date"].unique())
    services = sorted(demand["service"].unique())
    if planning_availability is None:
        planning_availability = project_planning_availability(staff, historical_availability, demand["date"], config)
    else:
        planning_availability = planning_availability.copy()
        planning_availability["date"] = pd.to_datetime(planning_availability["date"])
    date_index = {date: index for index, date in enumerate(dates)}
    demand_by_key = demand.set_index(["service", "date"])["requested_admissions"]
    beds_by_key = beds.set_index(["service", "date"])
    active_staff = staff[staff["active"]].copy()
    available = {
        (row.staff_id, date_index[pd.Timestamp(row.date)], row.shift)
        for row in planning_availability[planning_availability["available"]].itertuples(index=False)
    }
    return (
        ExactInputs(
            dates=dates,
            services=services,
            shifts=[shift.code for shift in config.shifts],
            roles=list(config.roles),
            staff_ids=sorted(active_staff["staff_id"].tolist()),
            requested={
                (service, index): int(demand_by_key[(service, date)])
                for service in services
                for index, date in enumerate(dates)
            },
            initial_occupancy={
                service: int(beds_by_key.loc[(service, dates[0]), "occupancy_start"]) for service in services
            },
            occupancy_required={
                (service, index): int(beds_by_key.loc[(service, date), "occupancy_required"])
                for service in services
                for index, date in enumerate(dates)
            },
            capacity={
                (service, index): int(beds_by_key.loc[(service, date), "capacity_available"])
                for service in services
                for index, date in enumerate(dates)
            },
            staff_role=active_staff.set_index("staff_id")["role"].to_dict(),
            staff_max_shifts=active_staff.set_index("staff_id")["max_shifts"].astype(int).to_dict(),
            qualified_services={
                row.staff_id: set(json.loads(row.qualified_services)) for row in active_staff.itertuples(index=False)
            },
            available=available,
        ),
        planning_availability,
    )


def _comparable_staff(inputs: ExactInputs, role: str) -> list[str]:
    """Professionnels actifs du rôle, disponibles au moins une fois sur l'horizon."""
    present = {staff_id for staff_id, _, _ in inputs.available}
    return [staff_id for staff_id in inputs.staff_ids if inputs.staff_role[staff_id] == role and staff_id in present]


def _eligible_keys(inputs: ExactInputs) -> list[tuple[str, int, str, str]]:
    return [
        (staff_id, date_index, service, shift)
        for staff_id in inputs.staff_ids
        for date_index in range(len(inputs.dates))
        for service in inputs.services
        for shift in inputs.shifts
        if (staff_id, date_index, shift) in inputs.available and service in inputs.qualified_services[staff_id]
    ]


def _hint_values(
    variables: dict[str, dict[object, object]],
    inputs: ExactInputs,
    greedy_hint: GreedyResult,
    staff: pd.DataFrame,
) -> dict[object, int]:
    """Construit une solution initiale valide depuis la baseline Greedy."""
    date_index = {date: index for index, date in enumerate(inputs.dates)}
    beds = greedy_hint.bed_allocations.set_index(["service", "date"])
    assignments = {
        (row.staff_id, date_index[pd.Timestamp(row.date)], row.service, row.shift)
        for row in greedy_hint.staff_assignments.itertuples(index=False)
    }
    coverage = greedy_hint.staff_coverage.set_index(["service", "date", "shift", "role"])
    values: dict[object, int] = {}
    for service in inputs.services:
        for date_index_value, date in enumerate(inputs.dates):
            row = beds.loc[(service, date)]
            values[variables["accepted"][(service, date_index_value)]] = int(row["accepted_admissions"])
            values[variables["occupancy"][(service, date_index_value)]] = int(row["occupancy_end"])
            values[variables["opened"][(service, date_index_value)]] = int(row["opened_beds"])
            values[variables["open"][(service, date_index_value)]] = int(row["opened_beds"] > 0)
            for shift in inputs.shifts:
                for role in inputs.roles:
                    values[variables["shortage"][(service, date_index_value, shift, role)]] = int(
                        coverage.loc[(service, date, shift, role), "target_shortage"]
                    )
    for key, variable in variables["assignment"].items():
        values[variable] = int(key in assignments)
    active_staff = staff.loc[staff["active"], ["staff_id", "role"]].copy()
    assignment_counts = greedy_hint.staff_assignments.groupby("staff_id").size().rename("assigned_shifts")
    active_staff = active_staff.join(assignment_counts, on="staff_id").fillna({"assigned_shifts": 0})
    for role in inputs.roles:
        role_loads = active_staff.loc[active_staff["staff_id"].isin(_comparable_staff(inputs, role)), "assigned_shifts"]
        values[variables["load_min"][role]] = int(role_loads.min()) if len(role_loads) else 0
        values[variables["load_max"][role]] = int(role_loads.max()) if len(role_loads) else 0
    return values


def _set_cp_sat_hint(
    model: object,
    variables: dict[str, dict[object, object]],
    inputs: ExactInputs,
    greedy_hint: GreedyResult,
    staff: pd.DataFrame,
) -> None:
    for variable, value in _hint_values(variables, inputs, greedy_hint, staff).items():
        model.add_hint(variable, value)


_CBC_NUMBER = r"(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
_CBC_INCOMPLETE_MARKERS = (
    "Exiting on maximum",
    "Stopped on",
    "Partial search",
    "LP relaxation is infeasible or too expensive",
)


def _solve_with_cbc(model: object, config: HospitalConfig, attempts: int = 4) -> tuple[object, str, int]:
    """Lance CBC et retourne ses statistiques, son journal et la graine utilisée.

    Certaines instances déclenchent une assertion interne de CBC (CLP), selon sa
    graine. Le processus s'arrête alors sans solution : on relance avec la graine
    suivante, dans le temps restant, pour ne jamais dépasser le budget configuré.
    """
    import pulp

    deadline = perf_counter() + config.planning_policy.solver_time_limit_seconds
    for attempt in range(attempts):
        solver_seed = config.random_seed + attempt
        with TemporaryDirectory(prefix="hospital-cbc-") as log_directory:
            log_path = Path(log_directory) / "cbc.log"
            try:
                stats = model.solve(
                    pulp.COIN_CMD(
                        msg=False,
                        timeLimit=max(int(deadline - perf_counter() + 0.5), 1),
                        threads=config.planning_policy.solver_num_workers,
                        randomSeed=solver_seed,
                        logPath=str(log_path),
                    )
                )
            except pulp.PulpSolverError:
                if attempt == attempts - 1 or perf_counter() >= deadline:
                    raise
                continue
            return stats, log_path.read_text(encoding="utf-8", errors="replace"), solver_seed
    raise AssertionError("Aucune tentative CBC exécutée.")


def _cbc_search_completed(log: str) -> bool:
    """Indique si CBC a réellement terminé sa recherche.

    Interrompu pendant le nœud racine, CBC peut annoncer « Optimal solution found »
    pour un simple incumbent : ce statut seul ne prouve donc pas l'optimalité.
    """
    return bool(log) and not any(marker in log for marker in _CBC_INCOMPLETE_MARKERS)


def _cbc_best_bound(log: str) -> float | None:
    """Extrait la meilleure borne du journal CBC, sans le terme constant.

    « best possible » est plus précis que « Lower bound », arrondi à six chiffres.
    """
    for pattern in (rf"best possible {_CBC_NUMBER}", rf"Lower bound:\s+{_CBC_NUMBER}"):
        values = [float(value) for value in re.findall(pattern, log)]
        values = [value for value in values if abs(value) < 1e100]
        if values:
            return values[-1]
    return None


def _relative_gap(objective_value: float, best_bound: float | None) -> float | None:
    """Écart relatif (solution - borne) / solution, ou None sans borne exploitable."""
    if best_bound is None:
        return None
    if objective_value == 0:
        return 0.0 if best_bound >= 0 else None
    return max((objective_value - best_bound) / objective_value, 0.0)


def _create_pulp_variables(
    model: object, inputs: ExactInputs, config: HospitalConfig
) -> dict[str, dict[object, object]]:
    variables: dict[str, dict[object, object]] = {
        name: {}
        for name in ("accepted", "occupancy", "opened", "open", "shortage", "assignment", "load_min", "load_max")
    }
    for service in inputs.services:
        for date_index in range(len(inputs.dates)):
            suffix = f"{service}_{date_index}"
            variables["accepted"][(service, date_index)] = model.add_variable(
                f"accepted_{suffix}", 0, inputs.requested[(service, date_index)], "Integer"
            )
            variables["occupancy"][(service, date_index)] = model.add_variable(
                f"occupancy_{suffix}", 0, inputs.occupancy_required[(service, date_index)], "Integer"
            )
            variables["opened"][(service, date_index)] = model.add_variable(
                f"opened_{suffix}", 0, inputs.capacity[(service, date_index)], "Integer"
            )
            variables["open"][(service, date_index)] = model.add_variable(f"open_{suffix}", 0, 1, "Binary")
            for shift in inputs.shifts:
                for role in inputs.roles:
                    variables["shortage"][(service, date_index, shift, role)] = model.add_variable(
                        f"shortage_{suffix}_{shift}_{role}", 0, None, "Integer"
                    )
    for key in _eligible_keys(inputs):
        variables["assignment"][key] = model.add_variable("x_" + "_".join(map(str, key)), 0, 1, "Binary")
    for role in inputs.roles:
        variables["load_min"][role] = model.add_variable(f"load_min_{role}", 0, None, "Integer")
        variables["load_max"][role] = model.add_variable(f"load_max_{role}", 0, None, "Integer")
    return variables


def _pulp_sum(values: list[object]) -> object:
    import pulp

    return pulp.lpSum(values)


def _add_pulp_constraints(
    model: object, variables: dict[str, dict[object, object]], inputs: ExactInputs, config: HospitalConfig
) -> None:
    assignment = variables["assignment"]
    for service in inputs.services:
        length_of_stay = config.services[service].length_of_stay_days
        for date_index in range(len(inputs.dates)):
            accepted = variables["accepted"][(service, date_index)]
            occupancy = variables["occupancy"][(service, date_index)]
            opened = variables["opened"][(service, date_index)]
            open_indicator = variables["open"][(service, date_index)]
            cohort_indices = range(max(0, date_index - length_of_stay + 1), date_index + 1)
            model += (
                occupancy
                + _pulp_sum(
                    [inputs.requested[(service, day)] - variables["accepted"][(service, day)] for day in cohort_indices]
                )
                == inputs.occupancy_required[(service, date_index)]
            )
            model += occupancy <= opened
            model += opened <= inputs.capacity[(service, date_index)] * open_indicator
            model += opened >= open_indicator
            if config.planning_policy.mode.value == "strict":
                model += accepted == inputs.requested[(service, date_index)]
            for shift in inputs.shifts:
                for role in inputs.roles:
                    staffed = _pulp_sum(
                        [
                            assignment[key]
                            for key in assignment
                            if key[1:] == (date_index, service, shift) and inputs.staff_role[key[0]] == role
                        ]
                    )
                    minimum = config.synthetic_data.minimum_staff_by_role[role]
                    ratio = config.synthetic_data.staff_per_ten_beds[role]
                    shortage = variables["shortage"][(service, date_index, shift, role)]
                    model += staffed >= minimum * open_indicator
                    model += 10 * (staffed + shortage) >= ratio * opened
                    if config.planning_policy.mode.value == "strict":
                        model += shortage == 0
    _add_pulp_staff_constraints(model, variables, inputs, config)


def _add_pulp_staff_constraints(
    model: object, variables: dict[str, dict[object, object]], inputs: ExactInputs, config: HospitalConfig
) -> None:
    assignment = variables["assignment"]
    for staff_id in inputs.staff_ids:
        staff_keys = [key for key in assignment if key[0] == staff_id]
        model += _pulp_sum([assignment[key] for key in staff_keys]) <= inputs.staff_max_shifts[staff_id]
        for date_index in range(len(inputs.dates)):
            day_keys = [key for key in staff_keys if key[1] == date_index]
            model += _pulp_sum([assignment[key] for key in day_keys]) <= 1
        for date_index in range(len(inputs.dates) - 1):
            for shift in inputs.shifts:
                for next_shift in inputs.shifts:
                    if _insufficient_rest(
                        inputs.dates[date_index], shift, inputs.dates[date_index + 1], next_shift, config
                    ):
                        current = [assignment[key] for key in staff_keys if key[1] == date_index and key[3] == shift]
                        following = [
                            assignment[key] for key in staff_keys if key[1] == date_index + 1 and key[3] == next_shift
                        ]
                        model += _pulp_sum(current + following) <= 1
        for start in range(len(inputs.dates) - config.planning_policy.max_consecutive_nights):
            nights = [
                assignment[key]
                for key in staff_keys
                if key[3] == "NIGHT" and start <= key[1] < start + config.planning_policy.max_consecutive_nights + 1
            ]
            model += _pulp_sum(nights) <= config.planning_policy.max_consecutive_nights
    for role in inputs.roles:
        role_staff = _comparable_staff(inputs, role)
        if not role_staff:
            model += variables["load_max"][role] == 0
            model += variables["load_min"][role] == 0
        for staff_id in role_staff:
            load = _pulp_sum([assignment[key] for key in assignment if key[0] == staff_id])
            model += variables["load_min"][role] <= load
            model += variables["load_max"][role] >= load


def _pulp_objective(variables: dict[str, dict[object, object]], inputs: ExactInputs, config: HospitalConfig) -> object:
    opened = _pulp_sum(list(variables["opened"].values()))
    weights = config.objective_weights
    unmet = _pulp_sum(
        [
            weights.unmet_weight(key[0]) * (inputs.occupancy_required[key] - variables["occupancy"][key])
            for key in variables["occupancy"]
        ]
    )
    rejected = _pulp_sum(
        [
            weights.rejection_weight(key[0]) * (inputs.requested[key] - variables["accepted"][key])
            for key in variables["accepted"]
        ]
    )
    shortage = _pulp_sum(
        [weights.shortage_weight(key[0]) * variable for key, variable in variables["shortage"].items()]
    )
    workload_range = _pulp_sum([variables["load_max"][role] - variables["load_min"][role] for role in inputs.roles])
    return weights.opened_bed * opened + unmet + rejected + shortage + weights.workload_imbalance * workload_range


def _create_cp_sat_variables(
    model: object, inputs: ExactInputs, config: HospitalConfig
) -> dict[str, dict[object, object]]:
    variables: dict[str, dict[object, object]] = {
        name: {}
        for name in ("accepted", "occupancy", "opened", "open", "shortage", "assignment", "load_min", "load_max")
    }
    for service in inputs.services:
        for date_index in range(len(inputs.dates)):
            suffix = f"{service}_{date_index}"
            variables["accepted"][(service, date_index)] = model.new_int_var(
                0, inputs.requested[(service, date_index)], f"accepted_{suffix}"
            )
            variables["occupancy"][(service, date_index)] = model.new_int_var(
                0, inputs.occupancy_required[(service, date_index)], f"occupancy_{suffix}"
            )
            variables["opened"][(service, date_index)] = model.new_int_var(
                0, inputs.capacity[(service, date_index)], f"opened_{suffix}"
            )
            variables["open"][(service, date_index)] = model.new_bool_var(f"open_{suffix}")
            for shift in inputs.shifts:
                for role in inputs.roles:
                    variables["shortage"][(service, date_index, shift, role)] = model.new_int_var(
                        0, inputs.capacity[(service, date_index)], f"shortage_{suffix}_{shift}_{role}"
                    )
    for key in _eligible_keys(inputs):
        variables["assignment"][key] = model.new_bool_var("x_" + "_".join(map(str, key)))
    for role in inputs.roles:
        variables["load_min"][role] = model.new_int_var(0, max(inputs.staff_max_shifts.values()), f"load_min_{role}")
        variables["load_max"][role] = model.new_int_var(0, max(inputs.staff_max_shifts.values()), f"load_max_{role}")
    return variables


def _add_cp_sat_constraints(
    model: object, variables: dict[str, dict[object, object]], inputs: ExactInputs, config: HospitalConfig
) -> None:
    assignment = variables["assignment"]
    for service in inputs.services:
        length_of_stay = config.services[service].length_of_stay_days
        for date_index in range(len(inputs.dates)):
            cohort_indices = range(max(0, date_index - length_of_stay + 1), date_index + 1)
            model.add(
                variables["occupancy"][(service, date_index)]
                + sum(
                    inputs.requested[(service, day)] - variables["accepted"][(service, day)] for day in cohort_indices
                )
                == inputs.occupancy_required[(service, date_index)]
            )
            model.add(variables["occupancy"][(service, date_index)] <= variables["opened"][(service, date_index)])
            model.add(
                variables["opened"][(service, date_index)]
                <= inputs.capacity[(service, date_index)] * variables["open"][(service, date_index)]
            )
            model.add(variables["opened"][(service, date_index)] >= variables["open"][(service, date_index)])
            if config.planning_policy.mode.value == "strict":
                model.add(variables["accepted"][(service, date_index)] == inputs.requested[(service, date_index)])
            for shift in inputs.shifts:
                for role in inputs.roles:
                    staffed = sum(
                        assignment[key]
                        for key in assignment
                        if key[1:] == (date_index, service, shift) and inputs.staff_role[key[0]] == role
                    )
                    minimum = config.synthetic_data.minimum_staff_by_role[role]
                    ratio = config.synthetic_data.staff_per_ten_beds[role]
                    shortage = variables["shortage"][(service, date_index, shift, role)]
                    model.add(staffed >= minimum * variables["open"][(service, date_index)])
                    model.add(10 * (staffed + shortage) >= ratio * variables["opened"][(service, date_index)])
                    if config.planning_policy.mode.value == "strict":
                        model.add(shortage == 0)
    _add_cp_sat_staff_constraints(model, variables, inputs, config)


def _add_cp_sat_staff_constraints(
    model: object, variables: dict[str, dict[object, object]], inputs: ExactInputs, config: HospitalConfig
) -> None:
    assignment = variables["assignment"]
    for staff_id in inputs.staff_ids:
        staff_keys = [key for key in assignment if key[0] == staff_id]
        model.add(sum(assignment[key] for key in staff_keys) <= inputs.staff_max_shifts[staff_id])
        for date_index in range(len(inputs.dates)):
            model.add(sum(assignment[key] for key in staff_keys if key[1] == date_index) <= 1)
        for date_index in range(len(inputs.dates) - 1):
            for shift in inputs.shifts:
                for next_shift in inputs.shifts:
                    if _insufficient_rest(
                        inputs.dates[date_index], shift, inputs.dates[date_index + 1], next_shift, config
                    ):
                        current = [assignment[key] for key in staff_keys if key[1] == date_index and key[3] == shift]
                        following = [
                            assignment[key] for key in staff_keys if key[1] == date_index + 1 and key[3] == next_shift
                        ]
                        model.add(sum(current + following) <= 1)
        for start in range(len(inputs.dates) - config.planning_policy.max_consecutive_nights):
            nights = [
                assignment[key]
                for key in staff_keys
                if key[3] == "NIGHT" and start <= key[1] < start + config.planning_policy.max_consecutive_nights + 1
            ]
            model.add(sum(nights) <= config.planning_policy.max_consecutive_nights)
    for role in inputs.roles:
        role_staff = _comparable_staff(inputs, role)
        if not role_staff:
            model.add(variables["load_max"][role] == 0)
            model.add(variables["load_min"][role] == 0)
        for staff_id in role_staff:
            load = sum(assignment[key] for key in assignment if key[0] == staff_id)
            model.add(variables["load_min"][role] <= load)
            model.add(variables["load_max"][role] >= load)


def _cp_sat_objective(
    variables: dict[str, dict[object, object]], inputs: ExactInputs, config: HospitalConfig
) -> object:
    opened = sum(variables["opened"].values())
    weights = config.objective_weights
    unmet = sum(
        weights.unmet_weight(key[0]) * (inputs.occupancy_required[key] - variables["occupancy"][key])
        for key in variables["occupancy"]
    )
    rejected = sum(
        weights.rejection_weight(key[0]) * (inputs.requested[key] - variables["accepted"][key])
        for key in variables["accepted"]
    )
    shortage = sum(
        weights.shortage_weight(key[0]) * variable for key, variable in variables["shortage"].items()
    )
    workload_range = sum(variables["load_max"][role] - variables["load_min"][role] for role in inputs.roles)
    return weights.opened_bed * opened + unmet + rejected + shortage + weights.workload_imbalance * workload_range


def _extract_pulp_solution(
    variables: dict[str, dict[object, object]], inputs: ExactInputs, config: HospitalConfig
) -> tuple[pd.DataFrame, pd.DataFrame]:
    import pulp

    def value(variable: object) -> int:
        return int(round(float(pulp.value(variable))))

    return _extract_solution(value, variables, inputs, config)


def _extract_cp_sat_solution(
    solver: object, variables: dict[str, dict[object, object]], inputs: ExactInputs, config: HospitalConfig
) -> tuple[pd.DataFrame, pd.DataFrame]:
    return _extract_solution(lambda variable: int(solver.value(variable)), variables, inputs, config)


def _extract_solution(
    value: object, variables: dict[str, dict[object, object]], inputs: ExactInputs, config: HospitalConfig
) -> tuple[pd.DataFrame, pd.DataFrame]:
    records: list[dict[str, object]] = []
    for service in inputs.services:
        # Le premier jour part du recensement initial de l'instance, pas du besoin de fin de journée.
        occupancy_start = inputs.initial_occupancy[service]
        for date_index, date in enumerate(inputs.dates):
            accepted = value(variables["accepted"][(service, date_index)])
            occupancy = value(variables["occupancy"][(service, date_index)])
            discharges = occupancy_start + accepted - occupancy
            records.append(
                {
                    "date": date,
                    "service": service,
                    "occupancy_start": occupancy_start,
                    "expected_discharges": discharges,
                    "requested_admissions": inputs.requested[(service, date_index)],
                    "occupancy_required": inputs.occupancy_required[(service, date_index)],
                    "accepted_admissions": accepted,
                    "rejected_admissions": inputs.requested[(service, date_index)] - accepted,
                    "occupancy_end": occupancy,
                    "opened_beds": value(variables["opened"][(service, date_index)]),
                    "capacity_available": inputs.capacity[(service, date_index)],
                }
            )
            occupancy_start = occupancy
    assignments = [
        {
            "staff_id": staff_id,
            "date": inputs.dates[date_index],
            "service": service,
            "shift": shift,
            "role": inputs.staff_role[staff_id],
        }
        for (staff_id, date_index, service, shift), variable in variables["assignment"].items()
        if value(variable) == 1
    ]
    return (
        pd.DataFrame.from_records(records).sort_values(["date", "service"]).reset_index(drop=True),
        pd.DataFrame.from_records(assignments, columns=["staff_id", "date", "service", "shift", "role"]),
    )


def _finalize_result(
    method_name: str,
    status: MethodStatus,
    native_status: str,
    runtime_seconds: float,
    started_at: datetime,
    bed_allocations: pd.DataFrame,
    assignments: pd.DataFrame,
    planning_availability: pd.DataFrame,
    staff: pd.DataFrame,
    instance_metadata: dict[str, object],
    config: HospitalConfig,
    best_bound: float | None,
    bed_requirements: pd.DataFrame,
    solver_seed: int,
) -> ExactResult:
    del started_at
    report, coverage = validate_solution(
        bed_allocations, assignments, planning_availability, staff, config, bed_requirements
    )
    instance = instance_metadata["instance"]
    return _result_from_artifacts(
        method_name,
        status if report.valid else MethodStatus.INFEASIBLE,
        native_status,
        runtime_seconds,
        bed_allocations,
        assignments,
        coverage,
        report,
        instance,
        staff,
        config,
        planning_availability,
        best_bound,
        solver_seed,
    )


def _result_from_artifacts(
    method_name: str,
    status: MethodStatus,
    native_status: str,
    runtime_seconds: float,
    bed_allocations: pd.DataFrame,
    assignments: pd.DataFrame,
    coverage: pd.DataFrame,
    report: object,
    instance: dict[str, object],
    staff: pd.DataFrame,
    config: HospitalConfig,
    planning_availability: pd.DataFrame,
    best_bound: float | None,
    solver_seed: int,
) -> ExactResult:
    required_occupancy = int(bed_allocations["occupancy_required"].sum())
    supported_occupancy = int(bed_allocations["occupancy_end"].sum())
    unmet_patient_days = required_occupancy - supported_occupancy
    shortage = int(coverage["target_shortage"].sum())
    workload_range = calculate_workload_range(assignments, staff, planning_availability)
    required = sum_by_service(bed_allocations, "occupancy_required")
    supported = sum_by_service(bed_allocations, "occupancy_end")
    components = calculate_objective_components(
        int(bed_allocations["opened_beds"].sum()),
        {service: required[service] - supported[service] for service in required},
        sum_by_service(bed_allocations, "rejected_admissions"),
        sum_by_service(coverage, "target_shortage"),
        workload_range,
        config,
    )
    method_result = MethodResult(
        experiment_id=f"{method_name}-{instance['instance_id']}",
        scenario_id=instance["scenario_id"],
        method_name=method_name,
        profile_id=instance.get("profile_id", DEFAULT_PROFILE_ID),
        status=status,
        runtime_seconds=runtime_seconds,
        objective_value=components.total_cost,
        objective_components=components,
        best_bound=best_bound,
        optimality_gap=_relative_gap(components.total_cost, best_bound),
        solver_seed=solver_seed,
        solver_time_limit_seconds=config.planning_policy.solver_time_limit_seconds,
        solver_num_workers=config.planning_policy.solver_num_workers,
        unmet_demand_patient_days=unmet_patient_days,
        rejected_admissions=int(bed_allocations["rejected_admissions"].sum()),
        staff_shortage_total=shortage,
        coverage_rate=supported_occupancy / required_occupancy if required_occupancy else 1.0,
        beds_opened_total=int(bed_allocations["opened_beds"].sum()),
        fairness_metric=float(workload_range),
        seed=config.random_seed,
        config_hash=instance["forecast"]["config_hash"],
        validation=report,
        native_status=native_status,
    )
    return ExactResult(method_result, bed_allocations, assignments, coverage, planning_availability)


def _empty_result(
    method_name: str,
    native_status: str,
    runtime_seconds: float,
    instance_metadata: dict[str, object],
    config: HospitalConfig,
) -> ExactResult:
    instance = instance_metadata["instance"]
    method_result = MethodResult(
        experiment_id=f"{method_name}-{instance['instance_id']}",
        scenario_id=instance["scenario_id"],
        method_name=method_name,
        profile_id=instance.get("profile_id", DEFAULT_PROFILE_ID),
        status=MethodStatus.INFEASIBLE if "infeasible" in native_status.lower() else MethodStatus.UNKNOWN,
        runtime_seconds=runtime_seconds,
        seed=config.random_seed,
        config_hash=instance["forecast"]["config_hash"],
        native_status=native_status,
        solver_time_limit_seconds=config.planning_policy.solver_time_limit_seconds,
        solver_num_workers=config.planning_policy.solver_num_workers,
    )
    empty_assignments = pd.DataFrame(columns=["staff_id", "date", "service", "shift", "role"])
    empty_beds = pd.DataFrame()
    return ExactResult(method_result, empty_beds, empty_assignments, pd.DataFrame(), pd.DataFrame())


def _insufficient_rest(
    date: pd.Timestamp, shift: str, next_date: pd.Timestamp, next_shift: str, config: HospitalConfig
) -> bool:
    shift_by_code = {item.code: item for item in config.shifts}
    current = shift_by_code[shift]
    following = shift_by_code[next_shift]
    current_start = date.normalize() + timedelta(hours=current.start_hour)
    current_end = current_start + timedelta(hours=current.duration_hours)
    next_start = next_date.normalize() + timedelta(hours=following.start_hour)
    return next_start - current_end < timedelta(hours=config.planning_policy.min_rest_hours)


def main() -> None:
    """Exécute MILP et CP-SAT sur l'instance S0, sans scénario de phase 7."""
    config = load_hospital_config(Path("configs/hospital.json"))
    instance_directory = Path("results/operational_instances/S0")
    demand = pd.read_csv(instance_directory / "demand_requirements.csv", parse_dates=["date"])
    beds = pd.read_csv(instance_directory / "bed_requirements.csv", parse_dates=["date"])
    staff = pd.read_csv("data/synthetic/staff.csv")
    availability = pd.read_csv("data/synthetic/staff_availability.csv", parse_dates=["date"])
    metadata = json.loads((instance_directory / "operational_instance.json").read_text(encoding="utf-8"))
    save_exact_result(
        run_milp(demand, beds, staff, availability, metadata, config), Path("results/allocations/milp/S0")
    )
    save_exact_result(
        run_cp_sat(demand, beds, staff, availability, metadata, config), Path("results/allocations/cp_sat/S0")
    )


if __name__ == "__main__":
    main()
