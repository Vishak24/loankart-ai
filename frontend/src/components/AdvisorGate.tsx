import { useState, type FormEvent, type ReactNode } from "react";
import { authService } from "../api/services";
import { Button, Card, ErrorNotice, Layout, Loading, PageTitle, useAction, useLoad } from "./ui";

/** Wraps the advisor and demo-control pages: nothing inside renders (or fetches) until the server confirms an advisor session. */
export function AdvisorGate({ children }: { children: ReactNode }) {
  const me = useLoad(() => authService.me(), []);
  const [password, setPassword] = useState("");
  const action = useAction();

  if (me.error) return <Layout><ErrorNotice message={me.error} onRetry={me.reload} /></Layout>;
  if (!me.data) return <Layout><Loading label="Checking sign-in" /></Layout>;

  if (!me.data.advisor) {
    const submit = (e: FormEvent) => {
      e.preventDefault();
      void action.run("login", async () => { me.setData(await authService.login(password)); setPassword(""); });
    };
    return (
      <Layout>
        <PageTitle title="Advisor sign-in" lead="This area is for LoanKart advisors and the demo presenter." />
        <Card>
          <form onSubmit={submit} className="space-y-4">
            <label className="block">
              <span className="font-medium">Passcode</span>
              <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)}
                className="mt-1 block min-h-11 w-full rounded-lg border border-line bg-surface px-3 py-2" />
            </label>
            {action.error && <p role="alert" className="text-danger">{action.error}</p>}
            <Button type="submit" busy={action.busy === "login"}>Sign in</Button>
            {me.data.environment === "development" && (
              <p className="text-sm text-muted">
                Local demo: choose your passcode once by running <code>python scripts/set_advisor_password.py</code> in the{" "}
                <code>backend</code> folder, then restart the backend.
              </p>
            )}
          </form>
        </Card>
      </Layout>
    );
  }

  return (
    <>
      <div className="border-b border-line bg-surface px-4 py-1 text-right text-sm text-muted">
        Signed in as advisor ·{" "}
        <button type="button" className="font-medium text-teal underline underline-offset-4"
          onClick={() => void authService.logout().then((s) => me.setData(s))}>Sign out</button>
      </div>
      {children}
    </>
  );
}
