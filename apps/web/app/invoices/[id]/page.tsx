"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback } from "react";

import { Loaded } from "@/components/Feedback";
import { RoleShell, type Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Card";
import { day, pkr } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { market, type CommissionInvoiceDetail } from "@/lib/market";

/** The period ends at the start of the next month; show its last day. */
function lastDay(periodEnd: string): Date {
  return new Date(new Date(periodEnd).getTime() - 24 * 60 * 60 * 1000);
}

function Invoice({ invoice, session }: { invoice: CommissionInvoiceDetail; session: Session }) {
  const { locale, me } = session;
  return (
    <article className="mx-auto max-w-3xl rounded border border-line bg-surface p-6 print:border-0 print:p-0">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 print:hidden">
        <Link
          href={me.is_admin ? "/admin/commissions" : "/invoices"}
          className="text-sm font-semibold text-accent underline"
        >
          {t(locale, "invoices.back")}
        </Link>
        <Button variant="secondary" onClick={() => window.print()}>
          {t(locale, "invoices.print")}
        </Button>
      </div>

      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-lg font-bold">{t(locale, "app.name")}</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">
            {t(locale, "invoices.title")}
          </h1>
          <p className="font-mono text-sm">{invoice.number}</p>
        </div>
        <div className="text-sm">
          <Badge tone={invoice.status === "paid" ? "ok" : "warn"}>
            {t(locale, `invoices.status.${invoice.status}`)}
          </Badge>
          <p className="mt-2">
            {invoice.paid_at
              ? t(locale, "invoices.paidOn", { date: day(invoice.paid_at) })
              : t(locale, "invoices.due", { date: day(invoice.due_at) })}
          </p>
          {invoice.paid_reference ? (
            <p className="font-mono text-xs">{invoice.paid_reference}</p>
          ) : null}
        </div>
      </header>

      <section className="mb-6 text-sm">
        <p className="text-ink-soft">{t(locale, "invoices.billedTo")}</p>
        <p className="font-semibold">{invoice.brand_name}</p>
        <p className="mt-2">
          {t(locale, "invoices.period", {
            start: day(invoice.period_start),
            end: day(lastDay(invoice.period_end)),
          })}
        </p>
      </section>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-line text-ink-soft">
              <th scope="col" className="py-2 pe-3 font-semibold">
                {t(locale, "invoices.order")}
              </th>
              <th scope="col" className="py-2 pe-3 font-semibold">
                {t(locale, "invoices.confirmed")}
              </th>
              <th scope="col" className="py-2 pe-3 text-end font-semibold">
                {t(locale, "invoices.goods")}
              </th>
              <th scope="col" className="py-2 pe-3 text-end font-semibold">
                {t(locale, "invoices.refunded")}
              </th>
              <th scope="col" className="py-2 pe-3 text-end font-semibold">
                {t(locale, "invoices.rate")}
              </th>
              <th scope="col" className="py-2 text-end font-semibold">
                {t(locale, "invoices.commission")}
              </th>
            </tr>
          </thead>
          <tbody>
            {invoice.lines.map((line) => (
              <tr key={line.order_id} className="border-b border-line">
                <td className="py-2 pe-3 font-mono">
                  <Link href={`/orders/${line.order_id}`} className="underline print:no-underline">
                    {line.order_code}
                  </Link>
                </td>
                <td className="py-2 pe-3">{day(line.confirmed_at)}</td>
                <td className="py-2 pe-3 text-end">{pkr(line.subtotal_pkr)}</td>
                <td className="py-2 pe-3 text-end">
                  {line.refunded_pkr ? pkr(line.refunded_pkr) : ""}
                </td>
                <td className="py-2 pe-3 text-end">{`${line.commission_percent}%`}</td>
                <td className="py-2 text-end">{pkr(line.commission_pkr)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row" colSpan={5} className="py-3 pe-3 text-end font-semibold">
                {t(locale, "invoices.total")}
              </th>
              <td className="py-3 text-end text-lg font-bold">{pkr(invoice.commission_pkr)}</td>
            </tr>
          </tfoot>
        </table>
      </div>

      <p className="mt-6 text-sm text-ink-soft">{t(locale, "invoices.howToPay")}</p>
    </article>
  );
}

function InvoiceContent({ session, id }: { session: Session; id: string }) {
  const { token, locale } = session;
  const invoice = useResource(useCallback(() => market.commissionInvoice(token, id), [token, id]));
  return (
    <Loaded resource={invoice} locale={locale} rows={6}>
      {(data) => <Invoice invoice={data} session={session} />}
    </Loaded>
  );
}

export default function InvoicePage() {
  const { id } = useParams<{ id: string }>();
  return (
    <RoleShell allow={["brand", "admin"]}>
      {(session) => <InvoiceContent session={session} id={id} />}
    </RoleShell>
  );
}
