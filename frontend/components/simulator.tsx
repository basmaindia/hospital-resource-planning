"use client";

import { useCallback, useEffect, useState } from "react";

import { loadHospitalConfig, loadJob, loadProfiles, loadScenarioComparison, submitExperiment } from "../lib/api-client";
import type { CustomScenarioRequest, ExperimentMetric, HospitalConfig, JobResponse, LoadState, OperationalArtifact, Profile } from "../lib/api-types";
import { fmt, methodLabel, serviceLabels } from "./dashboard-data";
import { constraintsLabel, percent } from "./staffing";

const heuristics = ["naive", "greedy"] as const;
const exactSolvers = ["milp", "cp_sat"] as const;
/** Construction du modèle, validation et écriture, en plus du budget du solveur. */
const solverOverheadSeconds = 4;
const heuristicSeconds = 1;

type Kpi = { key: "rejected_admissions" | "coverage_rate" | "staff_shortage_total" | "staff_coverage_rate"; label: string; unit: string; lowerIsBetter: boolean; rate: boolean };
const kpis: Kpi[] = [
  { key: "rejected_admissions", label: "Admissions refusées", unit: "patients", lowerIsBetter: true, rate: false },
  { key: "coverage_rate", label: "Couverture de la demande", unit: "", lowerIsBetter: false, rate: true },
  { key: "staff_shortage_total", label: "Déficit RH", unit: "postes manquants", lowerIsBetter: true, rate: false },
  { key: "staff_coverage_rate", label: "Postes cibles couverts", unit: "", lowerIsBetter: false, rate: true },
];
function shown(kpi: Kpi, value: number | null | undefined) { return value === null || value === undefined ? "n/a" : kpi.rate ? percent(value) : fmt.format(value); }
function Gap({ kpi, simulated, reference, feasible }: { kpi: Kpi; simulated: number | null | undefined; reference: number | null | undefined; feasible: boolean }) {
  // Un plan irréalisable ne peut pas être « mieux » que S0.
  if (!feasible) return <span className="gap gap-none">non comparable</span>;
  if (simulated === null || simulated === undefined || reference === null || reference === undefined) return <span className="gap gap-none">écart n/a</span>;
  const delta = simulated - reference;
  const rounded = kpi.rate ? Math.round(delta * 1000) / 10 : delta;
  if (rounded === 0) return <span className="gap gap-none">= S0</span>;
  const better = (delta < 0) === kpi.lowerIsBetter;
  const text = `${rounded > 0 ? "+" : "−"}${fmt.format(Math.abs(rounded))}${kpi.rate ? " pt" : ""}`;
  return <span className={better ? "gap gap-better" : "gap gap-worse"}>{rounded > 0 ? "▲" : "▼"} {text} <small>{better ? "mieux" : "moins bien"}</small></span>;
}

/** Part maximale de lits qu'on peut fermer sans expulser des patients déjà admis. */
function closureLimit(operational: LoadState<OperationalArtifact>, service: string | null): number | null {
  if (operational.status !== "success") return null;
  const limits = [...new Set(operational.data.beds.map((row) => row.service))].filter((item) => service === null || item === service).map((item) => {
    const rows = operational.data.beds.filter((row) => row.service === item).sort((a, b) => a.date.localeCompare(b.date));
    // Sans aucune nouvelle admission, le recensement ne fait que décroître : le premier soir est le plus contraint.
    const first = rows[0];
    return first ? 1 - (first.occupancy_start - first.expected_discharges) / first.capacity_available : 1;
  });
  return limits.length ? Math.max(0, Math.min(...limits)) : null;
}

type Props = { apiBaseUrl: string; operational: LoadState<OperationalArtifact>; onRefresh: () => void; onOpen: (scenarioId: string, experimentId: string, method: string) => void };
export function SimulatorView({ apiBaseUrl, operational, onRefresh, onOpen }: Props) {
  const [config, setConfig] = useState<LoadState<HospitalConfig>>({ status: "loading" });
  const [profiles, setProfiles] = useState<LoadState<Profile[]>>({ status: "loading" });
  const [profileId, setProfileId] = useState("equilibre");
  const [demand, setDemand] = useState(125);
  const [demandService, setDemandService] = useState("ALL");
  const [absence, setAbsence] = useState(10);
  const [closure, setClosure] = useState(0);
  const [closureService, setClosureService] = useState("ALL");
  const [methods, setMethods] = useState<string[]>([...heuristics]);
  const [job, setJob] = useState<JobResponse | null>(null);
  const [startedAt, setStartedAt] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [message, setMessage] = useState<string | null>(null);
  const [custom, setCustom] = useState<ExperimentMetric[]>([]);
  const [reference, setReference] = useState<ExperimentMetric[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const running = job !== null && ["QUEUED", "RUNNING"].includes(job.status);

  const reload = useCallback(async () => {
    const [simulations, scenarios] = await Promise.all([loadScenarioComparison(apiBaseUrl, profileId, "custom"), loadScenarioComparison(apiBaseUrl, profileId)]);
    setCustom(simulations.status === "success" ? simulations.data : []);
    setReference(scenarios.status === "success" ? scenarios.data.filter((row) => row.scenario_id === "S0_BASELINE") : []);
    const failure = [simulations, scenarios].find((item) => item.status === "error");
    setMessage(failure?.status === "error" ? failure.message : null);
  }, [apiBaseUrl, profileId]);

  useEffect(() => { void loadHospitalConfig(apiBaseUrl).then(setConfig); void loadProfiles(apiBaseUrl).then(setProfiles); }, [apiBaseUrl]);
  useEffect(() => { setSelected(null); void reload(); }, [reload]);
  useEffect(() => {
    if (!running || !job) return;
    const timer = window.setTimeout(() => {
      setElapsed(Math.round((Date.now() - startedAt) / 1000));
      void loadJob(apiBaseUrl, job.job_id).then((next) => {
        setJob(next);
        if (next.status === "COMPLETED") {
          setElapsed(Math.round((Date.now() - startedAt) / 1000));
          void reload().then(() => setSelected(next.experiment_ids[0] ?? null));
          onRefresh();
        }
      }).catch((error: unknown) => { setJob(null); setMessage(error instanceof Error ? error.message : "Erreur de suivi de la simulation."); });
    }, 500);
    return () => window.clearTimeout(timer);
  }, [apiBaseUrl, job, running, startedAt, reload, onRefresh]);

  const services = config.status === "success" ? Object.keys(config.data.services) : [];
  const solverLimit = config.status === "success" ? config.data.planning_policy.solver_time_limit_seconds : null;
  const methodSeconds = (method: string) => (heuristics as readonly string[]).includes(method) ? heuristicSeconds : solverLimit === null ? null : solverLimit + solverOverheadSeconds;
  const estimates = methods.map(methodSeconds);
  const total = estimates.includes(null) ? null : estimates.reduce<number>((acc, value) => acc + (value ?? 0), 2);
  const limit = closureLimit(operational, closureService === "ALL" ? null : closureService);
  const tooManyClosures = limit !== null && closure / 100 > limit;

  const launch = async () => {
    const request: CustomScenarioRequest = { demand_multiplier: demand / 100, demand_service: demandService === "ALL" ? null : demandService, absence_rate: absence / 100, closure_rate: closure / 100, closure_service: closureService === "ALL" ? null : closureService };
    setMessage(null); setElapsed(0); setStartedAt(Date.now());
    try { setJob(await submitExperiment(apiBaseUrl, { custom_scenario: request, methods: [...heuristics, ...exactSolvers].filter((item) => methods.includes(item)), profile_id: profileId })); }
    catch (error) { setJob(null); setMessage(error instanceof Error ? error.message : "Lancement impossible."); }
  };
  const toggle = (method: string) => setMethods((current) => current.includes(method) ? current.filter((item) => item !== method) : [...current, method]);
  const experimentIds = [...new Set(custom.map((row) => row.experiment_id))];
  const currentId = selected !== null && experimentIds.includes(selected) ? selected : experimentIds[0] ?? null;
  const rows = custom.filter((row) => row.experiment_id === currentId);
  const broken = rows.filter((row) => row.validation_passed === false || row.objective_value === null);
  const serviceOptions = (all: string) => <><option value="ALL">{all}</option>{services.map((item) => <option key={item} value={item}>{item} · {serviceLabels[item] ?? item}</option>)}</>;

  return <>
    <header className="page-header"><div><p className="eyebrow">Pilotage synthétique · scénario personnalisé</p><h1>Simulateur</h1><p className="lead">Réglez une situation de crise, lancez le calcul et comparez le résultat à S0. Les simulations sont enregistrées à part des scénarios S0–S5.</p></div></header>
    <div className="simulator-layout">
      <section className="card simulator-form">
        <h2>Réglages</h2>
        <fieldset><legend>Demande</legend>
          <label>Multiplicateur d’admissions <output>×{(demand / 100).toFixed(2).replace(".", ",")}</output><input type="range" min={100} max={200} step={5} value={demand} onChange={(event) => setDemand(Number(event.target.value))} /></label>
          <label>Service concerné<select value={demandService} onChange={(event) => setDemandService(event.target.value)}>{serviceOptions("Tous les services")}</select></label>
        </fieldset>
        <fieldset><legend>Personnel</legend>
          <label>Taux d’absence <output>{absence} %</output><input type="range" min={0} max={50} step={5} value={absence} onChange={(event) => setAbsence(Number(event.target.value))} /></label>
        </fieldset>
        <fieldset><legend>Lits</legend>
          <label>Lits fermés <output>{closure} %</output><input type="range" min={0} max={50} step={5} value={closure} onChange={(event) => setClosure(Number(event.target.value))} /></label>
          <label>Service concerné<select value={closureService} onChange={(event) => setClosureService(event.target.value)}>{serviceOptions("Tous les services")}</select></label>
          {tooManyClosures && limit !== null && <p className="sim-warning">⚠ Au-delà de {percent(limit, 0)} de lits fermés ici, les patients déjà présents le premier jour dépassent les lits restants : aucun plan ne peut respecter les contraintes.</p>}
        </fieldset>
        <fieldset><legend>Objectif et méthodes</legend>
          <label>Profil de pondération<select value={profileId} disabled={running} onChange={(event) => setProfileId(event.target.value)}>{profiles.status === "success" ? profiles.data.map((item) => <option key={item.profile_id} value={item.profile_id}>{item.label}</option>) : <option value={profileId}>{profileId}</option>}</select></label>
          <div className="method-checks">{[...heuristics, ...exactSolvers].map((method) => { const seconds = methodSeconds(method); return <label key={method} className="method-check"><input type="checkbox" checked={methods.includes(method)} onChange={() => toggle(method)} /> {methodLabel(method)} <small>{seconds === null ? "durée n/a" : seconds <= heuristicSeconds ? "≈ 1 s" : `≈ ${seconds} s`}</small></label>; })}</div>
        </fieldset>
        <button className="primary-button" type="button" disabled={running || methods.length === 0} onClick={() => void launch()}>{running ? `Calcul en cours… ${elapsed} s` : `Lancer la simulation${total === null ? "" : ` (≈ ${total} s)`}`}</button>
        {running && <p className="chart-caption">{total === null ? "Durée estimée indisponible." : `Durée estimée ≈ ${total} s${elapsed > total + 5 ? " (le premier lancement lit les données, une autre expérience peut être en file)" : ""}.`} Le calcul continue si vous changez de vue.</p>}
        {job?.status === "COMPLETED" && <p className="notice">Simulation terminée en {elapsed} s et enregistrée.</p>}
        {job?.status === "FAILED" && <p className="data-note">Échec : {job.error_message ?? "erreur inconnue"}</p>}
        {message && <p className="data-note">{message}</p>}
      </section>

      <div className="card-stack">
        {currentId && rows.length ? <>
          <section className="card">
            <div className="sim-title"><div><h2>{rows[0].scenario_description || rows[0].scenario_id}</h2><p className="chart-caption">{rows[0].scenario_id} · profil {profiles.status === "success" ? profiles.data.find((item) => item.profile_id === profileId)?.label ?? profileId : profileId} · comparé à S0, même profil et même méthode</p></div></div>
            {broken.length > 0 && <p className="sim-warning">⚠ {broken.map((row) => row.objective_value === null ? `${methodLabel(row.method_name)} : aucune solution trouvée (${row.native_status ?? row.status})` : `${methodLabel(row.method_name)} : contraintes non respectées (${row.hard_constraint_violations ?? "n/a"} violation(s))`).join(" ; ")}. Ces chiffres ne décrivent pas un plan réalisable.</p>}
            <div className="sim-methods">{rows.map((row) => { const base = reference.find((item) => item.method_name === row.method_name); return <article key={row.method_name} className="sim-method">
              <header><strong>{methodLabel(row.method_name)}</strong><span className={row.validation_passed ? "constraint-ok" : "constraint-ko"}>{row.validation_passed ? "✓" : "✕"} contraintes {constraintsLabel(row.validation_passed).toLowerCase()}</span></header>
              <table className="sim-table"><thead><tr><th>Indicateur</th><th>S0</th><th>Simulation</th><th>Écart</th></tr></thead><tbody>{kpis.map((kpi) => <tr key={kpi.key}><td>{kpi.label}{kpi.unit ? <small> ({kpi.unit})</small> : null}</td><td>{shown(kpi, base?.[kpi.key])}</td><td><b>{shown(kpi, row[kpi.key])}</b></td><td><Gap kpi={kpi} simulated={row[kpi.key]} reference={base?.[kpi.key]} feasible={row.validation_passed === true} /></td></tr>)}</tbody></table>
              <footer><span>{row.runtime_seconds.toFixed(1).replace(".", ",")} s de calcul{base ? "" : " · S0 non calculé avec cette méthode"}</span>{row.objective_value !== null && <button type="button" className="ghost-button" onClick={() => onOpen(row.scenario_id, row.experiment_id, row.method_name)}>Voir l’allocation →</button>}</footer>
            </article>; })}</div>
          </section>
        </> : <section className="card empty-state"><div><h2>Aucune simulation avec ce profil</h2><p>Réglez les paramètres puis lancez la simulation : le résultat s’affichera ici, à côté de S0.</p></div></section>}
        {experimentIds.length > 0 && <section className="card"><h2>Simulations enregistrées ({experimentIds.length})</h2><div className="table-wrap"><table><thead><tr><th>Scénario</th><th>Méthodes</th><th>Date</th><th></th></tr></thead><tbody>{experimentIds.map((id) => { const items = custom.filter((row) => row.experiment_id === id); return <tr key={id} className={id === currentId ? "selected-row" : undefined}><td>{items[0].scenario_description || items[0].scenario_id}</td><td>{items.map((row) => methodLabel(row.method_name)).join(", ")}</td><td>{items[0].created_at ? new Date(items[0].created_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "n/a"}</td><td><button type="button" className="ghost-button" onClick={() => setSelected(id)}>{id === currentId ? "Affichée" : "Afficher"}</button></td></tr>; })}</tbody></table></div></section>}
      </div>
    </div>
  </>;
}
