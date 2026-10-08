"use client";

import { useRef, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Field, TextInput } from "@/components/ui/Field";
import { ApiError, api } from "@/lib/api";
import { DEFAULT_LOCALE, t } from "@/lib/i18n";
import { saveTokens } from "@/lib/session";

type Step = "phone" | "code";

/**
 * Phone OTP sign in.
 *
 * Two steps on one route rather than two pages, so a mistyped number is one
 * tap to fix instead of a back navigation that loses the entered code.
 *
 * The validation here mirrors the server rule exactly, 11 digits starting 03,
 * because an error the user can see before the request is a better experience
 * than a round trip, and the server still checks it regardless.
 */
export default function LoginPage() {
  const locale = DEFAULT_LOCALE;
  const [step, setStep] = useState<Step>("phone");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [devCode, setDevCode] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const codeInput = useRef<HTMLInputElement>(null);

  const normalise = (raw: string) => raw.replace(/\D/g, "");

  const sendCode = async () => {
    const digits = normalise(phone);
    if (digits.length !== 11 || !digits.startsWith("03")) {
      setFieldError(t(locale, "login.phoneHint"));
      return;
    }

    setFieldError(null);
    setFormError(null);
    setBusy(true);
    try {
      const result = await api.requestOtp(digits);
      setDevCode(result.dev_code);
      setStep("code");
      // Move focus to the code box so a keyboard or screen reader user is not
      // left on a button that has just disappeared.
      requestAnimationFrame(() => codeInput.current?.focus());
    } catch (cause) {
      setFormError(cause instanceof Error ? cause.message : t(locale, "error.network"));
    } finally {
      setBusy(false);
    }
  };

  const verify = async () => {
    const digits = normalise(code);
    if (digits.length < 4) {
      setFieldError(t(locale, "error.required"));
      return;
    }

    setFieldError(null);
    setFormError(null);
    setBusy(true);
    try {
      const pair = await api.verifyOtp(normalise(phone), digits);
      saveTokens(pair);
      window.location.href = "/";
    } catch (cause) {
      if (cause instanceof ApiError) {
        setFieldError(cause.message);
      } else {
        setFormError(t(locale, "error.network"));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <AppShell locale={locale}>
      <div className="mx-auto max-w-md">
        <Card>
          <CardHeader>
            <CardTitle as="h2">{t(locale, "login.title")}</CardTitle>
          </CardHeader>
          <CardBody>
            {step === "phone" ? (
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void sendCode();
                }}
              >
                <p className="mb-4 text-sm text-ink-soft">{t(locale, "login.intro")}</p>

                <Field
                  label={t(locale, "login.phone")}
                  htmlFor="phone"
                  hint={t(locale, "login.phoneHint")}
                  error={fieldError}
                >
                  <TextInput
                    id="phone"
                    name="phone"
                    type="tel"
                    inputMode="numeric"
                    autoComplete="tel"
                    placeholder="03001234567"
                    value={phone}
                    hasHint
                    hasError={Boolean(fieldError)}
                    onChange={(event) => setPhone(event.target.value)}
                    required
                  />
                </Field>

                {formError ? (
                  <p role="alert" className="mb-3 text-sm font-semibold text-danger">
                    {formError}
                  </p>
                ) : null}

                <Button type="submit" loading={busy} className="w-full">
                  {t(locale, "login.sendCode")}
                </Button>
              </form>
            ) : (
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void verify();
                }}
              >
                <p className="mb-2 text-sm text-ink-soft">
                  {t(locale, "login.codeSent", { phone: normalise(phone) })}
                </p>

                {devCode ? (
                  // Only present when the API is running with the development
                  // echo on, which production refuses to boot with.
                  <p className="mb-4 rounded border border-accent bg-accent-subtle px-3 py-2 text-sm font-semibold text-accent">
                    {t(locale, "login.devCode", { code: devCode })}
                  </p>
                ) : null}

                <Field label={t(locale, "login.code")} htmlFor="code" error={fieldError}>
                  <TextInput
                    id="code"
                    ref={codeInput}
                    name="code"
                    type="text"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={6}
                    value={code}
                    hasError={Boolean(fieldError)}
                    onChange={(event) => setCode(event.target.value)}
                    required
                  />
                </Field>

                {formError ? (
                  <p role="alert" className="mb-3 text-sm font-semibold text-danger">
                    {formError}
                  </p>
                ) : null}

                <Button type="submit" loading={busy} className="w-full">
                  {t(locale, "login.verify")}
                </Button>

                <Button
                  variant="ghost"
                  className="mt-2 w-full"
                  onClick={() => {
                    setStep("phone");
                    setCode("");
                    setDevCode(null);
                    setFieldError(null);
                  }}
                >
                  {t(locale, "login.changeNumber")}
                </Button>
              </form>
            )}
          </CardBody>
        </Card>
      </div>
    </AppShell>
  );
}
