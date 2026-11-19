"use client";

import Link from "next/link";
import { useCallback, useState, type FormEvent } from "react";

import { ActionError, Loaded, PageHeader } from "@/components/Feedback";
import { RoleShell, type Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardBody, CardHeader, CardTitle, Stat } from "@/components/ui/Card";
import { Field, SelectInput, TextInput } from "@/components/ui/Field";
import { pkr } from "@/lib/format";
import { useAction, useResource } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { market, type BrandDashboard } from "@/lib/market";

function RegisterBrand({ session }: { session: Session }) {
  const { token, locale } = session;
  const action = useAction();
  const [name, setName] = useState("");
  const [city, setCity] = useState("");
  const [ntn, setNtn] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void action
      .run(() => market.registerBrand(token, { name, city, ntn: ntn || undefined }))
      .then((done) => {
        if (done) window.location.reload();
      });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle as="h2">{t(locale, "brand.register")}</CardTitle>
      </CardHeader>
      <CardBody>
        <form onSubmit={submit} className="max-w-prose">
          <Field label={t(locale, "brand.name")} htmlFor="brand-name">
            <TextInput
              id="brand-name"
              required
              minLength={2}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </Field>
          <Field label={t(locale, "account.city")} htmlFor="brand-city">
            <TextInput
              id="brand-city"
              required
              minLength={2}
              value={city}
              onChange={(event) => setCity(event.target.value)}
            />
          </Field>
          <Field label={t(locale, "account.ntn")} htmlFor="brand-ntn">
            <TextInput
              id="brand-ntn"
              value={ntn}
              onChange={(event) => setNtn(event.target.value)}
            />
          </Field>
          <Button type="submit" loading={action.busy}>
            {t(locale, "brand.create")}
          </Button>
          <ActionError message={action.error} />
        </form>
      </CardBody>
    </Card>
  );
}

function Verification({
  view,
  session,
  reload,
}: {
  view: BrandDashboard;
  session: Session;
  reload: () => Promise<void>;
}) {
  const { token, locale } = session;
  const action = useAction();
  const [docType, setDocType] = useState(view.documents_missing[0] ?? "ntn");

  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle as="h2">{t(locale, "brand.verification")}</CardTitle>
      </CardHeader>
      <CardBody>
        <p className="flex flex-wrap items-center gap-2 text-sm">
          <Badge tone={view.is_verified ? "ok" : "warn"}>
            {t(locale, `verification.${view.brand.status}`)}
          </Badge>
          {view.brand.review_note}
        </p>
        {!view.is_verified ? (
          <>
            {view.documents_missing.length > 0 ? (
              <p className="mt-3 text-sm">
                {t(locale, "brand.missing", { documents: view.documents_missing.join(", ") })}
              </p>
            ) : null}
            <div className="mt-3 flex flex-wrap items-end gap-3">
              <div className="w-48">
                <Field label={t(locale, "brand.documentType")} htmlFor="doc-type">
                  <SelectInput
                    id="doc-type"
                    value={docType}
                    onChange={(event) => setDocType(event.target.value)}
                  >
                    {["ntn", "incorporation", "cnic", "bank_letter", "sales_tax", "other"].map(
                      (type) => (
                        <option key={type} value={type}>
                          {type.replace("_", " ")}
                        </option>
                      ),
                    )}
                  </SelectInput>
                </Field>
              </div>
              <label className="mb-4 inline-flex min-h-touch cursor-pointer items-center text-sm font-semibold text-accent underline">
                {t(locale, "brand.upload")}
                <input
                  type="file"
                  className="sr-only"
                  accept="application/pdf,image/jpeg,image/png"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.target.value = "";
                    if (!file) return;
                    void action.run(async () => {
                      await market.uploadDocument(token, view.brand.id, docType, file);
                      await reload();
                    });
                  }}
                />
              </label>
            </div>
            <Button
              disabled={action.busy || !view.can_request_verification}
              onClick={() =>
                void action.run(async () => {
                  await market.requestVerification(token, view.brand.id);
                  await reload();
                })
              }
            >
              {t(locale, "brand.requestReview")}
            </Button>
          </>
        ) : null}
        <ActionError message={action.error} />
      </CardBody>
    </Card>
  );
}

function SellingSettings({
  view,
  session,
  reload,
}: {
  view: BrandDashboard;
  session: Session;
  reload: () => Promise<void>;
}) {
  const { token, locale } = session;
  const action = useAction();
  const [label, setLabel] = useState(view.brand.unbranded_label ?? "");

  const toggle = (key: "allow_cod" | "allow_part_lot_orders", value: boolean) =>
    void action.run(async () => {
      await market.updatePolicy(token, view.brand.id, { [key]: value });
      await reload();
    });

  return (
    <Card>
      <CardHeader>
        <CardTitle as="h2">{t(locale, "brand.settings")}</CardTitle>
      </CardHeader>
      <CardBody>
        <p className="mb-3 text-sm text-ink-soft">
          {t(locale, "brand.terms", {
            commission: view.policy.commission_percent,
            days: view.policy.payout_terms_days,
          })}
        </p>
        <label className="flex min-h-touch items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={view.policy.allow_part_lot_orders}
            disabled={action.busy}
            onChange={(event) => toggle("allow_part_lot_orders", event.target.checked)}
          />
          {t(locale, "brand.allowPart")}
        </label>
        <label className="flex min-h-touch items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={view.policy.allow_cod}
            disabled={action.busy}
            onChange={(event) => toggle("allow_cod", event.target.checked)}
          />
          {t(locale, "brand.allowCod")}
        </label>
        <form
          className="mt-4 max-w-prose"
          onSubmit={(event) => {
            event.preventDefault();
            void action.run(async () => {
              await market.setUnbrandedLabel(token, view.brand.id, label);
              await reload();
            });
          }}
        >
          <Field
            label={t(locale, "brand.label")}
            htmlFor="unbranded-label"
            hint={t(locale, "brand.labelHint")}
          >
            <TextInput
              id="unbranded-label"
              hasHint
              required
              minLength={3}
              value={label}
              onChange={(event) => setLabel(event.target.value)}
            />
          </Field>
          <Button type="submit" variant="secondary" disabled={action.busy}>
            {t(locale, "account.save")}
          </Button>
        </form>
        <ActionError message={action.error} />
      </CardBody>
    </Card>
  );
}

function BrandHome({ session, brandId }: { session: Session; brandId: string }) {
  const { token, locale } = session;
  const dashboard = useResource(
    useCallback(() => market.brandDashboard(token, brandId), [token, brandId]),
  );

  return (
    <Loaded resource={dashboard} locale={locale}>
      {(view) => (
        <>
          <PageHeader
            title={view.brand.name}
            subtitle={view.brand.city}
            action={
              <Link
                href="/lots/new"
                className="inline-flex min-h-touch items-center rounded bg-brand px-4 text-sm font-semibold text-white hover:bg-brand-hover"
              >
                {t(locale, "lots.new")}
              </Link>
            }
          />
          <dl className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-3">
            <Stat label={t(locale, "brand.liveLots")} value={String(view.live_lots)} />
            <Stat label={t(locale, "brand.ordersMonth")} value={String(view.orders_this_month)} />
            <Stat label={t(locale, "brand.awaitingPayout")} value={pkr(view.awaiting_payout_pkr)} />
          </dl>
          <Verification view={view} session={session} reload={dashboard.reload} />
          <SellingSettings
            key={view.brand.unbranded_label ?? ""}
            view={view}
            session={session}
            reload={dashboard.reload}
          />
        </>
      )}
    </Loaded>
  );
}

function DashboardContent({ session }: { session: Session }) {
  const brandId = session.me.brand_ids[0];
  if (brandId) return <BrandHome session={session} brandId={brandId} />;
  return (
    <>
      <PageHeader title={t(session.locale, "nav.dashboard")} />
      <RegisterBrand session={session} />
    </>
  );
}

export default function DashboardPage() {
  return (
    <RoleShell allow={["brand", "reseller"]}>
      {(session) => <DashboardContent session={session} />}
    </RoleShell>
  );
}
