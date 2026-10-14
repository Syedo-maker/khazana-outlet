"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AppShell, BRAND_NAV } from "@/components/AppShell";
import { Badge, Card, CardBody } from "@/components/ui/Card";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";
import { ApiError, catalog, type Lot, type LotStatus } from "@/lib/api";
import { DEFAULT_LOCALE, type Locale, t } from "@/lib/i18n";
import { getAccessToken } from "@/lib/session";

/** Status to badge tone. Never the only signal: the label always says it too. */
const TONES: Record<LotStatus, "neutral" | "ok" | "warn" | "danger" | "accent"> = {
  draft: "neutral",
  pending_approval: "warn",
  approved: "accent",
  live: "ok",
  paused: "warn",
  sold: "neutral",
  withdrawn: "neutral",
  expired: "danger",
};

function pkr(amount: number): string {
  // Grouping only, no currency symbol glyph: "PKR" reads unambiguously in all
  // three locales and avoids a symbol that renders inconsistently on Android.
  return `${amount.toLocaleString("en-PK")} PKR`;
}

/**
 * The brand's own lots.
 *
 * The one judgement worth stating: the manifest warning is shown on the list
 * rather than only inside the editor. A brand with twenty drafts needs to see
 * which one is blocking from here, not after opening each.
 */
export default function LotsPage() {
  const locale: Locale = DEFAULT_LOCALE;
  const [lots, setLots] = useState<Lot[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    const token = getAccessToken();
    if (!token) {
      setError(t(locale, "error.network"));
      return;
    }
    try {
      const body = await catalog.listLots(token);
      setLots(body.items);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not load your lots.");
    }
  }, [locale]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <AppShell nav={BRAND_NAV} locale={locale}>
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">{t(locale, "lots.title")}</h1>
        <p className="mt-1 text-sm text-ink-soft">{t(locale, "lots.subtitle")}</p>
      </header>

      {error ? (
        <ErrorState
          title={t(locale, "state.errorTitle")}
          message={error}
          onRetry={() => void load()}
          retryLabel={t(locale, "state.retry")}
        />
      ) : lots === null ? (
        <Skeleton rows={4} />
      ) : lots.length === 0 ? (
        <EmptyState
          title={t(locale, "state.emptyTitle")}
          description={t(locale, "lots.empty")}
        />
      ) : (
        <ul className="space-y-3">
          {lots.map((lot) => (
            <li key={lot.id}>
              <Card>
                <CardBody className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={TONES[lot.status]}>{t(locale, `status.${lot.status}`)}</Badge>
                      <span className="font-mono text-xs text-ink-faint">{lot.lot_code}</span>
                      {lot.is_manifest_balanced ? null : (
                        <Badge tone="danger">{t(locale, "lots.manifestShort")}</Badge>
                      )}
                    </div>
                    <h2 className="mt-1 truncate text-base font-semibold">
                      <Link
                        href={`/lots/${lot.id}`}
                        className="underline decoration-line hover:decoration-ink"
                      >
                        {lot.title}
                      </Link>
                    </h2>
                    <p className="mt-1 text-sm text-ink-soft">
                      {lot.total_pieces} {t(locale, "lots.pieces").toLowerCase()}
                      {" · "}
                      {lot.stock_city}
                      {" · "}
                      {t(locale, `visibility.${lot.visibility}`)}
                    </p>
                  </div>

                  <dl className="flex shrink-0 gap-6 text-sm">
                    <div>
                      <dt className="text-xs uppercase tracking-wide text-ink-faint">
                        {t(locale, "lots.price")}
                      </dt>
                      <dd className="font-semibold">{pkr(lot.lot_price_pkr)}</dd>
                    </div>
                    <div>
                      <dt className="text-xs uppercase tracking-wide text-ink-faint">
                        {t(locale, "lots.discount")}
                      </dt>
                      <dd className="font-semibold">{Math.round(lot.discount_percent)}%</dd>
                    </div>
                  </dl>
                </CardBody>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </AppShell>
  );
}
