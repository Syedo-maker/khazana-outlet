"use client";

import { useCallback, useState } from "react";

import { AdminPage } from "@/components/admin/AdminPage";
import { AuthedDocumentLink } from "@/components/admin/AuthedDocumentLink";
import { ActionError, Loaded } from "@/components/Feedback";
import type { Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { TextInput } from "@/components/ui/Field";
import { EmptyState } from "@/components/ui/States";
import { useAction, useResource } from "@/lib/hooks";
import { adminApi } from "@/lib/market";

function Decision({
  id,
  onDecide,
}: {
  id: string;
  onDecide: (approve: boolean, note: string) => Promise<unknown>;
}) {
  const action = useAction();
  const [note, setNote] = useState("");
  return (
    <div className="mt-3">
      <TextInput
        id={`note-${id}`}
        aria-label="Decision note"
        placeholder="Note, required when rejecting"
        value={note}
        onChange={(event) => setNote(event.target.value)}
      />
      <div className="mt-2 flex gap-2">
        <Button
          size="sm"
          disabled={action.busy}
          onClick={() => void action.run(() => onDecide(true, note))}
        >
          Approve
        </Button>
        <Button
          size="sm"
          variant="danger"
          disabled={action.busy || note.trim().length < 10}
          onClick={() => void action.run(() => onDecide(false, note))}
        >
          Reject
        </Button>
      </div>
      <ActionError message={action.error} />
    </div>
  );
}

function Verification({ session }: { session: Session }) {
  const { token, locale } = session;
  const resellers = useResource(useCallback(() => adminApi.resellers(token), [token]));
  const brands = useResource(useCallback(() => adminApi.brands(token, "pending"), [token]));

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle as="h2">Brands</CardTitle>
        </CardHeader>
        <CardBody>
          <Loaded resource={brands} locale={locale}>
            {(rows) =>
              rows.length === 0 ? (
                <EmptyState title="No brands are waiting" />
              ) : (
                <ul className="space-y-4">
                  {rows.map(({ brand, documents }) => (
                    <li key={brand.id} className="border-b border-line pb-4">
                      <p className="font-semibold">{brand.name}</p>
                      <p className="text-sm text-ink-soft">
                        {brand.city} {brand.ntn ? `· NTN ${brand.ntn}` : ""}
                      </p>
                      <ul className="mt-1 text-sm">
                        {documents.map((document) => (
                          <li key={document.id}>
                            <AuthedDocumentLink
                              token={token}
                              documentId={document.id}
                              label={`${document.doc_type}: ${document.original_filename ?? "file"}`}
                            />
                          </li>
                        ))}
                      </ul>
                      <Decision
                        id={brand.id}
                        onDecide={async (approve, note) => {
                          await adminApi.reviewBrand(token, brand.id, approve, note);
                          await brands.reload();
                        }}
                      />
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
          <CardTitle as="h2">Resellers</CardTitle>
        </CardHeader>
        <CardBody>
          <Loaded resource={resellers} locale={locale}>
            {(rows) =>
              rows.length === 0 ? (
                <EmptyState title="No resellers are waiting" />
              ) : (
                <ul className="space-y-4">
                  {rows.map((row) => (
                    <li key={row.id} className="border-b border-line pb-4">
                      <p className="font-semibold">{row.business_name}</p>
                      <p className="text-sm text-ink-soft">
                        {row.full_name} · {row.phone} · {row.city}
                      </p>
                      {row.shop_address ? <p className="text-sm">{row.shop_address}</p> : null}
                      <Decision
                        id={row.id}
                        onDecide={async (approve, note) => {
                          await adminApi.reviewReseller(token, row.id, approve, note);
                          await resellers.reload();
                        }}
                      />
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

export default function VerificationPage() {
  return (
    <AdminPage title="Verification" subtitle="Oldest requests first.">
      {(session) => <Verification session={session} />}
    </AdminPage>
  );
}
