import { afterEach, describe, expect, it, vi } from "vitest";
import { onRequest } from "../functions/api/[[path]]";

const BACKEND = "https://loankart-api.onrender.com";
const env = { LOANKART_BACKEND_URL: BACKEND };
const SITE = "https://loankart-ai.pages.dev";

const upstream = vi.fn<(url: string, init: RequestInit) => Promise<Response>>();
vi.stubGlobal("fetch", upstream);
afterEach(() => upstream.mockReset());

const call = (path: string, init?: RequestInit, e: { LOANKART_BACKEND_URL?: string } = env) =>
  onRequest({ request: new Request(SITE + path, init), env: e });

describe("Pages Function /api proxy", () => {
  it("forwards GET with query string to the fixed backend", async () => {
    upstream.mockResolvedValue(Response.json({ ok: 1 }));
    const res = await call("/api/borrowers/b1?x=1&y=a%20b");
    expect(upstream.mock.calls[0][0]).toBe(`${BACKEND}/api/borrowers/b1?x=1&y=a%20b`);
    expect(await res.json()).toEqual({ ok: 1 });
  });

  it("forwards POST method and body, plus Origin, Cookie and CSRF-relevant headers", async () => {
    upstream.mockResolvedValue(Response.json({}, { status: 201 }));
    const res = await call("/api/borrowers", {
      method: "POST", body: JSON.stringify({ a: 1 }),
      headers: { "Content-Type": "application/json", Origin: SITE, Cookie: "lk_adv=tok; lk_bor=tok2", "X-CSRF-Token": "t" },
    });
    const [, init] = upstream.mock.calls[0];
    const h = new Headers(init.headers);
    expect(res.status).toBe(201);
    expect(init.method).toBe("POST");
    expect(h.get("origin")).toBe(SITE);
    expect(h.get("cookie")).toBe("lk_adv=tok; lk_bor=tok2");
    expect(h.get("x-csrf-token")).toBe("t");
    expect(h.get("content-type")).toBe("application/json");
    expect(await new Response(init.body as ReadableStream).text()).toBe('{"a":1}');
  });

  it("drops client-supplied forwarding headers and cf-* headers", async () => {
    upstream.mockResolvedValue(Response.json({}));
    await call("/api/x", { headers: { "X-Forwarded-For": "6.6.6.6", "CF-Connecting-IP": "1.2.3.4", Host: "evil.example" } });
    const h = new Headers(upstream.mock.calls[0][1].headers);
    expect([...h.keys()].filter((k) => k === "x-forwarded-for" || k === "host" || k.startsWith("cf-"))).toEqual([]);
  });

  it("returns every Set-Cookie header separately and keeps the status", async () => {
    const headers = new Headers();
    headers.append("Set-Cookie", "lk_adv=a; HttpOnly; Secure; SameSite=lax; Path=/");
    headers.append("Set-Cookie", "lk_bor=b; HttpOnly; Secure; SameSite=lax; Path=/");
    upstream.mockResolvedValue(new Response("{}", { status: 200, headers }));
    const res = await call("/api/auth/advisor/login", { method: "POST", body: "{}" });
    expect(res.headers.getSetCookie()).toEqual([
      "lk_adv=a; HttpOnly; Secure; SameSite=lax; Path=/",
      "lk_bor=b; HttpOnly; Secure; SameSite=lax; Path=/",
    ]);
  });

  it("passes error statuses through untouched (403 CSRF refusal, 401)", async () => {
    upstream.mockResolvedValue(Response.json({ detail: "Cross-site request refused." }, { status: 403 }));
    const res = await call("/api/borrowers", { method: "POST", body: "{}", headers: { Origin: "https://evil.example" } });
    expect(res.status).toBe(403);
    expect((await res.json()).detail).toMatch(/Cross-site/);
  });

  it("preserves binary PDF bytes and headers", async () => {
    const bytes = new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x00, 0xff, 0xfe, 0x80]);
    upstream.mockResolvedValue(new Response(bytes, { headers: { "Content-Type": "application/pdf", "Content-Disposition": "inline; filename=a.pdf" } }));
    const res = await call("/api/documents/d1/file");
    expect(res.headers.get("content-type")).toBe("application/pdf");
    expect(res.headers.get("content-disposition")).toBe("inline; filename=a.pdf");
    expect(new Uint8Array(await res.arrayBuffer())).toEqual(bytes);
  });

  it("does not follow redirects and rewrites a Location pointing at the backend to a relative path", async () => {
    upstream.mockResolvedValue(new Response(null, { status: 307, headers: { Location: `${BACKEND}/api/cases/c1?a=1` } }));
    const res = await call("/api/cases/c1/");
    expect(upstream.mock.calls[0][1].redirect).toBe("manual");
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe("/api/cases/c1?a=1");
  });

  it("returns a safe 502 when the backend is unreachable, without leaking the backend URL", async () => {
    upstream.mockRejectedValue(new TypeError(`fetch failed: connect ECONNREFUSED ${BACKEND}`));
    const res = await call("/api/health-check");
    const text = await res.text();
    expect(res.status).toBe(502);
    expect(text).not.toContain("onrender");
    expect(JSON.parse(text).detail).toBeTruthy();
  });

  it("returns 504 on timeout", async () => {
    upstream.mockRejectedValue(new DOMException("timed out", "TimeoutError"));
    expect((await call("/api/x")).status).toBe(504);
  });

  it("only proxies /api/*: other paths never reach the backend", async () => {
    for (const p of ["/health", "/case/x/investigation", "/apix/foo", "/"]) expect((await call(p)).status).toBe(404);
    expect(upstream).not.toHaveBeenCalled();
  });

  it("cannot be steered to another destination through the path", async () => {
    upstream.mockResolvedValue(Response.json({}));
    for (const p of ["/api//evil.example/x", "/api/@evil.example/x", "/api/..%2f..%2fx"]) await call(p);
    for (const [u] of upstream.mock.calls) expect(new URL(u).origin).toBe(BACKEND);
  });

  it("refuses to run unconfigured, or with a non-https / malformed backend URL", async () => {
    for (const bad of [undefined, "", "not a url", "http://loankart-api.onrender.com", "ftp://x.example"]) {
      expect((await call("/api/x", undefined, { LOANKART_BACKEND_URL: bad })).status).toBe(503);
    }
    expect(upstream).not.toHaveBeenCalled();
  });

  it("allows plain http only for loopback development", async () => {
    upstream.mockResolvedValue(Response.json({}));
    expect((await call("/api/x", undefined, { LOANKART_BACKEND_URL: "http://127.0.0.1:8000" })).status).toBe(200);
  });
});
