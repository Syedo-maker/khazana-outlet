"use client";

import Link from "next/link";
import { useCallback } from "react";

import { Loaded, PageHeader } from "@/components/Feedback";
import { RoleShell, type Session } from "@/components/RoleShell";
import { Badge, Card, CardBody } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/States";
import { dateTime, pkr } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { market } from "@/lib/market";

function PayoutsContent({ session }: { session: Session }) {
  const { token, locale } = session;
  const payouts = useResource(useCallback(() => market.payouts(token), [token]));

  return (
    <>
      <PageHeader title={t(locale, "payouts.title")} subtitle={t(locale, "payouts.subtitle")} />
      <Loaded resource={payouts} locale={locale}>
        {(rows) =>
          rows.length === 0 ? (
            <EmptyState title={t(locale, "payouts.none")} />
          ) : (
            <ul className="space-y-3">
              {rows.map((payout) => (
                <li key={payout.id}>
                  <Card>
                    <CardBody className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <Badge tone={payout.status === "paid" ? "ok" : "warn"}>
                          {t(locale, `payout.status.${payout.status}`)}
                        </Badge>
                        <p className="mt-1 text-sm text-ink-soft">
                          {payout.paid_at
                            ? t(locale, "payouts.paidOn", { date: dateTime(payout.paid_at) })
                            : t(locale, "payouts.dueOn", { date: dateTime(payout.scheduled_for) })}
                        </p>
                        <Link
                          href={`/orders/${payout.order_id}`}
                          className="text-sm font-semibold text-accent underline"
                        >
                          {t(locale, "payouts.viewOrder")}
                        </Link>
                      </div>
                      <p className="text-lg font-semibold">{pkr(payout.amount_pkr)}</p>
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

export default function PayoutsPage() {
  return (
    <RoleShell allow={["brand"]}>{(session) => <PayoutsContent session={session} />}</RoleShell>
  );
}
