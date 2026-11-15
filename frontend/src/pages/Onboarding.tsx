import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { ApiError, api } from "../api/client";
import { caseService } from "../api/services";
import { Button, ErrorNotice, Layout, SyntheticBadge } from "../components/ui";
import { fmt, useT } from "../i18n";
import { AnswerList } from "../onboarding/AnswerList";
import { FieldInput, fieldLabel } from "../onboarding/FieldInput";
import { ProgressThread } from "../onboarding/ProgressThread";
import {
  emptyForm, fromProfile, toPayload, validateStep, visibleFields, visibleSteps,
  type FieldName, type FormState,
} from "../onboarding/steps";

const REVIEW = "review";
const DRAFT_KEY = "loankart:onboarding-draft"; // only for new profiles; edits always start from the server copy

type Draft = { form: FormState; stepId: string };

function loadDraft(): Draft | null {
  try {
    const d = JSON.parse(localStorage.getItem(DRAFT_KEY) ?? "null");
    return d?.form ? { form: { ...emptyForm, ...d.form }, stepId: d.stepId ?? "name" } : null;
  } catch {
    return null;
  }
}
const saveDraft = (d: Draft) => { try { localStorage.setItem(DRAFT_KEY, JSON.stringify(d)); } catch { /* storage unavailable */ } };
const clearDraft = () => { try { localStorage.removeItem(DRAFT_KEY); } catch { /* storage unavailable */ } };

export default function Onboarding() {
  const t = useT();
  const navigate = useNavigate();
  const { id: editId } = useParams();
  const [params] = useSearchParams();
  const intent = params.get("intent") === "new" ? "new" : "rejected";
  const isEdit = Boolean(editId);

  const [form, setForm] = useState<FormState>(() => {
    if (isEdit) return emptyForm;
    const draft = loadDraft();
    if (draft) return draft.form;
    return intent === "rejected" ? { ...emptyForm, previously_rejected: "yes" } : emptyForm;
  });
  const [stepId, setStepId] = useState<string>(() => (isEdit ? REVIEW : loadDraft()?.stepId ?? "name"));
  const [errors, setErrors] = useState<Partial<Record<FieldName, string>>>({});
  const [returnToReview, setReturnToReview] = useState(false);
  const [loadState, setLoadState] = useState<"idle" | "loading" | "error">(isEdit ? "loading" : "idle");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [loadMessage, setLoadMessage] = useState<string>(t.errors.notFound);
  const [openingDemo, setOpeningDemo] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);

  const loadExisting = () => {
    if (!editId) return;
    setLoadState("loading");
    api.get(editId)
      .then((b) => { setForm(fromProfile(b)); setLoadState("idle"); })
      .catch((err: ApiError) => {
        // Say why: a missing session is not a missing profile. The server's own text is safe to show.
        setLoadMessage(err.kind === "network" ? t.errors.network : err.kind === "notFound" ? t.errors.notFound : err.message);
        setLoadState("error");
      });
  };

  // The shared synthetic demo borrower. Opening it through the server is what grants this browser access to it.
  const openDemo = async () => {
    setOpeningDemo(true);
    setSaveError(null);
    try {
      const demo = await api.getDemo();
      navigate(`/borrower/intake/${demo.id}`);
    } catch (err) {
      const e = err as ApiError;
      setSaveError(e.kind === "network" ? t.errors.network : e.message);
    } finally {
      setOpeningDemo(false);
    }
  };
  useEffect(loadExisting, [editId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { if (!isEdit) saveDraft({ form, stepId }); }, [form, stepId, isEdit]);
  // Question steps autofocus their first input (labelled by the question); review focuses its heading.
  useEffect(() => { window.scrollTo({ top: 0 }); if (stepId === REVIEW) headingRef.current?.focus(); }, [stepId]);

  const steps = visibleSteps(form);
  const index = stepId === REVIEW ? steps.length : Math.max(0, steps.findIndex((s) => s.id === stepId));
  const step = steps[index];

  const update = (name: FieldName, value: string) => {
    setForm((f) => {
      const next = { ...f, [name]: value };
      // Clear answers to questions that no longer apply, so stale values can't come back.
      if (name === "previously_rejected" && value !== "yes") { next.rejection_reason = ""; next.rejection_note = ""; }
      if (name === "existing_loan_count" && value !== "" && Number(value) === 0) { next.outstanding_loan_amount = ""; next.monthly_emi = ""; }
      return next;
    });
    setErrors((e) => ({ ...e, [name]: undefined }));
  };

  /** First visible step with an invalid answer, if any. */
  const firstInvalid = (f: FormState) => visibleSteps(f).find((s) => Object.keys(validateStep(s, f, t)).length);

  const goNext = (e?: FormEvent) => {
    e?.preventDefault();
    if (!step) return;
    const errs = validateStep(step, form, t);
    if (Object.keys(errs).length) { setErrors(errs); return; }
    if (returnToReview) {
      const invalid = firstInvalid(form);
      if (invalid && invalid.id !== step.id) { setStepId(invalid.id); return; }
      setReturnToReview(false);
      setStepId(REVIEW);
      return;
    }
    setStepId(steps[index + 1]?.id ?? REVIEW);
  };

  const goBack = () => {
    setErrors({});
    if (index === 0) { if (isEdit) navigate(-1); else navigate("/"); }
    else setStepId(steps[index - 1].id);
  };

  const jumpTo = (id: string) => { setReturnToReview(true); setErrors({}); setStepId(id); };

  const save = async () => {
    const invalid = firstInvalid(form);
    if (invalid) { jumpTo(invalid.id); return; }
    setSaving(true);
    setSaveError(null);
    try {
      const payload = toPayload(form);
      const saved = editId ? await api.update(editId, payload) : await api.create(payload);
      const opened = await caseService.open(saved.id, payload.previously_rejected ? "rejected" : "new");
      if (!isEdit) clearDraft();
      navigate(`/case/${opened.id}/investigation`);
    } catch (err) {
      const e = err as ApiError;
      setSaveError(e.kind === "network" ? t.errors.network : e.kind === "notFound" ? t.errors.notFound : fmt(t.errors.server, { detail: e.message }));
    } finally {
      setSaving(false);
    }
  };

  const startOver = () => { clearDraft(); setForm(intent === "rejected" ? { ...emptyForm, previously_rejected: "yes" } : emptyForm); setStepId("name"); setErrors({}); };

  if (loadState === "loading") return <Layout><p className="text-muted">{t.common.loading}</p></Layout>;
  if (loadState === "error") return <Layout><ErrorNotice message={loadMessage} onRetry={loadExisting} /></Layout>;

  const actionBar = (primary: ReactNode) => (
    <div className="fixed inset-x-0 bottom-0 z-10 border-t border-line bg-surface/95 px-4 py-3 backdrop-blur sm:static sm:mt-10 sm:border-0 sm:bg-transparent sm:p-0 sm:backdrop-blur-none">
      <div className="mx-auto flex max-w-[640px] items-center justify-between gap-3">
        <Button variant="quiet" onClick={stepId === REVIEW ? () => setStepId(steps[steps.length - 1].id) : goBack}>{t.common.back}</Button>
        {primary}
      </div>
    </div>
  );

  if (stepId === REVIEW) {
    return (
      <Layout>
        <ProgressThread steps={steps} currentIndex={steps.length} />
        {isEdit && <p className="mb-2 text-sm font-medium text-muted">{t.onboarding.editing}</p>}
        <h1 ref={headingRef} tabIndex={-1} className="text-3xl font-semibold leading-tight tracking-tight focus:outline-none sm:text-4xl">
          {t.onboarding.review.title}
        </h1>
        <p className="mb-8 mt-2 text-muted">{t.onboarding.review.body}</p>
        <AnswerList form={form} onChange={jumpTo} />
        {saveError && <div className="mt-6"><ErrorNotice message={saveError} /></div>}
        {actionBar(
          <Button onClick={save} disabled={saving}>
            {saving ? t.onboarding.review.saving : isEdit ? t.onboarding.review.saveEdit : t.onboarding.review.saveNew}
          </Button>,
        )}
      </Layout>
    );
  }

  const q = t.questions[step.question] as { title: string; help?: string; why?: string };
  const fields = visibleFields(step, form);
  const titleId = `q-${step.id}`;

  return (
    <Layout>
      <ProgressThread steps={steps} currentIndex={index} />
      {!isEdit && index > 0 && <p role="status" className="-mt-4 mb-4 text-sm text-muted">{t.onboarding.saved}</p>}
      {index === 0 && !isEdit && (
        <p className="mb-3 text-muted">{intent === "rejected" ? t.onboarding.introRejected : t.onboarding.introNew}</p>
      )}
      <form onSubmit={goNext} noValidate>
        <h1 id={titleId} className="text-3xl font-semibold leading-tight tracking-tight focus:outline-none sm:text-4xl">
          {q.title}
        </h1>
        {q.help && <p className="mt-2 text-muted">{q.help}</p>}
        {q.why && (
          <details className="mt-3 rounded-lg border border-line bg-surface px-4 py-2 text-muted">
            <summary className="min-h-8 font-medium text-teal">{t.common.whyWeAsk}</summary>
            <p className="pb-2 pt-1">{q.why}</p>
          </details>
        )}
        <div className="mt-8 space-y-6">
          {fields.map((field, i) => (
            <FieldInput
              key={field.name}
              field={field}
              value={form[field.name]}
              error={errors[field.name]}
              onChange={(v) => update(field.name, v)}
              label={step.fields.length > 1 ? fieldLabel(t, field.name) : undefined}
              labelledBy={titleId}
              autoFocus={i === 0}
            />
          ))}
        </div>
        {index === 0 && !isEdit && (
          <button
            type="button"
            onClick={openDemo}
            disabled={openingDemo}
            className="mt-8 block w-full rounded-xl border border-line bg-surface p-4 text-left hover:border-teal"
          >
            <SyntheticBadge />
            <span className="mt-2 block font-semibold text-teal">{t.onboarding.useDemo}</span>
            <span className="mt-1 block text-muted">{t.onboarding.useDemoBody}</span>
          </button>
        )}
        {index === 0 && !isEdit && saveError && <div className="mt-4"><ErrorNotice message={saveError} /></div>}
        {index === 0 && !isEdit && (
          <p className="mt-6 text-sm text-muted">
            {t.onboarding.draftNote}{" "}
            {form.borrower_name && (
              <button type="button" onClick={startOver} className="font-semibold text-teal underline-offset-4 hover:underline">
                {t.onboarding.startOver}
              </button>
            )}
          </p>
        )}
        {actionBar(<Button type="submit">{t.common.continue}</Button>)}
      </form>
    </Layout>
  );
}
