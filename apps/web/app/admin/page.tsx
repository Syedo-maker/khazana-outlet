"use client";

import { useCallback } from "react";

import { AdminPage } from "@/components/admin/AdminPage";
import { ActionError, Loaded } from "@/components/Feedback";
import type { Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Badge, Stat } from "@/components/ui/Card";
import { pkr } from "@/lib/format";
import { useAction, useResource } from "@/lib/hooks";
import { adminApi } from "@/lib/market";

function Overview({ session }: { session: Session }) {
  const { token, locale } = session;
  const overview = useResource(useCallback(() => adminApi.overview(token), [token]));
  const action = useAction();

  return (
    <Loaded resource={overview} locale={locale}>
      {(data) => (
        <>
          <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Brands to review" value={String(data.brands_awaiting_review)} />
            <Stat label="Resellers to review" value={String(data.resellers_awaiting_review)} />
            <Stat label="Listings awaiting approval" value={String(data.listings_awaiting_approval)} />
            <Stat label="Live listings" value={String(data.live_listings)} />
            <Stat label="Open disputes" value={String(data.open_disputes)} />
            <Stat label="Transfers to confirm" value={String(data.bank_transfers_to_confirm)} />
            <Stat label="Funds held" value={pkr(data.held_funds_pkr)} />
            <Stat label="Payouts due" value={pkr(data.payouts_due_pkr)} />
          </dl>
          <p className="mt-4 text-sm text-ink-soft">
            AI spend today: ${data.ai_spend_today_usd.toFixed(2)}
          </p>
          <h2 className="mt-6 text-lg font-semibold">Orders by status</h2>
          <ul className="mt-2 flex flex-wrap gap-2">
            {Object.entries(data.orders_by_status).map(([status, count]) => (
              <li key={status}>
                <Badge>
                  {status.replace("_", " ")}: {count}
                </Badge>
              </li>
            ))}
          </ul>
          <Button
            className="mt-6"
            variant="secondary"
            disabled={action.busy}
            onClick={() =>
              void action.run(async () => {
                await adminApi.closeDisputeWindows(token);
                await overview.reload();
              })
            }
          >
            Close ended dispute windows
          </Button>
          <ActionError message={action.error} />
        </>
      )}
    </Loaded>
  );
}

export default function AdminHomePage() {
  return (
    <AdminPage title="Overview" subtitle="What needs a decision today.">
      {(session) => <Overview session={session} />}
    </AdminPage>
  );
}
