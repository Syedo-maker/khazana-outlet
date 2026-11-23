"use client";

import { useCallback, useState } from "react";

import { ActionError } from "@/components/Feedback";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { useAction, useResource } from "@/lib/hooks";
import { t, type Locale } from "@/lib/i18n";
import { market } from "@/lib/market";

/**
 * Partners who could use a lot that will not sell: tailors, artisans, NGOs
 * and recyclers. The brand offers; Khazana Outlet arranges the handover.
 */
export function RedirectCard({
  lotId,
  token,
  locale,
}: {
  lotId: string;
  token: string;
  locale: Locale;
}) {
  const action = useAction();
  const [open, setOpen] = useState(false);
  const [offered, setOffered] = useState<string | null>(null);
  const matches = useResource(
    useCallback(
      () => (open ? market.partnerMatches(token, lotId) : Promise.resolve([])),
      [open, token, lotId],
    ),
  );

  const offer = (partnerId: string, name: string) =>
    void action.run(async () => {
      await market.offerToPartner(token, lotId, { partner_id: partnerId, route: "donation" });
      setOffered(name);
    });

  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle as="h2">{t(locale, "redirect.title")}</CardTitle>
      </CardHeader>
      <CardBody>
        <p className="mb-3 text-sm text-ink-soft">{t(locale, "redirect.explain")}</p>
        {offered ? (
          <p className="text-sm font-semibold text-ok">
            {t(locale, "redirect.offered", { name: offered })}
          </p>
        ) : !open ? (
          <Button variant="secondary" onClick={() => setOpen(true)}>
            {t(locale, "redirect.find")}
          </Button>
        ) : (matches.data ?? []).length === 0 ? (
          <p className="text-sm text-ink-soft">{t(locale, "redirect.none")}</p>
        ) : (
          <ul className="divide-y divide-line">
            {(matches.data ?? []).map((match) => (
              <li key={match.partner_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <div>
                  <p className="font-semibold">{match.name}</p>
                  <p className="text-sm text-ink-soft">
                    {t(locale, `redirect.kind.${match.kind}`)} · {match.city}
                  </p>
                  {match.reasons.length > 0 ? (
                    <p className="text-xs text-ink-faint">{match.reasons.join(". ")}</p>
                  ) : null}
                </div>
                <Button
                  size="sm"
                  loading={action.busy}
                  onClick={() => offer(match.partner_id, match.name)}
                >
                  {t(locale, "redirect.donate")}
                </Button>
              </li>
            ))}
          </ul>
        )}
        <ActionError message={action.error} />
      </CardBody>
    </Card>
  );
}
