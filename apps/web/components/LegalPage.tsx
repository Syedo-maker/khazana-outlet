"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { AppShell } from "@/components/AppShell";
import { Badge } from "@/components/ui/Card";
import { useLocale } from "@/lib/hooks";
import { t } from "@/lib/i18n";

export type LegalSection = { heading: string; body: ReactNode };

/**
 * The beta privacy notice and terms. The full text is English; a short
 * summary at the top is in the reader's language. Both pages say plainly that
 * this is a beta, because that changes what a reader should expect.
 */
export function LegalPage({
  title,
  version,
  summaryKey,
  sections,
}: {
  title: string;
  version: string;
  summaryKey: string;
  sections: LegalSection[];
}) {
  const locale = useLocale();
  return (
    <AppShell locale={locale}>
      <article className="mx-auto max-w-2xl">
        <header className="mb-6">
          <Badge tone="warn">{t(locale, "beta.label")}</Badge>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-1 text-sm text-ink-faint">Version {version}</p>
          <p className="mt-4 rounded border border-line bg-surface p-3 text-sm">
            {t(locale, summaryKey)}
          </p>
        </header>
        <div lang="en" dir="ltr" className="space-y-6 text-sm leading-relaxed">
          {sections.map((section, index) => (
            <section key={section.heading} aria-labelledby={`legal-${index}`}>
              <h2 id={`legal-${index}`} className="mb-2 text-base font-semibold">
                {section.heading}
              </h2>
              {section.body}
            </section>
          ))}
        </div>
        <footer className="mt-8 flex gap-4 text-sm">
          <Link href="/terms" className="font-semibold text-accent underline">
            {t(locale, "legal.terms")}
          </Link>
          <Link href="/privacy" className="font-semibold text-accent underline">
            {t(locale, "legal.privacy")}
          </Link>
        </footer>
      </article>
    </AppShell>
  );
}
