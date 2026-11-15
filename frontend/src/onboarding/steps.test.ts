import { describe, expect, it } from "vitest";
import { en } from "../i18n/en";
import { STEPS, UNSURE, emptyForm, fromProfile, toPayload, validateStep, visibleFields, visibleSteps, type FormState } from "./steps";

const filled: FormState = {
  ...emptyForm, borrower_name: " Asha Kumar ", business_name: "Asha Tiffin Centre", industry: "food_hospitality", city: "Madurai",
  state: "Tamil Nadu", business_vintage_years: "3", requested_amount: "500000", loan_purpose: "working_capital",
  monthly_revenue: "250000", monthly_expenses: "180000", existing_loan_count: "1", outstanding_loan_amount: "120000",
  monthly_emi: "9000", personal_monthly_income: "40000", collateral: "gold", collateral_value: "400000",
  gst_status: "not_registered", business_registration: "udyam_proprietorship", previously_rejected: "yes",
  rejection_reason: "unknown", rejection_note: "",
};
const step = (id: string) => STEPS.find((s) => s.id === id)!;

describe("onboarding steps", () => {
  it("asks follow-up questions only when they apply", () => {
    const ids = (f: FormState) => visibleSteps(f).map((s) => s.id);
    expect(ids({ ...filled, existing_loan_count: "0" })).not.toContain("emi");
    expect(ids({ ...filled, previously_rejected: "no" })).not.toContain("reason");
    expect(visibleFields(step("collateral"), { ...filled, collateral: "none" }).map((f) => f.name)).toEqual(["collateral"]);
    expect(visibleFields(step("collateral"), filled).map((f) => f.name)).toEqual(["collateral", "collateral_value"]);
  });

  it("builds the API payload and trims text", () => {
    const p = toPayload(filled);
    expect(p).toMatchObject({ borrower_name: "Asha Kumar", requested_amount: 500000, monthly_emi: 9000, previously_rejected: true,
      rejection_reason: "unknown", rejection_note: null, collateral_value: 400000 });
  });

  it("never sends answers to questions that no longer apply", () => {
    const p = toPayload({ ...filled, existing_loan_count: "0", previously_rejected: "no", collateral: "none" });
    expect(p).toMatchObject({ outstanding_loan_amount: 0, monthly_emi: 0, rejection_reason: null, collateral_value: null });
  });

  it("sends \"I'm not sure\" as unknown, not as zero, and reads it back", () => {
    const form = { ...filled, monthly_expenses: UNSURE, personal_monthly_income: UNSURE, collateral_value: UNSURE };
    const p = toPayload(form);
    expect([p.monthly_expenses, p.personal_monthly_income, p.collateral_value]).toEqual([null, null, null]);
    expect(validateStep(step("expenses"), form, en)).toEqual({});
    const back = fromProfile(p);
    expect([back.monthly_expenses, back.personal_monthly_income, back.collateral_value]).toEqual([UNSURE, UNSURE, UNSURE]);
  });

  it("survives a round trip through the API shape", () => {
    expect(toPayload(fromProfile(toPayload(filled)))).toEqual(toPayload(filled));
  });

  it("validates before the request is sent", () => {
    expect(validateStep(step("amount"), { ...filled, requested_amount: "0" }, en).requested_amount).toBe(en.errors.positive);
    expect(validateStep(step("name"), { ...filled, borrower_name: "A" }, en).borrower_name).toContain("at least 2");
    expect(validateStep(step("revenue"), { ...filled, monthly_revenue: "" }, en).monthly_revenue).toBe(en.errors.required);
    expect(validateStep(step("loans"), { ...filled, outstanding_loan_amount: "0" }, en).outstanding_loan_amount).toBe(en.errors.loansNeedAmount);
    expect(validateStep(step("revenue"), { ...filled, monthly_revenue: UNSURE }, en).monthly_revenue).toBeDefined();   // not offered there
  });
});
