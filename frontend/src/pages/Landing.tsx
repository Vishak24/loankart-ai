import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { errorText } from "../api/client";
import { demoService } from "../api/services";
import { Button, ErrorNotice, Layout, LinkButton, Pill, SyntheticBadge } from "../components/ui";
import { useT } from "../i18n";

export default function Landing() {
  const t = useT();
  const navigate = useNavigate();
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const c = t.landing.choices;

  const openDemo = async () => {
    setOpening(true);
    setError(null);
    try {
      const demo = await demoService.load("tiruppur_textile");
      navigate(`/case/${demo.id}/investigation`);
    } catch (e) {
      setError(errorText(e));
      setOpening(false);
    }
  };

  return (
    <Layout wide>
      <div className="grid gap-10 lg:grid-cols-12 lg:gap-6">
        <div className="lg:col-span-7">
          <h1 className="text-[32px] font-semibold leading-[1.12] tracking-tight sm:text-[44px]">{t.landing.title}</h1>
          <p className="mt-4 max-w-xl text-lg leading-relaxed text-muted">{t.landing.lead}</p>
          <div className="mt-8 flex flex-wrap gap-3">
            <LinkButton to="/borrower/intake?intent=rejected">{t.landing.start}</LinkButton>
            <a href="#how" className="inline-flex min-h-12 items-center rounded-lg border border-line bg-surface px-5 font-semibold hover:border-ink/40">
              {t.landing.how}
            </a>
          </div>
        </div>

        {/* The product's signature: the investigation-to-solution sequence, not a chat box. */}
        <ol id="how" aria-label={t.landing.how} className="lg:col-span-5">
          {t.landing.flow.map((step, i) => (
            <li key={step.title} className="relative flex gap-4 pb-5 last:pb-0">
              {i < t.landing.flow.length - 1 && <span aria-hidden className="absolute left-[15px] top-8 h-full w-px bg-line" />}
              <span className="z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-teal text-sm font-semibold text-white">{i + 1}</span>
              <div className="rounded-xl border border-line bg-surface p-4">
                <p className="font-semibold">{step.title}</p>
                <p className="mt-1 text-muted">{step.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>

      <h2 className="mt-14 text-xl font-semibold">{t.landing.choose}</h2>
      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Link to="/borrower/intake?intent=rejected" className="group rounded-xl border border-l-4 border-line border-l-teal bg-surface p-5 hover:border-teal">
          <Pill tone="teal">{t.landing.featured}</Pill>
          <span className="mt-3 block text-xl font-semibold group-hover:text-teal">{c.rejected.title}</span>
          <span className="mt-1 block text-muted">{c.rejected.body}</span>
        </Link>
        <Link to="/borrower/intake?intent=new" className="group rounded-xl border border-line bg-surface p-5 hover:border-teal">
          <span className="block text-xl font-semibold group-hover:text-teal">{c.new.title}</span>
          <span className="mt-1 block text-muted">{c.new.body}</span>
        </Link>
        <Link to="/advisor" className="group rounded-xl border border-line bg-surface p-5 hover:border-teal">
          <span className="block text-xl font-semibold group-hover:text-teal">{c.advisor.title}</span>
          <span className="mt-1 block text-muted">{c.advisor.body}</span>
        </Link>
      </div>

      <div className="mt-6 flex flex-wrap items-center justify-between gap-4 rounded-xl border border-line bg-surface p-5">
        <div className="max-w-2xl">
          <SyntheticBadge />
          <p className="mt-2 text-lg font-semibold">{t.landing.demo}</p>
          <p className="mt-1 text-muted">{t.landing.demoBody}</p>
        </div>
        <Button variant="quiet" onClick={openDemo} busy={opening}>{t.landing.demoOpen}</Button>
      </div>
      {error && <div className="mt-4"><ErrorNotice message={error} onRetry={openDemo} /></div>}

      <ul className="mt-10 grid gap-3 text-muted sm:grid-cols-2 lg:grid-cols-4">
        {t.landing.trust.map((line) => (
          <li key={line} className="flex gap-2"><span aria-hidden className="text-success">✓</span>{line}</li>
        ))}
      </ul>
    </Layout>
  );
}
