// Cloudflare Pages Function: same-origin reverse proxy for /api/* -> the FastAPI backend (Render).
// Why: the session cookie is SameSite=Lax; pages.dev and onrender.com are different sites, so the browser would drop it.
// Through this proxy the browser only ever talks to the Pages origin, and Set-Cookie is host-only on that origin.
// Config: LOANKART_BACKEND_URL (Pages environment variable), e.g. https://loankart-api.onrender.com. Nothing else is forwarded to.
// Files in this directory become routes: keep tests and helpers outside functions/.

type Env = { LOANKART_BACKEND_URL?: string };

const TIMEOUT_MS = 60_000;            // Render Free cold starts take up to ~50 s
const DROP_REQUEST = ["host", "connection", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip", "forwarded"];

const fail = (status: number, detail: string) => Response.json({ detail }, { status, headers: { "Cache-Control": "no-store" } });

/** The configured backend origin, or null if unset / not https (plain http only for loopback development). */
function backendOrigin(raw: string | undefined): string | null {
  try {
    const u = new URL(raw ?? "");
    const loopback = u.hostname === "localhost" || u.hostname === "127.0.0.1";
    return u.protocol === "https:" || (u.protocol === "http:" && loopback) ? u.origin : null;
  } catch {
    return null;
  }
}

export async function onRequest({ request, env }: { request: Request; env: Env }): Promise<Response> {
  const origin = backendOrigin(env.LOANKART_BACKEND_URL);
  if (!origin) return fail(503, "The LoanKart.ai server is not configured.");

  const url = new URL(request.url);
  if (!url.pathname.startsWith("/api/")) return fail(404, "Not found");   // the destination is always origin + the caller's /api path

  const headers = new Headers(request.headers);
  for (const h of DROP_REQUEST) headers.delete(h);
  for (const h of [...headers.keys()]) if (h.startsWith("cf-")) headers.delete(h);

  let upstream: Response;
  try {
    upstream = await fetch(origin + url.pathname + url.search, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
      redirect: "manual",                                   // never follow, never let the browser be sent to Render
      signal: AbortSignal.timeout(TIMEOUT_MS),
      // @ts-expect-error duplex is required by Node's fetch for streamed bodies; the Workers runtime ignores it
      duplex: "half",
    });
  } catch (e) {
    return e instanceof DOMException && e.name === "TimeoutError"
      ? fail(504, "The LoanKart.ai server took too long to respond. It may be waking up; try again in a minute.")
      : fail(502, "The LoanKart.ai server is unavailable. Please try again shortly.");
  }

  const res = new Response(upstream.body, upstream);        // keeps status, body stream and every Set-Cookie header
  const location = res.headers.get("location");
  if (location?.startsWith(origin)) res.headers.set("location", location.slice(origin.length) || "/");
  return res;
}
