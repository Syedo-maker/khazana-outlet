"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { ActionError, Loaded, PageHeader } from "@/components/Feedback";
import { RoleShell, type Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Field, TextInput } from "@/components/ui/Field";
import { useAction, useResource } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { market, type ResellerProfile } from "@/lib/market";

function ProfileForm({
  profile,
  session,
  onSaved,
}: {
  profile: ResellerProfile | null;
  session: Session;
  onSaved: () => Promise<void>;
}) {
  const { token, locale } = session;
  const action = useAction();
  const [businessName, setBusinessName] = useState("");
  const [city, setCity] = useState("");
  const [ntn, setNtn] = useState("");
  const [address, setAddress] = useState("");

  useEffect(() => {
    setBusinessName(profile?.business_name ?? "");
    setCity(profile?.city ?? "");
    setNtn(profile?.ntn ?? "");
    setAddress(profile?.shop_address ?? "");
  }, [profile]);

  const save = (event: FormEvent) => {
    event.preventDefault();
    void action.run(async () => {
      await market.saveResellerProfile(token, {
        business_name: businessName,
        city,
        ntn: ntn || null,
        shop_address: address || null,
      });
      await onSaved();
    });
  };

  return (
    <form onSubmit={save} className="max-w-prose">
      <Field label={t(locale, "account.business")} htmlFor="business">
        <TextInput
          id="business"
          required
          minLength={2}
          value={businessName}
          onChange={(event) => setBusinessName(event.target.value)}
        />
      </Field>
      <Field label={t(locale, "account.city")} htmlFor="city">
        <TextInput
          id="city"
          required
          minLength={2}
          value={city}
          onChange={(event) => setCity(event.target.value)}
        />
      </Field>
      <Field label={t(locale, "account.ntn")} htmlFor="ntn">
        <TextInput id="ntn" value={ntn} onChange={(event) => setNtn(event.target.value)} />
      </Field>
      <Field label={t(locale, "account.address")} htmlFor="address">
        <TextInput
          id="address"
          value={address}
          onChange={(event) => setAddress(event.target.value)}
        />
      </Field>
      <Button type="submit" loading={action.busy}>
        {t(locale, "account.save")}
      </Button>
      <ActionError message={action.error} />
    </form>
  );
}

function AccountContent({ session }: { session: Session }) {
  const { token, locale } = session;
  const profile = useResource(useCallback(() => market.resellerProfile(token), [token]));

  return (
    <>
      <PageHeader title={t(locale, "account.title")} subtitle={t(locale, "account.subtitle")} />
      <Card>
        <CardHeader>
          <CardTitle as="h2">{t(locale, "account.profile")}</CardTitle>
        </CardHeader>
        <CardBody>
          {profile.error || profile.loading ? (
            <Loaded resource={profile} locale={locale}>
              {() => null}
            </Loaded>
          ) : (
            <>
              {profile.data ? (
                <p className="mb-4 flex flex-wrap items-center gap-2 text-sm">
                  <Badge tone={profile.data.status === "verified" ? "ok" : "warn"}>
                    {t(locale, `verification.${profile.data.status}`)}
                  </Badge>
                  {profile.data.review_note}
                </p>
              ) : null}
              <ProfileForm profile={profile.data} session={session} onSaved={profile.reload} />
            </>
          )}
        </CardBody>
      </Card>
    </>
  );
}

export default function AccountPage() {
  return (
    <RoleShell allow={["reseller"]}>{(session) => <AccountContent session={session} />}</RoleShell>
  );
}
