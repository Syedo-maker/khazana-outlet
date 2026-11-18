"use client";

import Link from "next/link";
import { useCallback } from "react";

import { AdminPage } from "@/components/admin/AdminPage";
import { ActionError, Loaded } from "@/components/Feedback";
import type { Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/States";
import { dateTime, pkr } from "@/lib/format";
import { useAction, useResource } from "@/lib/hooks";
import { adminApi } from "@/lib/market";

function Payments({ session }: { session: Session }) {
  const { token, locale } = session;
  const action = useAction();
  const transfers = useResource(
    useCallback(() => adminApi.payments(token, "pending", "bank_transfer"), [token]),
  );
  const payments = useResource(useCallback(() => adminApi.payments(token), [token]));
  const issues = useResource(useCallback(() => adminApi.reconciliation(token), [token]));

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle as="h2">Bank transfers to confirm</CardTitle>
        </CardHeader>
        <CardBody>
          <Loaded resource={transfers} locale={locale} rows={2}>
            {(rows) => {
              const ready = rows.filter((row) => row.provider_reference);
              return ready.length === 0 ? (
                <EmptyState title="Nothing to confirm" />
              ) : (
                <ul className="space-y-2">
                  {ready.map((payment) => (
                    <li key={payment.id} className="flex flex-wrap items-center gap-3 text-sm">
                      <span className="font-semibold">{pkr(payment.amount_pkr)}</span>
                      <span className="font-mono">{payment.provider_reference}</span>
                      <Link href={`/orders/${payment.order_id}`} className="text-accent underline">
                        Order
                      </Link>
                      <Button
                        size="sm"
                        disabled={action.busy}
                        onClick={() =>
                          void action.run(async () => {
                            await adminApi.confirmTransfer(token, payment.id);
                            await Promise.all([transfers.reload(), payments.reload()]);
                          })
                        }
                      >
                        Money received
                      </Button>
                    </li>
                  ))}
                </ul>
              );
            }}
          </Loaded>
          <ActionError message={action.error} />
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle as="h2">Reconciliation</CardTitle>
        </CardHeader>
        <CardBody>
          <Loaded resource={issues} locale={locale} rows={2}>
            {(rows) =>
              rows.length === 0 ? (
                <p className="text-sm text-ok">Payments and orders agree.</p>
              ) : (
                <ul className="space-y-2 text-sm">
                  {rows.map((item) => (
                    <li key={`${item.kind}-${item.order_code}`}>
                      <Badge tone="danger">{item.kind.replaceAll("_", " ")}</Badge>{" "}
                      <span className="font-mono">{item.order_code}</span> {pkr(item.amount_pkr)}:{" "}
                      {item.detail}
                    </li>
                  ))}
                </ul>
              )
            }
          </Loaded>
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle as="h2">Recent payments</CardTitle>
        </CardHeader>
        <CardBody>
          <Loaded resource={payments} locale={locale}>
            {(rows) => (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="text-ink-faint">
                    <tr>
                      <th className="py-1">Amount</th>
                      <th>Method</th>
                      <th>Status</th>
                      <th>Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((payment) => (
                      <tr key={payment.id} className="border-t border-line">
                        <td className="py-1">
                          <Link href={`/orders/${payment.order_id}`} className="underline">
                            {pkr(payment.amount_pkr)}
                          </Link>
                        </td>
                        <td>{payment.method.replace("_", " ")}</td>
                        <td>{payment.status}</td>
                        <td>{dateTime(payment.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Loaded>
        </CardBody>
      </Card>
    </div>
  );
}

export default function AdminPaymentsPage() {
  return (
    <AdminPage title="Payments" subtitle="Held funds, confirmations and anything that disagrees.">
      {(session) => <Payments session={session} />}
    </AdminPage>
  );
}
