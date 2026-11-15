import { formatINR } from "../format";
import { useT } from "../i18n";
import type { Messages } from "../i18n/en";
import { OPTION_GROUP_BY_FIELD, UNSURE, displayValue, visibleFields, visibleSteps, type Field, type FormState } from "./steps";

function formatAnswer(field: Field, form: FormState, t: Messages): string {
  const raw = form[field.name];
  if (!raw) return t.common.notAnswered;
  if (raw === UNSURE) return t.common.notSure;
  if (field.kind === "money") return formatINR(Number(raw));
  if (field.name === "business_vintage_years") return `${raw} ${t.questions.business_vintage_years.suffix}`;
  return displayValue(field.name, raw, t, OPTION_GROUP_BY_FIELD);
}

/** Answers grouped by section. Pass onChange to show a "Change" link per question. */
export function AnswerList({ form, onChange }: { form: FormState; onChange?: (stepId: string) => void }) {
  const t = useT();
  const steps = visibleSteps(form);
  const sections = [...new Set(steps.map((s) => s.section))];

  return (
    <div className="space-y-8">
      {sections.map((sec) => (
        <section key={sec}>
          <h3 className="mb-1 text-sm font-semibold text-teal">{t.onboarding.sections[sec]}</h3>
          <dl className="divide-y divide-line border-y border-line">
            {steps.filter((s) => s.section === sec).flatMap((step) =>
              visibleFields(step, form).map((field, i) => {
                const label = (step.fields.length > 1 && (t.questions as Record<string, { label?: string }>)[field.name]?.label)
                  || (t.questions[step.question] as { title: string }).title;
                return (
                  <div key={field.name} className="grid grid-cols-[minmax(0,1fr)_4rem] gap-x-4 gap-y-1 py-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_4rem]">
                    <dt className="text-sm text-muted sm:text-base">{label}</dt>
                    <dd className="col-start-1 row-start-2 font-medium break-words sm:col-start-2 sm:row-start-1">
                      {formatAnswer(field, form, t)}
                    </dd>
                    {onChange && i === 0 ? (
                      <button
                        type="button"
                        onClick={() => onChange(step.id)}
                        className="row-span-2 min-h-11 self-center justify-self-end text-sm font-semibold text-teal underline-offset-4 hover:underline sm:row-span-1"
                        aria-label={`${t.common.change}: ${label}`}
                      >
                        {t.common.change}
                      </button>
                    ) : <span />}
                  </div>
                );
              }),
            )}
          </dl>
        </section>
      ))}
    </div>
  );
}
