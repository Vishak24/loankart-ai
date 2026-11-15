import { en, type Messages } from "./en";

// To add Tamil: create ta.ts exporting `ta: Messages`, add it here, and choose the locale from user preference.
const locales: Record<string, Messages> = { en };
const current = "en";

export function useT(): Messages {
  return locales[current];
}

/** Replace {name} placeholders. */
export function fmt(template: string, params: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_, k) => String(params[k] ?? `{${k}}`));
}
