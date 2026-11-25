"use client";

import { Fragment, useState } from "react";

import type { StaffAssignmentPoint, StaffCoveragePoint } from "../lib/api-types";
import { fmt, roleLabels, serviceLabels, shiftLabels, shiftOrder } from "./dashboard-data";

/** Rampe séquentielle à une seule teinte : du « presque rien » au maximum affiché. */
const heatRamp = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"];
const shiftColors: Record<string, string> = { MORNING: "#2a78d6", EVENING: "#eb6834", NIGHT: "#4a3aa7" };
const weekday = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "2-digit", month: "2-digit", timeZone: "UTC" });

function dayLabel(date: string) { return weekday.format(new Date(`${date.slice(0, 10)}T00:00:00Z`)); }
function unique(values: string[]) { return [...new Set(values)]; }
function sum(rows: StaffCoveragePoint[], key: "target_staff" | "assigned_staff" | "target_shortage") { return rows.reduce((total, row) => total + row[key], 0); }

/** Part des postes cibles réellement pourvus ; un surplus ailleurs ne compense pas un manque. */
export function coveredRate(rows: StaffCoveragePoint[]): number | null {
  const target = sum(rows, "target_staff");
  return target === 0 ? null : 1 - sum(rows, "target_shortage") / target;
}
export function percent(value: number | null | undefined, digits = 1) {
  return value === null || value === undefined ? "n/a" : `${(value * 100).toFixed(digits).replace(".", ",")} %`;
}
export function constraintsLabel(passed: boolean | null | undefined) {
  return passed ? "Respectées" : passed === false ? "Non respectées" : "n/a";
}

function Filter({ label, value, options, onChange }: { label: string; value: string; options: [string, string][]; onChange: (value: string) => void }) {
  return <label>{label}<select value={value} onChange={(event) => onChange(event.target.value)}>{options.map(([id, text]) => <option key={id} value={id}>{text}</option>)}</select></label>;
}
function shiftOptions(shifts: string[]): [string, string][] { return [["ALL", "Tous les postes"], ...shifts.map((item): [string, string] => [item, shiftLabels[item] ?? item])]; }
function roleOptions(roles: string[]): [string, string][] { return [["ALL", "Tous les rôles"], ...roles.map((item): [string, string] => [item, roleLabels[item] ?? item])]; }
function sortShifts(shifts: string[]) { return [...shifts].sort((a, b) => (shiftOrder[a] ?? 9) - (shiftOrder[b] ?? 9)); }

export function ShortageHeatmap({ coverage }: { coverage: StaffCoveragePoint[] }) {
  const [shift, setShift] = useState("ALL");
  const [role, setRole] = useState("ALL");
  const shifts = sortShifts(unique(coverage.map((row) => row.shift)));
  const roles = unique(coverage.map((row) => row.role));
  const dates = unique(coverage.map((row) => row.date)).sort();
  const services = unique(coverage.map((row) => row.service)).sort();
  const filtered = coverage.filter((row) => (shift === "ALL" || row.shift === shift) && (role === "ALL" || row.role === role));
  const cell = (service: string, date: string) => filtered.filter((row) => row.service === service && row.date === date);
  const max = Math.max(1, ...services.flatMap((service) => dates.map((date) => sum(cell(service, date), "target_shortage"))));
  const step = (value: number) => Math.min(heatRamp.length - 1, Math.floor((value / max) * heatRamp.length));
  const style = (value: number) => value === 0 ? { background: "#ffffff", color: "#355456" } : { background: heatRamp[step(value)], color: step(value) >= 3 ? "#ffffff" : "#12312f" };
  return <section className="card">
    <h2>Postes manquants par service et par jour</h2>
    <div className="filter-group" style={{ margin: "12px 0" }}>
      <Filter label="Poste" value={shift} options={shiftOptions(shifts)} onChange={setShift} />
      <Filter label="Rôle" value={role} options={roleOptions(roles)} onChange={setRole} />
    </div>
    <div className="table-wrap"><table className="heatmap" aria-label="Postes cibles manquants par service et par jour">
      <thead><tr><th scope="col">Service</th>{dates.map((date) => <th scope="col" key={date}>{dayLabel(date)}</th>)}<th scope="col">Semaine</th><th scope="col">% couverts</th></tr></thead>
      <tbody>{services.map((service) => {
        const serviceRows = filtered.filter((row) => row.service === service);
        return <tr key={service}><th scope="row">{service} <span>{serviceLabels[service] ?? ""}</span></th>
          {dates.map((date) => { const rows = cell(service, date); const missing = sum(rows, "target_shortage"); const target = sum(rows, "target_staff"); return <td key={date} className="heat-cell" tabIndex={0} style={style(missing)} title={`${service} · ${dayLabel(date)} : ${missing} poste(s) manquant(s) sur ${target} cible(s), ${percent(coveredRate(rows), 0)} couverts`}>{missing}</td>; })}
          <td className="heat-total">{fmt.format(sum(serviceRows, "target_shortage"))} / {fmt.format(sum(serviceRows, "target_staff"))}</td><td className="heat-total">{percent(coveredRate(serviceRows), 0)}</td></tr>;
      })}</tbody>
    </table></div>
    <div className="heat-legend" aria-hidden="true"><span>0</span>{heatRamp.map((color) => <i key={color} style={{ background: color }} />)}<span>{max} postes manquants</span></div>
    <p className="chart-caption">Un poste manquant est une place cible non pourvue (service × jour × poste × rôle). Survolez une case pour le détail.</p>
  </section>;
}

export function CoverageMatrix({ coverage }: { coverage: StaffCoveragePoint[] }) {
  const shifts = sortShifts(unique(coverage.map((row) => row.shift)));
  const roles = unique(coverage.map((row) => row.role));
  const services = unique(coverage.map((row) => row.service)).sort();
  const cell = (rows: StaffCoveragePoint[]) => { const rate = coveredRate(rows); return <td className="coverage-cell" title={`${sum(rows, "target_shortage")} poste(s) manquant(s) ; ${sum(rows, "assigned_staff")} affectation(s)`}><b>{percent(rate, 0)}</b><span>{fmt.format(sum(rows, "target_staff") - sum(rows, "target_shortage"))} / {fmt.format(sum(rows, "target_staff"))}</span><i className="coverage-bar"><i style={{ width: `${(rate ?? 0) * 100}%` }} /></i></td>; };
  return <section className="card">
    <h2>Couverture RH par service, rôle et poste</h2>
    <p>Part des postes cibles couverts sur la semaine, et nombre couvert / cible.</p>
    <div className="table-wrap"><table><thead><tr><th>Service</th><th>Rôle</th>{shifts.map((item) => <th key={item}>{shiftLabels[item] ?? item}</th>)}<th>Tous les postes</th></tr></thead>
      <tbody>{services.flatMap((service) => [...roles, "ALL"].map((role) => {
        const rows = coverage.filter((row) => row.service === service && (role === "ALL" || row.role === role));
        return <tr key={`${service}-${role}`} className={role === "ALL" ? "subtotal-row" : undefined}><td>{service}</td><td>{role === "ALL" ? "Total service" : roleLabels[role] ?? role}</td>{shifts.map((item) => <Fragment key={item}>{cell(rows.filter((row) => row.shift === item))}</Fragment>)}{cell(rows)}</tr>;
      }))}</tbody></table></div>
  </section>;
}

export function StaffPlanning({ assignments, coverage, service }: { assignments: StaffAssignmentPoint[]; coverage: StaffCoveragePoint[]; service: string }) {
  const [role, setRole] = useState("ALL");
  const [shift, setShift] = useState("ALL");
  const dates = unique(coverage.map((row) => row.date)).sort();
  const shifts = sortShifts(unique(coverage.map((row) => row.shift)));
  const roles = unique(coverage.map((row) => row.role));
  const inService = assignments.filter((row) => row.service === service && (role === "ALL" || row.role === role) && (shift === "ALL" || row.shift === shift));
  const people = unique(inService.map((row) => row.staff_id)).sort();
  const byPerson = new Map<string, StaffAssignmentPoint[]>();
  for (const row of assignments) byPerson.set(row.staff_id, [...(byPerson.get(row.staff_id) ?? []), row]);
  const serviceCoverage = coverage.filter((row) => row.service === service && (role === "ALL" || row.role === role));
  return <section className="card">
    <h2>Planning du personnel — {service} {serviceLabels[service] ? `(${serviceLabels[service]})` : ""}</h2>
    <div className="filter-group" style={{ margin: "12px 0" }}>
      <Filter label="Rôle" value={role} options={roleOptions(roles)} onChange={setRole} />
      <Filter label="Poste" value={shift} options={shiftOptions(shifts)} onChange={setShift} />
    </div>
    <div className="shift-legend">{shifts.map((item) => <span key={item}><i style={{ background: shiftColors[item] ?? "#52514e" }} />{(shiftLabels[item] ?? item).slice(0, 1)} = {shiftLabels[item] ?? item}</span>)}<span className="muted-shift">gris = poste dans un autre service</span></div>
    <div className="table-wrap"><table className="planning-summary"><thead><tr><th scope="col">Effectif / cible</th>{dates.map((date) => <th scope="col" key={date}>{dayLabel(date)}</th>)}</tr></thead><tbody>{shifts.map((item) => <tr key={item}><th scope="row">{shiftLabels[item] ?? item}</th>{dates.map((date) => { const rows = serviceCoverage.filter((row) => row.shift === item && row.date === date); return <td key={date} title={`${percent(coveredRate(rows), 0)} des postes cibles couverts`}>{sum(rows, "assigned_staff")} / {sum(rows, "target_staff")}</td>; })}</tr>)}</tbody></table></div>
    {people.length ? <div className="table-wrap planning-scroll"><table className="planning-grid"><thead><tr><th scope="col">Agent ({people.length})</th><th scope="col">Rôle</th>{dates.map((date) => <th scope="col" key={date}>{dayLabel(date)}</th>)}<th scope="col">Postes</th></tr></thead><tbody>{people.map((person) => {
      const rows = byPerson.get(person) ?? [];
      return <tr key={person}><th scope="row">{person}</th><td>{roleLabels[rows[0]?.role ?? ""] ?? rows[0]?.role}</td>{dates.map((date) => { const item = rows.find((row) => row.date === date); if (!item) return <td key={date} className="planning-off" aria-label="Repos">·</td>; const here = item.service === service; const name = shiftLabels[item.shift] ?? item.shift; return <td key={date}><span className={here ? "shift-chip" : "shift-chip muted-shift"} style={here ? { borderLeftColor: shiftColors[item.shift] ?? "#52514e" } : undefined} title={`${person} · ${dayLabel(date)} : ${name}, ${item.service}`}>{name.slice(0, 1)}{here ? "" : ` ${item.service}`}</span></td>; })}<td>{rows.length}</td></tr>;
    })}</tbody></table></div> : <p>Aucune affectation pour cette sélection.</p>}
    <p className="chart-caption">Agents synthétiques ayant au moins un poste dans ce service sur la semaine. « Postes » compte toute leur semaine, tous services confondus.</p>
  </section>;
}
