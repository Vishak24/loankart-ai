const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const plain = new Intl.NumberFormat("en-IN");

export const formatINR = (n: number) => inr.format(n);
export const formatNumber = (n: number) => plain.format(n);
/** Amount, or "Not available" when the value is missing. Missing stays missing: never show 0 for unknown. */
export const money = (n: number | null | undefined) => (n == null ? "Not available" : inr.format(n));
export const signedMoney = (n: number) => (n > 0 ? "+" : n < 0 ? "−" : "") + inr.format(Math.abs(n));

/** Short Indian-unit reading of an amount, e.g. 1500000 -> "15 lakh". */
export function inIndianUnits(n: number): string {
  const trim = (x: number) => String(Math.round(x * 100) / 100);
  if (n >= 1e7) return `${trim(n / 1e7)} crore`;
  if (n >= 1e5) return `${trim(n / 1e5)} lakh`;
  if (n >= 1e3) return `${trim(n / 1e3)} thousand`;
  return String(n);
}

export function formatMonth(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-IN", { month: "short", year: "numeric" });
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

/** "avg_business_receipts" -> "Avg business receipts" */
export const humanise = (key: string) => key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
