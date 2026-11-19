"use client";

import Link from "next/link";
import { useCallback } from "react";

import { Loaded, PageHeader } from "@/components/Feedback";
import { RoleShell, type Session } from "@/components/RoleShell";
import { Badge, Card, CardBody } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/States";
import { catalog } from "@/lib/api";
import { pkr } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import { t } from "@/lib/i18n";

const BAND_TONES = { low: "ok", medium: "warn", high: "danger", unknown: "neutral" } as const;

function QueueContent({ session }: { session: Session }) {
  const { token, locale } = session;
  const queue = useResource(useCallback(() => catalog.queue(token), [token]));

  return (
    <>
      <PageHeader title={t(locale, "queue.title")} subtitle={t(locale, "queue.subtitle")} />
      <Loaded resource={queue} locale={locale}>
        {(items) =>
          items.length === 0 ? (
            <EmptyState title={t(locale, "queue.none")} />
          ) : (
            <ul className="space-y-3">
              {items.map((item) => (
                <li key={item.lot.id}>
                  <Card>
                    <CardBody>
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone={BAND_TONES[item.risk_band]}>
                          {t(locale, "queue.risk", { score: item.risk_score })}
                        </Badge>
                        <Badge>{t(locale, `visibility.${item.lot.visibility}`)}</Badge>
                        <span className="font-mono text-xs text-ink-faint">
                          {item.lot.lot_code}
                        </span>
                      </div>
                      <h2 className="mt-1 font-semibold">
                        <Link href={`/lots/${item.lot.id}`} className="underline decoration-line">
                          {item.lot.title}
                        </Link>
                      </h2>
                      <p className="text-sm text-ink-soft">{pkr(item.lot.lot_price_pkr)}</p>
                      {item.findings.length > 0 ? (
                        <ul className="mt-2 list-disc pl-5 text-sm text-ink-soft">
                          {item.findings.map((finding) => (
                            <li key={finding}>{finding}</li>
                          ))}
                        </ul>
                      ) : null}
                    </CardBody>
                  </Card>
                </li>
              ))}
            </ul>
          )
        }
      </Loaded>
    </>
  );
}

export default function QueuePage() {
  return (
    <RoleShell allow={["brand", "admin"]}>
      {(session) => <QueueContent session={session} />}
    </RoleShell>
  );
}
