"""Budget configurable, borne, gap et statut réellement prouvé des solveurs exacts."""

import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from hospital_planning.api.app import get_dashboard_allocation
from hospital_planning.config.loader import with_solver_settings
from hospital_planning.domain.contracts import ExperimentJobRequest, HospitalConfig
from hospital_planning.optimization.exact import _cbc_best_bound, _cbc_search_completed, _relative_gap

TIME_LIMIT_LOG = """
Cbc0010I After 100 nodes, 9 on tree, -1239000 best solution, best possible -1263000.5 (9.1 seconds)
Cbc0020I Exiting on maximum time
Cbc0005I Partial search - best objective -1239164 (best possible -1262452), took 126568 iterations and 3900 nodes
Result - Stopped on time limit
Lower bound:                    -1.26245e+06
"""
# Journal réel de CBC interrompu au nœud racine : « Optimal » y est annoncé à tort.
FALSE_OPTIMAL_LOG = """
Cbc0012I Integer solution of -1218621 found by Reduced search after 0 iterations and 0 nodes (1.12 seconds)
Cbc0006I The LP relaxation is infeasible or too expensive
Cuts at root node changed objective from 1.79769e+308 to -1.79769e+308
Result - Optimal solution found
Objective value:                -1218621
"""
COMPLETED_LOG = """
Cbc0001I Search completed - best objective -10, took 0 iterations and 0 nodes (0.02 seconds)
Result - Optimal solution found
Objective value:                -10
"""


def test_cbc_status_is_optimal_only_when_the_search_is_completed() -> None:
    assert _cbc_search_completed(COMPLETED_LOG)
    assert not _cbc_search_completed(TIME_LIMIT_LOG)
    assert not _cbc_search_completed(FALSE_OPTIMAL_LOG)
    assert not _cbc_search_completed("")


def test_cbc_bound_uses_the_last_precise_value() -> None:
    assert _cbc_best_bound(TIME_LIMIT_LOG) == -1262452
    assert _cbc_best_bound("Lower bound:                    -1.26245e+06") == -1262450
    assert _cbc_best_bound("best possible -1.79769e+308") is None
    assert _cbc_best_bound(FALSE_OPTIMAL_LOG) is None


def test_relative_gap_is_explicit_without_bound() -> None:
    assert _relative_gap(200.0, 150.0) == pytest.approx(0.25)
    assert _relative_gap(200.0, 200.1) == 0.0
    assert _relative_gap(200.0, None) is None
    assert _relative_gap(0.0, 0.0) == 0.0


def test_solver_settings_override_only_the_budget(hospital_config: HospitalConfig) -> None:
    changed = with_solver_settings(hospital_config, time_limit_seconds=5, num_workers=2)

    assert changed.planning_policy.solver_time_limit_seconds == 5
    assert changed.planning_policy.solver_num_workers == 2
    assert changed.objective_weights == hospital_config.objective_weights
    assert with_solver_settings(hospital_config) == hospital_config
    with pytest.raises(ValueError):
        with_solver_settings(hospital_config, time_limit_seconds=0)


def test_job_request_bounds_the_solver_budget() -> None:
    request = ExperimentJobRequest(methods=["milp"], solver_time_limit_seconds=20, solver_num_workers=4)
    assert (request.solver_time_limit_seconds, request.solver_num_workers) == (20, 4)
    for invalid in ({"solver_time_limit_seconds": 0}, {"solver_time_limit_seconds": 601}, {"solver_num_workers": 0}):
        with pytest.raises(ValidationError):
            ExperimentJobRequest(**invalid)


def test_default_budget_keeps_a_scenario_under_two_minutes(hospital_config: HospitalConfig) -> None:
    exact_solvers = 2
    margin_seconds = 20  # construction des modèles, Greedy, validation et écriture
    budget = hospital_config.planning_policy.solver_time_limit_seconds * exact_solvers
    assert budget + margin_seconds <= 120


def test_method_without_solution_is_reported_as_absent(monkeypatch, tmp_path) -> None:
    directory = tmp_path / "experiment-x"
    (directory / "milp").mkdir(parents=True)
    for name in ("bed_allocations.csv", "staff_coverage.csv"):
        (directory / "milp" / name).write_text("\n", encoding="utf-8")
    result = {
        "experiment_id": "milp-x",
        "scenario_id": "S0_BASELINE",
        "method_name": "milp",
        "status": "UNKNOWN",
        "native_status": "TimeLimit",
        "runtime_seconds": 1.0,
        "seed": 42,
        "config_hash": "hash",
    }
    (directory / "milp" / "method_result.json").write_text(json.dumps(result), encoding="utf-8")
    artifacts = {
        "bed_allocations": "milp/bed_allocations.csv",
        "staff_coverage": "milp/staff_coverage.csv",
        "method_result": "milp/method_result.json",
    }
    metadata = {"method_artifacts": {"milp": artifacts}}
    (directory / "experiment.json").write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setenv("HOSPITAL_RESULTS_PATH", str(tmp_path))

    with pytest.raises(HTTPException) as error:
        get_dashboard_allocation("experiment-x", "milp")

    assert error.value.status_code == 404
    assert "UNKNOWN" in error.value.detail
