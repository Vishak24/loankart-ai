import { useEffect, useRef, useState } from "react";
import { apiUrl, type Doc, type Investigation as Inv } from "../api/client";
import { caseService, documentService, investigationService } from "../api/services";
import {
  Button, Card, EmptyState, ErrorNotice, LinkButton, Loading, Notice, PageTitle, Pill, StatePill, useAction, useLoad, type Tone,
} from "../components/ui";
import { formatMonth, money } from "../format";
import { useCase } from "./CaseLayout";

const TASK: Record<Inv["tasks"][number]["status"], [Tone, string]> = {
  queued: ["neutral", "Queued"], running: ["teal", "Analysing"], complete: ["success", "Complete"],
  needs_input: ["amber", "Needs your input"], failed: ["danger", "Failed"],
};
const DOC: Record<Doc["status"], [Tone, string]> = {
  loaded: ["neutral", "Loaded"], extracted: ["success", "Read"], unrecognised: ["amber", "Not recognised"], failed: ["danger", "Could not be read"],
};

function Documents({ docs, onUpload, busy }: { docs: Doc[]; onUpload: (f: File) => void; busy: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const groups = [...new Set(docs.map((d) => d.group))];
  return (
    <Card
      title={`Document library (${docs.length})`}
      aside={
        <>
          <input ref={input} type="file" accept="application/pdf,.pdf" className="sr-only" aria-label="Upload a PDF"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) onUpload(f); e.target.value = ""; }} />
          <Button size="sm" variant="quiet" busy={busy} onClick={() => input.current?.click()}>Add a PDF</Button>
        </>
      }
    >
      <div className="space-y-2">
        {groups.map((g) => {
          const rows = docs.filter((d) => d.group === g);
          return (
            <details key={g} className="rounded-lg border border-line">
              <summary className="flex min-h-12 items-center justify-between gap-3 px-4 font-medium">
                <span>{g}</span><span className="text-sm text-muted">{rows.length} file{rows.length > 1 ? "s" : ""}</span>
              </summary>
              <ul className="divide-y divide-line border-t border-line">
                {rows.map((d) => (
                  <li key={d.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-2.5">
                    <a href={apiUrl(d.url)} target="_blank" rel="noreferrer" className="font-medium text-teal underline underline-offset-4">{d.title}</a>
                    <span className="flex flex-wrap items-center gap-2 text-sm text-muted">
                      {d.checks.length > 0 && (d.checks.every((c) => c.ok) ? "Totals reconcile" : "Totals do not reconcile")}
                      {d.warnings[0]}
                      <Pill tone={DOC[d.status][0]}>{DOC[d.status][1]}</Pill>
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          );
        })}
      </div>
      <p className="mt-3 text-sm text-muted">Each file is a real PDF. Open any of them to see exactly what the investigation reads. PDFs you add are read if they follow a known layout; otherwise they are set aside.</p>
    </Card>
  );
}

/** Extra detail for a finished task, or null when the one-line output already says everything. */
function taskDetail(taskKey: string, inv: Inv) {
  if (taskKey === "identify_loans" && inv.obligations.length) {
    return (
      <ul className="space-y-1">
        {inv.obligations.map((o) => (
          <li key={o.account_no}>{o.lender}, {o.product}: EMI {money(o.emi)}, {o.status === "active" ? `${money(o.outstanding)} outstanding` : `ended ${o.last_seen}`} {o.documented ? "" : "(no loan statement supplied)"}</li>
        ))}
      </ul>
    );
  }
  if (taskKey === "cash_flow" && inv.months.length) {
    return (
      <div className="overflow-x-auto">
        <table className="w-full min-w-[30rem] text-sm">
          <thead><tr className="text-left text-muted"><th className="py-1 font-medium">Month</th><th className="py-1 text-right font-medium">Sales receipts</th><th className="py-1 text-right font-medium">Running costs</th><th className="py-1 text-right font-medium">EMIs</th><th className="py-1 text-right font-medium">Left over</th></tr></thead>
          <tbody>
            {inv.months.map((m) => (
              <tr key={m.month} className="border-t border-line">
                <td className="py-1">{formatMonth(m.month)}</td><td className="py-1 text-right">{money(m.business_receipts)}</td>
                <td className="py-1 text-right">{money(m.operating_expenses)}</td><td className="py-1 text-right">{money(m.loan_repayments)}</td>
                <td className="py-1 text-right">{money(m.operating_surplus - m.loan_repayments)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (taskKey === "reconcile" && inv.reconciliation.length) {
    return (
      <ul className="space-y-1">
        {inv.reconciliation.map((r) => <li key={r.item}>{r.item}: <strong>{r.status}</strong>{r.variance_pct != null ? ` (${r.variance_pct}% difference)` : ""}</li>)}
      </ul>
    );
  }
  if (taskKey === "findings" && inv.findings.length) return <ul className="space-y-1">{inv.findings.map((f) => <li key={f.id}>{f.title}</li>)}</ul>;
  if (taskKey === "extract_bank" && inv.unusual.length) {
    return <ul className="space-y-1">{inv.unusual.map((u) => <li key={u.date + u.narration}>{u.date} {u.narration}: {money(u.amount)}. {u.why}.</li>)}</ul>;
  }
  return null;
}

function Timeline({ inv }: { inv: Inv }) {
  const groups = [...new Set(inv.tasks.map((t) => t.group))];
  return (
    <div aria-live="polite" className="space-y-5">
      {groups.map((g) => (
        <div key={g}>
          <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">{g}</h3>
          <ol className="space-y-2">
            {inv.tasks.filter((t) => t.group === g).map((t) => {
              const detail = inv.status === "complete" ? taskDetail(t.key, inv) : null;
              return (
                <li key={t.key} className="rounded-lg border border-line p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium">{t.title}</span>
                    <Pill tone={TASK[t.status][0]}>{TASK[t.status][1]}</Pill>
                  </div>
                  {t.output && <p className="mt-1 text-muted">{t.output}</p>}
                  {detail && (
                    <details className="mt-2 text-sm">
                      <summary className="min-h-8 font-medium text-teal">View detail</summary>
                      <div className="pt-2">{detail}</div>
                    </details>
                  )}
                </li>
              );
            })}
          </ol>
        </div>
      ))}
    </div>
  );
}

export default function Investigation() {
  const { caseData, refresh } = useCase();
  const id = caseData.id;
  const docs = useLoad(() => documentService.list(id), [id]);
  const inv = useLoad(() => investigationService.get(id), [id]);
  const action = useAction();
  const [agreed, setAgreed] = useState(false);
  const running = inv.data?.status === "running";

  useEffect(() => {      // poll real task states while the backend is working
    if (!running) return;
    const timer = setInterval(() => { investigationService.get(id).then((next) => { inv.setData(next); if (next.status !== "running") { refresh(); docs.reload(); } }).catch(() => {}); }, 500);
    return () => clearInterval(timer);
  }, [running, id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (docs.error || inv.error) return <ErrorNotice message={docs.error ?? inv.error!} onRetry={() => { docs.reload(); inv.reload(); }} />;
  if (!docs.data || !inv.data) return <Loading label="Loading documents" lines={5} />;
  const consented = caseData.consents.analyse_documents;
  const open = inv.data.clarifications.filter((c) => !c.answer || c.answer === "not_sure").length;

  const run = () => action.run("run", async () => { inv.setData(await investigationService.run(id)); });

  return (
    <>
      <PageTitle title="Financial investigation" lead="LoanKart reads the documents, cross-checks them against each other and against what you told us, and shows its work step by step." />
      {action.error && <div className="mb-4"><ErrorNotice message={action.error} /></div>}
      <div className="grid gap-6 lg:grid-cols-12">
        <div className="space-y-6 lg:col-span-8">
          {docs.data.length === 0 ? (
            <EmptyState title="No documents yet">
              <p>Load the synthetic document pack for this case: bank statements, GST returns, tax returns, loan statements and more, as real PDF files.</p>
              <div className="mt-4 flex flex-wrap justify-center gap-3">
                <Button busy={action.busy === "load"} onClick={() => action.run("load", async () => { docs.setData(await documentService.loadSynthetic(id)); })}>Load the synthetic document pack</Button>
              </div>
            </EmptyState>
          ) : (
            <Documents docs={docs.data} busy={action.busy === "upload"}
              onUpload={(f) => action.run("upload", async () => { await documentService.upload(id, f); await docs.reload(); })} />
          )}

          {docs.data.length > 0 && !consented && (
            <Card title="Your permission to analyse these documents">
              <p className="text-muted"><strong className="text-ink">What:</strong> the documents listed above. <strong className="text-ink">Why:</strong> to work out what may have affected your application and which options fit. <strong className="text-ink">Who sees it:</strong> LoanKart only; nothing goes to a lender unless you choose to submit later. <strong className="text-ink">Change your mind:</strong> reset the case at any time from the demo control page.</p>
              <label className="mt-4 flex min-h-11 cursor-pointer items-center gap-3">
                <input type="checkbox" className="h-5 w-5 accent-teal" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
                I agree to LoanKart analysing these documents for this case.
              </label>
              <div className="mt-4">
                <Button disabled={!agreed} busy={action.busy === "consent"}
                  onClick={() => action.run("consent", async () => { await caseService.consent(id, "analyse_documents", true); await refresh(); })}>
                  Give permission
                </Button>
              </div>
            </Card>
          )}

          {docs.data.length > 0 && consented && (
            <Card
              title="Investigation timeline"
              aside={<Button size="sm" variant={inv.data.status === "complete" ? "quiet" : "primary"} busy={running || action.busy === "run"} onClick={run}>
                {inv.data.status === "not_started" ? "Run the investigation" : "Run again"}
              </Button>}
            >
              {inv.data.status === "not_started" ? (
                <p className="text-muted">Nothing has been analysed yet. Running the investigation reads every document and takes a few seconds.</p>
              ) : (
                <>
                  {inv.data.error && <div className="mb-4"><ErrorNotice message={inv.data.error} /></div>}
                  <Timeline inv={inv.data} />
                  <p className="mt-4 text-sm text-muted">{inv.data.pacing_note}</p>
                </>
              )}
            </Card>
          )}
        </div>

        <aside className="space-y-6 lg:col-span-4">
          <Card title="What the documents show">
            {inv.data.headline.length === 0 ? (
              <p className="text-muted">Figures appear here once the investigation has run.</p>
            ) : (
              <ul className="space-y-4">
                {inv.data.headline.map((h) => (
                  <li key={h.key}>
                    <p className="text-sm text-muted">{h.label}</p>
                    <p className="text-lg font-semibold">{h.unit === "inr" ? money(h.value) : h.value ?? "Not available"}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted">
                      <StatePill state={h.state} label={h.state_label} /> {h.source}
                      {h.original != null && <span>(was {h.unit === "inr" ? money(h.original) : h.original})</span>}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          {inv.data.status === "complete" && (
            <>
              {inv.data.lender_snapshot && <Notice tone="amber" title="Simulated lender check"><p>{inv.data.lender_snapshot.text}</p></Notice>}
              {open > 0 && <Notice tone="amber" title={`${open} question${open > 1 ? "s" : ""} for you`}><p>Some items need your confirmation before they are counted. You can answer them on the next step.</p></Notice>}
              <LinkButton to="../diagnosis">Review findings</LinkButton>
            </>
          )}
        </aside>
      </div>
    </>
  );
}
