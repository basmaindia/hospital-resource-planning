"""Chargement strict des fichiers JSON de configuration."""

import hashlib
import json
from pathlib import Path

from hospital_planning.domain.contracts import DEFAULT_PROFILE_ID, HospitalConfig, ProfileDefinition


def load_hospital_config(path: Path) -> HospitalConfig:
    """Charge une configuration hospitalière et échoue pour toute incohérence."""
    with path.open(encoding="utf-8") as config_file:
        raw_config = json.load(config_file)
    return HospitalConfig.model_validate(raw_config)


def with_solver_settings(
    config: HospitalConfig, time_limit_seconds: int | None = None, num_workers: int | None = None
) -> HospitalConfig:
    """Retourne une copie avec le budget de calcul demandé ; None conserve la configuration."""
    overrides = {
        name: value
        for name, value in (
            ("solver_time_limit_seconds", time_limit_seconds),
            ("solver_num_workers", num_workers),
        )
        if value is not None
    }
    if any(value < 1 for value in overrides.values()):
        raise ValueError("La limite de temps et le nombre de threads doivent être strictement positifs.")
    return config.model_copy(update={"planning_policy": config.planning_policy.model_copy(update=overrides)})


def demand_config_hash(config: HospitalConfig) -> str:
    """Empreinte des seuls paramètres qui déterminent la demande et l'instance.

    Les réglages de décision (solveurs, politique, poids de l'objectif) et le nom de
    l'hôpital en sont exclus : les modifier ne périme ni les prévisions ni l'instance.
    """
    demand_parameters = config.model_dump(
        mode="json", exclude={"hospital_name", "planning_policy", "objective_weights"}
    )
    serialized = json.dumps(demand_parameters, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def load_profiles(path: Path, config: HospitalConfig) -> list[ProfileDefinition]:
    """Charge les profils de pondération et vérifie les services référencés."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    profiles = [ProfileDefinition.model_validate(item) for item in raw["profiles"]]
    identifiers = [profile.profile_id for profile in profiles]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Les identifiants de profil doivent être uniques.")
    if DEFAULT_PROFILE_ID not in identifiers:
        raise ValueError(f"Le profil de référence {DEFAULT_PROFILE_ID} est requis.")
    for profile in profiles:
        weights = profile.objective_weights
        if weights is None:
            continue
        unknown = (set(weights.demand_multipliers) | set(weights.staff_multipliers)) - set(config.services)
        if unknown:
            raise ValueError(f"Services inconnus dans {profile.profile_id}: {sorted(unknown)}")
    return profiles


def with_profile(config: HospitalConfig, profile: ProfileDefinition) -> HospitalConfig:
    """Retourne une copie de la configuration avec les poids du profil."""
    if profile.objective_weights is None:
        return config
    return config.model_copy(update={"objective_weights": profile.objective_weights})
