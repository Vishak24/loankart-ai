import { useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import type { S } from "../api/client";
import { advisorService } from "../api/services";
import { LenderCatalogue } from "../components/LenderCatalogue";
import {
  Bullets, Button, Card, EmptyState, ErrorNotice, Layout, Loading, NarrativeCard, Notice, PageTitle, Pill, SeverityPill, StatePill,
  VerificationPill, useAction, useLoad, type Tone,
} from "../components/ui";
import { formatDateTime, humanise, money } from "../format";

const TABS = [["cases", "Cases"], ["escalated", "Escalations"], ["lenders", "Lender criteria"], ["knowledge", "Knowledge review"]] as const;
const STATUS: Record<S["AdvisorCaseRow"]["status"], Tone> = { escalated: "danger", unresolved: "amber", open: "teal", resolved: "success" };
const field = "block min-h-11 w-full rounded-lg border border-line bg-surface px-3 py-2";

function Queue({ status, onOpen }: { status: string; onOpen: (id: string) => void }) {
  const [filter, setFilter] = useState(status);
  const { data, error, reload } = useLoad(() => advisorService.queue(filter), [filter]);
  if (error) return <ErrorNotice message={error} onRetry={reload} />;
  if (!data) return <Loading label="Loading cases" />;
  return (
    <>
      {status === "all" && (
        <div role="group" aria-label="Filter cases" className="mb-4 flex flex-wrap gap-2">
          {["all", "escalated", "unresolved", "open", "resolved"].map((f) => (
            <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}
              className={`min-h-11 rounded-lg border px-3 ${filter === f ? "border-teal bg-teal-wash font-semibold" : "border-line bg-surface hover:border-teal"}`}>{humanise(f)}</button>
          ))}
        </div>
      )}
      {data.length === 0 ? (
        <EmptyState title="No cases here">Cases appear when a borrower starts one. Escalations appear when a borrower asks for an advisor.</EmptyState>
      ) : (
        <ul className="space-y-3">
          {data.map((r) => (
            <li key={r.case_id}>
              <button type="button" onClick={() => onOpen(r.case_id)} className="block w-full rounded-xl border border-line bg-surface p-4 text-left hover:border-teal">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div><p className="text-lg font-semibold">{r.business_name}</p><p className="text-muted">{r.borrower_name} · {r.city} · {money(r.requested_amount)}</p></div>
                  <div className="flex flex-wrap gap-2"><Pill tone={STATUS[r.status]}>{humanise(r.status)}</Pill>{r.is_synthetic && <Pill tone="amber">Synthetic</Pill>}</div>
                </div>
                <dl className="mt-3 grid gap-x-6 gap-y-1 text-[15px] sm:grid-cols-2 lg:grid-cols-4">
                  <div><dt className="inline text-muted">Stage: </dt><dd className="inline font-medium">{humanise(r.stage)}</dd></div>
                  <div><dt className="inline text-muted">Open items: </dt><dd className="inline font-medium">{r.open_items}</dd></div>
                  <div><dt className="inline text-muted">Application: </dt><dd className="inline font-medium">{r.application_status ?? "Not submitted"}</dd></div>
                  <div><dt className="inline text-muted">Last activity: </dt><dd className="inline font-medium">{formatDateTime(r.updated_at)}</dd></div>
                </dl>
                <p className="mt-2"><span className="text-muted">Blocker: </span>{r.blocker}</p>
              </button>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function CaseReview({ caseId, onBack }: { caseId: string; onBack: () => void }) {
  const { data, error, reload, setData } = useLoad(() => advisorService.detail(caseId), [caseId]);
  const action = useAction();
  const [note, setNote] = useState<Record<string, string>>({});
  const [value, setValue] = useState<Record<string, string>>({});
  if (error) return <ErrorNotice message={error} onRetry={reload} />;
  if (!data) return <Loading label="Loading case" lines={6} />;

  const act = (key: string, body: S["AdvisorActionIn"]) => action.run(key, async () => { setData(await advisorService.act(caseId, body)); setNote({ ...note, [key]: "" }); });
  const noteInput = (key: string, label: string) => (
    <input aria-label={label} placeholder={label} className={`${field} min-w-0 flex-1`} value={note[key] ?? ""} onChange={(e) => setNote({ ...note, [key]: e.target.value })} />
  );
  const { investigation: inv, restructure: rs, recommendations: recs, application: app } = data;
  const c = data.case;
  const openQuestions = inv.clarifications.filter((q) => !q.answer || q.answer === "not_sure");

  return (
    <div className="space-y-6">
      <button type="button" onClick={onBack} className="min-h-11 font-semibold text-teal underline underline-offset-4">← Back to the queue</button>
      <Card title={c.borrower.business_name} aside={<Link to={`/case/${c.id}/investigation`} className="font-semibold text-teal underline underline-offset-4">Open the borrower's view</Link>}>
        <p className="text-muted">{c.borrower.borrower_name} · {c.borrower.city} · asked for {money(c.borrower.requested_amount)} · case {c.id}</p>
        {c.escalation.status !== "none" && (
          <div className="mt-4">
            <Notice tone={c.escalation.status === "open" ? "danger" : "success"} title={c.escalation.status === "open" ? "Escalated by the borrower" : "Escalation resolved"}>
              <p>“{c.escalation.reason}”</p>{c.escalation.resolution && <p className="mt-1">Resolution: {c.escalation.resolution}</p>}
            </Notice>
            {c.escalation.summary && <div className="mt-3"><NarrativeCard narrative={c.escalation.summary} /></div>}
          </div>
        )}
      </Card>
      {action.error && <ErrorNotice message={action.error} />}

      {inv.status !== "complete" ? <EmptyState title="The investigation has not been run for this case" /> : (
        <>
          <Card title="Extracted figures">
            <p className="mb-3 text-muted">A correction applies to this case only, is attributed to you, and keeps the original value. It never changes lender policy.</p>
            <ul className="divide-y divide-line">
              {inv.headline.map((h) => (
                <li key={h.key} className="py-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span>{h.label}</span>
                    <span className="flex flex-wrap items-center gap-2"><span className="font-semibold">{h.unit === "inr" ? money(h.value) : h.value ?? "Not available"}</span>
                      <StatePill state={h.state} label={h.state_label} />{h.original != null && <span className="text-sm text-muted">was {h.unit === "inr" ? money(h.original) : h.original}</span>}</span>
                  </div>
                  {data.correctable.includes(h.key) && (
                    <details className="mt-1 text-sm">
                      <summary className="min-h-8 font-medium text-teal">Correct this value</summary>
                      <div className="mt-2 flex flex-wrap gap-2">
                        <input aria-label={`Corrected value for ${h.label}`} inputMode="numeric" placeholder="Correct value" className={`${field} w-36`} value={value[h.key] ?? ""} onChange={(e) => setValue({ ...value, [h.key]: e.target.value.replace(/\D/g, "") })} />
                        {noteInput(`fix-${h.key}`, "Source of the correction (required)")}
                        <Button size="sm" variant="quiet" busy={action.busy === `fix-${h.key}`} disabled={!value[h.key] || !note[`fix-${h.key}`]}
                          onClick={() => act(`fix-${h.key}`, { type: "correct_value", target: h.key, value: Number(value[h.key]), note: note[`fix-${h.key}`] })}>Save correction</Button>
                      </div>
                    </details>
                  )}
                </li>
              ))}
            </ul>
          </Card>

          <Card title={`AI findings (${inv.findings.length})`}>
            <ul className="space-y-4">
              {inv.findings.map((f) => (
                <li key={f.id} className="rounded-lg border border-line p-4">
                  <div className="flex flex-wrap items-center gap-2"><SeverityPill severity={f.severity} /><VerificationPill finding={f} />
                    {f.advisor_review && <Pill tone={f.advisor_review.action === "accept" ? "success" : "danger"}>You {f.advisor_review.action}ed this</Pill>}
                    {f.feedback && <Pill>Borrower: {humanise(f.feedback.action)}</Pill>}</div>
                  <p className="mt-2 font-semibold">{f.title}</p>
                  <p className="mt-1 text-muted">{f.explanation}</p>
                  <p className="mt-1 text-sm text-muted">{f.evidence.length} source reference{f.evidence.length === 1 ? "" : "s"}: {f.source_documents.slice(0, 3).join("; ")}{f.source_documents.length > 3 ? "…" : ""}</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {noteInput(`f-${f.id}`, "Rationale (optional)")}
                    <Button size="sm" variant="quiet" busy={action.busy === `f-${f.id}-accept`} onClick={() => act(`f-${f.id}-accept`, { type: "review_finding", target: f.id, decision: "accept", note: note[`f-${f.id}`] ?? "" })}>Accept</Button>
                    <Button size="sm" variant="quiet" busy={action.busy === `f-${f.id}-reject`} onClick={() => act(`f-${f.id}-reject`, { type: "review_finding", target: f.id, decision: "reject", note: note[`f-${f.id}`] ?? "" })}>Reject</Button>
                  </div>
                </li>
              ))}
            </ul>
          </Card>

          <Card title="Unresolved questions">
            {openQuestions.length === 0 ? <p className="text-muted">Nothing is waiting on the borrower.</p> : <Bullets items={openQuestions.map((q) => q.question)} tone="amber" />}
            <div className="mt-4 flex flex-wrap gap-2">
              {noteInput("ask", "Ask the borrower a question")}
              <Button size="sm" variant="quiet" busy={action.busy === "ask"} disabled={!note.ask} onClick={() => act("ask", { type: "request_clarification", note: note.ask })}>Send to borrower</Button>
            </div>
          </Card>

          {rs && recs && (
            <Card title="Proposed solution" aside={data.solution_review && <Pill tone={data.solution_review.action === "accept" ? "success" : "danger"}>You {data.solution_review.action}ed it</Pill>}>
              <p className="text-muted">Scenario: {money(rs.proposed.fresh_funds)} of fresh funds over {rs.proposed.tenure_months} months; repayments {money(rs.proposed.total_monthly_repayment)} a month against a surplus of {money(rs.proposed.operating_surplus)} (cover {rs.proposed.dscr ?? "–"}x; as requested it was {rs.current.dscr ?? "–"}x).</p>
              {recs.options.length === 0 ? <p className="mt-3 font-medium">No simulated lender fits. {recs.recovery_plan?.steps[0]}</p> : (
                <ul className="mt-3 divide-y divide-line">
                  {recs.options.slice(0, 4).map((o) => (
                    <li key={o.product_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                      <span><span className="font-medium">#{o.rank} {o.product_name}</span> <span className="text-muted">· {o.lender_name}</span>{recs.selected_product_id === o.product_id && <> <Pill tone="teal">Chosen by borrower</Pill></>}</span>
                      <span className="text-[15px]">{money(o.fresh_funds)} · {money(o.monthly_payment)}/month · APR {o.apr_pct}% · score {o.score}</span>
                    </li>
                  ))}
                </ul>
              )}
              <div className="mt-4 flex flex-wrap gap-2">
                {noteInput("sol", "Rationale (optional)")}
                <Button size="sm" variant="quiet" busy={action.busy === "sol-accept"} onClick={() => act("sol-accept", { type: "review_solution", decision: "accept", note: note.sol ?? "" })}>Accept solution</Button>
                <Button size="sm" variant="quiet" busy={action.busy === "sol-reject"} onClick={() => act("sol-reject", { type: "review_solution", decision: "reject", note: note.sol ?? "" })}>Reject solution</Button>
              </div>
            </Card>
          )}
        </>
      )}

      {app && app.reference && (
        <Card title="Application history" aside={<Pill tone="amber">{app.status_label}</Pill>}>
          <ul className="space-y-1.5">{app.events.map((e) => <li key={e.id}><span className="font-medium">{e.title}</span> <span className="text-muted">· {formatDateTime(e.created_at)}{e.detail ? ` · ${e.detail}` : ""}</span></li>)}</ul>
        </Card>
      )}

      <Card title="Comments and resolution">
        {data.comments.length === 0 ? <p className="text-muted">No advisor notes yet.</p> : (
          <ul className="space-y-2">{data.comments.map((m, i) => <li key={i}><Pill>{humanise(m.kind)}</Pill> {m.note} <span className="text-sm text-muted">· {m.by} · {formatDateTime(m.at)}</span></li>)}</ul>
        )}
        <div className="mt-4 flex flex-wrap gap-2">
          {noteInput("comment", "Add a comment or resolution note")}
          <Button size="sm" variant="quiet" busy={action.busy === "comment"} disabled={!note.comment} onClick={() => act("comment", { type: "comment", note: note.comment })}>Add comment</Button>
          <Button size="sm" busy={action.busy === "resolve"} disabled={!note.comment} onClick={() => act("resolve", { type: "resolve", note: note.comment })}>Mark case resolved</Button>
        </div>
      </Card>

      <details className="rounded-xl border border-line bg-surface">
        <summary className="min-h-12 px-4 py-3 font-semibold sm:px-6">Audit trail ({data.audit.length})</summary>
        <ul className="space-y-1.5 border-t border-line p-4 text-[15px] sm:p-6">
          {data.audit.map((e) => <li key={e.id}><span className="text-muted">{formatDateTime(e.created_at)} · {e.actor} · </span>{e.title}{e.detail ? <span className="text-muted"> · {e.detail}</span> : null}</li>)}
        </ul>
      </details>
    </div>
  );
}

function Knowledge() {
  const { data, error, reload } = useLoad(() => advisorService.knowledge(), []);
  const [text, setText] = useState("");
  const [source, setSource] = useState<"text" | "voice">("text");
  const [caseId, setCaseId] = useState("");
  const [recording, setRecording] = useState(false);
  const [voiceNote, setVoiceNote] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const cases = useLoad(() => advisorService.queue("all"), []);
  const action = useAction();

  const record = async () => {
    if (recording) { recorder.current?.stop(); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      rec.ondataavailable = (e) => chunks.push(e.data);
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        setRecording(false);
        const blob = new Blob(chunks, { type: rec.mimeType });
        action.run("voice", async () => {
          const out = await advisorService.transcribe(blob, `note.${rec.mimeType.includes("ogg") ? "ogg" : "webm"}`);
          setText(out.text); setSource("voice");
          setVoiceNote(out.provider === "mock" ? "Mock transcript shown: live speech-to-text needs a Sarvam API key." : "Transcribed by Sarvam speech-to-text. Check it before saving.");
        });
      };
      recorder.current = rec; rec.start(); setRecording(true);
      setTimeout(() => rec.state === "recording" && rec.stop(), 28000);    // the synchronous speech API accepts up to 30 seconds
    } catch { setVoiceNote("The microphone could not be used. Type the note instead."); }
  };

  if (error) return <ErrorNotice message={error} onRetry={reload} />;
  if (!data) return <Loading label="Loading knowledge" />;
  const entry = (k: S["KnowledgeEntry"]) => (
    <li key={k.id} className="rounded-xl border border-line bg-surface p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Pill tone={k.status === "approved" ? "success" : k.status === "rejected" ? "danger" : "amber"}>{humanise(k.status)}</Pill>
        <Pill>Practical experience, not lender policy</Pill><span className="text-sm text-muted">v{k.version} · {k.source} · {k.author}</span>
      </div>
      <dl className="mt-3 space-y-2">
        {([["Problem", k.problem], ["Reasoning", k.reasoning], ["What was done", k.intervention], ["Outcome", k.outcome], ["Scope", k.scope],
          ["Lender and product", [k.lender_name, k.product_id].filter(Boolean).join(" · ") || "Not specific to one lender"]] as const).map(([label, v]) => (
          <div key={label}><dt className="text-sm text-muted">{label}</dt><dd>{v}</dd></div>
        ))}
        <div><dt className="text-sm text-muted">Conditions</dt><dd><Bullets items={k.conditions} /></dd></div>
      </dl>
      <p className="mt-2 text-sm text-muted">{k.verification_status}{k.approver ? ` · approver: ${k.approver}` : ""} · structured by {k.structured_by} · {k.case_id ?? "no case linked"}</p>
      {k.status === "candidate" && (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" busy={action.busy === `ok-${k.id}`} onClick={() => action.run(`ok-${k.id}`, async () => { await advisorService.review(k.id, "approve"); await reload(); })}>Approve for reuse</Button>
          <Button size="sm" variant="quiet" busy={action.busy === `no-${k.id}`} onClick={() => action.run(`no-${k.id}`, async () => { await advisorService.review(k.id, "reject"); await reload(); })}>Reject</Button>
        </div>
      )}
    </li>
  );

  return (
    <div className="space-y-6">
      <Card title="Capture what worked">
        <p className="text-muted">Describe a case you solved: the problem, why your approach worked, what you did and the outcome. It is structured into a candidate and stays inactive until an expert approves it. One success is recorded as one case, not as a rule.</p>
        <label htmlFor="kn-text" className="mb-1 mt-4 block font-medium">Your explanation</label>
        <textarea id="kn-text" rows={5} maxLength={4000} value={text} onChange={(e) => { setText(e.target.value); setSource("text"); }} className={field} />
        {voiceNote && <p role="status" className="mt-1 text-sm text-muted">{voiceNote}</p>}
        <label htmlFor="kn-case" className="mb-1 mt-3 block font-medium">Case it came from <span className="font-normal text-muted">(optional)</span></label>
        <select id="kn-case" className={field} value={caseId} onChange={(e) => setCaseId(e.target.value)}>
          <option value="">Not linked to a case</option>
          {(cases.data ?? []).map((c) => <option key={c.case_id} value={c.case_id}>{c.business_name}</option>)}
        </select>
        {action.error && <p role="alert" className="mt-2 text-danger">{action.error}</p>}
        <div className="mt-4 flex flex-wrap gap-3">
          <Button size="sm" disabled={text.trim().length < 20} busy={action.busy === "capture"}
            onClick={() => action.run("capture", async () => { await advisorService.capture({ text: text.trim(), case_id: caseId || null, author: "Advisor", source }); setText(""); setVoiceNote(null); await reload(); })}>
            Structure as a candidate
          </Button>
          <Button size="sm" variant="quiet" busy={action.busy === "voice"} onClick={record}>{recording ? "Stop recording" : "Record a voice note (up to 30 s)"}</Button>
        </div>
      </Card>
      <ul className="space-y-4">{[...data].reverse().map(entry)}</ul>
    </div>
  );
}

export default function Advisor() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "cases";
  const caseId = params.get("case");
  const go = (next: Record<string, string>) => setParams(next);

  return (
    <Layout wide>
      <PageTitle title="Advisor workspace" lead="Review what the system found, correct it where it is wrong, and record what works." aside={<Pill tone="amber">Prototype: one shared passcode</Pill>} />
      <div className="grid gap-6 lg:grid-cols-12">
        <nav aria-label="Advisor sections" className="lg:col-span-2">
          <ul className="grid grid-cols-2 gap-2 lg:grid-cols-1">
            {TABS.map(([key, label]) => (
              <li key={key}>
                <button type="button" aria-current={tab === key && !caseId ? "page" : undefined} onClick={() => go({ tab: key })}
                  className={`min-h-11 w-full rounded-lg border px-3 text-left font-medium ${tab === key ? "border-teal bg-teal-wash" : "border-line bg-surface hover:border-teal"}`}>{label}</button>
              </li>
            ))}
          </ul>
        </nav>
        <div className="lg:col-span-10">
          {caseId ? <CaseReview caseId={caseId} onBack={() => go({ tab })} />
            : tab === "lenders" ? <LenderCatalogue editable />
            : tab === "knowledge" ? <Knowledge />
            : <Queue key={tab} status={tab === "escalated" ? "escalated" : "all"} onOpen={(id) => go({ tab, case: id })} />}
        </div>
      </div>
    </Layout>
  );
}
