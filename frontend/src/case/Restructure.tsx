import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import type { Restructure as R, RestructureInput, S } from "../api/client";
import { calculationService, caseService } from "../api/services";
import {
  Bullets, Button, Card, EmptyState, ErrorNotice, LinkButton, Loading, Notice, PageTitle, Pill, Stat, useAction, useLoad,
} from "../components/ui";
import { formatMonth, formatNumber, humanise, inIndianUnits, money, signedMoney } from "../format";
import { useCase } from "./CaseLayout";

const CATEGORIES: [RestructureInput["product_categories"][number], string][] = [
  ["working_capital", "Working-capital line"], ["term_loan", "Term loan"], ["unsecured_business", "Unsecured loan"],
  ["secured_business", "Secured loan"], ["lap", "Loan against property"], ["equipment", "Equipment finance"],
];
const inputCls = "min-h-11 w-full rounded-lg border border-line bg-surface px-3";

function cell(key: string, value: unknown): string {
  if (value == null) return "–";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value !== "number") return humanise(String(value));
  if (/pct|rate/.test(key)) return `${value}%`;
  if (/dscr/.test(key)) return `${value}x`;
  if (/months|tenure|viable|products|count/.test(key)) return String(value);
  return money(value);
}

/** Before/after for the one decision this page is about: can the business carry the repayments? */
function Compare({ data }: { data: R }) {
  const { current: a, proposed: b } = data;
  const scale = Math.max(a.total_monthly_repayment, b.total_monthly_repayment, a.operating_surplus, 1);
  const bar = (label: string, p: S["PositionOut"]) => {
    const over = p.total_monthly_repayment > p.operating_surplus;
    return (
      <div>
        <div className="mb-1 flex flex-wrap justify-between gap-2 text-sm"><span className="font-medium">{label}</span><span>{money(p.total_monthly_repayment)} a month in repayments</span></div>
        <div className="relative h-5 rounded bg-paper">
          <div className={`h-5 rounded ${over ? "bg-danger" : "bg-teal"}`} style={{ width: `${(p.total_monthly_repayment / scale) * 100}%` }} />
          <div aria-hidden className="absolute -top-1 h-7 w-0.5 bg-ink" style={{ left: `${(p.operating_surplus / scale) * 100}%` }} />
        </div>
      </div>
    );
  };
  const rows: [string, (p: S["PositionOut"]) => string][] = [
    ["Fresh funds to the business", (p) => money(p.fresh_funds)], ["Loan amount", (p) => money(p.loan_amount)],
    ["Tenure", (p) => `${p.tenure_months} months`], ["Existing EMIs that continue", (p) => money(p.existing_emi)],
    ["New EMI (illustrative)", (p) => money(p.new_emi)], ["Total monthly repayment", (p) => money(p.total_monthly_repayment)],
    ["Free cash after repayments", (p) => money(p.free_cash_after)], ["Cash-flow cover", (p) => (p.dscr == null ? "–" : `${p.dscr}x`)],
    ["Total interest on the new loan", (p) => money(p.total_interest)], ["Total repayment on the new loan", (p) => money(p.total_repayment)],
    ["Simulated products that fit in full", (p) => `${p.products_fitting_in_full} of ${p.products_evaluated}`],
    ["Simulated products that could work", (p) => `${p.products_viable} of ${p.products_evaluated}`],
  ];
  return (
    <Card title="Current request against your scenario">
      <div className="space-y-3">
        {bar("As requested", a)}
        {bar("Your scenario", b)}
        <p className="text-sm text-muted">
          The dark line marks {money(a.operating_surplus)}, what the bank statements show is left each month after running costs.
          As requested, repayments are {a.total_monthly_repayment > a.operating_surplus ? "above" : "within"} it; in your scenario they are {b.total_monthly_repayment > b.operating_surplus ? "above" : "within"} it.
        </p>
      </div>
      <div className="mt-5 overflow-x-auto">
        <table className="w-full min-w-[26rem]">
          <thead><tr className="border-b-2 border-ink text-left"><th className="py-2 pr-3 font-semibold">&nbsp;</th><th className="py-2 pr-3 text-right font-semibold">As requested</th><th className="py-2 text-right font-semibold">Your scenario</th></tr></thead>
          <tbody>
            {rows.map(([label, get]) => (
              <tr key={label} className="border-b border-line">
                <th scope="row" className="py-2 pr-3 text-left font-normal text-muted">{label}</th>
                <td className="py-2 pr-3 text-right">{get(a)}</td>
                <td className={`py-2 text-right font-semibold ${get(a) !== get(b) ? "text-teal-deep" : ""}`}>{get(b)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.notes.length > 0 && <div className="mt-4"><Bullets items={data.notes} /></div>}
    </Card>
  );
}

function Dimension({ d }: { d: R["dimensions"][number] }) {
  // Columns that only repeat the label or the controls above are left out so the table fits a phone.
  const hidden = ["account_no", "category", "kind", "tenure_months", "remaining_months", "rate", "new_rate", "new_tenure", "action", "repayment_type"];
  const cols = d.options.length ? Object.keys(d.options[0]).filter((k) => !hidden.includes(k) && !(k === "amount" && d.key !== "collateral")) : [];
  return (
    <details className="rounded-xl border border-line bg-surface" open={d.applied}>
      <summary className="flex min-h-14 flex-wrap items-center justify-between gap-2 px-4 py-3 sm:px-6">
        <span className="text-lg font-semibold">{d.title}</span>
        <span className="flex flex-wrap gap-2">
          {d.applied && <Pill tone="teal">In your scenario</Pill>}
          <Pill tone={d.relevant ? "amber" : "neutral"}>{d.relevant ? "Relevant to your case" : "Not needed now"}</Pill>
        </span>
      </summary>
      <div className="space-y-4 border-t border-line p-4 sm:p-6">
        <p className="text-muted">{d.why}</p>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="rounded-lg bg-paper p-3"><p className="text-sm text-muted">Current</p><p className="font-medium">{d.current}</p></div>
          <div className="rounded-lg bg-teal-wash p-3"><p className="text-sm text-muted">What could change</p><p className="font-medium">{d.proposed}</p></div>
        </div>
        {d.financial_impact && <p><span className="font-medium">Financial impact: </span>{d.financial_impact}</p>}
        {(d.emi_impact != null || d.total_repayment_impact != null) && (
          <div className="flex flex-wrap gap-x-8 gap-y-2">
            {d.emi_impact != null && <Stat label="Monthly repayment" value={signedMoney(d.emi_impact)} />}
            {d.total_repayment_impact != null && <Stat label="Total repaid" value={signedMoney(d.total_repayment_impact)} />}
          </div>
        )}
        {d.options.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[28rem] text-sm">
              <thead><tr className="border-b border-ink text-left">{cols.map((k, i) => <th key={k} className={`py-1.5 pr-3 font-semibold ${i ? "text-right" : ""}`}>{humanise(k)}</th>)}</tr></thead>
              <tbody>
                {d.options.map((row, i) => (
                  <tr key={i} className="border-b border-line">{cols.map((k, j) => <td key={k} className={`py-1.5 pr-3 ${j ? "text-right" : ""}`}>{k === "label" || k === "detail" ? String(row[k]) : cell(k, row[k])}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          {d.risks.length > 0 && <div><p className="mb-1 font-medium">Risks</p><Bullets items={d.risks} tone="amber" /></div>}
          {(d.additional_costs.length > 0 || d.required_evidence.length > 0) && (
            <div>
              {d.additional_costs.length > 0 && <><p className="mb-1 font-medium">Extra costs</p><Bullets items={d.additional_costs} /></>}
              {d.required_evidence.length > 0 && <><p className="mb-1 mt-3 font-medium">Evidence needed</p><Bullets items={d.required_evidence} /></>}
            </div>
          )}
        </div>
        <p className="rounded-lg border border-line p-3 text-sm">
          <Pill tone="amber">Demo simulation</Pill>{" "}
          With this change alone, {d.lender_fit_after} simulated product{d.lender_fit_after === 1 ? "" : "s"} could work (now {d.lender_fit_before}). {d.lender_fit_example}
        </p>
      </div>
    </details>
  );
}

function PaytmPanel({ paytm }: { paytm: NonNullable<R["paytm"]> }) {
  return (
    <Card title="Payment collections as supporting evidence" aside={<Pill tone="amber">Demo simulation</Pill>}>
      <p className="text-sm text-muted">{paytm.source}. Merchant {paytm.merchant_id}.</p>
      <div className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Gross payments, 12 months" value={money(paytm.total_gross)} />
        <Stat label="Net settlements" value={money(paytm.total_net)} sub={`${money(paytm.total_refunds)} refunded (${paytm.refund_rate_pct}%)`} />
        <Stat label="Settlements a month" value={paytm.settlements_per_month} sub={`about ${money(paytm.avg_net_settlements)} a month`} />
        <Stat label="Share of bank sales receipts" value={`${paytm.share_of_bank_receipts_pct}%`} sub={paytm.trend_pct == null ? undefined : `trend ${paytm.trend_pct}%`} />
      </div>
      <p className="mt-3 text-sm text-muted">Highest month {formatMonth(paytm.peak_month)}, lowest {formatMonth(paytm.low_month)}.</p>
      <div className="mt-3"><Bullets items={paytm.notes} /></div>
    </Card>
  );
}

export default function Restructure() {
  const { caseData, refresh } = useCase();
  const id = caseData.id;
  const navigate = useNavigate();
  const { data, error, reload, setData } = useLoad(() => calculationService.restructure(id), [id]);
  const [inputs, setInputs] = useState<RestructureInput | null>(null);
  const action = useAction();
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => { if (data && !inputs) setInputs(data.inputs); }, [data, inputs]);

  if (error) return error.includes("investigation") ? <EmptyState title="Run the investigation first"><LinkButton to="../investigation" size="sm">Go to the investigation</LinkButton></EmptyState> : <ErrorNotice message={error} onRetry={reload} />;
  if (!data || !inputs) return <Loading label="Loading scenario" lines={6} />;

  // Every change is recalculated by the backend engine; the page never does loan arithmetic itself.
  const change = (patch: Partial<RestructureInput>) => {
    const next = { ...inputs, ...patch };
    setInputs(next);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => action.run("preview", async () => setData(await calculationService.preview(id, next))), 250);
  };
  const save = () => action.run("save", async () => { setData(await calculationService.save(id, inputs)); await refresh(); });
  const reset = () => action.run("reset", async () => {
    const base = await calculationService.preview(id, { ...inputs, amount: caseData.borrower.requested_amount, tenure_months: 36, liability_actions: {}, offer_collateral: caseData.borrower.collateral !== "none", product_categories: [], co_applicant_income: 0, include_paytm_evidence: false });
    setInputs(base.inputs); setData(base);
  });
  const loans = data.dimensions.find((d) => d.key === "liabilities")!.options as { account_no: string; label: string; emi: number; outstanding: number }[];
  const cur = data.current;
  const paytmConsent = caseData.consents.paytm_evidence;

  return (
    <>
      <PageTitle title="Ways to improve the position"
        lead="Change one thing at a time or combine them. Every figure is recalculated by LoanKart's calculation engine, and nothing is applied unless you choose it." />

      <div className="mb-6 grid grid-cols-2 gap-4 rounded-xl border border-line bg-surface p-4 sm:p-6 lg:grid-cols-4">
        <Stat label="Left after running costs" value={money(cur.operating_surplus)} sub="monthly, from bank statements" />
        <Stat label="Existing EMIs" value={money(cur.existing_emi)} sub="monthly" />
        <Stat label="Free cash after EMIs" value={money(cur.operating_surplus - cur.existing_emi)} sub="before any new loan" />
        <Stat label="Amount you asked for" value={money(cur.fresh_funds)} sub={`EMI about ${money(cur.new_emi)} (illustrative)`} />
      </div>

      <div className="grid gap-6 lg:grid-cols-12">
        <div className="space-y-6 lg:col-span-5">
          <Card title="Your scenario" aside={data.saved ? <Pill tone="success">Saved</Pill> : <Pill tone="amber">Not saved</Pill>}>
            <div className="space-y-5">
              <div>
                <label htmlFor="amount" className="mb-1 block font-medium">Fresh funds needed</label>
                <div className="relative">
                  <span aria-hidden className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-muted">₹</span>
                  <input id="amount" inputMode="numeric" className={`${inputCls} pl-8`} value={formatNumber(inputs.amount)}
                    onChange={(e) => { const n = Number(e.target.value.replace(/\D/g, "")); if (n > 0) change({ amount: n }); }} />
                </div>
                <input type="range" aria-label="Fresh funds needed" className="mt-2 w-full accent-teal" min={50000} max={Math.max(caseData.borrower.requested_amount, inputs.amount)} step={10000}
                  value={inputs.amount} onChange={(e) => change({ amount: Number(e.target.value) })} />
                <p className="text-sm text-muted">{inIndianUnits(inputs.amount)}</p>
              </div>
              <div>
                <label htmlFor="tenure" className="mb-1 block font-medium">Tenure</label>
                <select id="tenure" className={inputCls} value={inputs.tenure_months} onChange={(e) => change({ tenure_months: Number(e.target.value) })}>
                  {[12, 24, 36, 48, 60, 84, 120].map((m) => <option key={m} value={m}>{m} months</option>)}
                </select>
              </div>
              {loans.length > 0 && (
                <fieldset>
                  <legend className="mb-1 font-medium">Existing loans</legend>
                  <ul className="space-y-3">
                    {loans.map((l) => (
                      <li key={l.account_no}>
                        <label htmlFor={`loan-${l.account_no}`} className="block text-sm text-muted">{l.label}: EMI {money(l.emi)}, {money(l.outstanding)} outstanding</label>
                        <select id={`loan-${l.account_no}`} className={inputCls} value={inputs.liability_actions?.[l.account_no]?.action ?? "keep"}
                          onChange={(e) => change({ liability_actions: { ...inputs.liability_actions, [l.account_no]: { action: e.target.value as "keep" | "refinance" | "consolidate" } } })}>
                          <option value="keep">Keep as it is</option>
                          <option value="refinance">Refinance over a longer period (illustrative)</option>
                          <option value="consolidate">Close it using the new loan</option>
                        </select>
                      </li>
                    ))}
                  </ul>
                </fieldset>
              )}
              {caseData.borrower.collateral !== "none" && (
                <label className="flex min-h-11 cursor-pointer items-center gap-3">
                  <input type="checkbox" className="h-5 w-5 accent-teal" checked={inputs.offer_collateral} onChange={(e) => change({ offer_collateral: e.target.checked })} />
                  Offer my {caseData.borrower.collateral.replace(/_/g, " ")} as security
                </label>
              )}
              <div>
                <label htmlFor="coapp" className="mb-1 block font-medium">Co-applicant's documented monthly income</label>
                <input id="coapp" inputMode="numeric" className={inputCls} value={inputs.co_applicant_income ? formatNumber(inputs.co_applicant_income) : ""} placeholder="None"
                  onChange={(e) => change({ co_applicant_income: Number(e.target.value.replace(/\D/g, "")) })} />
              </div>
              <fieldset>
                <legend className="mb-1 font-medium">Types of loan to consider <span className="font-normal text-muted">(none ticked means all)</span></legend>
                <div className="flex flex-wrap gap-2">
                  {CATEGORIES.map(([code, label]) => {
                    const on = inputs.product_categories.includes(code);
                    return (
                      <button key={code} type="button" aria-pressed={on}
                        onClick={() => change({ product_categories: on ? inputs.product_categories.filter((x) => x !== code) : [...inputs.product_categories, code] })}
                        className={`min-h-11 rounded-lg border px-3 text-[15px] ${on ? "border-teal bg-teal-wash font-semibold" : "border-line bg-surface hover:border-teal"}`}>{label}</button>
                    );
                  })}
                </div>
              </fieldset>
              <div className="rounded-lg border border-line p-3">
                <p className="font-medium">Paytm payment data as supporting evidence</p>
                {paytmConsent ? (
                  <label className="mt-2 flex min-h-11 cursor-pointer items-center gap-3">
                    <input type="checkbox" className="h-5 w-5 accent-teal" checked={inputs.include_paytm_evidence} onChange={(e) => change({ include_paytm_evidence: e.target.checked })} />
                    Include it with my scenario
                  </label>
                ) : (
                  <>
                    <p className="mt-1 text-sm text-muted"><strong className="text-ink">What:</strong> payment collections, settlements and refunds for your merchant account. <strong className="text-ink">Why:</strong> to show that sales receipts can be traced. <strong className="text-ink">Limits:</strong> it is one sales channel, never treated as total revenue. In this demo the data is a synthetic fixture, not from Paytm.</p>
                    <div className="mt-2"><Button size="sm" variant="quiet" busy={action.busy === "paytm"}
                      onClick={() => action.run("paytm", async () => { await caseService.consent(id, "paytm_evidence", true); await refresh(); await reload(); })}>Allow use of this data</Button></div>
                  </>
                )}
              </div>
            </div>
            {action.error && <p role="alert" className="mt-4 text-danger">{action.error}</p>}
            <div className="mt-5 flex flex-wrap gap-3">
              <Button size="sm" busy={action.busy === "save"} onClick={save}>Save scenario</Button>
              <Button size="sm" variant="quiet" busy={action.busy === "reset"} onClick={reset}>Reset to current</Button>
            </div>
          </Card>
        </div>

        <div className="space-y-6 lg:col-span-7" aria-busy={action.busy === "preview"}>
          <Compare data={data} />
          {data.proposed.products_viable === 0 && <Notice tone="danger" title="No simulated product works with this scenario"><p>Try a smaller amount, a longer tenure, or closing a costly loan with the new one.</p></Notice>}
          {data.paytm && <PaytmPanel paytm={data.paytm} />}
          <Button busy={action.busy === "continue"} onClick={() => action.run("continue", async () => { await calculationService.save(id, inputs); await refresh(); navigate("../options"); })}>
            Compare financing options
          </Button>
        </div>
      </div>

      <h2 className="mb-3 mt-10 text-xl font-semibold">The eight things that can change</h2>
      <div className="space-y-3">{data.dimensions.map((d) => <Dimension key={d.key} d={d} />)}</div>

      <details className="mt-6 rounded-xl border border-line bg-surface">
        <summary className="min-h-12 px-4 py-3 font-semibold sm:px-6">Assumptions behind these figures</summary>
        <div className="border-t border-line p-4 sm:p-6"><Bullets items={data.assumptions} /></div>
      </details>
    </>
  );
}
