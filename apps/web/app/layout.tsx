import type { Metadata, Viewport } from "next";

import { DEFAULT_LOCALE, directionFor, t } from "@/lib/i18n";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Khazana Outlet",
    template: "%s | Khazana Outlet",
  },
  description:
    "A controlled channel for Pakistani brands to clear surplus and previous " +
    "season stock in bulk, and for verified resellers to buy original branded " +
    "stock at wholesale prices.",
  robots: {
    // Private until launch. Phase 6 turns this on for the public storefront.
    index: false,
    follow: false,
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#14402f",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const locale = DEFAULT_LOCALE;

  return (
    <html lang={locale === "ur" ? "ur" : "en"} dir={directionFor(locale)}>
      <body className="min-h-screen">
        {/* First focusable element on the page, so a keyboard user does not
            have to tab through the whole header to reach the content. */}
        <a href="#main" className="skip-link">
          {t(locale, "nav.skip")}
        </a>
        {children}
      </body>
    </html>
  );
}
