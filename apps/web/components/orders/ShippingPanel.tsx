"use client";

import { useCallback, useState } from "react";

import { ActionError, Loaded } from "@/components/Feedback";
import type { Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Field, TextInput } from "@/components/ui/Field";
import { dateTime, pkr } from "@/lib/format";
import { useAction, useResource } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { fetchFile, market, type OrderDetail, type Shipment } from "@/lib/market";

function BrandControls({
  shipment,
  session,
  refresh,
}: {
  shipment: Shipment;
  session: Session;
  refresh: () => Promise<void>;
}) {
  const { token, locale } = session;
  const action = useAction();
  const [pickupAt, setPickupAt] = useState("");

  const finished = ["delivered", "returned", "lost"].includes(shipment.status);
  return (
    <div className="mt-3">
      <div className="flex flex-wrap gap-2">
        <Button
          variant="secondary"
          disabled={action.busy}
          onClick={() =>
            void action.run(async () => {
              const label = await fetchFile(`/shipments/${shipment.id}/label`, token);
              window.open(URL.createObjectURL(label), "_blank", "noopener");
            })
          }
        >
          {t(locale, "shipping.label")}
        </Button>
        {!finished ? (
          <Button
            variant="secondary"
            disabled={action.busy}
            onClick={() =>
              void action.run(async () => {
                await market.advanceShipment(token, shipment.id);
                await refresh();
              })
            }
          >
            {t(locale, "shipping.advance")}
          </Button>
        ) : null}
      </div>
      {shipment.status === "pending_pickup" ? (
        <form
          className="mt-3 flex max-w-md flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void action.run(async () => {
              await market.schedulePickup(token, shipment.id, new Date(pickupAt).toISOString());
              await refresh();
            });
          }}
        >
          <Field label={t(locale, "shipping.pickupAt")} htmlFor="pickup-at">
            <TextInput
              id="pickup-at"
              type="datetime-local"
              required
              value={pickupAt}
              onChange={(event) => setPickupAt(event.target.value)}
            />
          </Field>
          <Button type="submit" variant="secondary" className="mb-4" disabled={action.busy}>
            {t(locale, "shipping.schedule")}
          </Button>
        </form>
      ) : null}
      <ActionError message={action.error} />
    </div>
  );
}

/** Direct orders: the brand's own courier, entered by hand. */
function DirectShipForm({
  order,
  session,
  refresh,
}: {
  order: OrderDetail;
  session: Session;
  refresh: () => Promise<void>;
}) {
  const { token, locale } = session;
  const action = useAction();
  const [courier, setCourier] = useState("");
  const [tracking, setTracking] = useState("");
  return (
    <form
      className="mt-3 max-w-md"
      onSubmit={(event) => {
        event.preventDefault();
        void action.run(async () => {
          await market.enterShipment(token, order.id, courier, tracking);
          await refresh();
        });
      }}
    >
      <p className="mb-3 text-sm">
        {t(locale, "direct.shipBody", { amount: pkr(order.total_pkr) })}
      </p>
      <Field
        label={t(locale, "direct.courier")}
        htmlFor="direct-courier"
        hint={t(locale, "direct.courierHint")}
      >
        <TextInput
          id="direct-courier"
          hasHint
          required
          minLength={2}
          maxLength={40}
          autoComplete="off"
          value={courier}
          onChange={(event) => setCourier(event.target.value)}
        />
      </Field>
      <Field label={t(locale, "direct.tracking")} htmlFor="direct-tracking">
        <TextInput
          id="direct-tracking"
          required
          minLength={4}
          maxLength={80}
          autoComplete="off"
          value={tracking}
          onChange={(event) => setTracking(event.target.value)}
        />
      </Field>
      <Button type="submit" loading={action.busy}>
        {t(locale, "direct.save")}
      </Button>
      <ActionError message={action.error} />
    </form>
  );
}

function DirectOutcome({
  shipment,
  session,
  refresh,
}: {
  shipment: Shipment;
  session: Session;
  refresh: () => Promise<void>;
}) {
  const { token, locale } = session;
  const action = useAction();
  if (["delivered", "returned", "lost"].includes(shipment.status)) return null;
  const record = (status: "delivered" | "returned") =>
    void action.run(async () => {
      await market.enterOutcome(token, shipment.id, status);
      await refresh();
    });
  return (
    <div className="mt-3">
      <p className="mb-2 text-sm text-ink-soft">{t(locale, "direct.outcomeHint")}</p>
      <div className="flex flex-wrap gap-2">
        <Button disabled={action.busy} onClick={() => record("delivered")}>
          {t(locale, "direct.delivered")}
        </Button>
        <Button
          variant="secondary"
          disabled={action.busy}
          onClick={() => {
            if (window.confirm(t(locale, "direct.refusedConfirm"))) record("returned");
          }}
        >
          {t(locale, "direct.refused")}
        </Button>
      </div>
      <ActionError message={action.error} />
    </div>
  );
}

export function ShippingPanel({
  order,
  session,
  selling,
  onChanged,
}: {
  order: OrderDetail;
  session: Session;
  selling: boolean;
  onChanged: () => Promise<void>;
}) {
  const { token, locale } = session;
  const action = useAction();
  const tracking = useResource(
    useCallback(() => market.tracking(token, order.id), [token, order.id]),
  );

  const refresh = async () => {
    await tracking.reload();
    await onChanged();
  };
  const direct = order.settlement_mode === "direct";

  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle as="h2">{t(locale, "shipping.title")}</CardTitle>
      </CardHeader>
      <CardBody>
        <Loaded resource={tracking} locale={locale} rows={2}>
          {(shipments) =>
            shipments.length === 0 ? (
              <>
                <p className="text-sm text-ink-soft">{t(locale, "shipping.none")}</p>
                {direct && selling && order.status === "preparing" ? (
                  <DirectShipForm order={order} session={session} refresh={refresh} />
                ) : null}
                {!direct && selling && ["paid", "preparing"].includes(order.status) ? (
                  <Button
                    className="mt-3"
                    loading={action.busy}
                    onClick={() =>
                      void action.run(async () => {
                        await market.bookShipment(token, order.id);
                        await refresh();
                      })
                    }
                  >
                    {t(locale, "shipping.book")}
                  </Button>
                ) : null}
                <ActionError message={action.error} />
              </>
            ) : (
              shipments.map((shipment) => (
                <div key={shipment.id}>
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <Badge tone="accent">{t(locale, `shipment.status.${shipment.status}`)}</Badge>
                    {direct ? <span className="font-semibold">{shipment.courier}</span> : null}
                    <span className="font-mono">{shipment.tracking_number}</span>
                    {shipment.cost_pkr !== null ? <span>{pkr(shipment.cost_pkr)}</span> : null}
                  </div>
                  {shipment.pickup_scheduled_for ? (
                    <p className="mt-1 text-sm text-ink-soft">
                      {t(locale, "shipping.pickupOn", {
                        date: dateTime(shipment.pickup_scheduled_for),
                      })}
                    </p>
                  ) : null}
                  <ol className="mt-3 space-y-1 border-l-2 border-line pl-3 text-sm">
                    {shipment.events.map((event) => (
                      <li key={`${event.status}-${event.created_at}`}>
                        <span className="font-semibold">
                          {t(locale, `shipment.status.${event.status}`)}
                        </span>{" "}
                        <span className="text-ink-faint">{dateTime(event.created_at)}</span>
                        {event.location ? ` · ${event.location}` : ""}
                      </li>
                    ))}
                  </ol>
                  {selling && direct ? (
                    <DirectOutcome shipment={shipment} session={session} refresh={refresh} />
                  ) : null}
                  {selling && !direct ? (
                    <BrandControls shipment={shipment} session={session} refresh={refresh} />
                  ) : null}
                </div>
              ))
            )
          }
        </Loaded>
      </CardBody>
    </Card>
  );
}
