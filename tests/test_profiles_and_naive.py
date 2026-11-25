"""Stratégie naïve, profils de pondération et équité entre agents présents."""

import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi import HTTPException

from hospital_planning.api.app import create_experiment_job, get_dashboard_profiles, get_scenario_comparison
from hospital_planning.config.loader import load_profiles, with_profile
from hospital_planning.domain.contracts import ExperimentJobRequest, HospitalConfig, ObjectiveWeights
from hospital_planning.experiments.runner import METHODS, _previous_metadata, run_experiment, save_experiment
from hospital_planning.experiments.scenarios import ScenarioDefinition
from hospital_planning.optimization.exact import run_cp_sat, run_milp
from hospital_planning.optimization.greedy import run_greedy
from hospital_planning.optimization.naive import apportion, run_naive
from hospital_planning.optimization.objective import calculate_objective_components, calculate_workload_range
from hospital_planning.optimization.validator import validate_solution

METADATA = {"instance": {"instance_id": "tiny", "scenario_id": "S0", "forecast": {"config_hash": "hash"}}}


def _staff(config: HospitalConfig, services: list[str], count: int) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "staff_id": f"{role[:3]}-{index:03}",
                "role": role,
                "qualified_services": json.dumps(services),
                "max_shifts": 5,
                "active": True,
            }
            for role in config.roles
            for index in range(count)
        ]
    )


def _availability(config: HospitalConfig, staff: pd.DataFrame, dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"staff_id": staff_id, "date": pd.Timestamp(date), "shift": shift.code, "available": True}
            for staff_id in staff["staff_id"]
            for date in dates
            for shift in config.shifts
        ]
    )


def _instance(services: dict[str, tuple[int, int, int]], date: str = "2025-01-01") -> tuple[pd.DataFrame, pd.DataFrame]:
    """services : code -> (recensement initial, demande, capacité)."""
    demand = pd.DataFrame(
        [{"date": date, "service": code, "requested_admissions": value[1]} for code, value in services.items()]
    )
    beds = pd.DataFrame(
        [
            {
                "date": date,
                "service": code,
                "occupancy_start": start,
                "expected_discharges": 0,
                "requested_admissions": requested,
                "occupancy_required": start + requested,
                "beds_required": start + requested,
                "capacity_available": capacity,
                "capacity_gap": 0,
                "capacity_source": "configured_nominal",
            }
            for code, (start, requested, capacity) in services.items()
        ]
    )
    return demand, beds


def test_apportion_is_proportional_exact_and_deterministic() -> None:
    assert apportion({"A": 10, "B": 10}, 10) == {"A": 5, "B": 5}
    assert apportion({"A": 10, "B": 5}, 9) == {"A": 6, "B": 3}
    assert apportion({"B": 1, "A": 1, "C": 1}, 2) == {"A": 1, "B": 1, "C": 0}
    assert apportion({"A": 3, "B": 4}, 100) == {"A": 3, "B": 4}
    assert apportion({"A": 0, "B": 0}, 5) == {"A": 0, "B": 0}
    assert apportion({"A": 7}, 0) == {"A": 0}


def test_naive_uses_one_acceptance_rate_without_service_priority(hospital_config: HospitalConfig) -> None:
    demand, beds = _instance({"URG": (0, 10, 5), "MED": (0, 10, 5)})
    staff = _staff(hospital_config, ["URG", "MED"], 6)

    result = run_naive(
        demand, beds, staff, _availability(hospital_config, staff, ["2025-01-01"]), METADATA, hospital_config
    )

    assert result.bed_allocations.set_index("service")["accepted_admissions"].to_dict() == {"MED": 5, "URG": 5}
    assert result.method_result.method_name == "naive"
    assert result.method_result.validation is not None and result.method_result.validation.valid


def test_naive_is_deterministic_and_ignores_the_profile(hospital_config: HospitalConfig, repository_root: Path) -> None:
    demand, beds = _instance({"URG": (4, 10, 40), "CHI": (3, 8, 40)})
    staff = _staff(hospital_config, ["URG", "CHI"], 8)
    availability = _availability(hospital_config, staff, ["2025-01-01"])
    plans = [
        run_naive(demand, beds, staff, availability, METADATA, with_profile(hospital_config, profile))
        for profile in load_profiles(repository_root / "configs" / "profiles.json", hospital_config)
    ]

    for plan in plans[1:]:
        pd.testing.assert_frame_equal(plan.bed_allocations, plans[0].bed_allocations)
        pd.testing.assert_frame_equal(plan.staff_assignments, plans[0].staff_assignments)
    assert len({plan.method_result.objective_value for plan in plans}) > 1


def test_naive_shares_staff_in_proportion_to_targets(hospital_config: HospitalConfig) -> None:
    demand, beds = _instance({"URG": (30, 0, 75), "CHI": (30, 0, 60)})
    staff = _staff(hospital_config, ["URG", "CHI"], 12)

    result = run_naive(
        demand, beds, staff, _availability(hospital_config, staff, ["2025-01-01"]), METADATA, hospital_config
    )

    totals = result.staff_coverage.groupby("service")["assigned_staff"].sum()
    assert totals["URG"] == totals["CHI"]


def test_profiles_are_valid_and_balanced_matches_the_hospital(
    hospital_config: HospitalConfig, repository_root: Path
) -> None:
    profiles = {p.profile_id: p for p in load_profiles(repository_root / "configs" / "profiles.json", hospital_config)}

    assert set(profiles) == {"equilibre", "priorite_accueil", "priorite_personnel"}
    assert with_profile(hospital_config, profiles["equilibre"]) == hospital_config
    reception = with_profile(hospital_config, profiles["priorite_accueil"]).objective_weights
    staff = with_profile(hospital_config, profiles["priorite_personnel"]).objective_weights
    reference = hospital_config.objective_weights
    assert reception.rejected_admission > 0 and reception.unmet_weight("URG") > reception.unmet_weight("MED")
    assert reception.rejection_weight("URG") > reception.rejection_weight("MED")
    assert staff.staff_target_shortage > reference.staff_target_shortage
    assert staff.workload_imbalance > reference.workload_imbalance


def test_unknown_service_in_a_profile_is_rejected(tmp_path: Path, hospital_config: HospitalConfig) -> None:
    weights = hospital_config.objective_weights.model_dump() | {"demand_multipliers": {"XXX": 2}}
    content = {
        "profiles": [
            {"profile_id": "equilibre", "label": "É", "description": "d"},
            {"profile_id": "test", "label": "T", "description": "d", "objective_weights": weights},
        ]
    }
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    with pytest.raises(ValueError, match="XXX"):
        load_profiles(path, hospital_config)


def test_objective_components_apply_service_multipliers(hospital_config: HospitalConfig) -> None:
    weights = ObjectiveWeights(
        opened_bed=1,
        unmet_patient_day=10,
        staff_target_shortage=5,
        workload_imbalance=2,
        rejected_admission=100,
        demand_multipliers={"URG": 3},
        staff_multipliers={"URG": 2},
    )
    config = hospital_config.model_copy(update={"objective_weights": weights})

    result = calculate_objective_components(
        7, {"URG": 1, "MED": 1}, {"URG": 1, "MED": 2}, {"URG": 3, "MED": 1}, 4, config
    )

    assert result.unmet_patient_day_cost == 40
    assert result.rejected_admission_cost == 500
    assert result.staff_target_shortage_cost == 35
    assert result.workload_imbalance_cost == 8
    assert result.total_cost == 7 + 40 + 500 + 35 + 8


@pytest.mark.parametrize("runner", [run_milp, run_cp_sat])
def test_solver_objective_matches_the_canonical_one_with_a_profile(
    runner, hospital_config: HospitalConfig, repository_root: Path
) -> None:
    """Un solveur optimal doit atteindre borne = objectif recalculé depuis les tables."""
    profiles = {p.profile_id: p for p in load_profiles(repository_root / "configs" / "profiles.json", hospital_config)}
    config = with_profile(hospital_config, profiles["priorite_accueil"])
    # Un refus par service est inévitable : 2 demandes pour 1 lit.
    demand, beds = _instance({"URG": (0, 2, 1), "CHI": (0, 2, 1)})
    staff = _staff(hospital_config, ["URG", "CHI"], 6)

    result = runner(
        demand, beds, staff, _availability(hospital_config, staff, ["2025-01-01"]), METADATA, config
    ).method_result

    assert result.status.value == "OPTIMAL"
    assert result.best_bound == pytest.approx(result.objective_value)
    assert result.objective_components is not None
    assert result.objective_components.rejected_admission_cost == 5000 * 3 + 5000
    assert result.objective_components.unmet_patient_day_cost == 3000 * 3 + 3000


def test_fairness_excludes_staff_absent_over_the_whole_horizon(hospital_config: HospitalConfig) -> None:
    staff = _staff(hospital_config, ["URG"], 3)
    availability = _availability(hospital_config, staff, ["2025-01-01", "2025-01-02"])
    absent = availability["staff_id"] == "PHY-002"
    availability.loc[absent, "available"] = False
    # PHY-001 n'est là que le second jour : présent, donc compté.
    availability.loc[
        (availability["staff_id"] == "PHY-001") & (availability["date"] == pd.Timestamp("2025-01-01")), "available"
    ] = False
    assignments = pd.DataFrame(
        [
            {"staff_id": staff_id, "date": pd.Timestamp(date), "service": "URG", "shift": "MORNING", "role": role}
            for staff_id, date, role in (
                ("PHY-000", "2025-01-01", "PHYSICIAN"),
                ("PHY-001", "2025-01-02", "PHYSICIAN"),
            )
        ]
    )

    assert calculate_workload_range(assignments, staff, availability) == 0
    report, _ = validate_solution(
        pd.DataFrame(
            [
                {
                    "date": "2025-01-01",
                    "service": "URG",
                    "occupancy_start": 0,
                    "expected_discharges": 0,
                    "requested_admissions": 0,
                    "accepted_admissions": 0,
                    "occupancy_end": 0,
                    "opened_beds": 0,
                    "capacity_available": 75,
                }
            ]
        ),
        assignments,
        availability,
        staff,
        hospital_config,
    )
    assert report.workload_range == 0
    availability.loc[absent, "available"] = True
    assert calculate_workload_range(assignments, staff, availability) == 1


@pytest.mark.parametrize("runner", [run_milp, run_cp_sat])
def test_solvers_stay_bounded_when_a_role_is_entirely_absent(runner, hospital_config: HospitalConfig) -> None:
    demand, beds = _instance({"URG": (0, 1, 75)})
    staff = _staff(hospital_config, ["URG"], 3)
    availability = _availability(hospital_config, staff, ["2025-01-01"])
    availability.loc[availability["staff_id"].str.startswith("PHY"), "available"] = False

    result = runner(demand, beds, staff, availability, METADATA, hospital_config, availability).method_result

    # Sans médecin, la dotation minimale interdit d'ouvrir : le patient est refusé.
    assert result.status.value == "OPTIMAL"
    assert (result.rejected_admissions, result.beds_opened_total) == (1, 0)
    assert result.fairness_metric == 0


def _run(tmp_path: Path, config: HospitalConfig, methods: tuple[str, ...], profile_id: str):
    demand, beds = _instance({"URG": (0, 1, 75)})
    demand["source_type"] = "forecast_selected"
    staff = _staff(config, ["URG"], 3)
    availability = _availability(config, staff, ["2025-01-01"])
    definition = ScenarioDefinition(
        scenario_id="S0_BASELINE", description="Base.", demand_multiplier=1.0, absence_rate=0.0, capacity_reduction=0.0
    )
    experiment, outputs = run_experiment(
        definition,
        demand,
        beds,
        staff,
        availability,
        availability,
        METADATA,
        config,
        methods=methods,
        profile_id=profile_id,
    )
    save_experiment(experiment, outputs, tmp_path / experiment.experiment_id)
    return experiment


def test_profiles_are_stored_apart_and_compared_apart(
    monkeypatch, tmp_path: Path, hospital_config: HospitalConfig, repository_root: Path
) -> None:
    monkeypatch.setenv("HOSPITAL_RESULTS_PATH", str(tmp_path))
    monkeypatch.setenv("HOSPITAL_PROJECT_ROOT", str(repository_root))
    profiles = {p.profile_id: p for p in load_profiles(repository_root / "configs" / "profiles.json", hospital_config)}
    reference = _run(tmp_path, hospital_config, ("naive", "greedy"), "equilibre")
    reception = _run(
        tmp_path, with_profile(hospital_config, profiles["priorite_accueil"]), ("greedy",), "priorite_accueil"
    )

    assert reception.experiment_id == f"{reference.experiment_id}-priorite_accueil"
    assert [row["method_name"] for row in get_scenario_comparison()] == ["naive", "greedy"]
    rows = get_scenario_comparison(profile="priorite_accueil")
    assert [(row["method_name"], row["profile_id"]) for row in rows] == [("greedy", "priorite_accueil")]
    assert get_scenario_comparison(profile="priorite_personnel") == []


def test_methods_are_not_merged_when_weights_change(tmp_path: Path, hospital_config: HospitalConfig) -> None:
    experiment = _run(tmp_path, hospital_config, ("greedy",), "equilibre")
    path = tmp_path / experiment.experiment_id / "experiment.json"
    weights = experiment.objective_weights
    assert weights is not None
    input_hash = experiment.scenario.input_hash

    assert _previous_metadata(path, input_hash, "equilibre", weights) is not None
    assert _previous_metadata(path, input_hash, "equilibre", weights | {"unmet_patient_day": 1}) is None
    assert _previous_metadata(path, input_hash, "priorite_accueil", weights) is None


def test_job_with_unknown_profile_is_refused(monkeypatch, repository_root: Path) -> None:
    monkeypatch.setenv("HOSPITAL_PROJECT_ROOT", str(repository_root))
    assert {profile.profile_id for profile in get_dashboard_profiles()} >= {"equilibre"}
    assert all(profile.objective_weights is not None for profile in get_dashboard_profiles())
    with pytest.raises(HTTPException) as error:
        create_experiment_job(ExperimentJobRequest(methods=["naive"], profile_id="inconnu"))
    assert error.value.status_code == 422


def test_heuristics_stay_fast_on_the_real_instance(repository_root: Path, hospital_config: HospitalConfig) -> None:
    instance = repository_root / "results" / "operational_instances" / "S0"
    inputs = next((repository_root / "results" / "experiments").glob("experiment-s0_*/scenario_inputs"))
    planning = pd.read_csv(inputs / "planning_availability.csv", parse_dates=["date"])
    for runner in (run_naive, run_greedy):
        result = runner(
            pd.read_csv(instance / "demand_requirements.csv", parse_dates=["date"]),
            pd.read_csv(instance / "bed_requirements.csv", parse_dates=["date"]),
            pd.read_csv(repository_root / "data" / "synthetic" / "staff.csv"),
            planning,
            METADATA,
            hospital_config,
            planning,
        ).method_result
        assert result.validation is not None and result.validation.valid
        assert result.runtime_seconds < 5
    assert METHODS == ("naive", "greedy", "milp", "cp_sat")
