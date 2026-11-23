"use client";

import { ResellKitPanel } from "@/components/orders/ResellKitPanel";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useState, type ReactNode } from "react";

import { ActionError, Loaded, OrderBadge } from "@/components/Feedback";
import { PaymentPanel } from "@/components/orders/PaymentPanel";
import { ShippingPanel } from "@/components/orders/ShippingPanel";
import { RoleShell, type Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardBody, CardHeader, CardTitle, Stat } from "@/components/ui/Card";
import { Field, TextArea, TextInput } from "@/components/ui/Field";
import { dateTime, pkr } from "@/lib/format";
import { useAction, useResource } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { adminApi, market, type OrderDetail } from "@/lib/market";

const CANCELLABLE = ["created", "awaiting_payment", "preparing"];
const REFUNDABLE = ["paid", "preparing", "shipped", "disputed"];
const RETURNABLE = ["delivered", "disputed", "confirmed", "refunded"];

// A resell kit is for stock the buyer has paid for and still has.
const KIT_STATUSES: OrderDetail["status"][] = [
  "paid",
  "preparing",
  "shipped",
  "delivered",
  "confirmed",
  "disputed",
];

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle as="h2">{title}</CardTitle>
      </CardHeader>
      <CardBody>{children}</CardBody>
    </Card>
  );
}

function OrderActions({
  order,
  session,
  isBuyer,
  selling,
  refresh,
}: {
  order: OrderDetail;
  session: Session;
  isBuyer: boolean;
  selling: boolean;
  refresh: () => Promise<void>;
}) {
  const { token, locale, me } = session;
  const action = useAction();
  const [reason, setReason] = useState("");
  const [detail, setDetail] = useState("");
  const [pieces, setPieces] = useState("");

  const act = (work: () => Promise<unknown>) =>
    void action.run(async () => {
      await work();
      setReason("");
      setDetail("");
      setPieces("");
      await refresh();
    });

  const canCancel = (isBuyer || selling) && CANCELLABLE.includes(order.status);
  const canDispute = isBuyer && order.status === "delivered";
  const canRefund = me.is_admin && REFUNDABLE.includes(order.status);
  const canReturn = selling && RETURNABLE.includes(order.status);
  if (!canCancel && !canDispute && !canRefund && !canReturn) return null;

  return (
    <Section title={t(locale, "orderDetail.actions")}>
      {isBuyer && order.status === "delivered" ? (
        <div className="mb-4">
          <p className="mb-2 text-sm">
            {t(locale, "orderDetail.confirmHelp", {
              date: dateTime(order.dispute_window_ends_at),
            })}
          </p>
          <Button
            disabled={action.busy}
            onClick={() => act(() => market.confirmOrder(token, order.id))}
          >
            {t(locale, "orderDetail.confirm")}
          </Button>
        </div>
      ) : null}

      {canCancel || canDispute || canRefund ? (
        <Field
          label={t(locale, canDispute ? "orderDetail.problem" : "orderDetail.reason")}
          htmlFor="reason"
        >
          <TextInput
            id="reason"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </Field>
      ) : null}
      {canDispute ? (
        <Field label={t(locale, "orderDetail.problemDetail")} htmlFor="detail">
          <TextArea
            id="detail"
            value={detail}
            onChange={(event) => setDetail(event.target.value)}
          />
        </Field>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {canCancel ? (
          <Button
            variant="secondary"
            disabled={action.busy || reason.trim().length < 3}
            onClick={() => act(() => market.cancelOrder(token, order.id, reason))}
          >
            {t(locale, "orderDetail.cancel")}
          </Button>
        ) : null}
        {canDispute ? (
          <Button
            variant="danger"
            disabled={action.busy || reason.trim().length < 3}
            onClick={() => act(() => market.openDispute(token, order.id, reason, detail))}
          >
            {t(locale, "orderDetail.report")}
          </Button>
        ) : null}
        {canRefund ? (
          <Button
            variant="danger"
            disabled={action.busy || reason.trim().length < 10}
            onClick={() => act(() => adminApi.refund(token, order.id, reason))}
          >
            {t(locale, "orderDetail.refund")}
          </Button>
        ) : null}
      </div>

      {canReturn ? (
        <form
          className="mt-4 grid gap-2 sm:grid-cols-[8rem_1fr_auto] sm:items-end"
          onSubmit={(event) => {
            event.preventDefault();
            act(() => market.recordReturn(token, order.id, Number(pieces), detail));
          }}
        >
          <Field label={t(locale, "manifest.pieces")} htmlFor="return-pieces">
            <TextInput
              id="return-pieces"
              type="number"
              min={1}
              required
              value={pieces}
              onChange={(event) => setPieces(event.target.value)}
            />
          </Field>
          <Field label={t(locale, "orderDetail.returnReason")} htmlFor="return-reason">
            <TextInput
              id="return-reason"
              required
              value={detail}
              onChange={(event) => setDetail(event.target.value)}
            />
          </Field>
          <Button type="submit" variant="secondary" className="mb-4" disabled={action.busy}>
            {t(locale, "orderDetail.recordReturn")}
          </Button>
        </form>
      ) : null}
      <ActionError message={action.error} />
    </Section>
  );
}

function OrderView({
  order,
  session,
  refresh,
}: {
  order: OrderDetail;
  session: Session;
  refresh: () => Promise<void>;
}) {
  const { locale, me } = session;
  const selling = me.is_admin || me.user.role === "brand";
  const isBuyer = me.user.role === "reseller";

  return (
    <>
      <header className="mb-6">
        <div className="flex flex-wrap items-center gap-2">
          <OrderBadge status={order.status} locale={locale} />
          <span className="font-mono text-xs text-ink-faint">{order.order_code}</span>
        </div>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">{order.lot_title}</h1>
        <p className="mt-1 text-sm text-ink-soft">{order.seller_name}</p>
      </header>

      <dl className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label={t(locale, "manifest.pieces")} value={String(order.pieces)} />
        <Stat label={t(locale, "orderDetail.goods")} value={pkr(order.subtotal_pkr)} />
        <Stat label={t(locale, "orderDetail.shipping")} value={pkr(order.shipping_pkr)} />
        <Stat label={t(locale, "orderDetail.total")} value={pkr(order.total_pkr)} />
        {order.brand_payout_pkr !== null ? (
          <>
            <Stat
              label={t(locale, "orderDetail.commission")}
              value={pkr(order.commission_pkr ?? 0)}
              note={`${order.commission_percent}%`}
            />
            <Stat label={t(locale, "orderDetail.payout")} value={pkr(order.brand_payout_pkr)} />
          </>
        ) : null}
      </dl>

      {isBuyer && order.status !== "cancelled" ? (
        <PaymentPanel order={order} session={session} onChanged={refresh} />
      ) : null}
      {selling && order.status === "paid" ? (
        <p className="mb-6 text-sm text-ink-soft">{t(locale, "orderDetail.readyToPack")}</p>
      ) : null}
      <ShippingPanel order={order} session={session} selling={selling} onChanged={refresh} />
      {isBuyer && KIT_STATUSES.includes(order.status) ? (
        <ResellKitPanel orderId={order.id} session={session} />
      ) : null}
      <OrderActions
        order={order}
        session={session}
        isBuyer={isBuyer}
        selling={selling}
        refresh={refresh}
      />

      <Section title={t(locale, "orderDetail.delivery")}>
        <p className="text-sm">{order.delivery_city}</p>
        <p className="text-sm text-ink-soft">
          {order.delivery_address ?? t(locale, "orderDetail.addressLater")}
        </p>
        {order.delivery_phone ? <p className="text-sm">{order.delivery_phone}</p> : null}
        {order.buyer_business_name ? (
          <p className="mt-2 text-sm font-semibold">{order.buyer_business_name}</p>
        ) : null}
        <ul className="mt-3 text-sm text-ink-soft">
          {order.lines.map((line) => (
            <li key={`${line.size}-${line.color}`}>
              {line.size}, {line.color}: {line.pieces}
            </li>
          ))}
        </ul>
      </Section>

      {order.disputes.length > 0 ? (
        <Section title={t(locale, "orderDetail.disputes")}>
          <ul className="space-y-3 text-sm">
            {order.disputes.map((dispute) => (
              <li key={dispute.id}>
                <Badge tone="warn">{t(locale, `dispute.status.${dispute.status}`)}</Badge>
                <p className="mt-1 font-semibold">{dispute.reason}</p>
                {dispute.detail ? <p>{dispute.detail}</p> : null}
                {dispute.resolution ? <p className="mt-1">{dispute.resolution}</p> : null}
                {dispute.refund_pkr ? <p>{pkr(dispute.refund_pkr)}</p> : null}
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {order.returns.length > 0 ? (
        <Section title={t(locale, "orderDetail.returns")}>
          <ul className="space-y-1 text-sm">
            {order.returns.map((entry) => (
              <li key={entry.id}>
                {t(locale, "orders.pieces", { count: entry.pieces })}: {entry.reason}
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      <Section title={t(locale, "orderDetail.history")}>
        <ol className="space-y-2 border-l-2 border-line pl-3 text-sm">
          {order.events.map((event) => (
            <li key={`${event.to_status}-${event.created_at}`}>
              <span className="font-semibold">{t(locale, `order.status.${event.to_status}`)}</span>{" "}
              <span className="text-ink-faint">{dateTime(event.created_at)}</span>
              {event.note ? <p className="text-ink-soft">{event.note}</p> : null}
            </li>
          ))}
        </ol>
      </Section>
    </>
  );
}

function OrderContent({ session, orderId }: { session: Session; orderId: string }) {
  const { token, locale } = session;
  const order = useResource(useCallback(() => market.order(token, orderId), [token, orderId]));
  return (
    <>
      <nav className="mb-4">
        <Link href="/orders" className="text-sm font-semibold text-accent underline">
          {t(locale, "orderDetail.back")}
        </Link>
      </nav>
      <Loaded resource={order} locale={locale} rows={6}>
        {(data) => <OrderView order={data} session={session} refresh={order.reload} />}
      </Loaded>
    </>
  );
}

export default function OrderPage() {
  const { id } = useParams<{ id: string }>();
  return <RoleShell>{(session) => <OrderContent session={session} orderId={id} />}</RoleShell>;
}
