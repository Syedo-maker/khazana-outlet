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

function InvoicesContent({ session, brandId }: { session: Session; brandId: string }) {
  const { token, locale } = session;
  const invoices = useResource(
    useCallback(() => market.commissionInvoices(token, brandId), [token, brandId]),
  );
  const summary = useResource(
    useCallback(() => market.commissionSummary(token, brandId), [token, brandId]),
  );

  return (
    <>
      <PageHeader title={t(locale, "invoices.title")} subtitle={t(locale, "invoices.subtitle")} />
      {summary.data && summary.data.unbilled_commission_pkr > 0 ? (
        <p className="mb-4 text-sm">
          {t(locale, "invoices.unbilled", {
            amount: pkr(summary.data.unbilled_commission_pkr),
          })}
        </p>
      ) : null}
      <Loaded resource={invoices} locale={locale}>
        {(rows) =>
          rows.length === 0 ? (
            <EmptyState title={t(locale, "invoices.none")} />
          ) : (
            <ul className="space-y-3">
              {rows.map((invoice) => (
                <li key={invoice.id}>
                  <Card>
                    <CardBody className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge tone={invoice.status === "paid" ? "ok" : "warn"}>
                            {t(locale, `invoices.status.${invoice.status}`)}
                          </Badge>
                          <span className="font-mono text-sm">{invoice.number}</span>
                        </div>
                        <p className="mt-1 text-sm text-ink-soft">
                          {t(locale, "invoices.orders", { count: invoice.order_count })}
                          {" · "}
                          {invoice.paid_at
                            ? t(locale, "invoices.paidOn", { date: dateTime(invoice.paid_at) })
                            : t(locale, "invoices.due", { date: dateTime(invoice.due_at) })}
                        </p>
                        <Link
                          href={`/invoices/${invoice.id}`}
                          className="text-sm font-semibold text-accent underline"
                        >
                          {t(locale, "invoices.view")}
                        </Link>
                      </div>
                      <p className="text-lg font-semibold">{pkr(invoice.commission_pkr)}</p>
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

export default function InvoicesPage() {
  return (
    <RoleShell allow={["brand"]}>
      {(session) =>
        session.me.brand_ids[0] ? (
          <InvoicesContent session={session} brandId={session.me.brand_ids[0]} />
        ) : (
          <EmptyState title={t(session.locale, "invoices.none")} />
        )
      }
    </RoleShell>
  );
}
