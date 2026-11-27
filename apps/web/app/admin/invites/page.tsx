"use client";

import { useCallback, useState, type FormEvent } from "react";

import { AdminPage } from "@/components/admin/AdminPage";
import { ActionError, Loaded } from "@/components/Feedback";
import type { Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Field, SelectInput, TextInput } from "@/components/ui/Field";
import { EmptyState } from "@/components/ui/States";
import { dateTime } from "@/lib/format";
import { useAction, useResource } from "@/lib/hooks";
import { adminApi, type CreatedInvite, type Invite } from "@/lib/market";

const TONE = { pending: "accent", used: "ok", expired: "neutral", revoked: "warn" } as const;

function NewLink({ created }: { created: CreatedInvite }) {
  const [copied, setCopied] = useState(false);
  return (
    <div role="status" className="mt-4 rounded border border-accent bg-accent-subtle p-3 text-sm">
      <p className="font-semibold">
        Link for {created.full_name ?? created.phone} ({created.purpose}). It is shown only now.
      </p>
      <p className="mt-2 break-all font-mono text-xs">{created.link}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button
          variant="secondary"
          onClick={() =>
            void navigator.clipboard
              .writeText(created.link)
              .then(() => setCopied(true))
              .catch(() => setCopied(false))
          }
        >
          {copied ? "Copied" : "Copy link"}
        </Button>
        <a
          href={created.whatsapp_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex min-h-touch items-center rounded border border-line bg-surface px-3 text-sm font-semibold"
        >
          Send on WhatsApp
        </a>
      </div>
      <p className="mt-2 text-xs text-ink-soft">
        Send it only to {created.phone}. It works once and expires {dateTime(created.expires_at)}.
      </p>
    </div>
  );
}

function InviteRow({
  invite,
  token,
  reload,
}: {
  invite: Invite;
  token: string;
  reload: () => Promise<void>;
}) {
  const action = useAction();
  return (
    <li className="flex flex-wrap items-center gap-2 border-t border-line py-2 text-sm">
      <Badge tone={TONE[invite.status]}>{invite.status}</Badge>
      <span className="font-semibold">{invite.full_name ?? "No name"}</span>
      <span className="font-mono">{invite.phone}</span>
      <span>
        {invite.role}, {invite.purpose}
      </span>
      <span className="text-ink-faint">
        {invite.used_at ? `used ${dateTime(invite.used_at)}` : `expires ${dateTime(invite.expires_at)}`}
      </span>
      {invite.note ? <span className="text-ink-soft">{invite.note}</span> : null}
      {invite.status === "pending" ? (
        <Button
          variant="secondary"
          disabled={action.busy}
          onClick={() =>
            void action.run(async () => {
              await adminApi.revokeInvite(token, invite.id);
              await reload();
            })
          }
        >
          Revoke
        </Button>
      ) : null}
      <ActionError message={action.error} />
    </li>
  );
}

function Invites({ session }: { session: Session }) {
  const { token, locale } = session;
  const action = useAction();
  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<"reseller" | "brand">("reseller");
  const [brandId, setBrandId] = useState("");
  const [note, setNote] = useState("");
  const [created, setCreated] = useState<CreatedInvite | null>(null);
  const invites = useResource(useCallback(() => adminApi.invites(token), [token]));
  const brands = useResource(useCallback(() => adminApi.brands(token), [token]));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void action.run(async () => {
      const result = await adminApi.createInvite(token, {
        phone,
        full_name: name || null,
        role,
        brand_id: role === "brand" && brandId ? brandId : null,
        note: note || null,
      });
      setCreated(result);
      setPhone("");
      setName("");
      setNote("");
      await invites.reload();
    });
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle as="h2">New invite link</CardTitle>
        </CardHeader>
        <CardBody>
          <p className="mb-3 text-sm text-ink-soft">
            SMS codes are off during the beta. Make a link for one person, then send it to their
            number yourself. A person who already has an account gets a sign in link instead.
            Every new reseller still needs verifying under Verification before they can order.
          </p>
          <form className="grid max-w-xl gap-x-4 sm:grid-cols-2" onSubmit={submit}>
            <Field label="Mobile number" htmlFor="invite-phone">
              <TextInput
                id="invite-phone"
                type="tel"
                inputMode="numeric"
                placeholder="03001234567"
                required
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
              />
            </Field>
            <Field label="Name (optional)" htmlFor="invite-name">
              <TextInput
                id="invite-name"
                maxLength={120}
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </Field>
            <Field label="Joins as" htmlFor="invite-role">
              <SelectInput
                id="invite-role"
                value={role}
                onChange={(event) => setRole(event.target.value as "reseller" | "brand")}
              >
                <option value="reseller">Reseller</option>
                <option value="brand">Brand</option>
              </SelectInput>
            </Field>
            {role === "brand" ? (
              <Field label="Staff of an existing brand (optional)" htmlFor="invite-brand">
                <SelectInput
                  id="invite-brand"
                  value={brandId}
                  onChange={(event) => setBrandId(event.target.value)}
                >
                  <option value="">A new brand: they register it after signing in</option>
                  {(brands.data ?? []).map((row) => (
                    <option key={row.brand.id} value={row.brand.id}>
                      {row.brand.name}
                    </option>
                  ))}
                </SelectInput>
              </Field>
            ) : null}
            <Field label="Note for the team (optional)" htmlFor="invite-note">
              <TextInput
                id="invite-note"
                maxLength={300}
                value={note}
                onChange={(event) => setNote(event.target.value)}
              />
            </Field>
            <div className="sm:col-span-2">
              <Button type="submit" loading={action.busy}>
                Create link
              </Button>
              <ActionError message={action.error} />
            </div>
          </form>
          {created ? <NewLink created={created} /> : null}
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle as="h2">All invites</CardTitle>
        </CardHeader>
        <CardBody>
          <Loaded resource={invites} locale={locale}>
            {(rows) =>
              rows.length === 0 ? (
                <EmptyState title="No invites yet" />
              ) : (
                <ul>
                  {rows.map((invite) => (
                    <InviteRow key={invite.id} invite={invite} token={token} reload={invites.reload} />
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

export default function AdminInvitesPage() {
  return (
    <AdminPage
      title="Invites"
      subtitle="Single use sign in links, sent by hand, in place of SMS codes."
    >
      {(session) => <Invites session={session} />}
    </AdminPage>
  );
}
