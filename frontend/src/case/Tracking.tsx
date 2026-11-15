import { useState } from "react";
import type { Application } from "../api/client";
import { applicationService } from "../api/services";
import { Bullets, Button, Card, ErrorNotice, LinkButton, Loading, Notice, PageTitle, Pill, Rows, Stat, useAction, useLoad, type Tone } from "../components/ui";
import { formatDateTime, money } from "../format";
import { useCase } from "./CaseLayout";
import { Rules } from "./Options";

const STATUS: Record<Application["status"], Tone> = {
  draft: "neutral", ready: "teal", submitted: "teal", under_review: "teal", query_raised: "amber", info_supplied: "teal",
  offer_generated: "success", rejected: "danger", human_review: "amber",
};

function Query({ q, caseId, onChange }: { q: Application["queries"][number]; caseId: string; onChange: (a: Application) => void }) {
  const [text, setText] = useState(q.draft?.body ?? "");
  const action = useAction();
  if (q.status === "answered") {
    return <li className="rounded-lg border border-line p-4"><p className="font-medium">{q.text}</p><p className="mt-2"><Pill tone="success">Your reply</Pill> {q.response}</p></li>;
  }
  return (
    <li className="rounded-lg border border-amber/50 bg-amber-wash p-4">
      <div className="flex flex-wrap items-center gap-2"><Pill tone="amber">Open query (simulated)</Pill>{!q.routine && <Pill tone="danger">Needs more than the documents on file</Pill>}</div>
      <p className="mt-2 font-medium">{q.text}</p>
      {!q.routine && <p className="mt-1 text-sm text-muted">This is not a routine query. Consider asking an advisor to review, using the panel at the bottom of this page.</p>}
      <label htmlFor={`reply-${q.id}`} className="mb-1 mt-3 block font-medium">Your reply</label>
      <textarea id={`reply-${q.id}`} rows={4} maxLength={2000} value={text} onChange={(e) => setText(e.target.value)} className="block w-full rounded-lg border border-line bg-surface px-3 py-2" />
      {q.draft && <p className="mt-1 text-sm text-muted">Drafted by AI ({q.draft.provider === "mock" ? "mock provider" : q.draft.provider}) from your documents. Check it and edit before sending.</p>}
      {action.error && <p role="alert" className="mt-2 text-danger">{action.error}</p>}
      <div className="mt-3 flex flex-wrap gap-3">
        <Button size="sm" disabled={text.trim().length < 3} busy={action.busy === "send"} onClick={() => action.run("send", async () => onChange(await applicationService.respond(caseId, q.id, text.trim())))}>Send reply</Button>
        <Button size="sm" variant="quiet" busy={action.busy === "draft"}
          onClick={() => action.run("draft", async () => { const next = await applicationService.draft(caseId, q.id); onChange(next); setText(next.queries.find((x) => x.id === q.id)?.draft?.body ?? text); })}>
          Draft a reply from my documents
        </Button>
      </div>
    </li>
  );
}

export default function Tracking() {
  const { caseData, refresh } = useCase();
  const id = caseData.id;
  const { data: app, error, reload, setData } = useLoad(() => applicationService.get(id), [id]);
  const action = useAction();

  if (error) return <ErrorNotice message={error} onRetry={reload} />;
  if (!app) return <Loading label="Loading application" lines={5} />;
  const update = (next: Application) => { setData(next); refresh(); };
  const canAdvance = app.status === "under_review" || app.status === "info_supplied";
  const offer = app.offer;

  return (
    <>
      <div role="note" className="mb-5 rounded-xl border border-amber/50 bg-amber-wash px-4 py-3"><strong>Demo simulation.</strong> {app.banner.replace("Demo simulation: this", "This")}</div>
      <PageTitle title="Application tracking" lead={app.lender_name ? `${app.product_name} · ${app.lender_name}` : "No application has been submitted yet."} />

      <div className="grid gap-6 lg:grid-cols-12">
        <div className="space-y-6 lg:col-span-7">
          <Card title="Where things stand" aside={<Pill tone={STATUS[app.status]}>{app.status_label}</Pill>}>
            {app.reference && <p className="text-muted">Simulated reference <span className="font-semibold text-ink">{app.reference}</span></p>}
            <p className="mt-2 text-lg">{app.next_step}</p>
            {action.error && <p role="alert" className="mt-3 text-danger">{action.error}</p>}
            <div className="mt-4 flex flex-wrap gap-3">
              {!app.reference && <LinkButton to="../proposal">Go to the proposal</LinkButton>}
              {canAdvance && <Button busy={action.busy === "advance"} onClick={() => action.run("advance", async () => update(await applicationService.advance(id)))}>Check for a lender update (simulated)</Button>}
              {app.status === "rejected" && <LinkButton to="../diagnosis">Return to the diagnosis</LinkButton>}
              {app.status === "rejected" && <LinkButton to="../options" variant="quiet">See other options</LinkButton>}
            </div>
          </Card>

          {app.queries.length > 0 && (
            <Card title="Lender queries">
              <ul className="space-y-4">{app.queries.map((q) => <Query key={q.id + q.status} q={q} caseId={id} onChange={update} />)}</ul>
            </Card>
          )}

          {offer && (
            <Card title={offer.label} rail aside={<Pill tone="amber">Not a real offer</Pill>}>
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                <Stat label="Amount" value={money(offer.amount)} />
                <Stat label="Monthly repayment" value={money(offer.monthly_payment)} sub={offer.repayment_type === "interest_only" ? "interest only" : "EMI"} />
                <Stat label="Rate / APR" value={`${offer.rate_pct}% / ${offer.apr_pct}%`} />
                <Stat label="Tenure" value={`${offer.tenure_months} months`} />
              </div>
              <div className="mt-4"><Rows rows={[["Fees and charges", money(offer.fees)], ["Total repayment", money(offer.total_repayment)]]} /></div>
              <p className="mt-3 font-medium">Conditions</p>
              <Bullets items={offer.conditions} />
              <p className="mt-3 text-sm text-muted">{offer.validity}</p>
            </Card>
          )}

          {app.status === "rejected" && (
            <Notice tone="danger" title={`${app.decision_label} (simulated)`}>
              <p>{app.decision_explanation}</p>
              {app.failed_rules.length > 0 && <div className="mt-3"><Rules rules={app.failed_rules} /></div>}
              <p className="mt-3 text-muted">This is not the end of the road. The diagnosis and the restructuring page show what could change before trying another route.</p>
            </Notice>
          )}
          {app.status === "human_review" && <Notice tone="amber" title="With a LoanKart advisor"><p>{app.decision_explanation ?? "This case needs a person. The advisor has the full history."}</p></Notice>}
        </div>

        <div className="lg:col-span-5">
          <Card title="Timeline">
            {app.events.length === 0 ? <p className="text-muted">No updates yet.</p> : (
              <ol>
                {app.events.map((e, i) => (
                  <li key={e.id} className="relative flex gap-3 pb-5 last:pb-0">
                    {i < app.events.length - 1 && <span aria-hidden className="absolute left-[7px] top-5 h-full w-px bg-line" />}
                    <span aria-hidden className="z-10 mt-1.5 h-[15px] w-[15px] shrink-0 rounded-full border-2 border-teal bg-surface" />
                    <div className="min-w-0">
                      <p className="font-medium">{e.title}</p>
                      {e.detail && <p className="text-muted">{e.detail}</p>}
                      <p className="text-sm text-muted">{formatDateTime(e.created_at)} · {e.actor.replace(/-/g, " ")}</p>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}
