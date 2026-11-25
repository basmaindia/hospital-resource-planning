"""Objectif canonique partagé par les méthodes de planification."""

import pandas as pd

from hospital_planning.domain.contracts import HospitalConfig, ObjectiveComponents


def present_staff_ids(planning_availability: pd.DataFrame) -> set[str]:
    """Professionnels disponibles au moins une fois sur l'horizon."""
    return set(planning_availability.loc[planning_availability["available"].astype(bool), "staff_id"])


def calculate_workload_range(
    staff_assignments: pd.DataFrame, staff: pd.DataFrame, planning_availability: pd.DataFrame
) -> int:
    """Calcule la somme des étendues de charge par rôle parmi les présents.

    Les groupes comparables sont les professionnels actifs du même rôle,
    disponibles au moins une fois sur l'horizon. Un présent sans affectation
    compte avec une charge nulle ; un agent absent sur tout l'horizon est exclu,
    sinon l'étendue resterait au plafond quelle que soit la méthode.
    """
    active_mask = staff["active"] if "active" in staff else pd.Series(True, index=staff.index)
    present = present_staff_ids(planning_availability)
    comparable = staff.loc[active_mask & staff["staff_id"].isin(present), ["staff_id", "role"]].copy()
    if comparable.empty:
        return 0
    assignment_counts = staff_assignments.groupby("staff_id").size().rename("assigned_shifts")
    comparable = comparable.join(assignment_counts, on="staff_id")
    comparable["assigned_shifts"] = comparable["assigned_shifts"].fillna(0).astype(int)
    ranges = comparable.groupby("role")["assigned_shifts"].agg(lambda values: int(values.max() - values.min()))
    return int(ranges.sum())


def calculate_objective_components(
    opened_beds_total: int,
    unmet_by_service: dict[str, int],
    rejected_by_service: dict[str, int],
    shortage_by_service: dict[str, int],
    workload_range: int,
    config: HospitalConfig,
) -> ObjectiveComponents:
    """Applique une seule fois les coefficients entiers du profil actif."""
    weights = config.objective_weights
    opened_bed_cost = opened_beds_total * weights.opened_bed
    unmet_cost = sum(value * weights.unmet_weight(service) for service, value in unmet_by_service.items())
    rejected_cost = sum(value * weights.rejection_weight(service) for service, value in rejected_by_service.items())
    shortage_cost = sum(value * weights.shortage_weight(service) for service, value in shortage_by_service.items())
    imbalance_cost = workload_range * weights.workload_imbalance
    return ObjectiveComponents(
        opened_bed_cost=float(opened_bed_cost),
        unmet_patient_day_cost=float(unmet_cost),
        staff_target_shortage_cost=float(shortage_cost),
        workload_imbalance_cost=float(imbalance_cost),
        rejected_admission_cost=float(rejected_cost),
        total_cost=float(opened_bed_cost + unmet_cost + rejected_cost + shortage_cost + imbalance_cost),
    )


def sum_by_service(table: pd.DataFrame, column: str) -> dict[str, int]:
    """Total entier d'une colonne par service."""
    return {str(service): int(value) for service, value in table.groupby("service")[column].sum().items()}
