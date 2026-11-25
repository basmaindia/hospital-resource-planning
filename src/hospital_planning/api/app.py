"""API FastAPI pour soumettre, consulter et télécharger les expériences locales."""

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from hospital_planning.api.jobs import JobRegistry
from hospital_planning.config.loader import load_hospital_config, load_profiles, with_profile, with_solver_settings
from hospital_planning.domain.contracts import (
    DEFAULT_PROFILE_ID,
    AllocationArtifactResponse,
    ArtifactProvenance,
    ExperimentJobRequest,
    ExperimentSummary,
    ExplorationArtifactResponse,
    ForecastArtifactResponse,
    HospitalConfig,
    JobResponse,
    MethodResult,
    OperationalArtifactResponse,
    ProfileDefinition,
    ScenarioReadModel,
    SensitivityManifestEntry,
)
from hospital_planning.experiments.runner import run_experiment, save_experiment
from hospital_planning.experiments.scenarios import CUSTOM_PREFIX, custom_definition, load_scenarios
from hospital_planning.experiments.sensitivity import RESULTS_FILE as SENSITIVITY_RESULTS_FILE
from hospital_planning.optimization.availability import project_planning_availability

app = FastAPI(
    title="Hospital Resource Planning API",
    version="0.1.0",
    description="API locale pour les expériences hospitalières synthétiques.",
)
job_registry = JobRegistry()


def cors_origins() -> list[str]:
    """Retourne les origines Next.js locales autorisées, jamais un joker global."""
    raw_origins = os.environ.get(
        "HOSPITAL_CORS_ORIGINS",
        "http://localhost:3011,http://127.0.0.1:3011,http://localhost:3000,http://127.0.0.1:3000",
    )
    origins = [origin.strip().rstrip("/") for origin in raw_origins.split(",") if origin.strip()]
    if not origins or "*" in origins or any(not origin.startswith(("http://", "https://")) for origin in origins):
        raise ValueError("HOSPITAL_CORS_ORIGINS doit contenir des origines HTTP(S) explicites, sans '*'.")
    return origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


def project_root() -> Path:
    """Résout la racine locale configurée, sans dépendre du chemin d'installation."""
    return Path(os.environ.get("HOSPITAL_PROJECT_ROOT", Path.cwd())).resolve()


def hospital_config_path() -> Path:
    """Résout la configuration sans dépendre du chemin d'installation du paquet."""
    configured_path = os.environ.get("HOSPITAL_CONFIG_PATH")
    return Path(configured_path) if configured_path else project_root() / "configs" / "hospital.json"


def experiments_root() -> Path:
    """Retourne le répertoire d'artefacts, configurable pour les tests ou déploiements locaux."""
    configured_path = os.environ.get("HOSPITAL_RESULTS_PATH")
    return Path(configured_path).resolve() if configured_path else project_root() / "results" / "experiments"


def synthetic_data_root() -> Path:
    """Retourne le répertoire de données synthétiques produit par la phase 2."""
    return project_root() / "data" / "synthetic"


def forecast_root() -> Path:
    """Retourne le répertoire des artefacts persistés de prévision."""
    return project_root() / "results" / "forecasts"


def operational_root(scenario_id: str) -> Path:
    """Retourne l'instance opérationnelle sans accepter de traversée de chemin."""
    root = (project_root() / "results" / "operational_instances").resolve()
    # L'artefact canonique de l'instance nominale est historiquement nommé S0,
    # tandis que la configuration de scénarios le désigne S0_BASELINE.
    directory_name = {"S0_BASELINE": "S0"}.get(scenario_id, scenario_id)
    directory = (root / directory_name).resolve()
    if not directory.is_relative_to(root):
        raise HTTPException(status_code=404, detail="Instance opérationnelle introuvable.")
    return directory


@app.get("/health")
def health() -> dict[str, str]:
    """Expose l'état minimal du service sans déclencher de calcul."""
    return {"status": "ok"}


@app.get("/api/v1/config/hospital", response_model=HospitalConfig)
def get_hospital_config() -> HospitalConfig:
    """Retourne la configuration validée de l'hôpital synthétique."""
    try:
        return load_hospital_config(hospital_config_path())
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=500, detail="Configuration hospitalière invalide.") from error


@app.post("/api/v1/jobs/experiments", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def create_experiment_job(request: ExperimentJobRequest) -> JobResponse:
    """Soumet un job explicite; aucun endpoint de lecture ne lance de calcul."""
    known = {profile.profile_id for profile in get_dashboard_profiles()}
    if request.profile_id not in known:
        raise HTTPException(status_code=422, detail=f"Profil inconnu: {request.profile_id}")
    if request.custom_scenario is not None:
        try:
            custom_definition(request.custom_scenario, get_hospital_config())
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    return job_registry.submit(lambda: _run_experiment_job(request))


@app.get("/api/v1/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str) -> JobResponse:
    """Retourne l'état réel d'un job local sans jamais le relancer."""
    response = job_registry.get(job_id)
    if response is None:
        raise HTTPException(status_code=404, detail=f"Job inconnu: {job_id}")
    return response


@app.get("/api/v1/experiments", response_model=list[ExperimentSummary])
def list_experiments() -> list[ExperimentSummary]:
    """Liste les expériences déjà stockées; cette lecture est strictement passive.

    Dans un scénario, la graine de référence vient en premier : le dashboard
    sélectionne ainsi par défaut la même expérience que la comparaison.
    """
    root = experiments_root()
    if not root.exists():
        return []
    reference = _reference_seed()
    summaries = [
        summary for path in sorted(root.glob("*/experiment.json")) if (summary := _read_experiment_summary(path))
    ]
    return sorted(
        summaries,
        key=lambda item: (
            item.scenario_id,
            item.profile_id != DEFAULT_PROFILE_ID,
            item.seed != reference,
            -item.created_at.timestamp(),
            item.experiment_id,
        ),
    )


@app.get("/api/v1/experiments/{experiment_id}")
def get_experiment(experiment_id: str) -> dict[str, object]:
    """Retourne les métadonnées et KPI d'une expérience stockée, sans calcul."""
    directory = _experiment_directory(experiment_id)
    metadata_path = directory / "experiment.json"
    metrics_path = directory / "metrics.csv"
    if not metadata_path.is_file() or not metrics_path.is_file():
        raise HTTPException(status_code=404, detail=f"Expérience inconnue: {experiment_id}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    return {"metadata": metadata, "metrics": _metric_rows(metrics_path)}


@app.get("/api/v1/dashboard/scenario-comparison")
def get_scenario_comparison(
    seed: int | None = None,
    profile: str = DEFAULT_PROFILE_ID,
    scope: Literal["reference", "custom"] = "reference",
) -> list[dict[str, object]]:
    """Agrège les KPI persistés d'une seule expérience par scénario, pour un profil.

    `reference` ne contient que les scénarios déclarés (S0–S5) ; `custom` ne contient
    que les simulations personnalisées, de la plus récente à la plus ancienne.

    Les objectifs de profils différents ne sont pas comparables : ils ne sont jamais
    mélangés dans une même réponse.

    Avec `seed`, seules les expériences de cette graine sont retenues. Sans `seed`,
    la graine de référence (`random_seed` de la configuration) est prioritaire : un
    essai lancé avec une autre graine ne remplace donc jamais la comparaison. À
    défaut d'expérience de référence, la plus récente est utilisée. À graine égale,
    l'expérience la plus récente est retenue. Chaque ligne porte sa graine.
    """
    root = experiments_root()
    if not root.exists():
        return []
    wanted_seed = _reference_seed() if seed is None else seed
    selected: dict[str, tuple[bool, float, ExperimentSummary, Path]] = {}
    for metadata_path in sorted(root.glob("*/experiment.json")):
        summary = _read_experiment_summary(metadata_path)
        metrics_path = metadata_path.parent / "metrics.csv"
        if summary is None or not metrics_path.is_file() or summary.profile_id != profile:
            continue
        if summary.scenario_id.startswith(CUSTOM_PREFIX) != (scope == "custom"):
            continue
        matches = summary.seed == wanted_seed
        if seed is not None and not matches:
            continue
        candidate = (matches, summary.created_at.timestamp(), summary, metrics_path)
        current = selected.get(summary.scenario_id)
        if current is None or candidate[:2] > current[:2]:
            selected[summary.scenario_id] = candidate
    rows: list[dict[str, object]] = []
    ordered = sorted(selected) if scope == "reference" else sorted(selected, key=lambda key: -selected[key][1])
    for scenario_id in ordered:
        _, _, summary, metrics_path = selected[scenario_id]
        context = {
            "seed": summary.seed,
            "profile_id": profile,
            "scenario_description": summary.scenario_description,
            "created_at": summary.created_at.isoformat(),
        }
        rows.extend(row | context for row in _metric_rows(metrics_path))
    return rows


@app.get("/api/v1/experiments/{experiment_id}/downloads/{artifact_path:path}")
def download_experiment_artifact(experiment_id: str, artifact_path: str) -> FileResponse:
    """Télécharge un artefact existant après contrôle strict du chemin."""
    directory = _experiment_directory(experiment_id)
    artifact = (directory / artifact_path).resolve()
    if not artifact.is_relative_to(directory) or not artifact.is_file():
        raise HTTPException(status_code=404, detail="Artefact introuvable.")
    return FileResponse(artifact, filename=artifact.name)


@app.get("/api/v1/dashboard/scenarios", response_model=list[ScenarioReadModel])
def get_dashboard_scenarios() -> list[ScenarioReadModel]:
    """Expose les scénarios déclarés, sans les transformer ni les exécuter."""
    try:
        config = load_hospital_config(hospital_config_path())
        return [
            ScenarioReadModel(**scenario.model_dump())
            for scenario in load_scenarios(project_root() / "configs" / "scenarios.json", config)
        ]
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=500, detail="Scénarios invalides ou indisponibles.") from error


@app.get("/api/v1/dashboard/profiles", response_model=list[ProfileDefinition])
def get_dashboard_profiles() -> list[ProfileDefinition]:
    """Expose les profils de pondération ; les poids absents sont ceux de hospital.json."""
    try:
        config = load_hospital_config(hospital_config_path())
        return [
            profile.model_copy(update={"objective_weights": with_profile(config, profile).objective_weights})
            for profile in load_profiles(project_root() / "configs" / "profiles.json", config)
        ]
    except (OSError, ValueError, KeyError) as error:
        raise HTTPException(status_code=500, detail="Profils invalides ou indisponibles.") from error


@app.get("/api/v1/dashboard/sensitivity/manifest", response_model=list[SensitivityManifestEntry])
def get_sensitivity_manifest() -> list[SensitivityManifestEntry]:
    """Expose le manifeste déjà produit, sans déclencher la grille coûteuse."""
    path = experiments_root() / "sensitivity_manifest.csv"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Manifeste de sensibilité non généré.")
    return [SensitivityManifestEntry.model_validate(record) for record in _csv_records(path)]


@app.get("/api/v1/dashboard/sensitivity/results")
def get_sensitivity_results(profile: str = DEFAULT_PROFILE_ID) -> list[dict[str, object]]:
    """Lit les KPI de sensibilité déjà calculés pour un profil, sans lancer de calcul."""
    path = experiments_root() / SENSITIVITY_RESULTS_FILE
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Analyse de sensibilité non calculée.")
    frame = pd.read_csv(path)
    frame = frame[frame["profile_id"] == profile]
    return frame.astype(object).where(pd.notna(frame), None).to_dict(orient="records")


@app.get("/api/v1/dashboard/forecasts", response_model=ForecastArtifactResponse)
def get_dashboard_forecasts() -> ForecastArtifactResponse:
    """Lit les prévisions finales et métriques enregistrées, sans les recalculer."""
    root = forecast_root()
    forecasts_path = root / "forecast_results.csv"
    metrics_path = root / "metrics_summary.csv"
    metadata_path = root / "metadata.json"
    _require_files(forecasts_path, metrics_path, metadata_path, detail="Artefacts de prévision non générés.")
    metadata = _read_json(metadata_path, detail="Métadonnées de prévision invalides.")
    forecasts = _csv_records(
        forecasts_path,
        date_columns=("date", "origin_date"),
        columns=("date", "service", "model_name", "horizon", "yhat", "selected", "origin_date"),
    )
    metrics = _csv_records(metrics_path)
    return ForecastArtifactResponse(
        provenance=ArtifactProvenance(
            artifact_path=str(root.relative_to(project_root())),
            generated_at=metadata.get("created_at"),
            config_hash=metadata.get("demand_config_hash"),
            source_id=metadata.get("forecast_run_id"),
        ),
        forecasts=forecasts,
        metrics=metrics,
    )


@app.get("/api/v1/dashboard/exploration", response_model=ExplorationArtifactResponse)
def get_dashboard_exploration() -> ExplorationArtifactResponse:
    """Lit les séries synthétiques historiques nécessaires aux graphiques d'exploration."""
    root = synthetic_data_root()
    demand_path = root / "historical_demand.csv"
    occupancy_path = root / "occupancy.csv"
    capacity_path = root / "bed_capacity.csv"
    _require_files(demand_path, occupancy_path, capacity_path, detail="Données synthétiques non générées.")
    return ExplorationArtifactResponse(
        provenance=ArtifactProvenance(
            artifact_path=str(root.relative_to(project_root())),
            random_seed=load_hospital_config(hospital_config_path()).random_seed,
            source_id="synthetic-data",
        ),
        historical_demand=_csv_records(
            demand_path,
            date_columns=("date",),
            columns=(
                "date",
                "service",
                "admissions",
                "discharges",
                "emergency_arrivals",
                "is_holiday",
                "is_special_event",
            ),
        ),
        occupancy=_csv_records(
            occupancy_path,
            date_columns=("date",),
            columns=("date", "service", "occupancy_end", "overflow"),
        ),
        capacity=_csv_records(
            capacity_path,
            date_columns=("date",),
            columns=("date", "service", "beds_operational", "beds_unavailable"),
        ),
    )


@app.get("/api/v1/dashboard/operational/{scenario_id}", response_model=OperationalArtifactResponse)
def get_dashboard_operational(scenario_id: str) -> OperationalArtifactResponse:
    """Lit une instance canonique opérationnelle, sans déclencher de décision."""
    root = operational_root(scenario_id)
    demand_path = root / "demand_requirements.csv"
    beds_path = root / "bed_requirements.csv"
    metadata_path = root / "operational_instance.json"
    _require_files(demand_path, beds_path, metadata_path, detail="Instance opérationnelle non générée.")
    metadata = _read_json(metadata_path, detail="Métadonnées opérationnelles invalides.")
    instance = metadata.get("instance", {})
    forecast = instance.get("forecast", {}) if isinstance(instance, dict) else {}
    return OperationalArtifactResponse(
        provenance=ArtifactProvenance(
            artifact_path=str(root.relative_to(project_root())),
            generated_at=instance.get("created_at") if isinstance(instance, dict) else None,
            config_hash=forecast.get("config_hash"),
            source_id=instance.get("instance_id") if isinstance(instance, dict) else None,
        ),
        demand=_csv_records(demand_path, date_columns=("date",)),
        beds=_csv_records(beds_path, date_columns=("date",)),
    )


@app.get(
    "/api/v1/dashboard/experiments/{experiment_id}/methods/{method_name}",
    response_model=AllocationArtifactResponse,
)
def get_dashboard_allocation(experiment_id: str, method_name: str) -> AllocationArtifactResponse:
    """Lit les allocations et la couverture RH d'une méthode déjà terminée."""
    directory = _experiment_directory(experiment_id)
    metadata_path = directory / "experiment.json"
    if not metadata_path.is_file():
        raise HTTPException(status_code=404, detail="Expérience inconnue.")
    metadata = _read_json(metadata_path, detail="Métadonnées d'expérience invalides.")
    artifacts = metadata.get("method_artifacts", {}).get(method_name)
    if not isinstance(artifacts, dict):
        raise HTTPException(status_code=404, detail="Méthode non disponible pour cette expérience.")
    allocations_path = _resolve_experiment_artifact(directory, artifacts.get("bed_allocations"))
    coverage_path = _resolve_experiment_artifact(directory, artifacts.get("staff_coverage"))
    assignments_path = _resolve_experiment_artifact(directory, artifacts.get("staff_assignments"))
    result_path = _resolve_experiment_artifact(directory, artifacts.get("method_result"))
    _require_files(
        allocations_path,
        coverage_path,
        assignments_path,
        result_path,
        detail="Artefacts d'allocation non générés.",
    )
    result = MethodResult.model_validate(_read_json(result_path, detail="Résultat de méthode invalide."))
    if result.objective_value is None:
        # Budget épuisé avant toute solution : les tables d'allocation sont vides.
        raise HTTPException(
            status_code=404,
            detail=f"Aucune solution trouvée par {method_name} (statut {result.status.value}, {result.native_status}).",
        )
    return AllocationArtifactResponse(
        provenance=ArtifactProvenance(
            artifact_path=str(directory.relative_to(experiments_root().resolve())),
            generated_at=metadata.get("created_at"),
            random_seed=metadata.get("seed"),
            config_hash=result.config_hash,
            source_id=experiment_id,
        ),
        method_result=result,
        allocations=_csv_records(allocations_path, date_columns=("date",)),
        staff_coverage=_csv_records(coverage_path, date_columns=("date",)),
        staff_assignments=_csv_records(assignments_path, date_columns=("date",)),
    )


def _metric_rows(metrics_path: Path) -> list[dict[str, object]]:
    """Lit les KPI d'une expérience et y joint la part des postes cibles couverts.

    Ce taux se déduit de la table de couverture persistée de chaque méthode : il
    distingue « contraintes respectées » de « effectifs suffisants ».
    """
    frame = pd.read_csv(metrics_path)
    frame["staff_coverage_rate"] = [
        _staff_coverage_rate(metrics_path.parent / str(method) / "staff_coverage.csv")
        for method in frame["method_name"]
    ]
    return frame.astype(object).where(pd.notna(frame), None).to_dict(orient="records")


def _staff_coverage_rate(coverage_path: Path) -> float | None:
    """Part des postes cibles pourvus, ou None sans table exploitable."""
    try:
        coverage = pd.read_csv(coverage_path, usecols=["target_staff", "target_shortage"])
    except (OSError, ValueError):
        return None
    target = int(coverage["target_staff"].sum())
    return None if target == 0 else 1 - int(coverage["target_shortage"].sum()) / target


def _reference_seed() -> int | None:
    """Graine de la configuration, ou None si celle-ci est illisible."""
    try:
        return load_hospital_config(hospital_config_path()).random_seed
    except (OSError, ValueError):
        return None


def _experiment_directory(experiment_id: str) -> Path:
    root = experiments_root().resolve()
    directory = (root / experiment_id).resolve()
    if not directory.is_relative_to(root):
        raise HTTPException(status_code=404, detail="Expérience introuvable.")
    return directory


def _resolve_experiment_artifact(directory: Path, raw_path: object) -> Path:
    """Résout un chemin d'artefact absolu, local ou historique sans traversée."""
    if not isinstance(raw_path, str) or not raw_path:
        raise HTTPException(status_code=404, detail="Artefact introuvable.")
    # Les métadonnées produites sous Windows contiennent des « \\ » : on les
    # normalise pour que le dépôt fonctionne quel que soit le système.
    candidate = Path(raw_path.replace("\\", "/"))
    candidates = [candidate.resolve()] if candidate.is_absolute() else [
        (directory / candidate).resolve(),
        (project_root() / candidate).resolve(),
    ]
    for artifact in candidates:
        if artifact.is_relative_to(directory) and artifact.is_file():
            return artifact
    raise HTTPException(status_code=404, detail="Artefact introuvable.")


def _require_files(*paths: Path, detail: str) -> None:
    """Retourne une erreur explicite lorsque la phase productrice n'a pas tourné."""
    if any(not path.is_file() for path in paths):
        raise HTTPException(status_code=404, detail=detail)


def _read_json(path: Path, *, detail: str) -> dict[str, object]:
    """Charge un JSON artefact avec une erreur HTTP stable."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=500, detail=detail) from error
    if not isinstance(value, dict):
        raise HTTPException(status_code=500, detail=detail)
    return value


def _csv_records(
    path: Path,
    *,
    date_columns: tuple[str, ...] = (),
    columns: tuple[str, ...] | None = None,
) -> list[dict[str, object]]:
    """Sérialise un CSV artefact en enregistrements JSON sans perdre les dates."""
    try:
        frame = pd.read_csv(path, parse_dates=list(date_columns))
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=500, detail="Artefact CSV invalide.") from error
    if columns is not None:
        missing = set(columns) - set(frame.columns)
        if missing:
            raise HTTPException(status_code=500, detail="Colonnes d'artefact inattendues.")
        frame = frame.loc[:, list(columns)]
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def _read_experiment_summary(metadata_path: Path) -> ExperimentSummary | None:
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        scenario = metadata["scenario"]
        return ExperimentSummary(
            experiment_id=metadata["experiment_id"],
            scenario_id=scenario["scenario_id"],
            scenario_description=scenario.get("description", ""),
            created_at=metadata["created_at"],
            seed=metadata.get("seed"),
            profile_id=metadata.get("profile_id", DEFAULT_PROFILE_ID),
            methods=metadata["methods"],
            scenario_input_hash=metadata["scenario_input_hash"],
        )
    except (KeyError, OSError, ValueError):
        return None


JobInputs = tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]


def _job_inputs(root: Path) -> JobInputs:
    """Charge les entrées communes des jobs, relues seulement si un fichier change.

    L'historique de disponibilité (772 000 lignes) prend plusieurs secondes à lire :
    le garder en mémoire rend les simulations rapides. Les méthodes travaillent sur
    des copies, ces tables ne sont jamais modifiées.
    """
    files = (
        root / "results" / "operational_instances" / "S0" / "demand_requirements.csv",
        root / "results" / "operational_instances" / "S0" / "bed_requirements.csv",
        root / "data" / "synthetic" / "staff.csv",
        root / "data" / "synthetic" / "staff_availability.csv",
        root / "results" / "operational_instances" / "S0" / "operational_instance.json",
        hospital_config_path(),
    )
    return _read_job_inputs(files, tuple(path.stat().st_mtime_ns for path in files))


@lru_cache(maxsize=1)
def _read_job_inputs(files: tuple[Path, ...], _versions: tuple[int, ...]) -> JobInputs:
    demand_path, beds_path, staff_path, availability_path, metadata_path, config_path = files
    demand = pd.read_csv(demand_path, parse_dates=["date"])
    staff = pd.read_csv(staff_path)
    planning_availability = project_planning_availability(
        staff,
        pd.read_csv(availability_path, parse_dates=["date"]),
        demand["date"],
        load_hospital_config(config_path),
    )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    return demand, pd.read_csv(beds_path, parse_dates=["date"]), staff, planning_availability, metadata


def _run_experiment_job(request: ExperimentJobRequest) -> list[str]:
    """Exécute les scénarios demandés dans l'unique worker local borné."""
    root = project_root()
    config = with_solver_settings(
        load_hospital_config(hospital_config_path()),
        request.solver_time_limit_seconds,
        request.solver_num_workers,
    )
    profiles = {
        profile.profile_id: profile for profile in load_profiles(root / "configs" / "profiles.json", config)
    }
    if request.profile_id not in profiles:
        raise ValueError(f"Profil inconnu: {request.profile_id}")
    config = with_profile(config, profiles[request.profile_id])
    demand, beds, staff, planning_availability, metadata = _job_inputs(root)
    scenarios = load_scenarios(root / "configs" / "scenarios.json", config)
    if request.custom_scenario is not None:
        scenarios = [custom_definition(request.custom_scenario, config)]
    elif request.scenario_ids is not None:
        requested_ids = set(request.scenario_ids)
        scenarios = [scenario for scenario in scenarios if scenario.scenario_id in requested_ids]
        missing = requested_ids - {scenario.scenario_id for scenario in scenarios}
        if missing:
            raise ValueError(f"Scénarios inconnus: {sorted(missing)}")
    experiment_ids = []
    for scenario in scenarios:
        experiment, outputs = run_experiment(
            scenario,
            demand,
            beds,
            staff,
            planning_availability,
            planning_availability,
            metadata,
            config,
            methods=tuple(request.methods),
            seed=request.seed,
            profile_id=request.profile_id,
        )
        save_experiment(experiment, outputs, experiments_root() / experiment.experiment_id)
        experiment_ids.append(experiment.experiment_id)
    return experiment_ids
