// One service per backend area. Pages call these; nothing else in the app builds a URL.
import {
  request, type Application, type Case, type Doc, type Investigation, type LenderProduct, type Priority,
  type Proposal, type Recommendations, type Restructure, type RestructureInput, type S,
} from "./client";

const post = (data?: unknown): RequestInit => ({ method: "POST", body: data === undefined ? undefined : JSON.stringify(data) });
const put = (data: unknown): RequestInit => ({ method: "PUT", body: JSON.stringify(data) });
const c = (caseId: string) => `/api/cases/${encodeURIComponent(caseId)}`;
// shortcut: a role header stands in for sign-in in this prototype (see backend/app/routes.py advisor_role).
const asAdvisor = (init: RequestInit = {}): RequestInit => ({ ...init, headers: { ...init.headers, "X-LoanKart-Role": "advisor" } });

export const caseService = {
  open: (borrowerId: string, intent: "new" | "rejected") => request<Case>("/api/cases", post({ borrower_id: borrowerId, intent })),
  get: (id: string) => request<Case>(c(id)),
  consent: (id: string, key: S["ConsentIn"]["key"], granted: boolean) => request<Case>(`${c(id)}/consents`, post({ key, granted })),
  escalate: (id: string, reason: string) => request<Case>(`${c(id)}/escalate`, post({ reason })),
};

export const documentService = {
  list: (id: string) => request<Doc[]>(`${c(id)}/documents`),
  loadSynthetic: (id: string) => request<Doc[]>(`${c(id)}/documents/synthetic`, post()),
  upload: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Doc>(`${c(id)}/documents`, { method: "POST", body: form });
  },
};

export const investigationService = {
  get: (id: string) => request<Investigation>(`${c(id)}/investigation`),
  run: (id: string) => request<Investigation>(`${c(id)}/investigation/run`, post()),
  answer: (id: string, clarificationId: string, answer: string) =>
    request<Investigation>(`${c(id)}/clarifications/${encodeURIComponent(clarificationId)}`, post({ answer })),
  feedback: (id: string, findingId: string, action: S["FeedbackIn"]["action"], note = "") =>
    request<Investigation>(`${c(id)}/findings/${encodeURIComponent(findingId)}/feedback`, post({ action, note })),
  explain: (id: string) => request<Investigation>(`${c(id)}/investigation/explain`, post()),
};

export const calculationService = {
  emi: (input: S["EmiIn"]) => request<S["EmiOut"]>("/api/calculations/emi", post(input)),
  restructure: (id: string) => request<Restructure>(`${c(id)}/restructure`),
  preview: (id: string, input: RestructureInput) => request<Restructure>(`${c(id)}/restructure/preview`, post(input)),
  save: (id: string, input: RestructureInput) => request<Restructure>(`${c(id)}/restructure`, put(input)),
};

export const lenderCatalogService = {
  list: () => request<LenderProduct[]>("/api/lenders"),
  update: (product: LenderProduct) => request<LenderProduct>(`/api/lenders/${product.id}`, asAdvisor(put(product))),
};

export const recommendationService = {
  get: (id: string, priority?: Priority) => request<Recommendations>(`${c(id)}/recommendations${priority ? `?priority=${priority}` : ""}`),
  explain: (id: string, priority: Priority) => request<Recommendations>(`${c(id)}/recommendations/explain?priority=${priority}`, post()),
  select: (id: string, productId: string, priority: Priority) => request<Proposal>(`${c(id)}/selection`, post({ product_id: productId, priority })),
};

export const applicationService = {
  proposal: (id: string) => request<Proposal>(`${c(id)}/proposal`),
  checkpoint: (id: string, key: string, done: boolean) => request<Proposal>(`${c(id)}/proposal/checkpoints`, post({ key, done })),
  get: (id: string) => request<Application>(`${c(id)}/application`),
  submit: (id: string) => request<Application>(`${c(id)}/application/submit`, post()),
  advance: (id: string) => request<Application>(`${c(id)}/application/advance`, post()),
  draft: (id: string, queryId: string) => request<Application>(`${c(id)}/application/queries/${queryId}/draft`, post()),
  respond: (id: string, queryId: string, text: string) => request<Application>(`${c(id)}/application/queries/${queryId}/respond`, post({ text })),
};

export const advisorService = {
  queue: (status: string) => request<S["AdvisorCaseRow"][]>(`/api/advisor/cases?status=${status}`, asAdvisor()),
  detail: (id: string) => request<S["AdvisorCaseDetail"]>(`/api/advisor/cases/${encodeURIComponent(id)}`, asAdvisor()),
  act: (id: string, action: S["AdvisorActionIn"]) =>
    request<S["AdvisorCaseDetail"]>(`/api/advisor/cases/${encodeURIComponent(id)}/actions`, asAdvisor(post(action))),
  knowledge: () => request<S["KnowledgeEntry"][]>("/api/knowledge", asAdvisor()),
  capture: (input: S["KnowledgeCaptureIn"]) => request<S["KnowledgeEntry"]>("/api/knowledge", asAdvisor(post(input))),
  review: (id: string, decision: "approve" | "reject") =>
    request<S["KnowledgeEntry"]>(`/api/knowledge/${id}/review`, asAdvisor(post({ decision }))),
  transcribe: (audio: Blob, filename: string) => {
    const form = new FormData();
    form.append("file", audio, filename);
    return request<S["TranscriptOut"]>("/api/ai/transcribe", asAdvisor({ method: "POST", body: form }));
  },
};

export const demoService = {
  scenarios: () => request<S["ScenarioOut"][]>("/api/demo/scenarios"),
  load: (scenarioId: string) => request<Case>("/api/demo/load", post({ scenario_id: scenarioId })),
  reset: () => request<S["BorrowerOut"]>("/api/demo/reset", post()),
  regenerate: (caseId: string) => request<Doc[]>(`/api/demo/regenerate-documents/${encodeURIComponent(caseId)}`, post()),
  trigger: (caseId: string, action: S["DemoTriggerIn"]["action"]) => request<Application>("/api/demo/trigger", post({ case_id: caseId, action })),
  state: () => request<S["DemoState"]>("/api/demo/state"),
  logs: () => request<S["EventOut"][]>("/api/demo/logs?limit=80"),
  groundTruth: (caseId: string) => request<S["GroundTruthOut"]>(`/api/demo/ground-truth/${encodeURIComponent(caseId)}`),
};

export const aiProviderService = {
  status: () => request<S["AIStatus"]>("/api/ai/status"),
  check: () => request<S["AIStatus"]>("/api/ai/check", post()),
  setMode: (mode: "mock" | "live") => request<S["AIStatus"]>("/api/ai/mode", put({ mode })),
  translate: (text: string, target: S["TranslateIn"]["target_language"]) =>
    request<S["TranscriptOut"]>("/api/ai/translate", post({ text, target_language: target })),
};
