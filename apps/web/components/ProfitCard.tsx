"use client";

import { useCallback, useState, type FormEvent } from "react";

import { Loaded } from "@/components/Feedback";
import { type Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Field, TextInput } from "@/components/ui/Field";
import { pkr } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { market } from "@/lib/market";

/**
 * What a lot could make if resold in the buyer's city.
 *
 * Every number comes from the API, which shows its assumptions. The page
 * never computes a profit itself, so the estimate and its explanation can
 * not disagree.
 */
export function ProfitCard({ session, lotId }: { session: Session; lotId: string }) {
  const { token, locale } = session;
  const [price, setPrice] = useState("");
  const [applied, setApplied] = useState<number | undefined>(undefined);

  const estimate = useResource(
    useCallback(
      () => market.profit(token, lotId, { selling_price_pkr: applied }),
      [token, lotId, applied],
    ),
  );

  const apply = (event: FormEvent) => {
    event.preventDefault();
    const value = Number.parseInt(price, 10);
    setApplied(Number.isFinite(value) && value > 0 ? value : undefined);
  };

  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle as="h2">{t(locale, "profit.title")}</CardTitle>
      </CardHeader>
      <CardBody>
        <Loaded resource={estimate} locale={locale} rows={3}>
          {(data) => (
            <>
              <p className="mb-3 text-sm text-ink-soft">
                {t(locale, "profit.cost", {
                  pieces: data.pieces,
                  city: data.city,
                  amount: pkr(data.cost_pkr),
                })}
              </p>
              <table className="mb-3 w-full text-sm">
                <thead>
                  <tr className="text-start text-ink-soft">
                    <th className="py-1 text-start font-normal">{t(locale, "profit.scenario")}</th>
                    <th className="py-1 text-end font-normal">{t(locale, "profit.sellAt")}</th>
                    <th className="py-1 text-end font-normal">{t(locale, "profit.profit")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.scenarios.map((row) => (
                    <tr key={row.name} className="border-t border-line">
                      <td className="py-1">{t(locale, `profit.name.${row.name}`)}</td>
                      <td className="py-1 text-end">{pkr(row.price_per_piece_pkr)}</td>
                      <td
                        className={`py-1 text-end font-semibold ${
                          row.profit_pkr < 0 ? "text-danger" : ""
                        }`}
                      >
                        {pkr(row.profit_pkr)} ({row.margin_percent}%)
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.break_even_pieces ? (
                <p className="mb-3 text-sm">
                  {t(locale, "profit.breakEven", { count: data.break_even_pieces })}
                </p>
              ) : null}
              <details className="mb-3 text-sm">
                <summary className="cursor-pointer font-semibold">
                  {t(locale, "profit.assumptions")}
                </summary>
                <ul className="mt-2 list-disc ps-5 text-ink-soft">
                  {data.assumptions.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </details>
            </>
          )}
        </Loaded>
        <form onSubmit={apply} className="flex items-end gap-2">
          <div className="flex-1">
            <Field label={t(locale, "profit.ownPrice")} htmlFor="own-price">
              <TextInput
                id="own-price"
                inputMode="numeric"
                value={price}
                onChange={(event) => setPrice(event.target.value)}
              />
            </Field>
          </div>
          <Button type="submit" variant="secondary" className="mb-4">
            {t(locale, "profit.recalculate")}
          </Button>
        </form>
        <p className="text-xs text-ink-faint">{t(locale, "profit.notPromise")}</p>
      </CardBody>
    </Card>
  );
}
