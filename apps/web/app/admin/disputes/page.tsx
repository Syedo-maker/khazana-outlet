"use client";

import Link from "next/link";
import { useCallback, useState } from "react";

import { AdminPage } from "@/components/admin/AdminPage";
import { ActionError, Loaded } from "@/components/Feedback";
import type { Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardBody } from "@/components/ui/Card";
import { Field, TextArea, TextInput } from "@/components/ui/Field";
import { EmptyState } from "@/components/ui/States";
import { pkr } from "@/lib/format";
import { useAction, useResource } from "@/lib/hooks";
import { adminApi, type AdminDispute } from "@/lib/market";

function DisputeRow({
  dispute,
  token,
  reload,
}: {
  dispute: AdminDispute;
  token: string;
  reload: () => Promise<void>;
}) {
  const action = useAction();
  const [resolution, setResolution] = useState("");
  const [refund, setRefund] = useState("0");
  const open = dispute.status === "open" || dispute.status === "under_review";

  return (
    <Card>
      <CardBody>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={open ? "warn" : "neutral"}>{dispute.status.replace("_", " ")}</Badge>
          <Link href={`/orders/${dispute.order_id}`} className="font-mono text-xs underline">
            {dispute.order_code}
          </Link>
          <span className="text-sm">{pkr(dispute.total_pkr)}</span>
        </div>
        <h2 className="mt-1 font-semibold">{dispute.reason}</h2>
        {dispute.detail ? <p className="text-sm">{dispute.detail}</p> : null}
        {dispute.resolution ? (
          <p className="mt-2 text-sm text-ink-soft">
            {dispute.resolution}
            {dispute.refund_pkr ? ` Refund: ${pkr(dispute.refund_pkr)}.` : ""}
          </p>
        ) : null}

        {open ? (
          <div className="mt-3 max-w-prose">
            {dispute.status === "open" ? (
              <Button
                size="sm"
                variant="secondary"
                className="mb-3"
                disabled={action.busy}
                onClick={() =>
                  void action.run(async () => {
                    await adminApi.startDisputeReview(token, dispute.id);
                    await reload();
                  })
                }
              >
                Take for review
              </Button>
            ) : null}
            <Field label="Decision, read by both sides" htmlFor={`resolution-${dispute.id}`}>
              <TextArea
                id={`resolution-${dispute.id}`}
                value={resolution}
                onChange={(event) => setResolution(event.target.value)}
              />
            </Field>
            <Field
              label="Refund to the buyer, in PKR"
              htmlFor={`refund-${dispute.id}`}
              hint="0 finds for the seller. The full order total reverses the sale."
            >
              <TextInput
                id={`refund-${dispute.id}`}
                hasHint
                type="number"
                min={0}
                max={dispute.total_pkr}
                value={refund}
                onChange={(event) => setRefund(event.target.value)}
              />
            </Field>
            <Button
              disabled={action.busy || resolution.trim().length < 10}
              onClick={() =>
                void action.run(async () => {
                  await adminApi.resolveDispute(token, dispute.id, resolution, Number(refund));
                  await reload();
                })
              }
            >
              Record the decision
            </Button>
          </div>
        ) : null}
        <ActionError message={action.error} />
      </CardBody>
    </Card>
  );
}

function Disputes({ session }: { session: Session }) {
  const { token, locale } = session;
  const disputes = useResource(useCallback(() => adminApi.disputes(token), [token]));
  return (
    <Loaded resource={disputes} locale={locale}>
      {(rows) =>
        rows.length === 0 ? (
          <EmptyState title="No disputes" />
        ) : (
          <ul className="space-y-3">
            {rows.map((dispute) => (
              <li key={dispute.id}>
                <DisputeRow dispute={dispute} token={token} reload={disputes.reload} />
              </li>
            ))}
          </ul>
        )
      }
    </Loaded>
  );
}

export default function AdminDisputesPage() {
  return (
    <AdminPage title="Disputes" subtitle="An admin decides every one of these.">
      {(session) => <Disputes session={session} />}
    </AdminPage>
  );
}
