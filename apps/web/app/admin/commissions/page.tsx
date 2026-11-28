"use client";

import Link from "next/link";
import { useCallback, useState } from "react";

import { AdminPage } from "@/components/admin/AdminPage";
import { ActionError, Loaded } from "@/components/Feedback";
import type { Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Field, TextInput } from "@/components/ui/Field";
import { EmptyState } from "@/components/ui/States";
import { day, pkr } from "@/lib/format";
import { useAction, useResource } from "@/lib/hooks";
import { adminApi, type CommissionInvoice } from "@/lib/market";

function lastMonth(): { year: number; month: number } {
  const now = new Date();
  const month = now.getMonth(); // 0 based, so this is last month's 1 based number
  return month === 0
    ? { year: now.getFullYear() - 1, month: 12 }
    : { year: now.getFullYear(), month };
}

function InvoiceRow({
  invoice,
  token,
  reload,
}: {
  invoice: CommissionInvoice;
  token: string;
  reload: () => Promise<void>;
}) {
  const action = useAction();
  const [reference, setReference] = useState("");
  return (
    <li className="border-t border-line py-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge tone={invoice.status === "paid" ? "ok" : "warn"}>{invoice.status}</Badge>
        <Link href={`/invoices/${invoice.id}`} className="font-mono text-accent underline">
          {invoice.number}
        </Link>
        <span className="font-semibold">{invoice.brand_name}</span>
        <span>{pkr(invoice.commission_pkr)}</span>
        <span className="text-ink-soft">{invoice.order_count} orders</span>
        <span className="text-ink-faint">
          {invoice.paid_at ? `paid ${day(invoice.paid_at)}` : `due ${day(invoice.due_at)}`}
        </span>
        {invoice.paid_reference ? (
          <span className="font-mono">{invoice.paid_reference}</span>
        ) : null}
      </div>
      {invoice.status === "issued" ? (
        <form
          className="mt-2 flex max-w-md gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void action.run(async () => {
              await adminApi.markCommissionPaid(token, invoice.id, reference);
              await reload();
            });
          }}
        >
          <TextInput
            id={`reference-${invoice.id}`}
            aria-label={`Bank reference for ${invoice.number}`}
            placeholder="Bank reference of the brand's transfer"
            required
            minLength={3}
            value={reference}
            onChange={(event) => setReference(event.target.value)}
          />
          <Button type="submit" disabled={action.busy}>
            Mark paid
          </Button>
        </form>
      ) : null}
      <ActionError message={action.error} />
    </li>
  );
}

function Commissions({ session }: { session: Session }) {
  const { token, locale } = session;
  const action = useAction();
  const initial = lastMonth();
  const [year, setYear] = useState(String(initial.year));
  const [month, setMonth] = useState(String(initial.month));
  const [issued, setIssued] = useState<number | null>(null);
  const invoices = useResource(useCallback(() => adminApi.commissionInvoices(token), [token]));

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle as="h2">Issue a month</CardTitle>
        </CardHeader>
        <CardBody>
          <p className="mb-3 text-sm text-ink-soft">
            The scheduler issues last month&apos;s invoices on the 1st at 06:00 Pakistan time.
            Issuing again by hand bills nothing twice.
          </p>
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              void action.run(async () => {
                const created = await adminApi.issueCommissionInvoices(
                  token,
                  Number(year),
                  Number(month),
                );
                setIssued(created.length);
                await invoices.reload();
              });
            }}
          >
            <Field label="Year" htmlFor="issue-year">
              <TextInput
                id="issue-year"
                inputMode="numeric"
                required
                value={year}
                onChange={(event) => setYear(event.target.value)}
              />
            </Field>
            <Field label="Month (1 to 12)" htmlFor="issue-month">
              <TextInput
                id="issue-month"
                inputMode="numeric"
                required
                value={month}
                onChange={(event) => setMonth(event.target.value)}
              />
            </Field>
            <Button type="submit" className="mb-4" disabled={action.busy}>
              Issue invoices
            </Button>
          </form>
          {issued !== null ? (
            <p role="status" className="text-sm">
              {issued === 0 ? "Nothing new to invoice for that month." : `${issued} issued.`}
            </p>
          ) : null}
          <ActionError message={action.error} />
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle as="h2">All invoices</CardTitle>
        </CardHeader>
        <CardBody>
          <Loaded resource={invoices} locale={locale}>
            {(rows) =>
              rows.length === 0 ? (
                <EmptyState title="No commission invoices yet" />
              ) : (
                <ul>
                  {rows.map((invoice) => (
                    <InvoiceRow
                      key={invoice.id}
                      invoice={invoice}
                      token={token}
                      reload={invoices.reload}
                    />
                  ))}
                </ul>
              )
            }
          </Loaded>
        </CardBody>
      </Card>
    </div>
  );
}

export default function AdminCommissionsPage() {
  return (
    <AdminPage
      title="Commission invoices"
      subtitle="Brands paid directly by cash on delivery owe commission monthly. Record each payment when it reaches the bank."
    >
      {(session) => <Commissions session={session} />}
    </AdminPage>
  );
}
