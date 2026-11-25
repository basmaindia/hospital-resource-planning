"""Analyse de sensibilité : calcul, fusion sans mélange d'instances et lecture API."""

import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi import HTTPException

from hospital_planning.api.app import _job_inputs, get_sensitivity_manifest, get_sensitivity_results
from hospital_planning.domain.contracts import HospitalConfig
from hospital_planning.experiments.scenarios import sensitivity_definitions
from hospital_planning.experiments.sensitivity import merge_results, run_sensitivity


def test_two_cases_are_computed_with_their_parameters(
    monkeypatch, repository_root: Path, hospital_config: HospitalConfig
) -> None:
    monkeypatch.setenv("HOSPITAL_PROJECT_ROOT", str(repository_root))
    demand, beds, staff, planning, metadata = _job_inputs(repository_root)
    wanted = {"SENS_A00_D100_C00", "SENS_A20_D125_C05"}
    definitions = [item for item in sensitivity_definitions() if item.scenario_id in wanted]

    rows = run_sensitivity(
        definitions, demand, beds, staff, planning, metadata, hospital_config, methods=("naive", "greedy")
    )

    assert len(rows) == 4
    stored = json.loads(
        next((repository_root / "results" / "experiments").glob("experiment-s0_*/greedy/method_result.json")).read_text(
            encoding="utf-8"
        )
    )
    base = rows[(rows["scenario_id"] == "SENS_A00_D100_C00") & (rows["method_name"] == "greedy")].iloc[0]
    # Sans perturbation, la grille redonne exactement le plan Greedy de S0.
    for key in ("rejected_admissions", "staff_shortage_total", "beds_opened_total"):
        assert base[key] == stored[key]
    hard = rows[(rows["scenario_id"] == "SENS_A20_D125_C05") & (rows["method_name"] == "greedy")].iloc[0]
    assert (hard["absence_rate"], hard["demand_multiplier"], hard["capacity_reduction"]) == (0.2, 1.25, 0.05)
    assert hard["staff_coverage_rate"] < base["staff_coverage_rate"]


def _rows(scenario: str, method: str, input_hash: str, value: int) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "scenario_id": scenario,
                "profile_id": "equilibre",
                "method_name": method,
                "scenario_input_hash": input_hash,
                "objective_value": value,
            }
        ]
    )


def test_merge_replaces_recomputed_cases_and_keeps_the_others() -> None:
    previous = pd.concat([_rows("A", "greedy", "h", 1), _rows("A", "naive", "h", 2), _rows("B", "greedy", "k", 3)])

    merged = merge_results(previous, pd.concat([_rows("A", "greedy", "h", 9), _rows("A", "cp_sat", "h", 8)]))

    assert list(zip(merged["scenario_id"], merged["method_name"], merged["objective_value"], strict=True)) == [
        ("A", "naive", 2),
        ("A", "greedy", 9),
        ("A", "cp_sat", 8),
        ("B", "greedy", 3),
    ]


def test_merge_drops_rows_computed_on_other_data() -> None:
    merged = merge_results(_rows("A", "naive", "ancien", 2), _rows("A", "greedy", "nouveau", 1))
    assert merged["method_name"].tolist() == ["greedy"]


def test_results_endpoint_exposes_the_whole_computed_grid(monkeypatch, repository_root: Path) -> None:
    monkeypatch.setenv("HOSPITAL_PROJECT_ROOT", str(repository_root))
    rows = get_sensitivity_results()
    cases = {entry.scenario_id for entry in get_sensitivity_manifest()}

    for method in ("naive", "greedy"):
        assert {row["scenario_id"] for row in rows if row["method_name"] == method} == cases
    json.dumps(rows, allow_nan=False)
    # Fermer 20 % des lits dépasse les patients déjà présents en MED : à signaler, pas à masquer.
    assert all(not row["validation_passed"] for row in rows if row["capacity_reduction"] == 0.2)


def test_missing_results_are_an_explicit_empty_state(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOSPITAL_RESULTS_PATH", str(tmp_path))
    with pytest.raises(HTTPException) as error:
        get_sensitivity_results()
    assert error.value.status_code == 404
