"use client";

import { OpenPoolCard } from "@/components/pools/OpenPoolCard";
import { ProfitCard } from "@/components/ProfitCard";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import { AuthedImage } from "@/components/AuthedImage";
import { ActionError, Loaded } from "@/components/Feedback";
import { RoleShell, type Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardBody, CardHeader, CardTitle, Stat } from "@/components/ui/Card";
import { TextInput } from "@/components/ui/Field";
import { pkr } from "@/lib/format";
import { useAction, useResource } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { market, type CatalogDetail } from "@/lib/market";

const lineKey = (size: string, color: string) => `${size}|${color}`;

function PurchaseCard({ detail, session }: { detail: CatalogDetail; session: Session }) {
  const { token, locale, me } = session;
  const router = useRouter();
  const action = useAction();
  const [wholeLot, setWholeLot] = useState(true);
  const [quantities, setQuantities] = useState<Record<string, string>>({});

  const lines = useMemo(
    () =>
      detail.available_lines
        .map((line) => ({
          size: line.size,
          color: line.color,
          pieces: Number(quantities[lineKey(line.size, line.color)] || 0),
        }))
        .filter((line) => line.pieces > 0),
    [detail.available_lines, quantities],
  );
  const chosen = lines.reduce((sum, line) => sum + line.pieces, 0);

  if (me.user.role !== "reseller") {
    return <p className="text-sm text-ink-soft">{t(locale, "listing.resellersOnly")}</p>;
  }

  return (
    <>
      {detail.allows_part_lot ? (
        <fieldset className="mb-4">
          <legend className="text-sm font-semibold">{t(locale, "listing.howMuch")}</legend>
          {[true, false].map((value) => (
            <label key={String(value)} className="mt-2 flex min-h-touch items-center gap-2 text-sm">
              <input
                type="radio"
                name="purchase-kind"
                checked={wholeLot === value}
                onChange={() => setWholeLot(value)}
              />
              {t(locale, value ? "listing.whole" : "listing.part")}
            </label>
          ))}
        </fieldset>
      ) : (
        <p className="mb-4 text-sm text-ink-soft">{t(locale, "listing.wholeOnly")}</p>
      )}

      {!wholeLot ? (
        <div className="mb-4 space-y-2">
          {detail.available_lines.map((line) => {
            const key = lineKey(line.size, line.color);
            return (
              <div key={key} className="grid grid-cols-[1fr_6rem] items-center gap-3 text-sm">
                <label htmlFor={key}>
                  {line.size}, {line.color}{" "}
                  <span className="text-ink-faint">
                    {t(locale, "listing.left", { count: line.pieces })}
                  </span>
                </label>
                <TextInput
                  id={key}
                  type="number"
                  min={0}
                  max={line.pieces}
                  inputMode="numeric"
                  value={quantities[key] ?? ""}
                  onChange={(event) =>
                    setQuantities((current) => ({ ...current, [key]: event.target.value }))
                  }
                />
              </div>
            );
          })}
          <p className="text-sm font-semibold">
            {t(locale, "listing.chosen", { count: chosen })}
          </p>
        </div>
      ) : null}

      <Button
        className="w-full"
        loading={action.busy}
        disabled={!wholeLot && chosen === 0}
        onClick={() =>
          void action
            .run(() => market.setCartItem(token, detail.lot.id, wholeLot, wholeLot ? [] : lines))
            .then((done) => {
              if (done) router.push("/cart");
            })
        }
      >
        {t(locale, "listing.addToCart")}
      </Button>
      <ActionError message={action.error} />
    </>
  );
}

function ListingContent({ session, lotId }: { session: Session; lotId: string }) {
  const { token, locale } = session;
  const listing = useResource(useCallback(() => market.listing(token, lotId), [token, lotId]));

  return (
    <>
      <nav className="mb-4">
        <Link href="/catalog" className="text-sm font-semibold text-accent underline">
          {t(locale, "listing.back")}
        </Link>
      </nav>
      <Loaded resource={listing} locale={locale} rows={6}>
        {(detail) => (
          <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <Badge>{t(locale, `grade.${detail.lot.condition_grade}`)}</Badge>
                <span className="font-mono text-xs text-ink-faint">{detail.lot.lot_code}</span>
              </div>
              <h1 className="mt-2 text-2xl font-semibold tracking-tight">{detail.lot.title}</h1>
              <p className="mt-1 text-sm text-ink-soft">{detail.brand_name}</p>
              {detail.lot.description ? (
                <p className="mt-4 max-w-prose">{detail.lot.description}</p>
              ) : null}

              <dl className="my-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
                <Stat
                  label={t(locale, "lots.perPiece")}
                  value={pkr(detail.lot.price_per_piece_pkr)}
                />
                <Stat
                  label={t(locale, "lots.discount")}
                  value={`${Math.round(detail.lot.discount_percent)}%`}
                />
                <Stat
                  label={t(locale, "listing.available")}
                  value={String(detail.lot.available_pieces)}
                />
                <Stat label={t(locale, "lots.city")} value={detail.lot.stock_city} />
              </dl>

              {detail.photos.length > 0 ? (
                <ul className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-3">
                  {detail.photos.map((photo) => (
                    <li key={photo.id}>
                      <AuthedImage
                        path={`/catalog/${detail.lot.id}/photos/${photo.id}`}
                        token={token}
                        alt={`${detail.lot.title}, ${photo.kind}`}
                      />
                    </li>
                  ))}
                </ul>
              ) : null}

              <Card className="mb-6">
                <CardHeader>
                  <CardTitle as="h2">{t(locale, "manifest.title")}</CardTitle>
                </CardHeader>
                <CardBody>
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className="text-ink-faint">
                        <th className="py-1">{t(locale, "manifest.size")}</th>
                        <th>{t(locale, "manifest.colour")}</th>
                        <th>{t(locale, "manifest.pieces")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detail.manifest_lines.map((line) => (
                        <tr key={lineKey(line.size, line.color)} className="border-t border-line">
                          <td className="py-1">{line.size}</td>
                          <td>{line.color}</td>
                          <td>{line.pieces}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </CardBody>
              </Card>

              {detail.defects.length > 0 ? (
                <Card>
                  <CardHeader>
                    <CardTitle as="h2">{t(locale, "listing.defects")}</CardTitle>
                  </CardHeader>
                  <CardBody>
                    <ul className="list-disc space-y-1 pl-5 text-sm">
                      {detail.defects.map((defect) => (
                        <li key={defect.issue}>
                          {defect.issue} (
                          {t(locale, "listing.piecesAffected", { count: defect.pieces_affected })})
                        </li>
                      ))}
                    </ul>
                  </CardBody>
                </Card>
              ) : null}
            </div>

            <aside>
              <Card>
                <CardHeader>
                  <CardTitle as="h2">{t(locale, "listing.buy")}</CardTitle>
                </CardHeader>
                <CardBody>
                  <p className="mb-3 text-sm">
                    {t(locale, "listing.minimum", { count: detail.lot.min_order_pieces })}
                  </p>
                  <PurchaseCard detail={detail} session={session} />
                </CardBody>
              </Card>
              {session.me.user.role === "reseller" ? (
                <ProfitCard session={session} lotId={lotId} />
              ) : null}
              {session.me.user.role === "reseller" && detail.allows_pooling ? (
                <OpenPoolCard detail={detail} session={session} />
              ) : null}
            </aside>
          </div>
        )}
      </Loaded>
    </>
  );
}

export default function ListingPage() {
  const { id } = useParams<{ id: string }>();
  return <RoleShell>{(session) => <ListingContent session={session} lotId={id} />}</RoleShell>;
}
