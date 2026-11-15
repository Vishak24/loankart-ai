import { useState } from "react";
import { apiUrl, type Finding, type Investigation as Inv } from "../api/client";
import { aiProviderService, investigationService } from "../api/services";
import {
  Bullets, Button, Card, EmptyState, ErrorNotice, LinkButton, Loading, NarrativeCard, Notice, PageTitle, Pill, SeverityPill,
  VerificationPill, useAction, useLoad, type Tone,
} from "../components/ui";
import { humanise, money } from "../format";
import { useCase } from "./CaseLayout";

const DIMENSION: Record<string, string> = {
  amount: "Test a different amount or tenure", liabilities: "Look at existing loans", collateral: "Compare secured routes",
  product: "Compare loan types", evidence: "Strengthen the evidence", structure: "Consider a co-applicant", documentation: "Close document gaps",
};
const RECON: Record<Inv["reconciliation"][number]["status"], [Tone, string]> = {
  matched: ["success", "Matched"], variance: ["amber", "Difference"], missing: ["neutral", "Not available"],
};

/** Formats a figure by what its name says it is. Missing values are shown as missing. */
function figure(key: string, value: unknown): string {
  if (value == null) return "Not available";
  if (typeof value !== "number") return String(value);
  if (/pct$/.test(key)) return `${value}%`;
  if (/dscr|multiple/.test(key)) return `${value}x`;
  if (/count|returns|filings|months|days|years/.test(key)) return String(value);
  return money(value);
}

function FindingCard({ f, caseId, onChange }: { f: Finding; caseId: string; onChange: (inv: Inv) => void }) {
  const [all, setAll] = useState(false);
  const action = useAction();
  const evidence = all ? f.evidence : f.evidence.slice(0, 3);
  const mark = (a: "confirm" | "not_relevant") => action.run(a, async () => onChange(await investigationService.feedback(caseId, f.id, a)));
  return (
    <article className="rounded-xl border border-line bg-surface p-4 sm:p-6">
      <div className="flex flex-wrap items-center gap-2">
        <SeverityPill severity={f.severity} />
        <VerificationPill finding={f} />
        <span className="text-sm text-muted">{f.category} · {f.id}</span>
      </div>
      <h3 className="mt-3 text-lg font-semibold leading-snug">{f.title}</h3>
      <p className="mt-2">{f.explanation}</p>

      <details className="mt-4 rounded-lg border border-line">
        <summary className="min-h-11 px-4 py-2.5 font-medium text-teal">How we know: figures and {f.evidence.length} source reference{f.evidence.length === 1 ? "" : "s"}</summary>
        <div className="space-y-4 border-t border-line p-4">
          <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
            {Object.entries(f.figures).map(([k, v]) => (
              <div key={k} className="flex items-baseline justify-between gap-3 border-b border-line py-1">
                <dt className="text-muted">{humanise(k)}</dt><dd className="font-medium">{figure(k, v)}</dd>
              </div>
            ))}
          </dl>
          {f.evidence.length > 0 && (
            <ul className="space-y-2">
              {evidence.map((e, i) => (
                <li key={i} className="text-sm">
                  <a href={apiUrl(`/api/documents/${encodeURIComponent(e.document_id)}/file`)} target="_blank" rel="noreferrer" className="font-medium text-teal underline underline-offset-4">{e.document_title}</a>
                  <span className="text-muted"> · {e.locator}: </span><span className="font-medium">{e.value}</span>
                </li>
              ))}
            </ul>
          )}
          {f.evidence.length > 3 && (
            <button type="button" className="min-h-11 text-sm font-semibold text-teal underline underline-offset-4" onClick={() => setAll(!all)}>
              {all ? "Show fewer" : `Show all ${f.evidence.length} references`}
            </button>
          )}
        </div>
      </details>

      {f.unresolved_questions.length > 0 && (
        <div className="mt-4"><p className="mb-1 font-medium">Still uncertain</p><Bullets items={f.unresolved_questions} tone="amber" /></div>
      )}
      <p className="mt-4"><span className="font-medium">What would help: </span>{f.next_action}</p>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        {f.dimension && <LinkButton to="../restructure" size="sm" variant="quiet">{DIMENSION[f.dimension] ?? "See what could change"}</LinkButton>}
        {f.feedback ? (
          <Pill tone={f.feedback.action === "confirm" ? "success" : "neutral"}>{f.feedback.action === "confirm" ? "Confirmed by you" : "You marked this as not relevant"}</Pill>
        ) : f.severity !== "info" && (
          <>
            <Button size="sm" variant="quiet" busy={action.busy === "confirm"} onClick={() => mark("confirm")}>This is right</Button>
            <Button size="sm" variant="quiet" busy={action.busy === "not_relevant"} onClick={() => mark("not_relevant")}>Not relevant to me</Button>
          </>
        )}
        {f.advisor_review && <Pill tone="teal">Advisor {f.advisor_review.action === "accept" ? "agreed" : "disagreed"}{f.advisor_review.note ? `: ${f.advisor_review.note}` : ""}</Pill>}
      </div>
      {action.error && <p role="alert" className="mt-2 text-danger">{action.error}</p>}
    </article>
  );
}

function Questions({ inv, caseId, onChange }: { inv: Inv; caseId: string; onChange: (inv: Inv) => void }) {
  const action = useAction();
  const [text, setText] = useState<Record<string, string>>({});
  if (!inv.clarifications.length) return null;
  const send = (id: string, answer: string) => action.run(id, async () => onChange(await investigationService.answer(caseId, id, answer)));
  return (
    <Card title="Questions for you" id="questions">
      <p className="mb-4 text-muted">Your answers are recorded as “confirmed by you” and the analysis is recalculated. They never overwrite what a document shows.</p>
      <ul className="space-y-5">
        {inv.clarifications.map((c) => (
          <li key={c.id}>
            <p className="font-medium">{c.question}</p>
            <p className="text-sm text-muted">{c.why}</p>
            {c.free_text ? (
              c.answer ? <p className="mt-2"><Pill tone="success">Your answer</Pill> {c.answer}</p> : (
                <div className="mt-2 flex flex-wrap gap-2">
                  <input aria-label={c.question} value={text[c.id] ?? ""} onChange={(e) => setText({ ...text, [c.id]: e.target.value })}
                    className="min-h-11 min-w-0 flex-1 rounded-lg border border-line bg-surface px-3" />
                  <Button size="sm" busy={action.busy === c.id} disabled={!(text[c.id] ?? "").trim()} onClick={() => send(c.id, text[c.id].trim())}>Send</Button>
                </div>
              )
            ) : (
              <div role="group" aria-label={c.question} className="mt-2 flex flex-wrap gap-2">
                {c.options.map((o) => (
                  <button key={o.code} type="button" disabled={action.busy === c.id} onClick={() => send(c.id, o.code)} aria-pressed={c.answer === o.code}
                    className={`min-h-11 rounded-lg border px-3 text-left text-[15px] ${c.answer === o.code ? "border-teal bg-teal-wash font-semibold" : "border-line bg-surface hover:border-teal"}`}>
                    {o.label}
                  </button>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>
      {action.error && <p role="alert" className="mt-3 text-danger">{action.error}</p>}
    </Card>
  );
}

export default function Diagnosis() {
  const { caseData } = useCase();
  const id = caseData.id;
  const { data: inv, error, reload, setData } = useLoad(() => investigationService.get(id), [id]);
  const action = useAction();
  const [tamil, setTamil] = useState<string | null>(null);

  if (error) return <ErrorNotice message={error} onRetry={reload} />;
  if (!inv) return <Loading label="Loading findings" lines={5} />;
  if (inv.status !== "complete") return <EmptyState title="The investigation has not finished"><LinkButton to="../investigation" size="sm">Go to the investigation</LinkButton></EmptyState>;

  // Lead with the few findings that matter; minor points and context stay one click away.
  const main = inv.findings.filter((f) => f.severity === "high" || f.severity === "medium");
  const info = inv.findings.filter((f) => f.severity === "low" || f.severity === "info");
  const translate = () => action.run("ta", async () => {
    const out = await aiProviderService.translate(`${inv.summary!.headline}. ${inv.summary!.body}`, "ta-IN");
    setTamil(out.fallback ? "Tamil translation needs live mode with a Sarvam API key. See API_SETUP.md." : out.text);
  });

  return (
    <>
      <PageTitle title="What may have affected the application"
        lead="These are possible contributing factors found in your documents. A lender's actual reasons are only known where a document states them, and each finding says which it is." />
      <div className="space-y-6">
        <Card title="In plain language"
          aside={<Button size="sm" variant="quiet" busy={action.busy === "explain"} onClick={() => action.run("explain", async () => { setTamil(null); setData(await investigationService.explain(id)); })}>
            {inv.summary ? "Write it again" : "Explain the findings"}
          </Button>}>
          {inv.summary ? (
            <>
              <NarrativeCard narrative={inv.summary} />
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <Button size="sm" variant="quiet" busy={action.busy === "ta"} onClick={translate}>தமிழில் படிக்க (Read in Tamil)</Button>
              </div>
              {tamil && <p lang="ta" className="mt-3 rounded-lg border border-line p-3">{tamil}</p>}
            </>
          ) : <p className="text-muted">Ask for a short summary of the findings below. It explains them; it does not add or change any figure.</p>}
          {action.error && <p role="alert" className="mt-2 text-danger">{action.error}</p>}
        </Card>

        {main.length === 0 && <Notice tone="success" title="No clear problem found"><p>The documents supplied did not show a likely factor. The options page shows which simulated lenders fit as things stand.</p></Notice>}
        {main.map((f) => <FindingCard key={f.id} f={f} caseId={id} onChange={setData} />)}

        <Questions inv={inv} caseId={id} onChange={setData} />

        <Card title="Cross-checks between your sources">
          <ul className="divide-y divide-line">
            {inv.reconciliation.map((r) => (
              <li key={r.item} className="grid gap-x-4 gap-y-1 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
                <div>
                  <p className="font-medium">{r.item}</p>
                  <p className="text-sm text-muted">{r.source_a}: <strong className="text-ink">{money(r.value_a)}</strong> · {r.source_b}: <strong className="text-ink">{money(r.value_b)}</strong>{r.variance_pct != null ? ` · ${r.variance_pct}% difference` : ""}</p>
                  {r.note && <p className="text-sm text-muted">{r.note}</p>}
                </div>
                <Pill tone={RECON[r.status][0]}>{RECON[r.status][1]}</Pill>
              </li>
            ))}
          </ul>
        </Card>

        {inv.missing_documents.length > 0 && (
          <Card title="Documents that would help">
            <ul className="space-y-3">{inv.missing_documents.map((m) => <li key={m.label}><p className="font-medium">{m.label}</p><p className="text-sm text-muted">{m.reason}</p></li>)}</ul>
          </Card>
        )}

        {info.length > 0 && (
          <details className="rounded-xl border border-line bg-surface">
            <summary className="min-h-12 px-4 py-3 font-semibold sm:px-6">Also noted ({info.length}): minor points, context and strengths</summary>
            <div className="space-y-4 border-t border-line p-4 sm:p-6">{info.map((f) => <FindingCard key={f.id} f={f} caseId={id} onChange={setData} />)}</div>
          </details>
        )}

        <div className="flex flex-wrap gap-3">
          <LinkButton to="../restructure">Explore ways to improve</LinkButton>
        </div>
      </div>
    </>
  );
}
