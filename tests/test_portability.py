"""Non-régression : portabilité Windows/Linux et conservation des méthodes."""

import json

import pandas as pd

from hospital_planning.api.app import _resolve_experiment_artifact
from hospital_planning.experiments.runner import _previous_metadata
from hospital_planning.experiments.scenarios import _scenario_hash


def test_windows_artifact_paths_are_resolved_on_any_os(tmp_path, monkeypatch):
    directory = tmp_path / "results" / "experiments" / "experiment-x"
    (directory / "greedy").mkdir(parents=True)
    artifact = directory / "greedy" / "bed_allocations.csv"
    artifact.write_text("a\n1\n", encoding="utf-8")
    monkeypatch.setenv("HOSPITAL_PROJECT_ROOT", str(tmp_path))

    windows_path = "results\\experiments\\experiment-x\\greedy\\bed_allocations.csv"
    assert _resolve_experiment_artifact(directory, windows_path) == artifact.resolve()
    assert _resolve_experiment_artifact(directory, "greedy/bed_allocations.csv") == artifact.resolve()


def test_previous_metadata_is_reused_only_for_the_same_instance(tmp_path):
    metadata_path = tmp_path / "experiment.json"
    metadata_path.write_text(
        json.dumps(
            {
                "scenario_input_hash": "abc",
                "method_artifacts": {"greedy": {"bed_allocations": "results\\exp\\greedy\\bed_allocations.csv"}},
            }
        ),
        encoding="utf-8",
    )
    previous = _previous_metadata(metadata_path, "abc")
    assert previous is not None
    assert previous["method_artifacts"] == {"greedy": {"bed_allocations": "greedy/bed_allocations.csv"}}
    assert _previous_metadata(metadata_path, "other-hash") is None


def test_scenario_hash_does_not_depend_on_os_line_endings(monkeypatch):
    from hospital_planning.experiments.scenarios import ScenarioDefinition

    definition = ScenarioDefinition(
        scenario_id="S0_BASELINE", description="test", demand_multiplier=1.0, absence_rate=0.0, capacity_reduction=0.0
    )
    table = pd.DataFrame({"date": pd.to_datetime(["2026-01-01"]), "value": [1]})
    reference = _scenario_hash(definition, table, table, table, 42)

    original = pd.DataFrame.to_csv

    def windows_to_csv(self, *args, **kwargs):  # simule le défaut Windows « \r\n »
        kwargs.setdefault("lineterminator", "\r\n")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(pd.DataFrame, "to_csv", windows_to_csv)
    assert _scenario_hash(definition, table, table, table, 42) == reference
