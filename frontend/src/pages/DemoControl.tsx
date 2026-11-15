import { useState } from "react";
import { Link } from "react-router";
import type { S } from "../api/client";
import { aiProviderService, demoService } from "../api/services";
import { LenderCatalogue } from "../components/LenderCatalogue";
import { Button, Card, ErrorNotice, Layout, Loading, Notice, PageTitle, Pill, useAction, useLoad, type Tone } from "../components/ui";
import { formatDateTime, money } from "../format";

const PROVIDER: Record<S["ProviderStatus"]["state"], [Tone, string]> = {
  mock: ["neutral", "Mock"], ready: ["teal", "Key set, not checked"], not_configured: ["neutral", "Not configured"],
  ok: ["success", "Connected"], error: ["danger", "Error"], not_available: ["amber", "Fixture only"],
};
const TASK_TONE: Record<string, Tone> = { complete: "success", running: "teal", needs_input: "amber", failed: "danger", queued: "neutral" };

export default function DemoControl() {
  const state = useLoad(() => demoService.state(), []);
  const scenarios = useLoad(() => demoService.scenarios(), []);
  const ai = useLoad(() => aiProviderService.status(), []);
  const logs = useLoad(() => demoService.logs(), []);
  const [caseId, setCaseId] = useState("");
  const [truth, setTruth] = useState<S["GroundTruthOut"] | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const action = useAction();

  const refresh = () => Promise.all([state.reload(), scenarios.reload(), ai.reload(), logs.reload()]);
  const done = async (text: string) => { setMessage(text); await refresh(); };
  const error = state.error ?? scenarios.error ?? ai.error ?? logs.error;
  if (error) return <Layout wide><ErrorNotice message={error} onRetry={refresh} /></Layout>;
  if (!state.data || !scenarios.data || !ai.data || !logs.data) return <Layout wide><Loading label="Loading demo state" lines={6} /></Layout>;
  const selected = caseId || state.data.cases[0]?.case_id || "";
  const current = state.data.cases.find((c) => c.case_id === selected);

  return (
    <Layout wide>
      <PageTitle title="Demo control centre" lead="For preparing and running the demonstration. Not part of the borrower's product." aside={<Pill tone="amber">Internal</Pill>} />
      {message && <div className="mb-4"><Notice tone="success"><p role="status">{message}</p></Notice></div>}
      {action.error && <div className="mb-4"><ErrorNotice message={action.error} /></div>}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Reset">
          <p className="text-muted">Returns every case, document, lender policy, knowledge entry and event to the initial state. The same scenario then produces the same results again.</p>
          <div className="mt-4 flex flex-wrap gap-3">
            {confirmReset ? (
              <>
                <Button variant="danger" busy={action.busy === "reset"} onClick={() => action.run("reset", async () => { await demoService.reset(); setConfirmReset(false); setTruth(null); setCaseId(""); await done("Demo reset to its initial state."); })}>Yes, reset everything</Button>
                <Button variant="quiet" onClick={() => setConfirmReset(false)}>Cancel</Button>
              </>
            ) : <Button variant="danger" onClick={() => setConfirmReset(true)}>Reset all demo data</Button>}
          </div>
        </Card>

        <Card title="AI mode" aside={<Pill tone={ai.data.effective_mode === "live" ? "teal" : "neutral"}>Running in {ai.data.effective_mode} mode</Pill>}>
          <p className="text-muted">{ai.data.note}</p>
          <div className="mt-4 flex flex-wrap gap-3">
            {(["mock", "live"] as const).map((m) => (
              <Button key={m} size="sm" variant={ai.data!.mode === m ? "primary" : "quiet"} busy={action.busy === `mode-${m}`}
                onClick={() => action.run(`mode-${m}`, async () => { ai.setData(await aiProviderService.setMode(m)); await done(`AI mode set to ${m}.`); })}>
                {m === "mock" ? "Mock (no external calls)" : "Live AI"}
              </Button>
            ))}
            <Button size="sm" variant="quiet" busy={action.busy === "check"} onClick={() => action.run("check", async () => { ai.setData(await aiProviderService.check()); setMessage("Connectivity checked. Results are shown beside each provider."); })}>Check provider connectivity</Button>
          </div>
        </Card>
      </div>

      <div className="mt-6 space-y-6">
        <Card title="Providers">
          <ul className="divide-y divide-line">
            {ai.data.providers.map((p) => (
              <li key={p.name} className="grid gap-x-4 gap-y-1 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
                <div><p className="font-medium">{p.name} <span className="font-normal text-muted">· {p.model}</span></p><p className="text-sm text-muted">{p.purpose}. {p.detail}</p></div>
                <Pill tone={PROVIDER[p.state][0]}>{PROVIDER[p.state][1]}</Pill>
              </li>
            ))}
          </ul>
        </Card>

        <Card title="Synthetic borrowers">
          <ul className="space-y-3">
            {scenarios.data.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line p-4">
                <div className="min-w-0 flex-1 basis-64">
                  <p className="font-semibold">{s.business_name} {s.primary && <Pill tone="teal">Primary demo</Pill>}</p>
                  <p className="text-muted">{s.borrower_name} · {s.title}</p>
                  <p className="text-sm text-muted">Built to test: {s.tests}</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="quiet" busy={action.busy === `load-${s.id}`} onClick={() => action.run(`load-${s.id}`, async () => { await demoService.load(s.id); setCaseId(s.case_id); setTruth(null); await done(`${s.business_name} loaded with its document pack.`); })}>{s.loaded ? "Reload" : "Load"}</Button>
                  {s.loaded && <Link to={`/case/${s.case_id}/investigation`} className="inline-flex min-h-11 items-center rounded-lg bg-teal px-4 text-sm font-semibold text-white hover:bg-teal-deep">Open case</Link>}
                </div>
              </li>
            ))}
          </ul>
        </Card>

        <Card title="Case tools">
          {state.data.cases.length === 0 ? <p className="text-muted">No cases loaded.</p> : (
            <>
              <label htmlFor="case-select" className="mb-1 block font-medium">Case</label>
              <select id="case-select" className="min-h-11 w-full rounded-lg border border-line bg-surface px-3 lg:max-w-md" value={selected} onChange={(e) => { setCaseId(e.target.value); setTruth(null); }}>
                {state.data.cases.map((c) => <option key={c.case_id} value={c.case_id}>{c.business_name} ({c.case_id})</option>)}
              </select>
              {current && (
                <>
                  <p className="mt-3 text-muted">{current.documents} documents · investigation {current.investigation_status.replace("_", " ")} · application {current.application_status ?? "not submitted"} · escalation {current.escalation}</p>
                  {current.tasks.length > 0 && <ul className="mt-2 flex flex-wrap gap-2">{current.tasks.map((t) => <li key={t.key}><Pill tone={TASK_TONE[t.status]}>{t.title}: {t.status.replace("_", " ")}</Pill></li>)}</ul>}
                  <div className="mt-4 flex flex-wrap gap-2">
                    <Button size="sm" variant="quiet" busy={action.busy === "regen"} onClick={() => action.run("regen", async () => { const docs = await demoService.regenerate(selected); await done(`${docs.length} PDFs regenerated from the dataset. The investigation was cleared.`); })}>Regenerate documents</Button>
                    {(["query", "rejection", "alternative_offer"] as const).map((a) => (
                      <Button key={a} size="sm" variant="quiet" busy={action.busy === a} onClick={() => action.run(a, async () => { const app = await demoService.trigger(selected, a); await done(`Lender simulator: ${app.status_label}.`); })}>
                        Trigger {a === "query" ? "a lender query" : a === "rejection" ? "a simulated rejection" : "an alternative offer"}
                      </Button>
                    ))}
                    <Button size="sm" variant="quiet" busy={action.busy === "truth"} onClick={() => action.run("truth", async () => setTruth(await demoService.groundTruth(selected)))}>Compare with ground truth</Button>
                  </div>
                  <p className="mt-2 text-sm text-muted">Lender events need a submitted application.</p>
                </>
              )}
              {truth && (
                <div className="mt-4 rounded-lg border border-line p-4">
                  <p className="text-sm text-muted">{truth.note}</p>
                  <p className="mt-2 text-sm"><strong>Deliberate discrepancies:</strong> {truth.deliberate_discrepancies}</p>
                  <div className="mt-3 overflow-x-auto">
                    <table className="w-full min-w-[30rem]">
                      <thead><tr className="border-b-2 border-ink text-left"><th className="py-1.5 font-semibold">Figure</th><th className="py-1.5 text-right font-semibold">Dataset (truth)</th><th className="py-1.5 text-right font-semibold">Read from PDFs</th><th className="py-1.5 text-right font-semibold">Result</th></tr></thead>
                      <tbody>
                        {truth.comparison.map((l) => (
                          <tr key={l.metric} className="border-b border-line">
                            <td className="py-1.5">{l.metric}{l.note && <span className="block text-sm text-muted">{l.note}</span>}</td>
                            <td className="py-1.5 text-right">{l.ground_truth == null ? "–" : l.ground_truth > 100 ? money(l.ground_truth) : l.ground_truth}</td>
                            <td className="py-1.5 text-right">{l.investigated == null ? "Not run" : l.investigated > 100 ? money(l.investigated) : l.investigated}</td>
                            <td className="py-1.5 text-right">{l.match == null ? <Pill>Pending</Pill> : l.match ? <Pill tone="success">Match</Pill> : <Pill tone="danger">Differs</Pill>}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </>
          )}
        </Card>

        <Card title={`Synthetic lender profiles (${state.data.lenders} lenders, ${state.data.products} products)`}>
          <LenderCatalogue />
          <p className="mt-3 text-sm text-muted">Rules can be edited from the advisor workspace, under Lender criteria.</p>
        </Card>

        <div className="grid gap-6 lg:grid-cols-2">
          <Card title="Application events">
            {state.data.application_events.length === 0 ? <p className="text-muted">No simulated lender events yet.</p> : (
              <ul className="space-y-1.5 text-[15px]">{state.data.application_events.map((e) => <li key={e.id}><span className="text-muted">{formatDateTime(e.created_at)} · {e.case_id} · </span>{e.title}</li>)}</ul>
            )}
          </Card>
          <Card title="Logs and errors" aside={<Button size="sm" variant="quiet" onClick={() => { refresh(); }}>Refresh</Button>}>
            {logs.data.length === 0 ? <p className="text-muted">Nothing logged.</p> : (
              <ul className="max-h-96 space-y-1.5 overflow-y-auto text-[15px]">
                {[...logs.data].reverse().map((e) => (
                  <li key={e.id}>{e.kind === "log" && <Pill tone="danger">Log</Pill>} <span className="text-muted">{formatDateTime(e.created_at)} · {e.actor} · </span>{e.title}{e.detail ? <span className="text-muted"> · {e.detail}</span> : null}</li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </Layout>
  );
}
