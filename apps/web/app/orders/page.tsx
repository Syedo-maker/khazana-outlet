"use client";

import Link from "next/link";
import { useCallback, useState } from "react";

import { Loaded, OrderBadge, PageHeader } from "@/components/Feedback";
import { RoleShell, type Session } from "@/components/RoleShell";
import { Card, CardBody } from "@/components/ui/Card";
import { Field, SelectInput } from "@/components/ui/Field";
import { EmptyState } from "@/components/ui/States";
import { dateTime, pkr } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { market, type OrderStatus } from "@/lib/market";

const STATUSES: OrderStatus[] = [
  "awaiting_payment",
  "paid",
  "preparing",
  "shipped",
  "delivered",
  "confirmed",
  "disputed",
  "cancelled",
  "refunded",
];

function OrdersContent({ session }: { session: Session }) {
  const { token, locale } = session;
  const [status, setStatus] = useState<OrderStatus | "">("");
  const orders = useResource(
    useCallback(() => market.orders(token, status || undefined), [token, status]),
  );

  return (
    <>
      <PageHeader title={t(locale, "orders.title")} />
      <div className="mb-4 max-w-xs">
        <Field label={t(locale, "orders.status")} htmlFor="status">
          <SelectInput
            id="status"
            value={status}
            onChange={(event) => setStatus(event.target.value as OrderStatus | "")}
          >
            <option value="">{t(locale, "catalog.any")}</option>
            {STATUSES.map((option) => (
              <option key={option} value={option}>
                {t(locale, `order.status.${option}`)}
              </option>
            ))}
          </SelectInput>
        </Field>
      </div>
      <Loaded resource={orders} locale={locale}>
        {(rows) =>
          rows.length === 0 ? (
            <EmptyState title={t(locale, "orders.none")} />
          ) : (
            <ul className="space-y-3">
              {rows.map((order) => (
                <li key={order.id}>
                  <Card>
                    <CardBody className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <OrderBadge status={order.status} locale={locale} />
                          <span className="font-mono text-xs text-ink-faint">
                            {order.order_code}
                          </span>
                        </div>
                        <h2 className="mt-1 font-semibold">
                          <Link href={`/orders/${order.id}`} className="underline decoration-line">
                            {order.lot_title}
                          </Link>
                        </h2>
                        <p className="text-sm text-ink-soft">
                          {order.buyer_business_name ?? order.seller_name} ·{" "}
                          {dateTime(order.created_at)}
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="font-semibold">{pkr(order.total_pkr)}</p>
                        <p className="text-sm text-ink-soft">
                          {t(locale, "orders.pieces", { count: order.pieces })}
                        </p>
                      </div>
                    </CardBody>
                  </Card>
                </li>
              ))}
            </ul>
          )
        }
      </Loaded>
    </>
  );
}

export default function OrdersPage() {
  return <RoleShell>{(session) => <OrdersContent session={session} />}</RoleShell>;
}
