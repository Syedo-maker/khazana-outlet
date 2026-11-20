"use client";

import Link from "next/link";
import { useCallback } from "react";

import { Loaded, PageHeader } from "@/components/Feedback";
import { RoleShell, type Session } from "@/components/RoleShell";
import { Badge, Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/States";
import { dateTime } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { market, type BrandForecast } from "@/lib/market";

function ForecastView({ data, session }: { data: BrandForecast; session: Session }) {
  const { locale } = session;
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle as="h2">{t(locale, "forecast.atRisk")}</CardTitle>
          </CardHeader>
          <CardBody>
            {data.at_risk.length === 0 ? (
              <p className="text-sm text-ink-soft">{t(locale, "forecast.noneAtRisk")}</p>
            ) : (
              <ul className="divide-y divide-line">
                {data.at_risk.map((item) => (
                  <li key={item.lot_id} className="py-3">
                    <Link href={`/lots/${item.lot_id}`} className="font-semibold underline">
                      {item.title}
                    </Link>{" "}
                    <span className="font-mono text-xs text-ink-faint">{item.lot_code}</span>
                    <p className="text-sm text-ink-soft">{item.reason}</p>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>

        {data.warnings.length > 0 ? (
          <Card>
            <CardHeader>
              <CardTitle as="h2">{t(locale, "forecast.warnings")}</CardTitle>
            </CardHeader>
            <CardBody>
              <ul className="space-y-2 text-sm">
                {data.warnings.map((warning) => (
                  <li key={warning.category} className="rounded bg-accent-subtle px-3 py-2">
                    {warning.message}
                  </li>
                ))}
              </ul>
            </CardBody>
          </Card>
        ) : null}

        <Card>
          <CardHeader>
            <CardTitle as="h2">{t(locale, "forecast.onTrack")}</CardTitle>
          </CardHeader>
          <CardBody>
            <ul className="divide-y divide-line text-sm">
              {data.on_track.map((item) => (
                <li key={item.lot_id} className="flex flex-wrap justify-between gap-2 py-2">
                  <span>
                    {item.title}{" "}
                    <span className="font-mono text-xs text-ink-faint">{item.lot_code}</span>
                  </span>
                  <span className="text-ink-soft">{item.reason}</span>
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
      </div>

      <aside>
        <Card>
          <CardHeader>
            <CardTitle as="h2">{t(locale, "forecast.seasons")}</CardTitle>
          </CardHeader>
          <CardBody>
            <ul className="space-y-3 text-sm">
              {data.upcoming.map((event) => (
                <li key={event.id}>
                  <p className="font-semibold">
                    {event.name} <Badge tone="accent">×{event.demand_factor}</Badge>
                  </p>
                  <p className="text-ink-soft">
                    {t(locale, "forecast.range", { from: event.starts_on, to: event.ends_on })}
                  </p>
                  {event.note ? <p className="text-xs text-ink-faint">{event.note}</p> : null}
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
        {data.computed_at ? (
          <p className="mt-3 text-xs text-ink-faint">
            {t(locale, "forecast.computed", { at: dateTime(data.computed_at) })}
          </p>
        ) : null}
      </aside>
    </div>
  );
}

function ForecastContent({ session }: { session: Session }) {
  const { token, locale, me } = session;
  const brandId = me.brand_ids[0] ?? "";
  const forecast = useResource(
    useCallback(() => market.brandForecast(token, brandId), [token, brandId]),
  );
  return (
    <>
      <PageHeader title={t(locale, "forecast.title")} subtitle={t(locale, "forecast.subtitle")} />
      {brandId ? (
        <Loaded resource={forecast} locale={locale}>
          {(data) =>
            data.computed_at === null ? (
              <EmptyState title={t(locale, "forecast.notYet")} />
            ) : (
              <ForecastView data={data} session={session} />
            )
          }
        </Loaded>
      ) : (
        <EmptyState title={t(locale, "insights.noBrand")} />
      )}
    </>
  );
}

export default function ForecastPage() {
  return (
    <RoleShell allow={["brand"]}>{(session) => <ForecastContent session={session} />}</RoleShell>
  );
}
