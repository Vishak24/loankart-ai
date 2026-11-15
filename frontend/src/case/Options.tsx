import { useState } from "react";
import { useNavigate } from "react-router";
import type { LoanOption, Priority, Recommendations, S } from "../api/client";
import { recommendationService } from "../api/services";
import {
  Bullets, Button, Card, EmptyState, ErrorNotice, LinkButton, Loading, NarrativeCard, Notice, PageTitle, Pill, Stat, decisionTone,
  useAction, useLoad, type Tone,
} from "../components/ui";
import { formatDate, money } from "../format";
import { useCase } from "./CaseLayout";

const PRIORITIES: [Priority, string][] = [
  ["balanced", "Balanced"], ["lowest_emi", "Lowest monthly repayment"], ["lowest_cost", "Lowest total cost"],
  ["no_collateral", "Avoid offering security"], ["fastest", "Fastest decision"],
];
const RULE: Record<S["RuleCheck"]["status"], [Tone, string]> = { pass: ["success", "Met"], fail: ["danger", "Not met"], unresolved: ["amber", "Open"] };

export const payment = (o: Pick<LoanOption, "repayment_type" | "monthly_payment">) =>
  `${money(o.monthly_payment)} ${o.repayment_type === "interest_only" ? "interest a month" : "EMI"}`;

export function Rules({ rules }: { rules: S["RuleCheck"][] }) {
  return (
    <ul className="divide-y divide-line">
      {rules.map((r) => (
        <li key={r.rule} className="grid gap-x-4 gap-y-1 py-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
          <div><p className="font-medium">{r.label}</p><p className="text-sm text-muted">Needs: {r.required} · Yours: {r.actual}</p></div>
          <Pill tone={RULE[r.status][0]}>{RULE[r.status][1]}</Pill>
        </li>
      ))}
    </ul>
  );
}

function Provenance({ source }: { source: S["PolicySource"] }) {
  return <p className="text-sm text-muted">Simulated lender. Fictional policy version {source.policy_version}, effective {formatDate(source.effective_date)}. {source.description}.</p>;
}

function OptionCard({ o, best, compared, onCompare, onSelect, onExplain, busy }: {
  o: LoanOption; best: boolean; compared: boolean; onCompare: () => void; onSelect: () => void; onExplain?: () => void; busy: string | null;
}) {
  return (
    <article className={`rounded-xl border border-line bg-surface p-4 sm:p-6 ${best ? "border-l-4 border-l-teal" : ""}`}>
      <div className="flex flex-wrap items-center gap-2">
        <Pill tone="neutral">Rank {o.rank}</Pill>
        {best && <Pill tone="teal">Best fit against your stated priorities</Pill>}
        <Pill tone={decisionTone(o.decision)}>{o.status_label}</Pill>
      </div>
      <h3 className="mt-3 text-xl font-semibold leading-snug">{o.product_name}</h3>
      <p className="text-muted">{o.lender_name} · {o.lender_type}</p>

      <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-4 lg:grid-cols-4">
        <Stat label="Fresh funds" value={money(o.fresh_funds)} sub={o.takeover_amount ? `loan of ${money(o.suggested_amount)}` : undefined} />
        <Stat label="Monthly repayment" value={money(o.monthly_payment)} sub={o.repayment_type === "interest_only" ? "interest only" : "EMI"} />
        <Stat label="Rate / APR" value={`${o.rate_pct}% / ${o.apr_pct}%`} sub="APR includes fees" />
        <Stat label="Tenure" value={`${o.tenure_months} months`} />
        <Stat label="Total repayment" value={money(o.total_repayment)} sub={`${money(o.total_interest)} interest`} />
        <Stat label="Fees and charges" value={money(o.fees)} sub={`${o.processing_fee_pct}% + ${money(o.other_charges)}`} />
        <Stat label="Cash-flow cover after" value={o.dscr_after == null ? "–" : `${o.dscr_after}x`} />
        <Stat label="Eligibility fit" value={o.eligibility_fit} sub={`score ${o.score} of 100`} />
      </div>
      <p className="mt-3 text-sm text-muted">Illustrative estimates calculated by LoanKart. {o.explanation}</p>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        {o.required_changes.length > 0 && <div><p className="mb-1 font-medium">What you would need to do</p><Bullets items={o.required_changes} /></div>}
        {o.risks.length > 0 && <div><p className="mb-1 font-medium">Risks and trade-offs</p><Bullets items={o.risks} tone="amber" /></div>}
        {o.unresolved_conditions.length > 0 && <div><p className="mb-1 font-medium">Still unresolved</p><Bullets items={o.unresolved_conditions} tone="amber" /></div>}
        {o.exclusions.length > 0 && <div><p className="mb-1 font-medium">Conditions in this policy</p><Bullets items={o.exclusions} /></div>}
      </div>

      {o.ai_commentary && <div className="mt-4"><NarrativeCard narrative={o.ai_commentary} /></div>}

      <details className="mt-4 rounded-lg border border-line">
        <summary className="min-h-11 px-4 py-2.5 font-medium text-teal">Why it ranks here, and where each piece of information comes from</summary>
        <div className="space-y-5 border-t border-line p-4">
          <div>
            <p className="mb-2 font-medium">Score breakdown <span className="font-normal text-muted">(calculated, not written by AI)</span></p>
            <ul className="space-y-1.5 text-sm">
              {o.score_factors.map((f) => (
                <li key={f.key} className="flex flex-wrap justify-between gap-x-4"><span>{f.label}</span><span className="font-medium">{f.score} × {f.weight}% = {f.contribution}</span></li>
              ))}
            </ul>
          </div>
          <div>
            <p className="mb-1 font-medium"><Pill tone="neutral">Official simulated criteria</Pill></p>
            <Rules rules={o.rules} />
            <Provenance source={o.source} />
          </div>
          {o.expert_notes.length > 0 && (
            <div>
              <p className="mb-1 font-medium"><Pill tone="teal">Practical expert note</Pill></p>
              {o.expert_notes.map((n) => (
                <div key={n.id} className="text-sm">
                  <p>{n.intervention} {n.outcome}</p>
                  <p className="text-muted">Applies when: {n.conditions.join("; ")}. {n.scope} Approved by {n.approver}. Not lender policy.</p>
                </div>
              ))}
            </div>
          )}
          {o.historical_outcomes && (
            <div>
              <p className="mb-1 font-medium"><Pill tone="amber">Synthetic case history</Pill></p>
              <p className="text-sm">{o.historical_outcomes.label}. <span className="text-muted">{o.historical_outcomes.note}</span></p>
            </div>
          )}
          {o.supporting_evidence.length > 0 && <div><p className="mb-1 font-medium">Evidence supporting the match</p><Bullets items={o.supporting_evidence} /></div>}
        </div>
      </details>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <Button busy={busy === `select-${o.product_id}`} onClick={onSelect}>Review this option</Button>
        <label className="flex min-h-11 cursor-pointer items-center gap-2">
          <input type="checkbox" className="h-5 w-5 accent-teal" checked={compared} onChange={onCompare} /> Compare
        </label>
        {onExplain && <Button variant="quiet" size="sm" busy={busy === "explain"} onClick={onExplain}>Explain why this is first</Button>}
      </div>
    </article>
  );
}

function CompareTable({ options }: { options: LoanOption[] }) {
  const rows: [string, (o: LoanOption) => string][] = [
    ["Status", (o) => o.status_label], ["Fresh funds", (o) => money(o.fresh_funds)], ["Monthly repayment", payment],
    ["Interest rate", (o) => `${o.rate_pct}%`], ["APR including fees", (o) => `${o.apr_pct}%`], ["Tenure", (o) => `${o.tenure_months} months`],
    ["Fees and charges", (o) => money(o.fees)], ["Total repayment", (o) => money(o.total_repayment)],
    ["Security needed", (o) => (o.ltv_pct == null ? "None" : `Yes, loan to value ${o.ltv_pct}%`)],
    ["Cash-flow cover after", (o) => (o.dscr_after == null ? "–" : `${o.dscr_after}x`)], ["Typical turnaround", (o) => `${o.turnaround_days} days`],
    ["Main risk", (o) => o.risks[0] ?? "None noted"],
  ];
  return (
    <Card title={`Comparing ${options.length} options`} id="compare">
      {/* Table from tablet up; stacked cards on phones so nothing scrolls sideways. */}
      <div className="hidden sm:block">
        <table className="w-full table-fixed">
          <thead><tr className="border-b-2 border-ink text-left align-bottom"><th className="w-[22%] py-2" />{options.map((o) => <th key={o.product_id} className="py-2 pr-3 font-semibold">{o.product_name}<span className="block text-sm font-normal text-muted">{o.lender_name}</span></th>)}</tr></thead>
          <tbody>{rows.map(([label, get]) => <tr key={label} className="border-b border-line align-top"><th scope="row" className="py-2 pr-3 text-left font-normal text-muted">{label}</th>{options.map((o) => <td key={o.product_id} className="py-2 pr-3">{get(o)}</td>)}</tr>)}</tbody>
        </table>
      </div>
      <div className="space-y-4 sm:hidden">
        {options.map((o) => (
          <div key={o.product_id} className="rounded-lg border border-line p-3">
            <p className="font-semibold">{o.product_name}</p><p className="text-sm text-muted">{o.lender_name}</p>
            <dl className="mt-2 space-y-1 text-[15px]">{rows.map(([label, get]) => <div key={label} className="flex justify-between gap-3"><dt className="text-muted">{label}</dt><dd className="text-right font-medium">{get(o)}</dd></div>)}</dl>
          </div>
        ))}
      </div>
    </Card>
  );
}

export default function Options() {
  const { caseData, refresh } = useCase();
  const id = caseData.id;
  const navigate = useNavigate();
  const [priority, setPriority] = useState<Priority | undefined>();
  const { data, error, reload, setData } = useLoad<Recommendations>(() => recommendationService.get(id, priority), [id, priority]);
  const [compare, setCompare] = useState<string[]>([]);
  const action = useAction();

  if (error) return error.includes("investigation") ? <EmptyState title="Run the investigation first"><LinkButton to="../investigation" size="sm">Go to the investigation</LinkButton></EmptyState> : <ErrorNotice message={error} onRetry={reload} />;
  if (!data) return <Loading label="Evaluating lenders" lines={6} />;

  const toggle = (pid: string) => setCompare((c) => (c.includes(pid) ? c.filter((x) => x !== pid) : c.length < 3 ? [...c, pid] : c));
  const select = (pid: string) => action.run(`select-${pid}`, async () => { await recommendationService.select(id, pid, data.priority); await refresh(); navigate("../proposal"); });
  const compared = data.options.filter((o) => compare.includes(o.product_id));

  return (
    <>
      <PageTitle title="Financing routes compared"
        lead={`${data.products_evaluated} products from ${data.lenders_evaluated} fictional lenders were each checked against their own rules for ${money(data.requested_amount)} of fresh funds over ${data.tenure_months} months.`} />

      <div className="space-y-6">
        <Card title="How options are ranked">
          <p>{data.ranking.basis}</p>
          <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
            <div>
              <label htmlFor="priority" className="mb-1 block font-medium">What matters most to you</label>
              <select id="priority" className="min-h-11 w-full rounded-lg border border-line bg-surface px-3" value={data.priority}
                onChange={(e) => { setCompare([]); setPriority(e.target.value as Priority); }}>
                {PRIORITIES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
              </select>
            </div>
            <ul className="space-y-1 text-[15px]">
              {data.ranking.factors.map((f) => <li key={f.key} className="flex justify-between gap-4 border-b border-line py-1"><span>{f.label}</span><span className="font-semibold">{f.weight}%</span></li>)}
            </ul>
          </div>
          <p className="mt-3 text-sm text-muted">An option that would cover less than {data.ranking.minimum_coverage_pct}% of the need is listed below as unsuitable instead of being recommended.</p>
        </Card>

        <details className="rounded-xl border border-line bg-surface">
          <summary className="min-h-12 px-4 py-3 font-semibold sm:px-6">What the labels mean: match, estimate, offer, sanction</summary>
          <div className="border-t border-line p-4 sm:p-6"><Bullets items={Object.values(data.labels)} /></div>
        </details>

        {action.error && <ErrorNotice message={action.error} />}

        {data.recovery_plan && (
          <Notice tone="amber" title={data.recovery_plan.headline}>
            <p className="mt-2 font-medium">What blocked the match</p>
            <Bullets items={data.recovery_plan.blocking_reasons.map((r) => `${r.reason}: ${r.products} product${r.products > 1 ? "s" : ""}`)} />
            <p className="mt-3 font-medium">A recovery plan</p>
            <Bullets items={data.recovery_plan.steps} />
            <div className="mt-4 flex flex-wrap gap-3"><LinkButton to="../restructure" size="sm">Test changes</LinkButton></div>
          </Notice>
        )}

        {data.options.map((o, i) => (
          <OptionCard key={o.product_id} o={o} best={i === 0} compared={compare.includes(o.product_id)} busy={action.busy}
            onCompare={() => toggle(o.product_id)} onSelect={() => select(o.product_id)}
            onExplain={i === 0 ? () => action.run("explain", async () => setData(await recommendationService.explain(id, data.priority))) : undefined} />
        ))}

        {compare.length > 0 && compared.length < 2 && <p className="text-muted">Tick one or two more options to compare them side by side (up to three).</p>}
        {compared.length >= 2 && <CompareTable options={compared} />}

        <Card title={`Not suitable as things stand (${data.unsuitable.length})`}>
          <p className="mb-3 text-muted">Shown so nothing is hidden. Each was assessed by the lender simulator against that lender's own fictional rules.</p>
          <ul className="space-y-2">
            {data.unsuitable.map((u) => (
              <li key={u.product_id}>
                <details className="rounded-lg border border-line">
                  <summary className="flex min-h-12 flex-wrap items-center justify-between gap-2 px-4 py-2">
                    <span><span className="font-medium">{u.product_name}</span> <span className="text-muted">· {u.lender_name}</span></span>
                    <Pill tone={decisionTone(u.decision)}>{u.decision_label}</Pill>
                  </summary>
                  <div className="space-y-3 border-t border-line p-4"><p>{u.reason}</p><Rules rules={u.rules} /><Provenance source={u.source} /></div>
                </details>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  );
}
