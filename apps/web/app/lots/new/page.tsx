"use client";

import { useRouter } from "next/navigation";
import { useCallback, useState, type FormEvent } from "react";

import { ActionError, Loaded, PageHeader } from "@/components/Feedback";
import { RoleShell, type Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Card, CardBody } from "@/components/ui/Card";
import { Field, SelectInput, TextArea, TextInput } from "@/components/ui/Field";
import type { ConditionGrade } from "@/lib/api";
import { useAction, useResource } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { market } from "@/lib/market";

const NUMBER_FIELDS = [
  ["total_pieces", "lots.pieces"],
  ["retail_price_per_piece_pkr", "newLot.retail"],
  ["lot_price_pkr", "lots.price"],
  ["min_order_pieces", "newLot.minimum"],
] as const;

type NumberField = (typeof NUMBER_FIELDS)[number][0];

function NewLotContent({ session }: { session: Session }) {
  const { token, locale, me } = session;
  const router = useRouter();
  const action = useAction();
  const categories = useResource(useCallback(() => market.categories(token), [token]));
  const [title, setTitle] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [grade, setGrade] = useState<ConditionGrade>("A");
  const [city, setCity] = useState("");
  const [season, setSeason] = useState("");
  const [description, setDescription] = useState("");
  const [numbers, setNumbers] = useState<Record<NumberField, string>>({
    total_pieces: "",
    retail_price_per_piece_pkr: "",
    lot_price_pkr: "",
    min_order_pieces: "",
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void action.run(async () => {
      const lot = await market.createLot(token, {
        brand_id: me.brand_ids[0] ?? "",
        title,
        category_id: categoryId,
        condition_grade: grade,
        stock_city: city,
        season: season || undefined,
        description: description || undefined,
        total_pieces: Number(numbers.total_pieces),
        retail_price_per_piece_pkr: Number(numbers.retail_price_per_piece_pkr),
        lot_price_pkr: Number(numbers.lot_price_pkr),
        min_order_pieces: Number(numbers.min_order_pieces),
      });
      router.push(`/lots/${lot.id}`);
    });
  };

  return (
    <>
      <PageHeader title={t(locale, "lots.new")} subtitle={t(locale, "newLot.subtitle")} />
      <Loaded resource={categories} locale={locale}>
        {(rows) => (
          <Card>
            <CardBody>
              <form onSubmit={submit} className="grid gap-x-4 md:grid-cols-2">
                <div className="md:col-span-2">
                  <Field label={t(locale, "newLot.title")} htmlFor="title">
                    <TextInput
                      id="title"
                      required
                      minLength={3}
                      value={title}
                      onChange={(event) => setTitle(event.target.value)}
                    />
                  </Field>
                </div>
                <Field label={t(locale, "catalog.category")} htmlFor="category">
                  <SelectInput
                    id="category"
                    required
                    value={categoryId}
                    onChange={(event) => setCategoryId(event.target.value)}
                  >
                    <option value="">{t(locale, "newLot.choose")}</option>
                    {rows
                      .filter((row) => row.parent_id)
                      .map((row) => (
                        <option key={row.id} value={row.id}>
                          {row.name}
                        </option>
                      ))}
                  </SelectInput>
                </Field>
                <Field label={t(locale, "catalog.condition")} htmlFor="grade">
                  <SelectInput
                    id="grade"
                    value={grade}
                    onChange={(event) => setGrade(event.target.value as ConditionGrade)}
                  >
                    {(["A", "B", "C"] as const).map((option) => (
                      <option key={option} value={option}>
                        {t(locale, `grade.${option}`)}
                      </option>
                    ))}
                  </SelectInput>
                </Field>
                {NUMBER_FIELDS.map(([field, label]) => (
                  <Field key={field} label={t(locale, label)} htmlFor={field}>
                    <TextInput
                      id={field}
                      type="number"
                      min={1}
                      required
                      inputMode="numeric"
                      value={numbers[field]}
                      onChange={(event) =>
                        setNumbers((current) => ({ ...current, [field]: event.target.value }))
                      }
                    />
                  </Field>
                ))}
                <Field label={t(locale, "lots.city")} htmlFor="city">
                  <TextInput
                    id="city"
                    required
                    minLength={2}
                    value={city}
                    onChange={(event) => setCity(event.target.value)}
                  />
                </Field>
                <Field label={t(locale, "newLot.season")} htmlFor="season">
                  <TextInput
                    id="season"
                    value={season}
                    onChange={(event) => setSeason(event.target.value)}
                  />
                </Field>
                <div className="md:col-span-2">
                  <Field label={t(locale, "newLot.description")} htmlFor="description">
                    <TextArea
                      id="description"
                      value={description}
                      onChange={(event) => setDescription(event.target.value)}
                    />
                  </Field>
                  <Button type="submit" loading={action.busy}>
                    {t(locale, "newLot.create")}
                  </Button>
                  <ActionError message={action.error} />
                </div>
              </form>
            </CardBody>
          </Card>
        )}
      </Loaded>
    </>
  );
}

export default function NewLotPage() {
  return (
    <RoleShell allow={["brand"]}>{(session) => <NewLotContent session={session} />}</RoleShell>
  );
}
