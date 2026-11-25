"""Scénarios personnalisés : définition, isolement de S0–S5 et job de bout en bout."""

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from hospital_planning.api.app import (
    _job_inputs,
    _run_experiment_job,
    create_experiment_job,
    get_scenario_comparison,
    list_experiments,
)
from hospital_planning.domain.contracts import CustomScenarioRequest, ExperimentJobRequest, HospitalConfig
from hospital_planning.experiments.scenarios import apply_scenario, custom_definition, load_scenarios


@pytest.fixture
def inputs(monkeypatch, repository_root: Path):
    monkeypatch.setenv("HOSPITAL_PROJECT_ROOT", str(repository_root))
    return _job_inputs(repository_root)


def test_reference_identifiers_are_unchanged(inputs, hospital_config: HospitalConfig, repository_root: Path) -> None:
    """Le champ ajouté pour le simulateur ne doit pas changer l'instance de S0–S5."""
    demand, beds, _, planning, _ = inputs
    stored = {
        json.loads(path.read_text(encoding="utf-8"))["scenario"]["scenario_id"]: path.parent.name
        for path in (repository_root / "results" / "experiments").glob("experiment-s*/experiment.json")
        if path.parent.name.count("-") == 2
    }
    scenarios = load_scenarios(repository_root / "configs" / "scenarios.json", hospital_config)
    assert len(scenarios) == 6
    for definition in scenarios:
        instance = apply_scenario(definition, demand, beds, planning, hospital_config, seed=42)
        assert stored[definition.scenario_id].endswith(instance.input_hash[:12])


def test_custom_equivalent_to_s4_gives_the_same_instance(
    inputs, hospital_config: HospitalConfig, repository_root: Path
) -> None:
    demand, beds, _, planning, _ = inputs
    scenarios = load_scenarios(repository_root / "configs" / "scenarios.json", hospital_config)
    s4 = next(item for item in scenarios if item.scenario_id == "S4_COMBINED_CRISIS")
    custom = custom_definition(CustomScenarioRequest(demand_multiplier=1.25, absence_rate=0.15), hospital_config)

    left = apply_scenario(s4, demand, beds, planning, hospital_config, seed=42)
    right = apply_scenario(custom, demand, beds, planning, hospital_config, seed=42)

    pd.testing.assert_frame_equal(left.demand_requirements, right.demand_requirements)
    pd.testing.assert_frame_equal(left.bed_requirements, right.bed_requirements)
    pd.testing.assert_frame_equal(left.planning_availability, right.planning_availability)
    assert left.input_hash != right.input_hash


def test_custom_targets_only_the_chosen_services(inputs, hospital_config: HospitalConfig) -> None:
    demand, beds, _, planning, _ = inputs
    request = CustomScenarioRequest(
        demand_multiplier=1.5, demand_service="URG", closure_rate=0.1, closure_service="CHI"
    )
    definition = custom_definition(request, hospital_config)

    result = apply_scenario(definition, demand, beds, planning, hospital_config, seed=42)

    before = demand.groupby("service")["requested_admissions"].sum()
    after = result.demand_requirements.groupby("service")["requested_admissions"].sum()
    assert after["URG"] > before["URG"]
    assert after.drop("URG").equals(before.drop("URG"))
    capacity = result.bed_requirements.groupby("service")["capacity_available"].first().to_dict()
    assert capacity == {"CHI": 57, "MED": 106, "REA": 55, "URG": 75}
    assert definition.description == "Demande URG ×1,50 · lits fermés CHI 10 %"


def test_custom_identifier_depends_only_on_effective_settings(hospital_config: HospitalConfig) -> None:
    def identifier(**settings: object) -> str:
        return custom_definition(CustomScenarioRequest(**settings), hospital_config).scenario_id

    # Un service sans hausse ni fermeture n'a aucun effet.
    assert identifier(absence_rate=0.1, demand_service="URG") == identifier(absence_rate=0.1)
    assert identifier(absence_rate=0.1) != identifier(absence_rate=0.2)
    assert identifier(closure_rate=0.1) != identifier(closure_rate=0.1, closure_service="MED")


@pytest.mark.parametrize(
    "settings",
    [{"demand_multiplier": 0.9}, {"demand_multiplier": 2.1}, {"absence_rate": 0.6}, {"closure_rate": -0.1}],
)
def test_out_of_range_settings_are_rejected(settings: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        CustomScenarioRequest(**settings)


def test_job_request_refuses_ambiguous_or_unknown_targets(monkeypatch, repository_root: Path) -> None:
    monkeypatch.setenv("HOSPITAL_PROJECT_ROOT", str(repository_root))
    with pytest.raises(ValidationError):
        ExperimentJobRequest(scenario_ids=["S0_BASELINE"], custom_scenario=CustomScenarioRequest())
    with pytest.raises(HTTPException) as error:
        create_experiment_job(
            ExperimentJobRequest(custom_scenario=CustomScenarioRequest(closure_rate=0.1, closure_service="XXX"))
        )
    assert error.value.status_code == 422


def test_simulation_is_stored_apart_from_reference_scenarios(
    monkeypatch, tmp_path: Path, repository_root: Path
) -> None:
    source = next((repository_root / "results" / "experiments").glob("experiment-s0_baseline-*"))
    shutil.copytree(source, tmp_path / source.name, ignore=shutil.ignore_patterns("cp_sat", "milp", "planning_*"))
    monkeypatch.setenv("HOSPITAL_PROJECT_ROOT", str(repository_root))
    monkeypatch.setenv("HOSPITAL_RESULTS_PATH", str(tmp_path))
    request = ExperimentJobRequest(
        custom_scenario=CustomScenarioRequest(demand_multiplier=1.25, absence_rate=0.15),
        methods=["naive", "greedy"],
    )

    identifiers = _run_experiment_job(request)

    assert identifiers[0].startswith("experiment-custom_")
    assert {row["scenario_id"] for row in get_scenario_comparison()} == {"S0_BASELINE"}
    rows = get_scenario_comparison(scope="custom")
    assert [row["method_name"] for row in rows] == ["naive", "greedy"]
    assert all(row["scenario_id"].startswith("CUSTOM_") for row in rows)
    assert rows[0]["scenario_description"] == "Demande tous services ×1,25 · absences 15 %"
    # Mêmes réglages que S4 : mêmes refus et même déficit que le résultat de référence publié.
    assert (rows[1]["rejected_admissions"], rows[1]["staff_shortage_total"]) == (73, 1564)
    assert get_scenario_comparison(scope="custom", profile="priorite_accueil") == []
    summary = next(item for item in list_experiments() if item.scenario_id.startswith("CUSTOM_"))
    assert summary.scenario_description == rows[0]["scenario_description"]


def test_impossible_closure_is_reported_as_broken_constraints(
    monkeypatch, tmp_path: Path, repository_root: Path
) -> None:
    """Fermer 40 % des lits de MED : les patients déjà présents ne tiennent plus."""
    monkeypatch.setenv("HOSPITAL_PROJECT_ROOT", str(repository_root))
    monkeypatch.setenv("HOSPITAL_RESULTS_PATH", str(tmp_path))
    request = ExperimentJobRequest(
        custom_scenario=CustomScenarioRequest(closure_rate=0.4, closure_service="MED"), methods=["naive", "greedy"]
    )

    _run_experiment_job(request)

    rows = get_scenario_comparison(scope="custom")
    assert [row["validation_passed"] for row in rows] == [False, False]
    assert all(row["hard_constraint_violations"] > 0 for row in rows)
