import { useState } from "react";
import { Link, NavLink, Outlet, useOutletContext, useParams } from "react-router";
import type { Case } from "../api/client";
import { caseService } from "../api/services";
import { Button, Card, ErrorNotice, Layout, Loading, NarrativeCard, Notice, Pill, useAction, useLoad } from "../components/ui";
import { formatINR } from "../format";

export interface CaseContext { caseData: Case; refresh: () => Promise<unknown> }
export const useCase = () => useOutletContext<CaseContext>();

const STAGES: [keyof Case["stages"] & string, string][] = [
  ["investigation", "Investigate"], ["diagnosis", "Understand"], ["restructure", "Improve"],
  ["options", "Compare"], ["proposal", "Prepare"], ["tracking", "Track"],
];

function StageNav({ caseData }: { caseData: Case }) {
  return (
    <nav aria-label="Case stages" className="mt-4">
      <ol className="grid grid-cols-3 gap-2 lg:grid-cols-6">
        {STAGES.map(([key, label], i) => {
          const state = caseData.stages[key];
          const inner = (
            <>
              <span className="block text-[13px] text-muted">Step {i + 1}{state === "complete" ? " · done" : ""}</span>
              <span className="block font-semibold">{label}</span>
            </>
          );
          return (
            <li key={key}>
              {state === "locked" ? (
                <span aria-disabled className="block min-h-14 rounded-lg border border-dashed border-line px-3 py-2 opacity-60" title="Complete the earlier steps first">{inner}</span>
              ) : (
                <NavLink
                  to={key}
                  className={({ isActive }) => `block min-h-14 rounded-lg border px-3 py-2 ${isActive ? "border-teal bg-teal-wash" : "border-line bg-surface hover:border-teal"}`}
                >
                  {inner}
                </NavLink>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** Escalation keeps the whole case with it, so the borrower never has to repeat their story. */
function AdvisorHelp({ caseData, refresh }: CaseContext) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const action = useAction();
  const esc = caseData.escalation;

  if (esc.status !== "none") {
    return (
      <Card title={esc.status === "open" ? "An advisor has this case" : "Advisor review complete"}>
        <p className="text-muted">You asked: “{esc.reason}”</p>
        {esc.summary && <div className="mt-3"><NarrativeCard narrative={esc.summary} /></div>}
        {esc.status === "open" && <p className="mt-3 text-muted">The advisor sees your documents, the findings, the options and the full history. No response time is promised in this demo.</p>}
        {esc.resolution && <Notice tone="success" title="Advisor's note"><p>{esc.resolution}</p></Notice>}
        <p className="mt-3"><Link to="/advisor" className="font-semibold text-teal underline underline-offset-4">Open the advisor dashboard (demo)</Link></p>
      </Card>
    );
  }
  return (
    <Card title="Would you like a person to look at this?">
      <p className="text-muted">A LoanKart advisor can review the findings and options. The whole case goes with your request.</p>
      {open ? (
        <form
          className="mt-4"
          onSubmit={(e) => { e.preventDefault(); action.run("escalate", async () => { await caseService.escalate(caseData.id, reason); await refresh(); }); }}
        >
          <label htmlFor="esc-reason" className="mb-2 block font-medium">What would you like them to look at?</label>
          <textarea id="esc-reason" rows={3} required minLength={3} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)}
            className="block w-full rounded-lg border border-line bg-surface px-3 py-2" placeholder="e.g. I'm not sure which option is right for me" />
          {action.error && <p role="alert" className="mt-2 text-danger">{action.error}</p>}
          <div className="mt-3 flex gap-3">
            <Button type="submit" size="sm" busy={action.busy === "escalate"}>Send to an advisor</Button>
            <Button size="sm" variant="quiet" onClick={() => setOpen(false)}>Cancel</Button>
          </div>
        </form>
      ) : (
        <div className="mt-4"><Button size="sm" variant="quiet" onClick={() => setOpen(true)}>Ask an advisor to review</Button></div>
      )}
    </Card>
  );
}

export default function CaseLayout() {
  const { caseId } = useParams();
  const { data: caseData, error, reload } = useLoad(() => caseService.get(caseId!), [caseId]);

  if (error) return <Layout wide><ErrorNotice message={error} onRetry={reload} /></Layout>;
  if (!caseData) return <Layout wide><Loading label="Loading your case" /></Layout>;
  const b = caseData.borrower;

  return (
    <Layout wide>
      {caseData.is_synthetic && (
        <div className="mb-4 rounded-lg border border-amber/40 bg-amber-wash px-4 py-2 text-sm">
          <strong>Synthetic demo case.</strong> The borrower, every lender, every document and every figure here is fictional.
        </div>
      )}
      <header className="rounded-xl border border-line bg-surface p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-2xl font-semibold tracking-tight">{b.business_name}</p>
            <p className="text-muted">{b.borrower_name} · {b.city}, {b.state} · asking for {formatINR(b.requested_amount)}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Pill>Case {caseData.id.replace("case-", "")}</Pill>
            <Pill tone={caseData.ai_mode === "live" ? "teal" : "neutral"}>AI: {caseData.ai_mode} mode</Pill>
            <Link to={`/borrower/intake/${caseData.borrower_id}`} className="text-sm font-semibold text-teal underline underline-offset-4">Edit answers</Link>
          </div>
        </div>
        <StageNav caseData={caseData} />
      </header>
      <div className="mt-6">
        <Outlet context={{ caseData, refresh: reload } satisfies CaseContext} />
      </div>
      <div className="mt-10"><AdvisorHelp caseData={caseData} refresh={reload} /></div>
    </Layout>
  );
}
