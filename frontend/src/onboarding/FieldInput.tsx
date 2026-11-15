import { formatNumber, inIndianUnits } from "../format";
import { useT } from "../i18n";
import type { Messages } from "../i18n/en";
import { INDIAN_STATES, UNSURE, type Field } from "./steps";

type Props = {
  field: Field;
  value: string;
  error?: string;
  onChange: (v: string) => void;
  /** Visible label for multi-field steps; single-field steps use the question title via aria-labelledby. */
  label?: string;
  labelledBy?: string;
  autoFocus?: boolean;
};

const inputCls = (error?: string) =>
  `block w-full rounded-lg border bg-surface px-4 py-3 text-lg text-ink placeholder:text-muted/70 focus:border-teal focus:outline-none focus:ring-2 focus:ring-teal/20 ${
    error ? "border-danger" : "border-line"
  }`;

export function FieldInput({ field, value, error, onChange, label, labelledBy, autoFocus }: Props) {
  const t = useT();
  const id = `f-${field.name}`;
  const errId = `${id}-err`;
  const q = (t.questions as Record<string, { label?: string; placeholder?: string; suffix?: string }>)[field.name] ?? {};
  const aria = {
    "aria-invalid": error ? true : undefined,
    "aria-describedby": error ? errId : undefined,
    "aria-labelledby": label ? undefined : labelledBy,
  };

  let control;
  if (field.kind === "choice") {
    const opts = t.options[field.options!] as Record<string, string>;
    control = (
      <div role="radiogroup" aria-labelledby={label ? `${id}-label` : labelledBy} aria-describedby={aria["aria-describedby"]} className="grid gap-2">
        {Object.entries(opts).map(([code, text], i) => {
          const checked = value === code;
          return (
            <label
              key={code}
              className={`flex min-h-13 cursor-pointer items-center gap-3 rounded-lg border px-4 py-3 text-base transition-colors has-focus-visible:outline-3 has-focus-visible:outline-teal ${
                checked ? "border-teal bg-teal-wash font-medium" : "border-line bg-surface hover:border-ink/40"
              }`}
            >
              <input
                type="radio"
                name={field.name}
                value={code}
                checked={checked}
                onChange={() => onChange(code)}
                autoFocus={autoFocus && (checked || (!value && i === 0))}
                className="h-5 w-5 accent-teal"
              />
              {text}
            </label>
          );
        })}
      </div>
    );
  } else if (field.kind === "state") {
    control = (
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className={inputCls(error)} {...aria}>
        <option value="">{q.placeholder}</option>
        {INDIAN_STATES.map((s) => <option key={s}>{s}</option>)}
      </select>
    );
  } else if (field.kind === "textarea") {
    control = (
      <textarea id={id} rows={3} value={value} placeholder={q.placeholder} onChange={(e) => onChange(e.target.value)} className={inputCls(error)} {...aria} />
    );
  } else if (field.kind === "money") {
    const unsure = value === UNSURE;
    const n = unsure ? 0 : Number(value);
    control = (
      <>
        <div className="relative">
          <span aria-hidden className="pointer-events-none absolute inset-y-0 left-4 flex items-center text-lg text-muted">₹</span>
          <input
            id={id}
            inputMode="numeric"
            autoComplete="off"
            autoFocus={autoFocus}
            value={value && !unsure ? formatNumber(n) : ""}
            placeholder={unsure ? t.common.notSure : "0"}
            onChange={(e) => onChange(e.target.value.replace(/\D/g, "").replace(/^0+(?=\d)/, ""))}
            className={`${inputCls(error)} pl-9`}
            {...aria}
          />
        </div>
        {value && n > 0 && <p className="mt-2 text-sm text-muted">{inIndianUnits(n)}</p>}
        {field.unsure && (
          <label className="mt-3 flex min-h-11 cursor-pointer items-center gap-3 text-base">
            <input type="checkbox" checked={unsure} onChange={(e) => onChange(e.target.checked ? UNSURE : "")} className="h-5 w-5 accent-teal" />
            {t.common.notSure}
          </label>
        )}
      </>
    );
  } else {
    const decimal = field.name === "business_vintage_years";
    control = (
      <div className="flex items-center gap-3">
        <input
          id={id}
          inputMode={decimal ? "decimal" : "numeric"}
          autoComplete={field.kind === "text" ? (field.name === "borrower_name" ? "name" : "off") : "off"}
          autoFocus={autoFocus}
          value={value}
          placeholder={q.placeholder}
          onChange={(e) =>
            onChange(field.kind === "number" ? e.target.value.replace(decimal ? /[^\d.]/g : /\D/g, "") : e.target.value)
          }
          className={`${inputCls(error)} ${field.kind === "number" ? "max-w-40" : ""}`}
          {...aria}
        />
        {q.suffix && <span className="text-lg text-muted">{q.suffix}</span>}
      </div>
    );
  }

  return (
    <div>
      {label && (
        <label id={`${id}-label`} htmlFor={id} className="mb-2 block font-medium text-ink">
          {label}
          {field.optional && <span className="ml-2 text-sm font-normal text-muted">{t.common.optional}</span>}
        </label>
      )}
      {control}
      {error && <p id={errId} className="mt-2 text-sm font-medium text-danger">{error}</p>}
    </div>
  );
}

export function fieldLabel(t: Messages, name: string): string | undefined {
  return (t.questions as Record<string, { label?: string }>)[name]?.label;
}
