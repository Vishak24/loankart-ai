import { fmt, useT } from "../i18n";
import type { SectionId, Step } from "./steps";

/** Progress thread: one segment per visible question, grouped by section. */
export function ProgressThread({ steps, currentIndex }: { steps: Step[]; currentIndex: number }) {
  const t = useT();
  const sections: { id: SectionId; steps: number[] }[] = [];
  steps.forEach((s, i) => {
    const last = sections[sections.length - 1];
    if (last?.id === s.section) last.steps.push(i);
    else sections.push({ id: s.section, steps: [i] });
  });
  const onReview = currentIndex >= steps.length;
  const currentSection: SectionId = onReview ? "review" : steps[currentIndex].section;

  return (
    <div className="mb-8">
      <div className="mb-3 flex items-baseline justify-between gap-4 text-sm">
        <span className="font-semibold text-teal">{t.onboarding.sections[currentSection]}</span>
        {!onReview && (
          <span className="text-muted">{fmt(t.onboarding.questionOf, { current: currentIndex + 1, total: steps.length })}</span>
        )}
      </div>
      <div
        className="flex gap-2"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={steps.length}
        aria-valuenow={Math.min(currentIndex, steps.length)}
        aria-label={t.onboarding.sections[currentSection]}
      >
        {sections.map((sec) => (
          <div key={sec.id} className="flex flex-1 gap-0.5" style={{ flexGrow: sec.steps.length }}>
            {sec.steps.map((i) => (
              <span
                key={i}
                className={`h-1.5 flex-1 rounded-full transition-colors ${
                  i < currentIndex ? "bg-teal" : i === currentIndex ? "bg-ink" : "bg-line"
                }`}
              />
            ))}
          </div>
        ))}
      </div>
      <ol className="mt-2 hidden gap-2 text-[13px] text-muted sm:flex">
        {sections.map((sec) => (
          <li key={sec.id} className={`flex-1 truncate ${sec.id === currentSection ? "text-ink" : ""}`} style={{ flexGrow: sec.steps.length }}>
            {t.onboarding.sections[sec.id]}
          </li>
        ))}
      </ol>
    </div>
  );
}
