import { useState } from "react";
import type { LenderProduct } from "../api/client";
import { lenderCatalogService } from "../api/services";
import { Button, ErrorNotice, Loading, Pill, Rows, useAction, useLoad } from "./ui";
import { formatDate, humanise, money } from "../format";

/** The fictional lender policies, as stored. With `editable`, an advisor can change a rule; each edit bumps the version. */
export function LenderCatalogue({ editable = false }: { editable?: boolean }) {
  const { data, error, reload } = useLoad(() => lenderCatalogService.list(), []);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const action = useAction();
  if (error) return <ErrorNotice message={error} onRetry={reload} />;
  if (!data) return <Loading label="Loading lender policies" />;
  const lenders = [...new Set(data.map((p) => p.lender_name))];

  const save = (p: LenderProduct) => action.run(p.id, async () => {
    await lenderCatalogService.update({ ...p, interest_rate_pct: Number(draft[`${p.id}.rate`] ?? p.interest_rate_pct), min_dscr: Number(draft[`${p.id}.dscr`] ?? p.min_dscr),
      max_bounces_12m: Number(draft[`${p.id}.bounces`] ?? p.max_bounces_12m) });
    setDraft({});
    await reload();
  });
  const num = (p: LenderProduct, key: string, label: string, value: number, step: string) => (
    <label className="block text-sm">{label}
      <input type="number" step={step} min="0" className="mt-1 block min-h-11 w-28 rounded-lg border border-line bg-surface px-2"
        value={draft[`${p.id}.${key}`] ?? value} onChange={(e) => setDraft({ ...draft, [`${p.id}.${key}`]: e.target.value })} />
    </label>
  );

  return (
    <div className="space-y-4">
      <p className="text-muted">{data.length} products from {lenders.length} fictional lenders. These rules are invented for the simulation and are not any real lender's policy.</p>
      {action.error && <ErrorNotice message={action.error} />}
      {lenders.map((name) => (
        <details key={name} className="rounded-xl border border-line bg-surface">
          <summary className="flex min-h-12 flex-wrap items-center justify-between gap-2 px-4 py-2 font-semibold">
            <span>{name}</span><span className="text-sm font-normal text-muted">{data.find((p) => p.lender_name === name)!.lender_type}</span>
          </summary>
          <div className="space-y-4 border-t border-line p-4">
            {data.filter((p) => p.lender_name === name).map((p) => (
              <div key={p.id} className="rounded-lg border border-line p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold">{p.product_name}</span>
                  <Pill>{humanise(p.category)}</Pill><Pill tone="amber">Simulated · v{p.version}</Pill>
                </div>
                <div className="mt-2">
                  <Rows rows={[
                    ["Amount", `${money(p.min_amount)} to ${money(p.max_amount)}`], ["Rate and fees", `${p.interest_rate_pct}% · ${p.processing_fee_pct}% + ${money(p.other_charges)}`],
                    ["Tenure", `${p.min_tenure_months} to ${p.max_tenure_months} months · ${p.repayment_type === "interest_only" ? "interest only" : "EMI"}`],
                    ["Minimum business age", `${p.min_vintage_years} years`], ["Minimum monthly sales", p.min_monthly_revenue ? money(p.min_monthly_revenue) : "None"],
                    ["Income assessed from", humanise(p.income_method) + (p.gst_margin_pct ? ` (${p.gst_margin_pct}% of turnover)` : "")],
                    ["FOIR / DSCR", `${p.max_foir_pct == null ? "no FOIR rule" : `FOIR up to ${p.max_foir_pct}%`} · DSCR at least ${p.min_dscr}x`],
                    ["Repayment track", `up to ${p.max_bounces_12m} EMI returns · up to ${p.max_late_gst_filings} late GST filings · up to ${p.max_active_loans} running loans`],
                    ["Security", p.collateral_required ? `${p.collateral_accepted.map(humanise).join(", ")} · LTV up to ${p.max_ltv_pct}%` : "Unsecured"],
                    ["Sales multiple cap", p.turnover_multiple ? `${p.turnover_multiple}x monthly sales` : "None"],
                    ["Documents", p.required_documents.map(humanise).join(", ")], ["Exclusions", p.exclusions.join(" ") || "None"],
                    ["Takes over loans / counter-offers", `${p.allows_balance_transfer ? "Yes" : "No"} / ${p.counter_offers ? "Yes" : "No"}`],
                    ["Effective / status", `${formatDate(p.effective_date)} · ${p.verification_status}`], ["Source", p.source],
                  ]} />
                </div>
                {editable && (
                  <div className="mt-3 flex flex-wrap items-end gap-3 rounded-lg bg-paper p-3">
                    {num(p, "rate", "Rate %", p.interest_rate_pct, "0.25")}{num(p, "dscr", "Min DSCR", p.min_dscr, "0.05")}{num(p, "bounces", "Max EMI returns", p.max_bounces_12m, "1")}
                    <Button size="sm" variant="quiet" busy={action.busy === p.id} onClick={() => save(p)}>Save as version {p.version + 1}</Button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </details>
      ))}
    </div>
  );
}
