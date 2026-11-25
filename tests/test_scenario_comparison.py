"""La comparaison ne mélange ni ne perd de méthodes lorsqu'une autre graine est lancée."""

import json
from pathlib import Path

import pytest

from hospital_planning.api.app import get_scenario_comparison, list_experiments


def _write(root: Path, name: str, scenario: str, seed: int, created_at: str, methods: list[str]) -> None:
    directory = root / name
    directory.mkdir()
    metadata = {
        "experiment_id": name,
        "created_at": created_at,
        "scenario": {"scenario_id": scenario},
        "seed": seed,
        "scenario_input_hash": name,
        "methods": methods,
    }
    (directory / "experiment.json").write_text(json.dumps(metadata), encoding="utf-8")
    rows = "".join(f"{name},{scenario},{method},1\n" for method in methods)
    (directory / "metrics.csv").write_text(
        "experiment_id,scenario_id,method_name,objective_value\n" + rows, encoding="utf-8"
    )


@pytest.fixture
def stored(monkeypatch, tmp_path, repository_root) -> Path:
    monkeypatch.setenv("HOSPITAL_RESULTS_PATH", str(tmp_path))
    monkeypatch.setenv("HOSPITAL_CONFIG_PATH", str(repository_root / "configs" / "hospital.json"))
    three = ["greedy", "milp", "cp_sat"]
    _write(tmp_path, "experiment-s3-zref", "S3_STAFF_ABSENCE", 42, "2026-01-01T00:00:00+00:00", three)
    _write(tmp_path, "experiment-s3-aother", "S3_STAFF_ABSENCE", 7, "2026-01-02T00:00:00+00:00", ["greedy"])
    _write(tmp_path, "experiment-s5-only7", "S5_BED_CLOSURE", 7, "2026-01-02T00:00:00+00:00", ["greedy"])
    return tmp_path


def test_newer_run_with_another_seed_does_not_replace_the_reference(stored: Path) -> None:
    rows = get_scenario_comparison()

    reference = [row for row in rows if row["scenario_id"] == "S3_STAFF_ABSENCE"]
    assert [row["method_name"] for row in reference] == ["greedy", "milp", "cp_sat"]
    assert {row["seed"] for row in reference} == {42}
    # Sans expérience de référence, la plus récente reste visible avec sa vraie graine.
    assert [row["seed"] for row in rows if row["scenario_id"] == "S5_BED_CLOSURE"] == [7]


def test_explicit_seed_filters_strictly(stored: Path) -> None:
    rows = get_scenario_comparison(seed=7)
    assert {(row["scenario_id"], row["seed"]) for row in rows} == {("S3_STAFF_ABSENCE", 7), ("S5_BED_CLOSURE", 7)}
    assert {row["experiment_id"] for row in get_scenario_comparison(seed=42)} == {"experiment-s3-zref"}
    assert get_scenario_comparison(seed=999) == []


def test_most_recent_wins_for_the_same_seed(stored: Path) -> None:
    _write(stored, "experiment-s3-newer", "S3_STAFF_ABSENCE", 42, "2026-02-01T00:00:00+00:00", ["greedy"])
    rows = [row for row in get_scenario_comparison() if row["scenario_id"] == "S3_STAFF_ABSENCE"]
    assert {row["experiment_id"] for row in rows} == {"experiment-s3-newer"}


def test_experiment_list_puts_the_reference_seed_first(stored: Path) -> None:
    identifiers = [item.experiment_id for item in list_experiments() if item.scenario_id == "S3_STAFF_ABSENCE"]
    assert identifiers == ["experiment-s3-zref", "experiment-s3-aother"]
