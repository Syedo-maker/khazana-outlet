"use client";

import { useCallback, useState, type FormEvent } from "react";

import { ActionError, Loaded, PageHeader } from "@/components/Feedback";
import { RoleShell, type Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Card, CardBody } from "@/components/ui/Card";
import { useAction, useResource } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { market, type SizeRow } from "@/lib/market";

const FIELDS = [
  "chest_min_cm",
  "chest_max_cm",
  "waist_min_cm",
  "waist_max_cm",
  "hip_min_cm",
  "hip_max_cm",
] as const;

type Draft = Record<"audience" | "label" | (typeof FIELDS)[number], string>;

function toDraft(row: SizeRow): Draft {
  const draft = { audience: row.audience, label: row.label } as Draft;
  for (const field of FIELDS) draft[field] = row[field] === null ? "" : String(row[field]);
  return draft;
}

function ChartEditor({
  session,
  brandId,
  rows,
  reload,
}: {
  session: Session;
  brandId: string;
  rows: SizeRow[];
  reload: () => Promise<void>;
}) {
  const { token, locale } = session;
  const action = useAction();
  const [drafts, setDrafts] = useState<Draft[]>(() => rows.map(toDraft));

  const update = (index: number, field: keyof Draft, value: string) =>
    setDrafts((current) =>
      current.map((draft, i) => (i === index ? { ...draft, [field]: value } : draft)),
    );

  const save = (event: FormEvent) => {
    event.preventDefault();
    const body = drafts
      .filter((draft) => draft.label.trim())
      .map((draft) => {
        const row: Record<string, string | number | null> = {
          audience: draft.audience,
          label: draft.label.trim(),
        };
        for (const field of FIELDS) row[field] = draft[field] === "" ? null : Number(draft[field]);
        return row;
      });
    void action.run(async () => {
      await market.saveSizeChart(token, brandId, body);
      await reload();
    });
  };

  return (
    <form onSubmit={save}>
      <div className="relative overflow-x-auto">
        <table className="w-full min-w-[44rem] text-sm">
          <thead>
            <tr className="text-ink-soft">
              <th className="p-1 text-start font-normal">{t(locale, "sizes.audience")}</th>
              <th className="p-1 text-start font-normal">{t(locale, "sizes.label")}</th>
              {FIELDS.map((field) => (
                <th key={field} className="p-1 text-start font-normal">
                  {t(locale, `sizes.${field}`)}
                </th>
              ))}
              <th className="p-1 text-start font-normal">{t(locale, "sizes.standard")}</th>
            </tr>
          </thead>
          <tbody>
            {drafts.map((draft, index) => (
              <tr key={index} className="border-t border-line">
                <td className="p-1">
                  <select
                    aria-label={t(locale, "sizes.audience")}
                    className="rounded border border-line bg-surface px-2 py-1"
                    value={draft.audience}
                    onChange={(event) => update(index, "audience", event.target.value)}
                  >
                    {["women", "men", "kids", "unisex"].map((value) => (
                      <option key={value} value={value}>
                        {t(locale, `sizes.audience.${value}`)}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="p-1">
                  <input
                    aria-label={t(locale, "sizes.label")}
                    className="w-16 rounded border border-line bg-surface px-2 py-1"
                    value={draft.label}
                    onChange={(event) => update(index, "label", event.target.value)}
                  />
                </td>
                {FIELDS.map((field) => (
                  <td key={field} className="p-1">
                    <input
                      aria-label={t(locale, `sizes.${field}`)}
                      inputMode="decimal"
                      className="w-16 rounded border border-line bg-surface px-2 py-1"
                      value={draft[field]}
                      onChange={(event) => update(index, field, event.target.value)}
                    />
                  </td>
                ))}
                <td className="p-1 font-semibold">{rows[index]?.standard ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex gap-2">
        <Button
          variant="secondary"
          onClick={() =>
            setDrafts((current) => [
              ...current,
              {
                audience: current.at(-1)?.audience ?? "women",
                label: "",
                chest_min_cm: "",
                chest_max_cm: "",
                waist_min_cm: "",
                waist_max_cm: "",
                hip_min_cm: "",
                hip_max_cm: "",
              },
            ])
          }
        >
          {t(locale, "sizes.add")}
        </Button>
        <Button type="submit" loading={action.busy}>
          {t(locale, "account.save")}
        </Button>
      </div>
      <ActionError message={action.error} />
    </form>
  );
}

function SizesContent({ session }: { session: Session }) {
  const { token, locale, me } = session;
  const brandId = me.brand_ids[0] ?? "";
  const chart = useResource(useCallback(() => market.sizeChart(token, brandId), [token, brandId]));
  return (
    <>
      <PageHeader title={t(locale, "sizes.title")} subtitle={t(locale, "sizes.subtitle")} />
      <Card>
        <CardBody>
          <Loaded resource={chart} locale={locale}>
            {(rows) => (
              <ChartEditor
                key={JSON.stringify(rows)}
                session={session}
                brandId={brandId}
                rows={rows}
                reload={chart.reload}
              />
            )}
          </Loaded>
        </CardBody>
      </Card>
    </>
  );
}

export default function SizesPage() {
  return (
    <RoleShell allow={["brand"]}>{(session) => <SizesContent session={session} />}</RoleShell>
  );
}
