"""Tests de la baseline gloutonne et de son validateur indépendant."""

import json

import pandas as pd
import pytest

from hospital_planning.domain.contracts import HospitalConfig, ValidationReport
from hospital_planning.optimization.exact import run_cp_sat, run_milp
from hospital_planning.optimization.greedy import run_greedy
from hospital_planning.optimization.validator import validate_solution


def test_validator_detects_unavailable_assignment(hospital_config: HospitalConfig) -> None:
    staff = pd.DataFrame(
        [
            {
                "staff_id": "PHY-001",
                "role": "PHYSICIAN",
                "qualified_services": json.dumps(["URG"]),
                "max_shifts": 5,
            }
        ]
    )
    assignments = pd.DataFrame(
        [{"staff_id": "PHY-001", "date": "2025-01-01", "service": "URG", "shift": "MORNING", "role": "PHYSICIAN"}]
    )
    availability = pd.DataFrame([{"staff_id": "PHY-001", "date": "2025-01-01", "shift": "MORNING", "available": False}])
    beds = pd.DataFrame(
        [
            {
                "date": "2025-01-01",
                "service": "URG",
                "occupancy_start": 0,
                "expected_discharges": 0,
                "requested_admissions": 1,
                "accepted_admissions": 1,
                "occupancy_end": 1,
                "opened_beds": 1,
                "capacity_available": 75,
            }
        ]
    )

    report, _ = validate_solution(beds, assignments, availability, staff, hospital_config)

    assert not report.valid
    assert report.availability_violations == 1


def test_validator_detects_excessive_consecutive_nights(hospital_config: HospitalConfig) -> None:
    dates = pd.date_range("2025-01-01", periods=4, freq="D")
    staff = pd.DataFrame(
        [
            {
                "staff_id": "PHY-001",
                "role": "PHYSICIAN",
                "qualified_services": json.dumps(["URG"]),
                "max_shifts": 5,
            }
        ]
    )
    assignments = pd.DataFrame(
        [
            {"staff_id": "PHY-001", "date": date, "service": "URG", "shift": "NIGHT", "role": "PHYSICIAN"}
            for date in dates
        ]
    )
    availability = pd.DataFrame(
        [{"staff_id": "PHY-001", "date": date, "shift": "NIGHT", "available": True} for date in dates]
    )
    beds = pd.DataFrame(
        [
            {
                "date": date,
                "service": "URG",
                "occupancy_start": 0,
                "expected_discharges": 0,
                "requested_admissions": 0,
                "accepted_admissions": 0,
                "occupancy_end": 0,
                "opened_beds": 0,
                "capacity_available": 75,
            }
            for date in dates
        ]
    )

    report, _ = validate_solution(beds, assignments, availability, staff, hospital_config)

    assert not report.valid
    assert report.hard_constraint_violations == 1
    assert any("nuits consécutives" in message for message in report.messages)


def test_greedy_is_deterministic_and_respects_hard_constraints(hospital_config: HospitalConfig) -> None:
    staff_records = []
    for role in hospital_config.roles:
        for index in range(3):
            staff_records.append(
                {
                    "staff_id": f"{role[:3]}-{index}",
                    "role": role,
                    "qualified_services": json.dumps(["URG"]),
                    "max_shifts": 5,
                    "active": True,
                }
            )
    staff = pd.DataFrame(staff_records)
    history_availability = pd.DataFrame(
        [
            {"staff_id": staff_id, "date": "2025-01-01", "shift": shift.code, "available": True}
            for staff_id in staff["staff_id"]
            for shift in hospital_config.shifts
        ]
    )
    demand = pd.DataFrame([{"date": "2025-01-08", "service": "URG", "requested_admissions": 1}])
    beds = pd.DataFrame(
        [
            {
                "date": "2025-01-08",
                "service": "URG",
                "occupancy_start": 0,
                "expected_discharges": 0,
                "occupancy_required": 1,
                "capacity_available": 75,
            }
        ]
    )
    metadata = {"instance": {"instance_id": "test", "scenario_id": "S0", "forecast": {"config_hash": "hash"}}}

    first = run_greedy(demand, beds, staff, history_availability, metadata, hospital_config)
    second = run_greedy(demand, beds, staff, history_availability, metadata, hospital_config)

    pd.testing.assert_frame_equal(first.bed_allocations, second.bed_allocations)
    pd.testing.assert_frame_equal(first.staff_assignments, second.staff_assignments)
    assert first.method_result.status.value == "FEASIBLE"
    assert first.method_result.validation is not None
    assert first.method_result.validation.hard_constraint_violations == 0
    assert first.method_result.validation.workload_range == 0
    assert first.method_result.objective_components is not None
    assert first.method_result.objective_components.workload_imbalance_cost == 0


def test_exact_solvers_match_on_tiny_instance(hospital_config: HospitalConfig) -> None:
    staff_records = []
    for role in hospital_config.roles:
        for index in range(3):
            staff_records.append(
                {
                    "staff_id": f"{role[:3]}-{index:03}",
                    "role": role,
                    "qualified_services": json.dumps(["URG"]),
                    "max_shifts": 5,
                    "active": True,
                }
            )
    staff = pd.DataFrame(staff_records)
    availability = pd.DataFrame(
        [
            {"staff_id": staff_id, "date": "2025-01-01", "shift": shift.code, "available": True}
            for staff_id in staff["staff_id"]
            for shift in hospital_config.shifts
        ]
    )
    demand = pd.DataFrame([{"date": "2025-01-01", "service": "URG", "requested_admissions": 1}])
    beds = pd.DataFrame(
        [
            {
                "date": "2025-01-01",
                "service": "URG",
                "occupancy_start": 0,
                "expected_discharges": 0,
                "occupancy_required": 1,
                "capacity_available": 75,
            }
        ]
    )
    metadata = {"instance": {"instance_id": "tiny", "scenario_id": "S0", "forecast": {"config_hash": "hash"}}}

    milp = run_milp(demand, beds, staff, availability, metadata, hospital_config)
    cp_sat = run_cp_sat(demand, beds, staff, availability, metadata, hospital_config)

    assert milp.method_result.status.value == "OPTIMAL"
    assert cp_sat.method_result.status.value == "OPTIMAL"
    assert milp.method_result.objective_value == cp_sat.method_result.objective_value == 10.0
    assert milp.method_result.validation is not None and milp.method_result.validation.valid
    assert cp_sat.method_result.validation is not None and cp_sat.method_result.validation.valid


def _tiny_solution() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Deux jours URG : 4 présents, 2 sorties, 1 refus le premier jour faute de lit."""
    reference = pd.DataFrame(
        {
            "date": ["2025-01-01", "2025-01-02"],
            "service": ["URG", "URG"],
            "occupancy_start": [4, 5],
            "expected_discharges": [2, 2],
            "requested_admissions": [3, 1],
            "capacity_available": [4, 75],
        }
    )
    allocations = pd.DataFrame(
        {
            "date": ["2025-01-01", "2025-01-02"],
            "service": ["URG", "URG"],
            "occupancy_start": [4, 4],
            "expected_discharges": [2, 2],
            "requested_admissions": [3, 1],
            "accepted_admissions": [2, 1],
            "rejected_admissions": [1, 0],
            "occupancy_end": [4, 3],
            "opened_beds": [4, 3],
            "capacity_available": [4, 75],
        }
    )
    return allocations, reference


def _bed_report(allocations: pd.DataFrame, reference: pd.DataFrame, config: HospitalConfig) -> ValidationReport:
    staff = pd.DataFrame(columns=["staff_id", "role", "qualified_services", "max_shifts"])
    assignments = pd.DataFrame(columns=["staff_id", "date", "service", "shift", "role"])
    availability = pd.DataFrame(columns=["staff_id", "date", "shift", "available"])
    report, _ = validate_solution(allocations, assignments, availability, staff, config, reference)
    return report


def test_validator_accepts_coherent_admissions_and_cohorts(hospital_config: HospitalConfig) -> None:
    report = _bed_report(*_tiny_solution(), hospital_config)

    assert report.admission_violations == report.reference_violations == report.capacity_violations == 0


def test_validator_rejects_more_accepted_than_requested(hospital_config: HospitalConfig) -> None:
    allocations, reference = _tiny_solution()
    # Le bilan interne reste équilibré : seule la comparaison à la demande révèle l'erreur.
    allocations.loc[1, ["accepted_admissions", "rejected_admissions", "occupancy_end", "opened_beds"]] = [2, -1, 4, 4]

    report = _bed_report(allocations, reference, hospital_config)

    assert not report.valid
    assert report.capacity_violations == 0
    assert report.admission_violations == 1
    assert any("admissions acceptées" in message for message in report.messages)


def test_validator_rejects_wrong_initial_census_even_when_balanced(hospital_config: HospitalConfig) -> None:
    allocations, reference = _tiny_solution()
    allocations.loc[0, ["occupancy_start", "expected_discharges"]] = [5, 3]

    report = _bed_report(allocations, reference, hospital_config)

    assert report.capacity_violations == 0
    assert report.reference_violations == 1
    assert not report.valid


@pytest.mark.parametrize("runner", [run_greedy, run_milp, run_cp_sat])
def test_first_day_starts_from_instance_census(runner, hospital_config: HospitalConfig) -> None:
    staff = pd.DataFrame(
        [
            {
                "staff_id": f"{role[:3]}-{index:03}",
                "role": role,
                "qualified_services": json.dumps(["URG"]),
                "max_shifts": 5,
                "active": True,
            }
            for role in hospital_config.roles
            for index in range(3)
        ]
    )
    availability = pd.DataFrame(
        [
            {"staff_id": staff_id, "date": "2025-01-01", "shift": shift.code, "available": True}
            for staff_id in staff["staff_id"]
            for shift in hospital_config.shifts
        ]
    )
    demand = pd.DataFrame([{"date": "2025-01-01", "service": "URG", "requested_admissions": 1}])
    beds = pd.DataFrame(
        [
            {
                "date": "2025-01-01",
                "service": "URG",
                "occupancy_start": 5,
                "expected_discharges": 3,
                "occupancy_required": 3,
                "capacity_available": 75,
            }
        ]
    )
    metadata = {"instance": {"instance_id": "tiny", "scenario_id": "S0", "forecast": {"config_hash": "hash"}}}

    result = runner(demand, beds, staff, availability, metadata, hospital_config)

    row = result.bed_allocations.iloc[0]
    assert (row["occupancy_start"], row["expected_discharges"], row["occupancy_end"]) == (5, 3, 3)
    assert result.method_result.validation is not None and result.method_result.validation.valid
