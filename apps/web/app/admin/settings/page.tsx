"use client";

import { useCallback, useState } from "react";

import { AdminPage } from "@/components/admin/AdminPage";
import { ActionError, Loaded } from "@/components/Feedback";
import type { Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Field, SelectInput, TextInput } from "@/components/ui/Field";
import { pkr } from "@/lib/format";
import { useAction, useResource } from "@/lib/hooks";
import { adminApi, type AdminBrand, type Courier, type SettlementMode } from "@/lib/market";

function BrandTerms({
  row,
  token,
  reload,
}: {
  row: AdminBrand;
  token: string;
  reload: () => Promise<void>;
}) {
  const action = useAction();
  const [commission, setCommission] = useState(String(row.policy.commission_percent));
  const [days, setDays] = useState(String(row.policy.payout_terms_days));
  const [mode, setMode] = useState<SettlementMode>(row.policy.settlement_mode);

  return (
    <form
      className="grid items-end gap-3 border-t border-line py-3 sm:grid-cols-[1fr_8rem_8rem_12rem_auto]"
      onSubmit={(event) => {
        event.preventDefault();
        void action.run(async () => {
          await adminApi.updateTerms(token, row.brand.id, {
            commission_percent: Number(commission),
            payout_terms_days: Number(days),
            settlement_mode: mode,
          });
          await reload();
        });
      }}
    >
      <div className="pb-4">
        <p className="font-semibold">{row.brand.name}</p>
        <p className="text-sm text-ink-soft">{row.brand.status}</p>
        <ActionError message={action.error} />
      </div>
      <Field label="Commission %" htmlFor={`commission-${row.brand.id}`}>
        <TextInput
          id={`commission-${row.brand.id}`}
          type="number"
          min={0}
          max={50}
          step="0.5"
          value={commission}
          onChange={(event) => setCommission(event.target.value)}
        />
      </Field>
      <Field label="Payout days" htmlFor={`days-${row.brand.id}`}>
        <TextInput
          id={`days-${row.brand.id}`}
          type="number"
          min={0}
          max={90}
          value={days}
          onChange={(event) => setDays(event.target.value)}
        />
      </Field>
      <Field label="Buyers pay" htmlFor={`mode-${row.brand.id}`}>
        <SelectInput
          id={`mode-${row.brand.id}`}
          value={mode}
          onChange={(event) => setMode(event.target.value as SettlementMode)}
        >
          <option value="direct">The brand, cash on delivery</option>
          <option value="platform">The platform, held until confirmed</option>
        </SelectInput>
      </Field>
      <Button type="submit" variant="secondary" className="mb-4" disabled={action.busy}>
        Save
      </Button>
    </form>
  );
}

function CourierRates({
  courier,
  token,
  reload,
}: {
  courier: Courier;
  token: string;
  reload: () => Promise<void>;
}) {
  const action = useAction();
  const [origin, setOrigin] = useState("");
  const [destination, setDestination] = useState("");
  const [base, setBase] = useState("");
  const [perKg, setPerKg] = useState("");

  return (
    <section className="mb-6">
      <h3 className="flex flex-wrap items-center gap-2 font-semibold">
        {courier.name}
        {courier.is_default ? <Badge tone="ok">Default</Badge> : null}
        {!courier.is_active ? <Badge tone="danger">Inactive</Badge> : null}
      </h3>
      <ul className="mt-2 space-y-1 text-sm">
        {courier.rates.map((rate) => (
          <li key={rate.id} className="flex flex-wrap items-center gap-3">
            <span>
              {rate.origin_city ?? "Any city"} to {rate.destination_city ?? "any city"}:{" "}
              {pkr(rate.base_pkr)} + {pkr(rate.per_kg_pkr)} per kg
            </span>
            <Button
              size="sm"
              variant="ghost"
              disabled={action.busy}
              onClick={() =>
                void action.run(async () => {
                  await adminApi.updateRate(token, rate.id, { is_active: !rate.is_active });
                  await reload();
                })
              }
            >
              {rate.is_active ? "Disable" : "Enable"}
            </Button>
          </li>
        ))}
      </ul>
      <form
        className="mt-3 grid gap-x-3 sm:grid-cols-5 sm:items-end"
        onSubmit={(event) => {
          event.preventDefault();
          void action.run(async () => {
            await adminApi.addRate(token, courier.id, {
              origin_city: origin.trim() || null,
              destination_city: destination.trim() || null,
              base_pkr: Number(base),
              per_kg_pkr: Number(perKg),
            });
            setOrigin("");
            setDestination("");
            setBase("");
            setPerKg("");
            await reload();
          });
        }}
      >
        <Field label="From" htmlFor={`origin-${courier.id}`}>
          <TextInput
            id={`origin-${courier.id}`}
            value={origin}
            onChange={(event) => setOrigin(event.target.value)}
          />
        </Field>
        <Field label="To" htmlFor={`destination-${courier.id}`}>
          <TextInput
            id={`destination-${courier.id}`}
            value={destination}
            onChange={(event) => setDestination(event.target.value)}
          />
        </Field>
        <Field label="Base PKR" htmlFor={`base-${courier.id}`}>
          <TextInput
            id={`base-${courier.id}`}
            type="number"
            min={0}
            required
            value={base}
            onChange={(event) => setBase(event.target.value)}
          />
        </Field>
        <Field label="PKR per kg" htmlFor={`per-kg-${courier.id}`}>
          <TextInput
            id={`per-kg-${courier.id}`}
            type="number"
            min={0}
            required
            value={perKg}
            onChange={(event) => setPerKg(event.target.value)}
          />
        </Field>
        <Button type="submit" variant="secondary" className="mb-4" disabled={action.busy}>
          Add rate
        </Button>
      </form>
      <ActionError message={action.error} />
    </section>
  );
}

function Settings({ session }: { session: Session }) {
  const { token, locale } = session;
  const brands = useResource(useCallback(() => adminApi.brands(token), [token]));
  const couriers = useResource(useCallback(() => adminApi.couriers(token), [token]));

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle as="h2">Commercial terms</CardTitle>
        </CardHeader>
        <CardBody>
          <p className="mb-2 text-sm text-ink-soft">
            New terms apply to new orders. Existing orders keep the rate they were placed at.
          </p>
          <Loaded resource={brands} locale={locale}>
            {(rows) =>
              rows.map((row) => (
                <BrandTerms key={row.brand.id} row={row} token={token} reload={brands.reload} />
              ))
            }
          </Loaded>
        </CardBody>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle as="h2">Couriers and shipping rates</CardTitle>
        </CardHeader>
        <CardBody>
          <Loaded resource={couriers} locale={locale}>
            {(rows) =>
              rows.map((courier) => (
                <CourierRates
                  key={courier.id}
                  courier={courier}
                  token={token}
                  reload={couriers.reload}
                />
              ))
            }
          </Loaded>
        </CardBody>
      </Card>
    </div>
  );
}

export default function AdminSettingsPage() {
  return <AdminPage title="Settings">{(session) => <Settings session={session} />}</AdminPage>;
}
