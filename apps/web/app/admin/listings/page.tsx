"use client";

import { useCallback, useState } from "react";

import { AdminPage } from "@/components/admin/AdminPage";
import { ActionError, Loaded } from "@/components/Feedback";
import type { Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardBody } from "@/components/ui/Card";
import { Field, SelectInput, TextInput } from "@/components/ui/Field";
import { EmptyState } from "@/components/ui/States";
import type { LotStatus } from "@/lib/api";
import { pkr } from "@/lib/format";
import { useAction, useResource } from "@/lib/hooks";
import { adminApi, type AdminListing } from "@/lib/market";

const STATUSES: LotStatus[] = ["pending_approval", "live", "paused", "draft", "withdrawn", "sold"];
const BAND_TONES: Record<string, "ok" | "warn" | "danger"> = {
  low: "ok",
  medium: "warn",
  high: "danger",
};

function ListingRow({
  item,
  token,
  reload,
}: {
  item: AdminListing;
  token: string;
  reload: () => Promise<void>;
}) {
  const action = useAction();
  const [note, setNote] = useState("");
  const live = item.lot.status === "live";

  const takeDown = (withdraw: boolean) =>
    void action.run(async () => {
      await adminApi.takeDown(token, item.lot.id, note, withdraw);
      await reload();
    });

  return (
    <Card>
      <CardBody>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={BAND_TONES[item.risk_band] ?? "neutral"}>
            Risk {item.risk_score}, {item.risk_band}
          </Badge>
          <Badge>{item.lot.status.replace("_", " ")}</Badge>
          <Badge>{item.lot.visibility}</Badge>
          <span className="font-mono text-xs text-ink-faint">{item.lot.lot_code}</span>
        </div>
        <h2 className="mt-1 font-semibold">{item.lot.title}</h2>
        <p className="text-sm text-ink-soft">
          {item.brand_name} · {item.lot.total_pieces} pieces · {pkr(item.lot.lot_price_pkr)} ·{" "}
          {Math.round(item.lot.discount_percent)}% off
        </p>
        {item.findings.length > 0 ? (
          <ul className="mt-2 list-disc pl-5 text-sm">
            {item.findings.map((finding) => (
              <li key={finding}>{finding}</li>
            ))}
          </ul>
        ) : null}
        {live ? (
          <div className="mt-3">
            <TextInput
              id={`note-${item.lot.id}`}
              aria-label="Reason for taking this listing down"
              placeholder="Reason, at least 10 characters"
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
            <div className="mt-2 flex gap-2">
              <Button
                size="sm"
                variant="secondary"
                disabled={action.busy || note.trim().length < 10}
                onClick={() => takeDown(false)}
              >
                Pause
              </Button>
              <Button
                size="sm"
                variant="danger"
                disabled={action.busy || note.trim().length < 10}
                onClick={() => takeDown(true)}
              >
                Withdraw
              </Button>
            </div>
          </div>
        ) : null}
        <ActionError message={action.error} />
      </CardBody>
    </Card>
  );
}

function Listings({ session }: { session: Session }) {
  const { token, locale } = session;
  const [status, setStatus] = useState<LotStatus | "">("pending_approval");
  const [search, setSearch] = useState("");
  const listings = useResource(
    useCallback(
      () => adminApi.listings(token, status || undefined, search || undefined),
      [token, status, search],
    ),
  );

  return (
    <>
      <div className="mb-4 grid max-w-2xl gap-3 sm:grid-cols-2">
        <Field label="Status" htmlFor="status">
          <SelectInput
            id="status"
            value={status}
            onChange={(event) => setStatus(event.target.value as LotStatus | "")}
          >
            <option value="">All</option>
            {STATUSES.map((option) => (
              <option key={option} value={option}>
                {option.replace("_", " ")}
              </option>
            ))}
          </SelectInput>
        </Field>
        <Field label="Title or code" htmlFor="search">
          <TextInput
            id="search"
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </Field>
      </div>
      <Loaded resource={listings} locale={locale}>
        {(rows) =>
          rows.length === 0 ? (
            <EmptyState title="No listings match" />
          ) : (
            <ul className="space-y-3">
              {rows.map((item) => (
                <li key={item.lot.id}>
                  <ListingRow item={item} token={token} reload={listings.reload} />
                </li>
              ))}
            </ul>
          )
        }
      </Loaded>
    </>
  );
}

export default function AdminListingsPage() {
  return (
    <AdminPage
      title="Listing moderation"
      subtitle="Highest risk first. The score helps you look in the right place and decides nothing."
    >
      {(session) => <Listings session={session} />}
    </AdminPage>
  );
}
