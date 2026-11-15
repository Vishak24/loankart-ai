import { useNavigate } from "react-router";
import { apiUrl, type Proposal as P } from "../api/client";
import { applicationService } from "../api/services";
import { Bullets, Button, Card, EmptyState, ErrorNotice, LinkButton, Loading, NarrativeCard, PageTitle, Pill, Rows, StatePill, useAction, useLoad, type Tone } from "../components/ui";
import { money } from "../format";
import { useCase } from "./CaseLayout";

const ITEM: Record<P["checklist"][number]["status"], [Tone, string]> = {
  on_file: ["success", "On file"], missing: ["amber", "Missing"], to_provide: ["neutral", "You provide"],
};

export default function Proposal() {
  const { caseData, refresh } = useCase();
  const id = caseData.id;
  const navigate = useNavigate();
  const { data: p, error, reload, setData } = useLoad(() => applicationService.proposal(id), [id]);
  const action = useAction();

  if (error) return error.includes("Select") ? <EmptyState title="Choose a financing option first"><LinkButton to="../options" size="sm">Compare options</LinkButton></EmptyState> : <ErrorNotice message={error} onRetry={reload} />;
  if (!p) return <Loading label="Preparing proposal" lines={6} />;
  const groups = [...new Set(p.checklist.map((c) => c.group))];
  const submitted = p.status === "submitted";

  return (
    <>
      <div role="note" className="mb-5 rounded-xl border-2 border-amber bg-amber-wash px-4 py-3 text-center text-lg font-bold tracking-wide">{p.disclaimer}</div>
      <PageTitle title="Your financing proposal" lead={`A reviewable plan for ${p.option.product_name} from ${p.option.lender_name}. Nothing has been sent to anyone yet.`}
        aside={<a href={apiUrl(p.pdf_url)} target="_blank" rel="noreferrer" className="inline-flex min-h-11 items-center rounded-lg border border-line bg-surface px-4 text-sm font-semibold hover:border-ink/40">Open the draft as a PDF</a>} />

      <div className="grid gap-6 lg:grid-cols-12">
        <div className="space-y-6 lg:col-span-7">
          {p.summary && <NarrativeCard narrative={p.summary} />}
          <Card title="Proposed structure" aside={<Pill tone="amber">Illustrative estimate</Pill>}>
            <Rows rows={p.structure.map((s) => [s.code, s.label])} />
          </Card>
          <Card title="Figures this proposal relies on">
            <ul className="divide-y divide-line">
              {p.facts_used.map((h) => (
                <li key={h.key} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2">
                  <span className="text-muted">{h.label}</span>
                  <span className="flex flex-wrap items-center gap-2"><span className="font-semibold">{money(h.value)}</span><StatePill state={h.state} label={h.state_label} /></span>
                </li>
              ))}
            </ul>
          </Card>
          {p.option.required_changes.length > 0 && <Card title="What you would need to do"><Bullets items={p.option.required_changes} /></Card>}
          {p.option.risks.length > 0 && <Card title="Risks to weigh"><Bullets items={p.option.risks} tone="amber" /></Card>}
          <Card title="Assumptions"><Bullets items={p.assumptions} /></Card>
        </div>

        <div className="space-y-6 lg:col-span-5">
          <Card title="Document checklist">
            {groups.map((g) => (
              <div key={g} className="mb-4 last:mb-0">
                <h3 className="mb-1 text-sm font-semibold uppercase tracking-wide text-muted">{g}</h3>
                <ul className="divide-y divide-line">
                  {p.checklist.filter((c) => c.group === g).map((c) => (
                    <li key={c.id} className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1 py-2">
                      <div className="min-w-0 flex-1"><p className="font-medium">{c.label}</p><p className="text-sm text-muted">{c.detail}</p></div>
                      <Pill tone={ITEM[c.status][0]}>{ITEM[c.status][1]}</Pill>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </Card>
          {p.unresolved.length > 0 && <Card title="Still unresolved"><Bullets items={p.unresolved} tone="amber" /></Card>}
          <Card title="Before you submit" rail>
            <ul className="space-y-3">
              {p.checkpoints.map((c) => (
                <li key={c.key}>
                  <label className="flex cursor-pointer items-start gap-3">
                    <input type="checkbox" className="mt-0.5 h-5 w-5 shrink-0 accent-teal" checked={c.done} disabled={submitted || action.busy !== null}
                      onChange={(e) => action.run(c.key, async () => { setData(await applicationService.checkpoint(id, c.key, e.target.checked)); await refresh(); })} />
                    <span>{c.label}</span>
                  </label>
                </li>
              ))}
            </ul>
            {action.error && <p role="alert" className="mt-3 text-danger">{action.error}</p>}
            <div className="mt-5 flex flex-wrap gap-3">
              {submitted ? <LinkButton to="../tracking">Go to tracking</LinkButton> : (
                <Button disabled={p.status !== "ready"} busy={action.busy === "submit"}
                  onClick={() => action.run("submit", async () => { await applicationService.submit(id); await refresh(); navigate("../tracking"); })}>
                  Submit the simulated application
                </Button>
              )}
              {!submitted && <LinkButton to="../options" variant="quiet">Change option</LinkButton>}
            </div>
            {!submitted && p.status !== "ready" && <p className="mt-3 text-sm text-muted">Tick all three to continue.</p>}
          </Card>
        </div>
      </div>
    </>
  );
}
