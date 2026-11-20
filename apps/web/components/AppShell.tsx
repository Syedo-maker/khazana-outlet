"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { api } from "@/lib/api";
import { setLocale } from "@/lib/hooks";
import { LOCALES, type Locale, t } from "@/lib/i18n";
import { clearTokens, getAccessToken } from "@/lib/session";

type NavItem = { href: string; labelKey: string };

const LANGUAGE_NAMES: Record<Locale, string> = {
  en: "English",
  ur: "اردو",
  ur_roman: "Roman Urdu",
};

/**
 * The application frame: header, navigation, main region.
 *
 * Mobile first. The navigation is a horizontally scrolling row on a phone and
 * an inline row from the small breakpoint upward.
 */
export function AppShell({
  locale,
  children,
  nav = [],
  userLabel,
}: {
  locale: Locale;
  children: ReactNode;
  nav?: NavItem[];
  userLabel?: string;
}) {
  const [signedIn, setSignedIn] = useState(false);

  useEffect(() => {
    setSignedIn(Boolean(getAccessToken()));
  }, []);

  const signOut = async () => {
    const token = getAccessToken();
    if (token) {
      try {
        await api.signOut(token);
      } catch {
        // The local sign out below matters more than this request.
      }
    }
    clearTokens();
    window.location.href = "/login";
  };

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-shell items-center justify-between gap-4 px-4 py-3">
          <Link href="/" className="flex items-center gap-2 font-bold tracking-tight">
            <span
              aria-hidden="true"
              className="grid h-7 w-7 place-items-center rounded bg-brand text-xs font-bold text-white"
            >
              KO
            </span>
            <span className="text-lg">{t(locale, "app.name")}</span>
          </Link>

          <div className="flex items-center gap-3">
            <label className="sr-only" htmlFor="language">
              {t(locale, "nav.language")}
            </label>
            <select
              id="language"
              value={locale}
              onChange={(event) => setLocale(event.target.value as Locale)}
              className="min-h-touch rounded border border-line bg-surface px-2 text-sm"
            >
              {LOCALES.map((option) => (
                <option key={option} value={option}>
                  {LANGUAGE_NAMES[option]}
                </option>
              ))}
            </select>
            {userLabel ? (
              <span className="hidden text-sm text-ink-soft sm:inline">{userLabel}</span>
            ) : null}
            {signedIn ? (
              <button
                type="button"
                onClick={() => void signOut()}
                className="min-h-touch rounded px-3 text-sm font-semibold text-ink-soft hover:bg-surface-alt hover:text-ink"
              >
                {t(locale, "nav.signOut")}
              </button>
            ) : null}
          </div>
        </div>

        {nav.length > 0 ? (
          <nav aria-label="Main" className="mx-auto max-w-shell px-4">
            <ul className="-mb-px flex gap-1 overflow-x-auto">
              {nav.map((item) => (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    className="inline-flex min-h-touch items-center whitespace-nowrap border-b-2 border-transparent px-3 text-sm font-semibold text-ink-soft hover:border-line hover:text-ink"
                  >
                    {t(locale, item.labelKey)}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        ) : null}
      </header>

      <main id="main" className="mx-auto w-full max-w-shell flex-1 px-4 py-6">
        {children}
      </main>

      <footer className="border-t border-line bg-surface-alt px-4 py-6 text-sm text-ink-soft">
        <div className="mx-auto max-w-shell">
          <p className="font-semibold">{t(locale, "app.name")}</p>
          <p>{t(locale, "app.tagline")}</p>
        </div>
      </footer>
    </div>
  );
}

export const BRAND_NAV: NavItem[] = [
  { href: "/dashboard", labelKey: "nav.dashboard" },
  { href: "/lots", labelKey: "nav.lots" },
  { href: "/lots/queue", labelKey: "nav.approvals" },
  { href: "/insights", labelKey: "nav.insights" },
  { href: "/forecast", labelKey: "nav.forecast" },
  { href: "/sizes", labelKey: "nav.sizes" },
  { href: "/orders", labelKey: "nav.orders" },
  { href: "/payouts", labelKey: "nav.payouts" },
];

export const RESELLER_NAV: NavItem[] = [
  { href: "/catalog", labelKey: "nav.catalog" },
  { href: "/mixed-lot", labelKey: "nav.mixedLot" },
  { href: "/pools", labelKey: "nav.pools" },
  { href: "/assistant", labelKey: "nav.assistant" },
  { href: "/cart", labelKey: "nav.cart" },
  { href: "/orders", labelKey: "nav.orders" },
  { href: "/account", labelKey: "nav.account" },
];

export const ADMIN_NAV: NavItem[] = [
  { href: "/admin", labelKey: "nav.overview" },
  { href: "/admin/verification", labelKey: "nav.verification" },
  { href: "/admin/listings", labelKey: "nav.listings" },
  { href: "/orders", labelKey: "nav.orders" },
  { href: "/admin/payments", labelKey: "nav.payments" },
  { href: "/admin/disputes", labelKey: "nav.disputes" },
  { href: "/admin/payouts", labelKey: "nav.payouts" },
  { href: "/admin/settings", labelKey: "nav.settings" },
  { href: "/admin/audit", labelKey: "nav.audit" },
];
