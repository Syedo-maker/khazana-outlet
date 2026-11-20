"use client";

import { useCallback } from "react";

import { AdminPage } from "@/components/admin/AdminPage";
import { Loaded } from "@/components/Feedback";
import type { Session } from "@/components/RoleShell";
import { Card, CardBody, CardHeader, CardTitle, Stat } from "@/components/ui/Card";
import { pkr } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import { adminApi } from "@/lib/market";

function change(value: number | null): string | undefined {
  if (value === null) return undefined;
  return `${value > 0 ? "+" : ""}${value}% on the period before`;
}

function Costs({ session }: { session: Session }) {
  const { token, locale } = session;
  const data = useResource(
    useCallback(
      () => Promise.all([adminApi.aiCosts(token), adminApi.analytics(token)]),
      [token],
    ),
  );
  return (
    <Loaded resource={data} locale={locale}>
      {([costs, platform]) => (
        <div className="space-y-6">
          <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="GMV, 30 days" value={pkr(platform.gmv_pkr)} note={change(platform.change_percent.gmv)} />
            <Stat label="Orders" value={String(platform.orders)} note={change(platform.change_percent.orders)} />
            <Stat label="Commission" value={pkr(platform.commission_pkr)} />
            <Stat
              label="Active buyers"
              value={String(platform.active_buyers)}
              note={change(platform.change_percent.active_buyers)}
            />
          </dl>
          <dl className="grid grid-cols-2 gap-3 lg:grid-cols-3">
            <Stat label="AI spend, 30 days" value={`$${costs.total_usd}`} />
            <Stat
              label="AI cost per listing"
              value={costs.cost_per_listing_usd ? `$${costs.cost_per_listing_usd}` : "No listings"}
              note={`${costs.listings} listings created`}
            />
            <Stat
              label="AI cost per order"
              value={costs.cost_per_order_usd ? `$${costs.cost_per_order_usd}` : "No orders"}
              note={`${costs.orders} orders sold`}
            />
          </dl>
          <Card>
            <CardHeader>
              <CardTitle as="h2">Spend by feature</CardTitle>
            </CardHeader>
            <CardBody>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-ink-soft">
                    <th className="py-1 text-start font-normal">Feature</th>
                    <th className="py-1 text-end font-normal">Calls</th>
                    <th className="py-1 text-end font-normal">Cost</th>
                    <th className="py-1 text-end font-normal">Per call</th>
                  </tr>
                </thead>
                <tbody>
                  {costs.features.map((row) => (
                    <tr key={row.feature} className="border-t border-line">
                      <td className="py-1">{row.feature.replaceAll("_", " ")}</td>
                      <td className="py-1 text-end">{row.calls}</td>
                      <td className="py-1 text-end">${row.cost_usd}</td>
                      <td className="py-1 text-end">${row.average_usd}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-3 text-xs text-ink-faint">
                Per listing counts {costs.listing_features.join(", ").replaceAll("_", " ")}. Per order
                counts {costs.order_features.join(", ").replaceAll("_", " ")}.
              </p>
            </CardBody>
          </Card>
        </div>
      )}
    </Loaded>
  );
}

export default function AdminAiCostsPage() {
  return (
    <AdminPage title="Growth and AI cost" subtitle="Computed from the records when you open it.">
      {(session) => <Costs session={session} />}
    </AdminPage>
  );
}
