"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { type Locale, t } from "@/lib/i18n";

type NavItem = { href: string; labelKey: string };

/**
 * The application frame: header, navigation, main region.
 *
 * Mobile first. The navigation is a horizontally scrolling row on a phone and
 * a inline row from the small breakpoint upward. No hamburger menu for four
 * links, because a menu that hides four items costs a tap and gains nothing.
 */
export function AppShell({
  locale,
  children,
  nav = [],
  onSignOut,
  userLabel,
}: {
  locale: Locale;
  children: ReactNode;
  nav?: NavItem[];
  onSignOut?: () => void;
  userLabel?: string;
}) {
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
            {userLabel ? (
              <span className="hidden text-sm text-ink-soft sm:inline">{userLabel}</span>
            ) : null}
            {onSignOut ? (
              <button
                type="button"
                onClick={onSignOut}
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
  { href: "/orders", labelKey: "nav.orders" },
];
