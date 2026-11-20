"use client";

import { useCallback } from "react";

import { LotCard } from "@/components/LotCard";
import { type Session } from "@/components/RoleShell";
import { useResource } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { market } from "@/lib/market";

/** Up to four lots picked for this buyer, each with the reason it was picked. */
export function Recommendations({ session }: { session: Session }) {
  const { token, locale } = session;
  const picks = useResource(useCallback(() => market.recommendations(token), [token]));
  const items = (picks.data ?? []).slice(0, 4);
  if (items.length === 0) return null;
  return (
    <section aria-labelledby="for-you" className="mb-8">
      <h2 id="for-you" className="mb-3 text-lg font-semibold">
        {t(locale, "recommend.title")}
      </h2>
      <ul className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {items.map((item) => (
          <li key={item.lot.id} className="flex flex-col gap-2">
            <LotCard item={item} token={token} locale={locale} />
            {item.reasons[0] ? (
              <p className="text-xs text-ink-soft">{item.reasons[0]}</p>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
