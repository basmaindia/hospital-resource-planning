"""Stratégie naïve : partage proportionnel, sans priorité de service."""

from datetime import UTC, datetime

import pandas as pd

from hospital_planning.domain.contracts import HospitalConfig
from hospital_planning.optimization.availability import project_planning_availability
from hospital_planning.optimization.greedy import (
    GreedyResult,
    StaffAssigner,
    StaffSlot,
    build_slots,
    finalize_heuristic,
)


def run_naive(
    demand_requirements: pd.DataFrame,
    bed_requirements: pd.DataFrame,
    staff: pd.DataFrame,
    historical_availability: pd.DataFrame,
    instance_metadata: dict[str, object],
    config: HospitalConfig,
    planning_availability: pd.DataFrame | None = None,
) -> GreedyResult:
    """Construit un plan proportionnel, déterministe et indépendant du profil.

    Les admissions sont acceptées au même taux dans tous les services, et chaque
    besoin en personnel reçoit la même fraction de sa cible. Aucun service n'est
    prioritaire et aucun poids de l'objectif n'intervient dans les décisions.
    """
    started_at = datetime.now(UTC)
    bed_allocations = _allocate_beds_proportionally(demand_requirements, bed_requirements, config)
    if planning_availability is None:
        planning_availability = project_planning_availability(
            staff, historical_availability, bed_allocations["date"], config
        )
    staff_assignments = _assign_staff_proportionally(bed_allocations, staff, planning_availability, config)
    return finalize_heuristic(
        "naive",
        started_at,
        bed_allocations,
        staff_assignments,
        bed_requirements,
        staff,
        planning_availability,
        instance_metadata,
        config,
    )


def apportion(weights: dict[object, float], total: int) -> dict[object, int]:
    """Répartit `total` au prorata des poids (plus forts restes), sans dépasser un poids."""
    weight_sum = sum(weights.values())
    if weight_sum <= 0 or total <= 0:
        return dict.fromkeys(weights, 0)
    ratio = min(1.0, total / weight_sum)
    exact = {key: weight * ratio for key, weight in weights.items()}
    shares = {key: int(value) for key, value in exact.items()}
    remaining = min(total, int(round(weight_sum))) - sum(shares.values())
    # À reste égal, l'ordre des clés départage : le résultat est déterministe.
    for key in sorted(exact, key=lambda item: (shares[item] - exact[item], str(item)))[: max(remaining, 0)]:
        shares[key] += 1
    return shares


def _allocate_beds_proportionally(
    demand_requirements: pd.DataFrame, bed_requirements: pd.DataFrame, config: HospitalConfig
) -> pd.DataFrame:
    """Applique chaque jour un taux d'acceptation unique, borné par les lits du service."""
    demand = demand_requirements[["date", "service", "requested_admissions"]].copy()
    demand["date"] = pd.to_datetime(demand["date"])
    beds = bed_requirements[["date", "service", "occupancy_start", "expected_discharges", "capacity_available"]].copy()
    beds["date"] = pd.to_datetime(beds["date"])
    inputs = demand.merge(beds, on=["date", "service"], validate="one_to_one").sort_values(["date", "service"])
    census = inputs.groupby("service")["occupancy_start"].first().astype(int).to_dict()
    cancelled: dict[tuple[str, pd.Timestamp], int] = {}
    records: list[dict[str, object]] = []
    for date, group in inputs.groupby("date", sort=True):
        day = pd.Timestamp(date)
        start = dict(census)
        discharges: dict[str, int] = {}
        free: dict[str, int] = {}
        for row in group.itertuples(index=False):
            discharges[row.service] = max(int(row.expected_discharges) - cancelled.pop((row.service, day), 0), 0)
            census[row.service] -= discharges[row.service]
            free[row.service] = max(int(row.capacity_available) - census[row.service], 0)
        requested = {row.service: int(row.requested_admissions) for row in group.itertuples(index=False)}
        quotas = apportion(dict(requested), sum(free.values()))
        for row in group.itertuples(index=False):
            service = row.service
            accepted = min(quotas[service], free[service])
            rejected = requested[service] - accepted
            census[service] += accepted
            if rejected:
                key = (service, day + pd.DateOffset(days=config.services[service].length_of_stay_days))
                cancelled[key] = cancelled.get(key, 0) + rejected
            records.append(
                {
                    "date": day,
                    "service": service,
                    "occupancy_start": start[service],
                    "expected_discharges": discharges[service],
                    "requested_admissions": requested[service],
                    "accepted_admissions": accepted,
                    "rejected_admissions": rejected,
                    "occupancy_end": census[service],
                    "opened_beds": census[service],
                    "capacity_available": int(row.capacity_available),
                }
            )
    return pd.DataFrame.from_records(records).sort_values(["date", "service"]).reset_index(drop=True)


def _assign_staff_proportionally(
    bed_allocations: pd.DataFrame, staff: pd.DataFrame, availability: pd.DataFrame, config: HospitalConfig
) -> pd.DataFrame:
    """Vise la même fraction de la cible partout, après la dotation minimale obligatoire."""
    slots = build_slots(bed_allocations, config, dict.fromkeys(config.services, 0))
    capacity = _weekly_capacity(staff, availability)
    quotas: dict[StaffSlot, int] = {}
    for role in config.roles:
        role_targets = {slot: float(slot.target) for slot in slots if slot.role == role}
        quotas.update(apportion(role_targets, capacity.get(role, 0)))
    assigner = StaffAssigner(staff, availability, config)
    for slot in slots:
        assigner.fill(slot, slot.minimum)
    for slot in slots:
        assigner.fill(slot, quotas[slot] - slot.minimum)
    return assigner.assignments()


def _weekly_capacity(staff: pd.DataFrame, availability: pd.DataFrame) -> dict[str, int]:
    """Nombre maximal de postes réalisables par rôle sur l'horizon."""
    available_days = availability[availability["available"]].groupby("staff_id")["date"].nunique()
    limits = staff.set_index("staff_id")["max_shifts"]
    roles = staff.set_index("staff_id")["role"]
    per_person = pd.concat([available_days, limits.reindex(available_days.index)], axis=1).min(axis=1)
    return per_person.groupby(roles.reindex(per_person.index)).sum().astype(int).to_dict()
