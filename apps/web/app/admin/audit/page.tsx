"use client";

import { useCallback, useState } from "react";

import { AdminPage } from "@/components/admin/AdminPage";
import { Loaded } from "@/components/Feedback";
import type { Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardBody } from "@/components/ui/Card";
import { Field, TextInput } from "@/components/ui/Field";
import { EmptyState } from "@/components/ui/States";
import { dateTime } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import { adminApi } from "@/lib/market";

function Audit({ session }: { session: Session }) {
  const { token, locale } = session;
  const [action, setAction] = useState("");
  const [offset, setOffset] = useState(0);
  const entries = useResource(
    useCallback(() => adminApi.audit(token, action || undefined, offset), [token, action, offset]),
  );

  return (
    <>
      <div className="mb-4 max-w-sm">
        <Field label="Action starts with" htmlFor="action" hint="For example order. or payout_run.">
          <TextInput
            id="action"
            hasHint
            value={action}
            onChange={(event) => {
              setOffset(0);
              setAction(event.target.value);
            }}
          />
        </Field>
      </div>
      <Loaded resource={entries} locale={locale}>
        {(rows) =>
          rows.length === 0 ? (
            <EmptyState title="No entries" />
          ) : (
            <>
              <ul className="space-y-2">
                {rows.map((entry) => (
                  <li key={entry.id}>
                    <Card>
                      <CardBody className="text-sm">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-mono font-semibold">{entry.action}</span>
                          <Badge>{entry.actor_kind}</Badge>
                          {entry.actor_role ? <Badge>{entry.actor_role}</Badge> : null}
                          <span className="text-ink-faint">{dateTime(entry.created_at)}</span>
                        </div>
                        <p className="mt-1 text-ink-soft">
                          {entry.entity_type} {entry.entity_id}
                        </p>
                        {entry.note ? <p className="mt-1">{entry.note}</p> : null}
                        {entry.after ? (
                          <pre className="mt-2 overflow-x-auto rounded bg-surface-sunk p-2 text-xs">
                            {JSON.stringify(entry.after, null, 2)}
                          </pre>
                        ) : null}
                      </CardBody>
                    </Card>
                  </li>
                ))}
              </ul>
              <div className="mt-4 flex gap-2">
                <Button
                  variant="secondary"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - 50))}
                >
                  Newer
                </Button>
                <Button
                  variant="secondary"
                  disabled={rows.length < 50}
                  onClick={() => setOffset(offset + 50)}
                >
                  Older
                </Button>
              </div>
            </>
          )
        }
      </Loaded>
    </>
  );
}

export default function AdminAuditPage() {
  return (
    <AdminPage title="Audit log" subtitle="Append only. Nothing here can be changed.">
      {(session) => <Audit session={session} />}
    </AdminPage>
  );
}
