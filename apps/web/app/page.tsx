"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Skeleton } from "@/components/ui/States";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { clearTokens, getAccessToken } from "@/lib/session";

const HOME_BY_ROLE = { reseller: "/catalog", brand: "/dashboard", admin: "/admin" };

/** Sends a signed in person to their own starting point. */
export default function HomePage() {
  const locale = useLocale();
  const [signedOut, setSignedOut] = useState(false);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      setSignedOut(true);
      return;
    }
    api
      .me(token)
      .then((me) => window.location.replace(HOME_BY_ROLE[me.user.role]))
      .catch(() => {
        clearTokens();
        setSignedOut(true);
      });
  }, []);

  return (
    <AppShell locale={locale}>
      {signedOut ? (
        <section className="max-w-prose py-12">
          <h1 className="text-3xl font-semibold tracking-tight">{t(locale, "home.title")}</h1>
          <p className="mt-3 text-ink-soft">{t(locale, "home.body")}</p>
          <Link
            href="/login"
            className="mt-6 inline-flex min-h-touch items-center rounded bg-brand px-4 text-sm font-semibold text-white hover:bg-brand-hover"
          >
            {t(locale, "login.title")}
          </Link>
        </section>
      ) : (
        <Skeleton rows={3} />
      )}
    </AppShell>
  );
}
