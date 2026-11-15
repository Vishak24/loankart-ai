import type { BorrowerProfile } from "../api/client";
import type { Messages } from "../i18n/en";
import { fmt } from "../i18n";

// Form values are kept as strings so inputs stay controlled; converted to the API shape on save.
export type FormState = Record<keyof BorrowerProfile, string>;
export type FieldName = keyof FormState;

export const emptyForm: FormState = {
  borrower_name: "", business_name: "", industry: "", city: "", state: "",
  business_vintage_years: "", requested_amount: "", loan_purpose: "",
  monthly_revenue: "", monthly_expenses: "", existing_loan_count: "", outstanding_loan_amount: "",
  monthly_emi: "", personal_monthly_income: "", collateral: "", collateral_value: "", gst_status: "",
  business_registration: "", previously_rejected: "", rejection_reason: "", rejection_note: "",
};

export const INDIAN_STATES = [
  "Andaman and Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chandigarh",
  "Chhattisgarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Goa", "Gujarat", "Haryana",
  "Himachal Pradesh", "Jammu and Kashmir", "Jharkhand", "Karnataka", "Kerala", "Ladakh", "Lakshadweep",
  "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Puducherry",
  "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand",
  "West Bengal",
];

type OptionGroup = keyof Messages["options"];
export type FieldKind = "text" | "number" | "money" | "choice" | "state" | "textarea";
export type SectionId = keyof Messages["onboarding"]["sections"];

export interface Field {
  name: FieldName;
  kind: FieldKind;
  options?: OptionGroup;
  optional?: boolean;
  /** Offers an "I'm not sure" choice; the answer is then saved as unknown rather than as zero. */
  unsure?: boolean;
  showIf?: (f: FormState) => boolean;
}

export const UNSURE = "unsure";

export interface Step {
  id: string;
  section: SectionId;
  /** Key in Messages["questions"] holding title/help. */
  question: keyof Messages["questions"];
  fields: Field[];
  showIf?: (f: FormState) => boolean;
}

const hasLoans = (f: FormState) => Number(f.existing_loan_count) > 0;
const wasRejected = (f: FormState) => f.previously_rejected === "yes";
const hasCollateral = (f: FormState) => f.collateral !== "" && f.collateral !== "none";

export const STEPS: Step[] = [
  { id: "name", section: "about", question: "borrower_name", fields: [{ name: "borrower_name", kind: "text" }] },
  { id: "business", section: "about", question: "business_name", fields: [{ name: "business_name", kind: "text" }] },
  { id: "industry", section: "about", question: "industry", fields: [{ name: "industry", kind: "choice", options: "industry" }] },
  { id: "location", section: "about", question: "location", fields: [{ name: "city", kind: "text" }, { name: "state", kind: "state" }] },
  { id: "vintage", section: "about", question: "business_vintage_years", fields: [{ name: "business_vintage_years", kind: "number" }] },
  { id: "amount", section: "loan", question: "requested_amount", fields: [{ name: "requested_amount", kind: "money" }] },
  { id: "purpose", section: "loan", question: "loan_purpose", fields: [{ name: "loan_purpose", kind: "choice", options: "loan_purpose" }] },
  { id: "revenue", section: "money", question: "monthly_revenue", fields: [{ name: "monthly_revenue", kind: "money" }] },
  { id: "expenses", section: "money", question: "monthly_expenses", fields: [{ name: "monthly_expenses", kind: "money", unsure: true }] },
  { id: "income", section: "money", question: "personal_monthly_income", fields: [{ name: "personal_monthly_income", kind: "money", unsure: true }] },
  {
    id: "loans", section: "debts", question: "existing_loans",
    fields: [
      { name: "existing_loan_count", kind: "number" },
      { name: "outstanding_loan_amount", kind: "money", showIf: hasLoans },
    ],
  },
  { id: "emi", section: "debts", question: "monthly_emi", showIf: hasLoans, fields: [{ name: "monthly_emi", kind: "money" }] },
  {
    id: "collateral", section: "papers", question: "collateral",
    fields: [
      { name: "collateral", kind: "choice", options: "collateral" },
      { name: "collateral_value", kind: "money", unsure: true, showIf: hasCollateral },
    ],
  },
  { id: "gst", section: "papers", question: "gst_status", fields: [{ name: "gst_status", kind: "choice", options: "gst_status" }] },
  { id: "registration", section: "papers", question: "business_registration", fields: [{ name: "business_registration", kind: "choice", options: "business_registration" }] },
  { id: "rejected", section: "history", question: "previously_rejected", fields: [{ name: "previously_rejected", kind: "choice", options: "previously_rejected" }] },
  {
    id: "reason", section: "history", question: "rejection_reason", showIf: wasRejected,
    fields: [
      { name: "rejection_reason", kind: "choice", options: "rejection_reason" },
      { name: "rejection_note", kind: "textarea", optional: true },
    ],
  },
];

export const visibleSteps = (f: FormState) => STEPS.filter((s) => s.showIf?.(f) ?? true);
export const visibleFields = (s: Step, f: FormState) => s.fields.filter((x) => x.showIf?.(f) ?? true);

const TEXT_LIMITS: Partial<Record<FieldName, [number, number]>> = {
  borrower_name: [2, 100], business_name: [2, 150], city: [2, 80], rejection_note: [0, 500],
};
const MAX_AMOUNT = 1_000_000_000;

/** Mirrors backend validation so users see errors before the request. Returns a message or null. */
export function validateField(field: Field, f: FormState, t: Messages): string | null {
  const v = f[field.name].trim();
  const e = t.errors;
  if (!v) return field.optional ? null : e.required;
  if (field.unsure && v === UNSURE) return null;

  if (field.kind === "text" || field.kind === "textarea") {
    const [min, max] = TEXT_LIMITS[field.name] ?? [1, 200];
    if (v.length < min) return fmt(e.tooShort, { min });
    if (v.length > max) return fmt(e.tooLong, { max });
    return null;
  }
  if (field.kind === "number" || field.kind === "money") {
    const n = Number(v);
    if (!Number.isFinite(n)) return e.notNumber;
    const whole = field.name !== "business_vintage_years";
    if (whole && !Number.isInteger(n)) return e.notWhole;
    if (n < 0) return fmt(e.min, { min: 0 });
    if (field.name === "requested_amount" && n === 0) return e.positive;
    if (field.name === "outstanding_loan_amount" && n === 0) return e.loansNeedAmount;
    const max = field.name === "business_vintage_years" ? 100 : field.name === "existing_loan_count" ? 50 : MAX_AMOUNT;
    if (n > max) return fmt(e.max, { max: max.toLocaleString("en-IN") });
  }
  return null;
}

export function validateStep(step: Step, f: FormState, t: Messages): Partial<Record<FieldName, string>> {
  const errors: Partial<Record<FieldName, string>> = {};
  for (const field of visibleFields(step, f)) {
    const err = validateField(field, f, t);
    if (err) errors[field.name] = err;
  }
  return errors;
}

/** Applies conditional-step rules so hidden answers never reach the API. "Not sure" is sent as null, never as 0. */
export function toPayload(f: FormState): BorrowerProfile {
  const loans = hasLoans(f);
  const rejected = wasRejected(f);
  const amount = (v: string) => (v === UNSURE || v === "" ? null : Number(v));
  // Choice values are option codes from the same enums the backend validates.
  return {
    borrower_name: f.borrower_name.trim(),
    business_name: f.business_name.trim(),
    industry: f.industry,
    city: f.city.trim(),
    state: f.state,
    business_vintage_years: Number(f.business_vintage_years),
    requested_amount: Number(f.requested_amount),
    loan_purpose: f.loan_purpose,
    monthly_revenue: Number(f.monthly_revenue),
    monthly_expenses: amount(f.monthly_expenses),
    existing_loan_count: Number(f.existing_loan_count),
    outstanding_loan_amount: loans ? Number(f.outstanding_loan_amount) : 0,
    monthly_emi: loans ? Number(f.monthly_emi) : 0,
    personal_monthly_income: amount(f.personal_monthly_income),
    collateral: f.collateral,
    collateral_value: hasCollateral(f) ? amount(f.collateral_value) : null,
    gst_status: f.gst_status,
    business_registration: f.business_registration,
    previously_rejected: rejected,
    rejection_reason: rejected ? f.rejection_reason : null,
    rejection_note: rejected && f.rejection_note.trim() ? f.rejection_note.trim() : null,
  } as BorrowerProfile;
}

export function fromProfile(p: BorrowerProfile): FormState {
  const out = { ...emptyForm };
  for (const k of Object.keys(emptyForm) as FieldName[]) {
    const v = p[k];
    out[k] = typeof v === "boolean" ? (v ? "yes" : "no") : v == null ? "" : String(v);
  }
  // A saved "not sure" comes back as null: show it as that choice, not as an unanswered question.
  if (p.monthly_expenses == null) out.monthly_expenses = UNSURE;
  if (p.personal_monthly_income == null) out.personal_monthly_income = UNSURE;
  if (p.collateral !== "none" && p.collateral_value == null) out.collateral_value = UNSURE;
  return out;
}

/** Human-readable answer for review and summary screens. */
export function displayValue(name: FieldName, raw: string, t: Messages, groups: Partial<Record<FieldName, OptionGroup>>): string {
  if (!raw) return t.common.notAnswered;
  const group = groups[name];
  if (group) return (t.options[group] as Record<string, string>)[raw] ?? raw;
  return raw;
}

export const OPTION_GROUP_BY_FIELD: Partial<Record<FieldName, OptionGroup>> = Object.fromEntries(
  STEPS.flatMap((s) => s.fields).filter((f) => f.options).map((f) => [f.name, f.options!]),
);
