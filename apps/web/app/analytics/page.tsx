"use client";

import { useCallback } from "react";

import { Loaded, PageHeader } from "@/components/Feedback";
import { RoleShell, type Session } from "@/components/RoleShell";
import { Card, CardBody, CardHeader, CardTitle, Stat } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/States";
import { pkr } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { market, type BrandAnalytics, type BrandImpact } from "@/lib/market";

function Bars({ rows, label }: { rows: { name: string; pieces: number }[]; label: string }) {
  const top = Math.max(1, ...rows.map((row) => row.pieces));
  return (
    <ul className="space-y-2 text-sm" aria-label={label}>
      {rows.map((row) => (
        <li key={row.name}>
          <div className="flex justify-between">
            <span>{row.name}</span>
            <span className="text-ink-soft">{row.pieces}</span>
          </div>
          <div className="h-2 rounded bg-surface-sunk">
            <div
              className="h-2 rounded bg-brand"
              style={{ width: `${Math.round((row.pieces / top) * 100)}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

function Report({
  sales,
  impact,
  session,
}: {
  sales: BrandAnalytics;
  impact: BrandImpact;
  session: Session;
}) {
  const { locale } = session;
  return (
    <div className="space-y-6">
      <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label={t(locale, "analytics.goods")} value={pkr(sales.goods_pkr)} />
        <Stat label={t(locale, "analytics.payout")} value={pkr(sales.payout_pkr)} />
        <Stat label={t(locale, "analytics.pieces")} value={String(sales.pieces)} />
        <Stat
          label={t(locale, "analytics.avgPrice")}
          value={pkr(sales.average_price_per_piece_pkr)}
          note={t(locale, "analytics.avgDiscount", { percent: sales.average_discount_percent })}
        />
      </dl>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle as="h2">{t(locale, "analytics.byCity")}</CardTitle>
          </CardHeader>
          <CardBody>
            <Bars
              label={t(locale, "analytics.byCity")}
              rows={sales.by_city.map((row) => ({ name: row.city, pieces: row.pieces }))}
            />
          </CardBody>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle as="h2">{t(locale, "analytics.byCategory")}</CardTitle>
          </CardHeader>
          <CardBody>
            <Bars
              label={t(locale, "analytics.byCategory")}
              rows={sales.by_category.map((row) => ({ name: row.category, pieces: row.pieces }))}
            />
          </CardBody>
        </Card>
      </div>
      <Card>
        <CardHeader>
          <CardTitle as="h2">{t(locale, "analytics.impact")}</CardTitle>
        </CardHeader>
        <CardBody>
          <dl className="mb-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat
              label={t(locale, "analytics.keptFromWaste")}
              value={String(impact.sold.pieces + impact.second_life.pieces)}
            />
            <Stat label={t(locale, "analytics.kg")} value={`${impact.sold.kg + impact.second_life.kg}`} />
            <Stat
              label={t(locale, "analytics.water")}
              value={(impact.sold.water_litres + impact.second_life.water_litres).toLocaleString("en-PK")}
            />
            <Stat
              label={t(locale, "analytics.co2")}
              value={`${Math.round(impact.sold.co2_kg + impact.second_life.co2_kg)}`}
            />
          </dl>
          <p className="text-xs text-ink-faint">{impact.assumption}</p>
        </CardBody>
      </Card>
    </div>
  );
}

function AnalyticsContent({ session }: { session: Session }) {
  const { token, locale, me } = session;
  const brandId = me.brand_ids[0] ?? "";
  const both = useResource(
    useCallback(
      () =>
        Promise.all([market.brandAnalytics(token, brandId), market.brandImpact(token, brandId)]),
      [token, brandId],
    ),
  );
  return (
    <>
      <PageHeader title={t(locale, "analytics.title")} subtitle={t(locale, "analytics.subtitle")} />
      {brandId ? (
        <Loaded resource={both} locale={locale}>
          {([sales, impact]) => <Report sales={sales} impact={impact} session={session} />}
        </Loaded>
      ) : (
        <EmptyState title={t(locale, "insights.noBrand")} />
      )}
    </>
  );
}

export default function AnalyticsPage() {
  return (
    <RoleShell allow={["brand"]}>{(session) => <AnalyticsContent session={session} />}</RoleShell>
  );
}
