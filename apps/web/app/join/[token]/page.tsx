"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { AppShell } from "@/components/AppShell";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Field, TextInput } from "@/components/ui/Field";
import { ApiError, api, type InvitePreview } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { useLocale } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { saveTokens } from "@/lib/session";

/**
 * Where an invite link lands. The link itself is the credential, so the page
 * shows whom it is for, asks for the beta terms to be accepted, and signs the
 * person in. A new reseller also gives the shop name and city, which an admin
 * then verifies.
 */
export default function JoinPage() {
  const locale = useLocale();
  const { token } = useParams<{ token: string }>();
  const [invite, setInvite] = useState<InvitePreview | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [name, setName] = useState("");
  const [business, setBusiness] = useState("");
  const [city, setCity] = useState("");
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .invite(token)
      .then((preview) => {
        setInvite(preview);
        setName(preview.full_name ?? "");
      })
      .catch(() => setLoadFailed(true));
  }, [token]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!accepted) {
      setError(t(locale, "join.mustAccept"));
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const pair = await api.acceptInvite(token, {
        accept_terms: true,
        full_name: name || null,
        business_name: business || null,
        city: city || null,
      });
      saveTokens(pair);
      window.location.href = "/";
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : t(locale, "error.network"));
    } finally {
      setBusy(false);
    }
  };

  const signup = invite?.purpose === "signup";
  const reseller = invite?.role === "reseller";

  return (
    <AppShell locale={locale}>
      <div className="mx-auto max-w-md">
        <Card>
          <CardHeader>
            <CardTitle as="h1">
              {invite && !invite.valid
                ? t(locale, "join.invalid")
                : signup
                  ? t(locale, "join.title")
                  : t(locale, "join.signInTitle")}
            </CardTitle>
          </CardHeader>
          <CardBody>
            {loadFailed ? (
              <p role="alert" className="text-sm font-semibold text-danger">
                {t(locale, "error.network")}
              </p>
            ) : invite === null ? (
              <p aria-busy="true" className="text-sm text-ink-soft">
                {t(locale, "state.loading")}
              </p>
            ) : !invite.valid ? (
              <p className="text-sm">{t(locale, "join.invalidBody")}</p>
            ) : (
              <form onSubmit={(event) => void submit(event)} noValidate>
                <p className="mb-1 text-sm">
                  {invite.full_name
                    ? t(locale, "join.for", { name: invite.full_name, phone: invite.phone_hint ?? "" })
                    : t(locale, "join.forPhone", { phone: invite.phone_hint ?? "" })}
                </p>
                <p className="mb-4 text-sm text-ink-soft">
                  {t(locale, "join.expires", { date: dateTime(invite.expires_at) })}
                </p>

                {signup ? (
                  <Field label={t(locale, "join.name")} htmlFor="join-name">
                    <TextInput
                      id="join-name"
                      autoComplete="name"
                      required
                      maxLength={120}
                      value={name}
                      onChange={(event) => setName(event.target.value)}
                    />
                  </Field>
                ) : null}
                {signup && reseller ? (
                  <>
                    <Field
                      label={t(locale, "join.business")}
                      htmlFor="join-business"
                      hint={t(locale, "join.businessHint")}
                    >
                      <TextInput
                        id="join-business"
                        hasHint
                        autoComplete="organization"
                        maxLength={160}
                        value={business}
                        onChange={(event) => setBusiness(event.target.value)}
                      />
                    </Field>
                    <Field label={t(locale, "join.city")} htmlFor="join-city">
                      <TextInput
                        id="join-city"
                        autoComplete="address-level2"
                        maxLength={80}
                        value={city}
                        onChange={(event) => setCity(event.target.value)}
                      />
                    </Field>
                  </>
                ) : null}

                <div className="mb-4 flex items-start gap-2 text-sm">
                  <input
                    id="join-accept"
                    type="checkbox"
                    className="mt-1 h-5 w-5"
                    checked={accepted}
                    onChange={(event) => setAccepted(event.target.checked)}
                  />
                  <label htmlFor="join-accept">
                    {t(locale, "join.accept")}{" "}
                    <Link href="/terms" target="_blank" className="font-semibold text-accent underline">
                      {t(locale, "legal.terms")}
                    </Link>
                    {" · "}
                    <Link
                      href="/privacy"
                      target="_blank"
                      className="font-semibold text-accent underline"
                    >
                      {t(locale, "legal.privacy")}
                    </Link>
                  </label>
                </div>

                {error ? (
                  <p role="alert" className="mb-3 text-sm font-semibold text-danger">
                    {error}
                  </p>
                ) : null}
                <Button type="submit" loading={busy} className="w-full">
                  {t(locale, "join.submit")}
                </Button>
              </form>
            )}
          </CardBody>
        </Card>
      </div>
    </AppShell>
  );
}
