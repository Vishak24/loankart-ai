import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, NavLink } from "react-router";
import { errorText, type Narrative, type S } from "../api/client";
import { useT } from "../i18n";

// ---------------------------------------------------------------------------------------------- shell

export function Layout({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  const t = useT();
  const width = wide ? "max-w-[1280px]" : "max-w-[640px]";
  const nav = ({ isActive }: { isActive: boolean }) =>
    `rounded-lg px-2 py-2 text-sm font-medium ${isActive ? "text-teal" : "text-muted hover:text-ink"}`;
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex h-14 max-w-[1280px] items-center justify-between gap-3 px-4 sm:px-6">
          <Link to="/" className="text-lg font-semibold tracking-tight text-ink" aria-label={`${t.app.name} – ${t.app.home}`}>
            LoanKart<span className="text-teal">.ai</span>
          </Link>
          <nav aria-label="Main" className="flex items-center gap-1">
            <NavLink to="/advisor" className={nav}>Advisor</NavLink>
            <NavLink to="/demo-control" className={nav}>Demo control</NavLink>
          </nav>
        </div>
      </header>
      <main className={`mx-auto w-full flex-1 px-4 pb-28 pt-6 sm:px-6 sm:pb-16 sm:pt-10 ${width}`}>{children}</main>
      <footer className="border-t border-line px-4 py-5 text-center text-sm text-muted sm:px-6">{t.app.footer}</footer>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------- data loading

export function useLoad<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const reload = useCallback(() => { setError(null); return load().then(setData).catch((e) => setError(errorText(e))); }, deps);
  useEffect(() => { reload(); }, [reload]);
  return { data, error, reload, setData };
}

/** Runs an action, tracking busy and error state so every button gets the same behaviour. */
export function useAction() {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const run = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    setError(null);
    try { await fn(); return true; } catch (e) { setError(errorText(e)); return false; } finally { setBusy(null); }
  };
  return { busy, error, run, clearError: () => setError(null) };
}

export function Loading({ lines = 3, label = "Loading" }: { lines?: number; label?: string }) {
  return (
    <div role="status" aria-label={label} className="space-y-3 rounded-xl border border-line bg-surface p-5">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="h-4 animate-pulse rounded bg-line/70" style={{ width: `${90 - i * 18}%` }} />
      ))}
    </div>
  );
}

export function ErrorNotice({ message, onRetry }: { message: string; onRetry?: () => void }) {
  const t = useT();
  return (
    <div role="alert" className="rounded-xl border border-danger/40 bg-danger-wash p-4 text-danger">
      <p>{message}</p>
      {onRetry && (
        <button type="button" onClick={onRetry} className="mt-2 min-h-11 font-semibold underline underline-offset-4">
          {t.common.retry}
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line bg-surface p-6 text-center">
      <p className="font-semibold">{title}</p>
      {children && <div className="mt-2 text-muted">{children}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------- controls

type ButtonProps = {
  children: ReactNode;
  onClick?: () => void;
  type?: "button" | "submit";
  variant?: "primary" | "quiet" | "danger";
  size?: "md" | "sm";
  disabled?: boolean;
  busy?: boolean;
};

const buttonCls = (variant: ButtonProps["variant"] = "primary", size: ButtonProps["size"] = "md") => {
  const base = "inline-flex items-center justify-center rounded-lg font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60";
  const sizes = size === "sm" ? "min-h-11 px-4 text-sm" : "min-h-12 px-5 text-base";
  const styles = variant === "primary" ? "bg-teal text-white hover:bg-teal-deep"
    : variant === "danger" ? "border border-danger/50 bg-surface text-danger hover:bg-danger-wash"
    : "border border-line bg-surface text-ink hover:border-ink/40";
  return `${base} ${sizes} ${styles}`;
};

export function Button({ children, onClick, type = "button", variant, size, disabled, busy }: ButtonProps) {
  return (
    <button type={type} onClick={onClick} disabled={disabled || busy} aria-busy={busy || undefined} className={buttonCls(variant, size)}>
      {busy ? "Working…" : children}
    </button>
  );
}

export function LinkButton({ to, children, variant, size }: { to: string; children: ReactNode } & Pick<ButtonProps, "variant" | "size">) {
  return <Link to={to} className={buttonCls(variant, size)}>{children}</Link>;
}

// ---------------------------------------------------------------------------------------------- status

export type Tone = "neutral" | "teal" | "amber" | "success" | "danger";
const TONES: Record<Tone, string> = {
  neutral: "border-line bg-paper text-muted",
  teal: "border-teal/30 bg-teal-wash text-teal-deep",
  amber: "border-amber/40 bg-amber-wash text-[#8a5a1b]",
  success: "border-success/30 bg-success-wash text-success",
  danger: "border-danger/30 bg-danger-wash text-danger",
};
// Shape as well as colour, so status never depends on colour alone.
const GLYPH: Record<Tone, string> = { neutral: "○", teal: "●", amber: "▲", success: "✓", danger: "✕" };

export function Pill({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[13px] font-medium leading-5 ${TONES[tone]}`}>
      <span aria-hidden className="text-[10px]">{GLYPH[tone]}</span>
      {children}
    </span>
  );
}

const STATE_TONE: Record<S["HeadlineValue"]["state"], Tone> = {
  verified: "success", extracted: "teal", declared: "neutral", confirmed: "success", corrected: "amber",
  calculated: "teal", missing: "danger", simulated: "amber",
};
export const StatePill = ({ state, label }: { state: S["HeadlineValue"]["state"]; label: string }) => <Pill tone={STATE_TONE[state]}>{label}</Pill>;

const SEVERITY: Record<S["FindingOut"]["severity"], [Tone, string]> = {
  high: ["danger", "Significant"], medium: ["amber", "Moderate"], low: ["neutral", "Minor"], info: ["teal", "For information"],
};
export const SeverityPill = ({ severity }: { severity: S["FindingOut"]["severity"] }) => <Pill tone={SEVERITY[severity][0]}>{SEVERITY[severity][1]}</Pill>;

const VERIFICATION_TONE: Record<S["FindingOut"]["verification_state"], Tone> = {
  confirmed_in_document: "success", evidence_suggests: "amber", requires_confirmation: "danger",
};
export const VerificationPill = ({ finding }: { finding: Pick<S["FindingOut"], "verification_state" | "verification_label"> }) =>
  <Pill tone={VERIFICATION_TONE[finding.verification_state]}>{finding.verification_label}</Pill>;

export function decisionTone(decision: string): Tone {
  if (decision === "eligible") return "success";
  if (["alternative_amount_offered", "additional_documents_required", "clarification_required"].includes(decision)) return "amber";
  return "danger";
}

export function SyntheticBadge() {
  const t = useT();
  return <Pill tone="amber">{t.common.synthetic}</Pill>;
}
export const SimBadge = ({ children = "Demo simulation" }: { children?: ReactNode }) => <Pill tone="amber">{children}</Pill>;

// ---------------------------------------------------------------------------------------------- surfaces

export function Card({ title, aside, children, rail = false, id }: { title?: ReactNode; aside?: ReactNode; children: ReactNode; rail?: boolean; id?: string }) {
  return (
    <section id={id} className={`rounded-xl border border-line bg-surface p-4 sm:p-6 ${rail ? "border-l-4 border-l-teal" : ""}`}>
      {(title || aside) && (
        <div className="mb-4 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
          {title && <h2 className="text-lg font-semibold leading-snug">{title}</h2>}
          {aside}
        </div>
      )}
      {children}
    </section>
  );
}

export function Notice({ tone = "teal", title, children }: { tone?: Tone; title?: string; children: ReactNode }) {
  return (
    <div className={`rounded-xl border p-4 ${TONES[tone]}`}>
      {title && <p className="font-semibold">{title}</p>}
      <div className={`text-ink ${title ? "mt-1" : ""}`}>{children}</div>
    </div>
  );
}

export function Stat({ label, value, sub, pill }: { label: string; value: ReactNode; sub?: ReactNode; pill?: ReactNode }) {
  return (
    <div className="min-w-0">
      <p className="text-sm text-muted">{label}</p>
      <p className="mt-0.5 text-xl font-semibold tracking-tight">{value}</p>
      {sub && <p className="text-sm text-muted">{sub}</p>}
      {pill && <div className="mt-1">{pill}</div>}
    </div>
  );
}

export function Rows({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl className="divide-y divide-line">
      {rows.map(([k, v], i) => (
        <div key={i} className="flex items-baseline justify-between gap-4 py-2">
          <dt className="text-muted">{k}</dt>
          <dd className="text-right font-medium">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Bullets({ items, tone = "muted" }: { items: string[]; tone?: "muted" | "amber" }) {
  if (!items.length) return null;
  return (
    <ul className="space-y-1.5">
      {items.map((x, i) => (
        <li key={i} className="flex gap-2.5">
          <span aria-hidden className={`mt-2.5 h-1.5 w-1.5 shrink-0 rounded-full ${tone === "amber" ? "bg-amber" : "bg-muted"}`} />
          <span>{x}</span>
        </li>
      ))}
    </ul>
  );
}

export function PageTitle({ title, lead, aside }: { title: string; lead?: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-3xl">
        <h1 className="text-[28px] font-semibold leading-tight tracking-tight sm:text-[32px]">{title}</h1>
        {lead && <p className="mt-2 text-muted">{lead}</p>}
      </div>
      {aside}
    </div>
  );
}

/** AI-written text, always labelled as such and kept visually apart from calculated figures. */
export function NarrativeCard({ narrative }: { narrative: Narrative }) {
  const who = narrative.provider === "mock" ? "mock provider" : narrative.provider;
  return (
    <div className="rounded-xl border border-teal/30 bg-teal-wash p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Pill tone="teal">AI-written explanation</Pill>
        <span className="text-sm text-muted">
          {who}{narrative.fallback ? " (live provider unavailable, safe fallback used)" : ""}. Figures come from the calculations, not from AI.
        </span>
      </div>
      <p className="font-semibold">{narrative.headline}</p>
      <p className="mt-1">{narrative.body}</p>
      {(narrative.caveats ?? []).length > 0 && <div className="mt-2 text-sm text-muted"><Bullets items={narrative.caveats ?? []} /></div>}
    </div>
  );
}
