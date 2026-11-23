"use client";

import Link from "next/link";
import { useCallback, useState } from "react";

import { AdminPage } from "@/components/admin/AdminPage";
import { ActionError, Loaded } from "@/components/Feedback";
import type { Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { TextInput } from "@/components/ui/Field";
import { EmptyState } from "@/components/ui/States";
import { dateTime, pkr } from "@/lib/format";
import { useAction, useResource } from "@/lib/hooks";
import { adminApi, type PayoutRun } from "@/lib/market";

function RunRow({
  run,
  token,
  reload,
}: {
  run: PayoutRun;
  token: string;
  reload: () => Promise<void>;
}) {
  const action = useAction();
  const [reference, setReference] = useState("");
  return (
    <li className="border-t border-line py-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge tone={run.status === "paid" ? "ok" : "warn"}>{run.status}</Badge>
        <span className="font-semibold">{pkr(run.total_pkr)}</span>
        <span>{run.payout_count} payouts</span>
        <span className="text-ink-faint">{dateTime(run.created_at)}</span>
        {run.reference ? <span className="font-mono">{run.reference}</span> : null}
      </div>
      {run.status === "scheduled" ? (
        <form
          className="mt-2 flex max-w-md gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void action.run(async () => {
              await adminApi.markRunPaid(token, run.id, reference);
              await reload();
            });
          }}
        >
          <TextInput
            id={`reference-${run.id}`}
            aria-label="Bank batch reference"
            placeholder="Bank batch reference"
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

function Payouts({ session }: { session: Session }) {
  const { token, locale } = session;
  const action = useAction();
  const payouts = useResource(useCallback(() => adminApi.payouts(token), [token]));
  const runs = useResource(useCallback(() => adminApi.payoutRuns(token), [token]));
  const reload = async () => {
    await Promise.all([payouts.reload(), runs.reload()]);
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle as="h2">Payout runs</CardTitle>
        </CardHeader>
        <CardBody>
          <Button
            disabled={action.busy}
            onClick={() =>
              void action.run(async () => {
                await adminApi.createPayoutRun(token);
                await reload();
              })
            }
          >
            Gather due payouts
          </Button>
          <ActionError message={action.error} />
          <Loaded resource={runs} locale={locale} rows={2}>
            {(rows) => (
              <ul className="mt-3">
                {rows.map((run) => (
                  <RunRow key={run.id} run={run} token={token} reload={reload} />
                ))}
              </ul>
            )}
          </Loaded>
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle as="h2">All payouts</CardTitle>
        </CardHeader>
        <CardBody>
          <Loaded resource={payouts} locale={locale}>
            {(rows) =>
              rows.length === 0 ? (
                <EmptyState title="No payouts yet" />
              ) : (
                <ul className="space-y-2 text-sm">
                  {rows.map((payout) => (
                    <li key={payout.id} className="flex flex-wrap items-center gap-3">
                      <Badge>{payout.status}</Badge>
                      <span className="font-semibold">{pkr(payout.amount_pkr)}</span>
                      <span className="text-ink-soft">due {dateTime(payout.scheduled_for)}</span>
                      <Link href={`/orders/${payout.order_id}`} className="text-accent underline">
                        Order
                      </Link>
                    </li>
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

export default function AdminPayoutsPage() {
  return (
    <AdminPage title="Payouts" subtitle="Money reaches a brand only after a run is marked paid.">
      {(session) => <Payouts session={session} />}
    </AdminPage>
  );
}
