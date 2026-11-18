import Link from "next/link";

import { AuthedImage } from "@/components/AuthedImage";
import { Badge } from "@/components/ui/Card";
import { pkr } from "@/lib/format";
import { type Locale, t } from "@/lib/i18n";
import type { CatalogItem } from "@/lib/market";

export function LotCard({
  item,
  token,
  locale,
}: {
  item: CatalogItem;
  token: string;
  locale: Locale;
}) {
  const { lot } = item;
  return (
    <article className="flex h-full flex-col rounded-lg border border-line bg-surface p-3">
      {item.cover_photo_id ? (
        <AuthedImage
          path={`/catalog/${lot.id}/photos/${item.cover_photo_id}`}
          token={token}
          alt={lot.title}
        />
      ) : (
        <div className="grid aspect-[3/4] place-items-center rounded bg-surface-sunk px-3 text-center text-xs text-ink-faint">
          {t(locale, "catalog.noPhoto")}
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Badge>{t(locale, `grade.short.${lot.condition_grade}`)}</Badge>
        <span className="text-sm font-semibold text-ok">
          {t(locale, "catalog.percentOff", { percent: Math.round(lot.discount_percent) })}
        </span>
      </div>
      <h2 className="mt-2 text-base font-semibold">
        <Link href={`/catalog/${lot.id}`} className="underline decoration-line hover:decoration-ink">
          {lot.title}
        </Link>
      </h2>
      <p className="mt-1 text-sm text-ink-soft">{item.brand_name}</p>
      <p className="mt-auto pt-2 text-sm">
        <span className="font-semibold">{pkr(lot.price_per_piece_pkr)}</span>{" "}
        {t(locale, "catalog.perPiece")}
      </p>
      <p className="text-xs text-ink-faint">
        {t(locale, "catalog.availableIn", { count: lot.available_pieces, city: lot.stock_city })}
      </p>
    </article>
  );
}
