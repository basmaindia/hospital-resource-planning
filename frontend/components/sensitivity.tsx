"use client";

import { useEffect, useState } from "react";

import { loadSensitivityManifest, loadSensitivityResults } from "../lib/api-client";
import type { LoadState, SensitivityManifestEntry, SensitivityRow } from "../lib/api-types";
import { fmt, methodColors, methodLabel } from "./dashboard-data";
import { percent } from "./staffing";

/** Rampes à une seule teinte : ordinale pour les courbes, séquentielle pour la heatmap. */
const ordinalRamps: Record<number, string[]> = { 4: ["#86b6ef", "#3987e5", "#1c5cab", "#0d366b"], 5: ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#0d366b"] };
const heatRamp = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"];
const methodOrder = ["naive", "greedy", "milp", "cp_sat"];

type KpiKey = "staff_coverage_rate" | "staff_shortage_total" | "rejected_admissions" | "coverage_rate" | "objective_value";
const kpis: { key: KpiKey; label: string; rate: boolean; higherIsWorse: boolean }[] = [
  { key: "staff_coverage_rate", label: "Postes cibles couverts", rate: true, higherIsWorse: false },
  { key: "staff_shortage_total", label: "Déficit RH (postes)", rate: false, higherIsWorse: true },
  { key: "rejected_admissions", label: "Admissions refusées (patients)", rate: false, higherIsWorse: true },
  { key: "coverage_rate", label: "Couverture de la demande", rate: true, higherIsWorse: false },
  { key: "objective_value", label: "Coût total (objectif)", rate: false, higherIsWorse: true },
];
function show(value: number | null | undefined, rate: boolean) { return value === null || value === undefined ? "n/a" : rate ? percent(value) : fmt.format(Math.round(value)); }
function axis(value: number, rate: boolean) { return rate ? `${Math.round(value * 100)} %` : new Intl.NumberFormat("fr-FR", { notation: "compact", maximumFractionDigits: 1 }).format(value); }
function sorted(values: number[]) { return [...new Set(values)].sort((a, b) => a - b); }
const demandLabel = (value: number) => `×${value.toFixed(2).replace(".", ",")}`;
const rateLabel = (value: number) => `${Math.round(value * 100)} %`;

type Point = { value: number | null; feasible: boolean };
type Series = { name: string; color: string; points: Point[] };

function Curves({ title, xTitle, xLabels, series, rate }: { title: string; xTitle: string; xLabels: string[]; series: Series[]; rate: boolean }) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 560; const height = 270; const left = 54; const right = 70; const top = 16; const bottom = 44;
  const values = series.flatMap((item) => item.points.map((point) => point.value)).filter((value): value is number => value !== null);
  if (!values.length) return <section className="card"><h2>{title}</h2><p>Aucun résultat calculé pour cette sélection.</p></section>;
  const rawMin = Math.min(...values); const rawMax = Math.max(...values); const pad = (rawMax - rawMin || Math.abs(rawMax) || 1) * 0.12;
  const min = Math.max(0, rawMin - pad); const max = rate ? Math.min(1, rawMax + pad) : rawMax + pad;
  const x = (index: number) => left + (xLabels.length === 1 ? 0.5 : index / (xLabels.length - 1)) * (width - left - right);
  const y = (value: number) => top + (1 - (value - min) / (max - min)) * (height - top - bottom);
  const step = (width - left - right) / Math.max(1, xLabels.length - 1);
  // Étiquettes directes en bout de courbe, écartées pour ne pas se chevaucher.
  const ends = series.map((item) => { const last = item.points[item.points.length - 1]; return { item, y: last?.value === null || last === undefined ? null : y(last.value) }; }).filter((end): end is { item: Series; y: number } => end.y !== null).sort((a, b) => a.y - b.y);
  ends.forEach((end, index) => { if (index > 0 && end.y - ends[index - 1].y < 13) end.y = ends[index - 1].y + 13; });
  return <section className="card">
    <h2>{title}</h2>
    <div className="curve-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
        {[0, 0.5, 1].map((ratio) => { const value = min + ratio * (max - min); return <g key={ratio}><line className="chart-grid" x1={left} x2={width - right} y1={y(value)} y2={y(value)} /><text x={left - 7} y={y(value) + 4} textAnchor="end" fontSize="11" fill="#587070">{axis(value, rate)}</text></g>; })}
        {xLabels.map((label, index) => <text key={label} x={x(index)} y={height - bottom + 18} textAnchor="middle" fontSize="11" fill="#587070">{label}</text>)}
        <text x={left + (width - left - right) / 2} y={height - 6} textAnchor="middle" fontSize="11" fill="#587070">{xTitle}</text>
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={top} y2={height - bottom} stroke="#8aa3a3" strokeDasharray="3 3" />}
        {series.map((item) => <g key={item.name}>
          <polyline fill="none" stroke={item.color} strokeWidth="2" points={item.points.map((point, index) => point.value === null ? null : `${x(index)},${y(point.value)}`).filter(Boolean).join(" ")} />
          {item.points.map((point, index) => point.value === null ? null : <circle key={index} cx={x(index)} cy={y(point.value)} r="4.5" fill={point.feasible ? item.color : "#ffffff"} stroke={point.feasible ? "#ffffff" : item.color} strokeWidth="2" />)}
        </g>)}
        {ends.map((end) => <text key={end.item.name} x={width - right + 10} y={end.y + 4} fontSize="11" fill="#234346">{end.item.name}</text>)}
        {xLabels.map((label, index) => <rect key={label} x={x(index) - step / 2} y={top} width={step} height={height - top - bottom} fill="transparent" onMouseEnter={() => setHover(index)} onMouseLeave={() => setHover(null)} />)}
      </svg>
      {hover !== null && <div className="curve-tooltip" style={hover > xLabels.length / 2 ? { left: `${(left / width) * 100 + 1}%` } : { right: `${(right / width) * 100 + 1}%` }}><strong>{xTitle} : {xLabels[hover]}</strong>{series.map((item) => { const point = item.points[hover]; return <span key={item.name}><i style={{ background: item.color }} /><b>{show(point?.value, rate)}</b> {item.name}{point && point.value !== null && !point.feasible ? " · irréalisable" : ""}</span>; })}</div>}
    </div>
    <div className="curve-legend">{series.map((item) => <span key={item.name}><i style={{ background: item.color }} />{item.name}</span>)}</div>
  </section>;
}

function Heatmap({ rows, kpi, absences, demands }: { rows: SensitivityRow[]; kpi: (typeof kpis)[number]; absences: number[]; demands: number[] }) {
  const cell = (absence: number, demand: number) => rows.find((row) => row.absence_rate === absence && row.demand_multiplier === demand);
  const values = rows.map((row) => row[kpi.key]).filter((value): value is number => value !== null && value !== undefined);
  const min = Math.min(...values); const max = Math.max(...values);
  // Plus foncé = plus défavorable, quel que soit le sens de l'indicateur.
  const level = (value: number) => { const ratio = max === min ? 0 : (value - min) / (max - min); return Math.min(heatRamp.length - 1, Math.floor((kpi.higherIsWorse ? ratio : 1 - ratio) * heatRamp.length)); };
  return <section className="card">
    <h2>{kpi.label} — absences × demande</h2>
    <div className="table-wrap"><table className="heatmap" aria-label={`${kpi.label} selon les absences et la demande`}><thead><tr><th scope="col">Absences</th>{demands.map((demand) => <th scope="col" key={demand}>Demande {demandLabel(demand)}</th>)}</tr></thead><tbody>{absences.map((absence) => <tr key={absence}><th scope="row">{rateLabel(absence)}</th>{demands.map((demand) => { const row = cell(absence, demand); const value = row?.[kpi.key]; if (!row || value === null || value === undefined) return <td key={demand} className="heat-cell heat-empty">n/a</td>; const step = level(value); return <td key={demand} tabIndex={0} className="heat-cell" style={{ background: heatRamp[step], color: step >= 3 ? "#ffffff" : "#12312f" }} title={`Absences ${rateLabel(absence)}, demande ${demandLabel(demand)} : ${show(value, kpi.rate)}${row.validation_passed ? "" : " — contraintes non respectées"}`}>{show(value, kpi.rate)}{row.validation_passed ? "" : " ✕"}</td>; })}</tr>)}</tbody></table></div>
    <div className="heat-legend" aria-hidden="true"><span>favorable</span>{heatRamp.map((color) => <i key={color} style={{ background: color }} />)}<span>défavorable</span></div>
    <p className="chart-caption">✕ = contraintes non respectées : la valeur ne décrit pas un plan réalisable.</p>
  </section>;
}

export function SensitivityView({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [manifest, setManifest] = useState<LoadState<SensitivityManifestEntry[]>>({ status: "loading" });
  const [results, setResults] = useState<LoadState<SensitivityRow[]>>({ status: "loading" });
  const [method, setMethod] = useState("greedy");
  const [capacity, setCapacity] = useState(0);
  const [kpiKey, setKpiKey] = useState<KpiKey>("staff_coverage_rate");
  useEffect(() => { let active = true; void loadSensitivityManifest(apiBaseUrl).then((item) => { if (active) setManifest(item); }); void loadSensitivityResults(apiBaseUrl).then((item) => { if (active) setResults(item); }); return () => { active = false; }; }, [apiBaseUrl]);
  const header = <header className="page-header"><div><p className="eyebrow">Pilotage synthétique · grille de 80 cas</p><h1>Analyse de sensibilité</h1><p className="lead">Effet des absences, de la demande et des fermetures de lits sur les résultats, profil équilibré. Les valeurs viennent de calculs enregistrés.</p></div></header>;
  if (results.status !== "success") return <>{header}<section className="card empty-state"><div><h2>{results.status === "loading" ? "Chargement…" : results.status === "empty" ? "Aucune donnée disponible" : "Lecture indisponible"}</h2>{results.status !== "loading" && <p>{results.message}</p>}</div></section></>;
  const rows = results.data;
  const methods = methodOrder.filter((item) => rows.some((row) => row.method_name === item));
  const absences = sorted(rows.map((row) => row.absence_rate));
  const demands = sorted(rows.map((row) => row.demand_multiplier));
  const capacities = sorted(rows.map((row) => row.capacity_reduction));
  const declared = manifest.status === "success" ? manifest.data.length : null;
  const kpi = kpis.find((item) => item.key === kpiKey) ?? kpis[0];
  const selection = rows.filter((row) => row.method_name === method && row.capacity_reduction === capacity);
  const point = (candidates: SensitivityRow[], absence: number, demand: number, key: KpiKey): Point => { const row = candidates.find((item) => item.absence_rate === absence && item.demand_multiplier === demand); return { value: row?.[key] ?? null, feasible: row?.validation_passed === true }; };
  const byDemand: Series[] = demands.map((demand, index) => ({ name: demandLabel(demand), color: (ordinalRamps[demands.length] ?? heatRamp)[index], points: absences.map((absence) => point(selection, absence, demand, "staff_coverage_rate")) }));
  const byAbsence: Series[] = absences.map((absence, index) => ({ name: `Abs. ${rateLabel(absence)}`, color: (ordinalRamps[absences.length] ?? heatRamp)[index], points: demands.map((demand) => point(selection, absence, demand, "objective_value")) }));
  const byMethod: Series[] = methods.map((item) => ({ name: methodLabel(item), color: methodColors[item], points: absences.map((absence) => point(rows.filter((row) => row.method_name === item && row.capacity_reduction === capacity), absence, 1, kpiKey)) }));
  const infeasible = selection.filter((row) => row.validation_passed === false).length;
  return <>{header}
    <div className="kpi-grid">
      <section className="card kpi"><p>Cas calculés</p><strong>{new Set(rows.map((row) => row.scenario_id)).size}{declared === null ? "" : ` / ${declared}`}</strong><span>5 absences × 4 demandes × 4 fermetures</span></section>
      <section className="card kpi"><p>Méthodes</p><strong>{methods.length}</strong><span>{methods.map((item) => `${methodLabel(item)} : ${rows.filter((row) => row.method_name === item).length} cas`).join(" · ")}</span></section>
      <section className="card kpi"><p>Contraintes respectées</p><strong>{rows.filter((row) => row.validation_passed).length} / {rows.length}</strong><span>résultats, toutes méthodes</span></section>
      <section className="card kpi"><p>Postes cibles couverts</p><strong>{(() => { const values = selection.map((row) => row.staff_coverage_rate).filter((value): value is number => value !== null && value !== undefined); return values.length ? `${percent(Math.min(...values), 0)} à ${percent(Math.max(...values), 0)}` : "n/a"; })()}</strong><span>sélection : {methodLabel(method)}, {rateLabel(capacity)} de lits fermés</span></section>
    </div>
    <section className="card"><div className="filter-group sensitivity-filters">
      <label>Méthode<select value={method} onChange={(event) => setMethod(event.target.value)}>{methods.map((item) => <option key={item} value={item}>{methodLabel(item)}</option>)}</select></label>
      <label>Lits fermés<select value={capacity} onChange={(event) => setCapacity(Number(event.target.value))}>{capacities.map((item) => <option key={item} value={item}>{rateLabel(item)}</option>)}</select></label>
      <label>Indicateur<select value={kpiKey} onChange={(event) => setKpiKey(event.target.value as KpiKey)}>{kpis.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label>
    </div>
      <p className="chart-caption">Méthode et lits fermés s’appliquent à tous les graphiques (la comparaison des méthodes les montre toutes). L’indicateur s’applique à la heatmap et à la comparaison des méthodes.</p>
      {infeasible > 0 && <p className="sim-warning">⚠ {infeasible} cas sur {selection.length} de cette sélection ne respectent pas les contraintes (points évidés, cases ✕) : avec 20 % de lits fermés, les patients déjà présents en Médecine dépassent les lits restants.</p>}
    </section>
    <div className="two-columns" style={{ marginTop: 14 }}>
      <Curves title="Postes cibles couverts selon l’absentéisme, par niveau de demande" xTitle="Taux d’absence" xLabels={absences.map(rateLabel)} series={byDemand} rate />
      <Curves title="Coût total selon la demande, par taux d’absence" xTitle="Multiplicateur de demande" xLabels={demands.map(demandLabel)} series={byAbsence} rate={false} />
    </div>
    <div className="card-stack">
      <Heatmap rows={selection} kpi={kpi} absences={absences} demands={demands} />
      <Curves title={`${kpi.label} par méthode, demande ×1,00`} xTitle="Taux d’absence" xLabels={absences.map(rateLabel)} series={byMethod} rate={kpi.rate} />
      <section className="card"><details><summary>Tableau des {selection.length} cas affichés</summary><div className="table-wrap"><table><thead><tr><th>Cas</th><th>Absences</th><th>Demande</th><th>Lits fermés</th>{kpis.map((item) => <th key={item.key}>{item.label}</th>)}<th>Contraintes</th></tr></thead><tbody>{selection.map((row) => <tr key={row.scenario_id}><td>{row.scenario_id}</td><td>{rateLabel(row.absence_rate)}</td><td>{demandLabel(row.demand_multiplier)}</td><td>{rateLabel(row.capacity_reduction)}</td>{kpis.map((item) => <td key={item.key}>{show(row[item.key], item.rate)}</td>)}<td>{row.validation_passed ? "Respectées" : row.validation_passed === false ? "Non respectées" : "n/a"}</td></tr>)}</tbody></table></div></details></section>
    </div>
  </>;
}
