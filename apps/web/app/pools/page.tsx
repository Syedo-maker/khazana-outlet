"use client";

import Link from "next/link";
import { useCallback, useState } from "react";

import { ActionError, Loaded, PageHeader } from "@/components/Feedback";
import { PoolForm } from "@/components/pools/PoolForm";
import { RoleShell, type Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardBody } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/States";
import { dateTime } from "@/lib/format";
import { useAction, useResource } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { market, type Pool, type PoolLine } from "@/lib/market";

function JoinForm({
  pool,
  session,
  onDone,
}: {
  pool: Pool;
  session: Session;
  onDone: () => Promise<void>;
}) {
  const { token, locale, me } = session;
  const action = useAction();
  const listing = useResource(
    useCallback(() => market.listing(token, pool.item.lot.id), [token, pool.item.lot.id]),
  );
  return (
    <Loaded resource={listing} locale={locale} rows={3}>
      {(detail) => (
        <>
          <PoolForm
            idPrefix={`join-${pool.id}`}
            available={detail.available_lines}
            defaultPhone={me.user.phone}
            locale={locale}
            submitLabel={t(locale, "pools.join")}
            busy={action.busy}
            onSubmit={(membership) =>
              void action.run(async () => {
                await market.joinPool(token, pool.id, membership);
                await onDone();
              })
            }
          />
          <ActionError message={action.error} />
        </>
      )}
    </Loaded>
  );
}

function Lines({ lines }: { lines: PoolLine[] }) {
  return (
    <div className="flex flex-wrap gap-1">
      {lines.map((line) => (
        <Badge key={`${line.size}-${line.color}`}>
          {line.size} {line.color} × {line.pieces}
        </Badge>
      ))}
    </div>
  );
}

function PoolCard({
  pool,
  session,
  reload,
}: {
  pool: Pool;
  session: Session;
  reload: () => Promise<void>;
}) {
  const { token, locale } = session;
  const action = useAction();
  const [joining, setJoining] = useState(false);
  const [placed, setPlaced] = useState(false);

  return (
    <Card>
      <CardBody>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <Link href={`/catalog/${pool.item.lot.id}`} className="font-semibold underline">
            {pool.item.lot.title}
          </Link>
          <span className="text-sm">{t(locale, "pools.covered", { pieces: pool.pieces_covered })}</span>
        </div>
        <p className="mb-2 text-sm text-ink-soft">
          {t(locale, "pools.places", {
            members: pool.members,
            left: pool.places_left,
            date: dateTime(pool.closes_at),
          })}
        </p>
        {pool.shortfall.map((line) => (
          <p key={line} dir="auto" className="text-sm text-warn">
            {line}
          </p>
        ))}
        {pool.uncovered.length > 0 ? (
          <div className="mt-2">
            <p className="mb-1 text-xs font-semibold">{t(locale, "pools.uncovered")}</p>
            <Lines lines={pool.uncovered} />
          </div>
        ) : null}

        {pool.mine ? (
          <div className="mt-3 rounded bg-surface-sunk p-3">
            <p className="mb-1 text-xs font-semibold">{t(locale, "pools.yours")}</p>
            <Lines lines={pool.mine.allocated ?? pool.mine.requested} />
            <div className="mt-3 flex flex-wrap gap-2">
              {pool.mine.is_organiser && pool.meets_minimum ? (
                <Button
                  loading={action.busy}
                  onClick={() =>
                    void action.run(async () => {
                      await market.placePool(token, pool.id);
                      setPlaced(true);
                      await reload();
                    })
                  }
                >
                  {t(locale, "pools.place")}
                </Button>
              ) : null}
              <Button
                variant="ghost"
                loading={action.busy}
                onClick={() =>
                  void action.run(async () => {
                    await market.leavePool(token, pool.id);
                    await reload();
                  })
                }
              >
                {t(locale, "pools.leave")}
              </Button>
            </div>
          </div>
        ) : pool.places_left > 0 ? (
          <div className="mt-3">
            {joining ? (
              <JoinForm pool={pool} session={session} onDone={reload} />
            ) : (
              <Button variant="secondary" onClick={() => setJoining(true)}>
                {t(locale, "pools.join")}
              </Button>
            )}
          </div>
        ) : null}
        {placed ? <p className="mt-2 text-sm text-ok">{t(locale, "pools.ordered")}</p> : null}
        <ActionError message={action.error} />
      </CardBody>
    </Card>
  );
}

function PoolsContent({ session }: { session: Session }) {
  const { token, locale } = session;
  const pools = useResource(useCallback(() => market.pools(token), [token]));
  return (
    <>
      <PageHeader title={t(locale, "pools.title")} subtitle={t(locale, "pools.subtitle")} />
      <Loaded resource={pools} locale={locale}>
        {(items) =>
          items.length === 0 ? (
            <EmptyState title={t(locale, "pools.none")} />
          ) : (
            <ul className="space-y-4">
              {items.map((pool) => (
                <li key={pool.id}>
                  <PoolCard pool={pool} session={session} reload={pools.reload} />
                </li>
              ))}
            </ul>
          )
        }
      </Loaded>
    </>
  );
}

export default function PoolsPage() {
  return (
    <RoleShell allow={["reseller"]}>{(session) => <PoolsContent session={session} />}</RoleShell>
  );
}
