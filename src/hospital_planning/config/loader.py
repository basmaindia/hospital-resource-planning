"""Chargement strict des fichiers JSON de configuration."""

import json
from pathlib import Path

from hospital_planning.domain.contracts import HospitalConfig


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
