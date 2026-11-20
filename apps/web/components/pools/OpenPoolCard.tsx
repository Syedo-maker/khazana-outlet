"use client";

import { useRouter } from "next/navigation";

import { ActionError } from "@/components/Feedback";
import { PoolForm } from "@/components/pools/PoolForm";
import { type Session } from "@/components/RoleShell";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { useAction } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { market, type CatalogDetail } from "@/lib/market";

/** Start a committee pool on a lot whose brand allows pooled orders. */
export function OpenPoolCard({ detail, session }: { detail: CatalogDetail; session: Session }) {
  const { token, locale, me } = session;
  const router = useRouter();
  const action = useAction();
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle as="h2">{t(locale, "pools.open")}</CardTitle>
      </CardHeader>
      <CardBody>
        <p className="mb-3 text-sm text-ink-soft">{t(locale, "pools.subtitle")}</p>
        <PoolForm
          idPrefix="open-pool"
          available={detail.available_lines}
          defaultPhone={me.user.phone}
          locale={locale}
          submitLabel={t(locale, "pools.open")}
          busy={action.busy}
          onSubmit={(membership) =>
            void action.run(async () => {
              await market.openPool(token, { ...membership, lot_id: detail.lot.id });
              router.push("/pools");
            })
          }
        />
        <ActionError message={action.error} />
      </CardBody>
    </Card>
  );
}
