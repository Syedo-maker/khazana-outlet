"use client";

import Link from "next/link";
import { useCallback, useState, type FormEvent } from "react";

import { ActionError, Loaded, PageHeader } from "@/components/Feedback";
import { LotCard } from "@/components/LotCard";
import { RoleShell, type Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Field, SelectInput, TextInput } from "@/components/ui/Field";
import { EmptyState } from "@/components/ui/States";
import type { ConditionGrade } from "@/lib/api";
import { errorMessage, useAction, useResource } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { market, type SearchFilters, type SearchResult } from "@/lib/market";

type Draft = {
  q: string;
  category_id: string;
  stock_city: string;
  grade: "" | ConditionGrade;
  max_price: string;
  min_discount: string;
  sort: NonNullable<SearchFilters["sort"]>;
};

const EMPTY: Draft = {
  q: "",
  category_id: "",
  stock_city: "",
  grade: "",
  max_price: "",
  min_discount: "",
  sort: "newest",
};

function toFilters(draft: Draft): SearchFilters {
  return {
    q: draft.q.trim() || undefined,
    category_id: draft.category_id || undefined,
    stock_city: draft.stock_city.trim() || undefined,
    grade: draft.grade ? [draft.grade] : undefined,
    max_price_per_piece_pkr: draft.max_price ? Number(draft.max_price) : undefined,
    min_discount_percent: draft.min_discount ? Number(draft.min_discount) : undefined,
    sort: draft.sort,
  };
}

function CatalogContent({ session }: { session: Session }) {
  const { token, locale, me } = session;
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [filters, setFilters] = useState<SearchFilters>({ sort: "newest" });
  const [offset, setOffset] = useState(0);
  const [photoResult, setPhotoResult] = useState<SearchResult | null>(null);
  const [saveName, setSaveName] = useState("");
  const action = useAction();

  const results = useResource(
    useCallback(() => market.search(token, filters, offset), [token, filters, offset]),
  );
  const categories = useResource(useCallback(() => market.categories(token), [token]));
  const saved = useResource(useCallback(() => market.savedSearches(token), [token]));
  const profile = useResource(
    useCallback(
      () =>
        me.user.role === "reseller" ? market.resellerProfile(token) : Promise.resolve(null),
      [token, me.user.role],
    ),
  );

  const update = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));

  const applySearch = (event: FormEvent) => {
    event.preventDefault();
    setPhotoResult(null);
    setOffset(0);
    setFilters(toFilters(draft));
  };

  const searchPhoto = async (file: File) => {
    action.setError(null);
    try {
      setPhotoResult(await market.searchByPhoto(token, file));
    } catch (cause) {
      action.setError(errorMessage(cause));
    }
  };

  const shown = photoResult ?? results.data;
  const needsVerification =
    me.user.role === "reseller" && profile.data?.status !== "verified" && !profile.loading;

  return (
    <>
      <PageHeader title={t(locale, "catalog.title")} subtitle={t(locale, "catalog.subtitle")} />

      {needsVerification ? (
        <p className="mb-4 rounded border border-line bg-accent-subtle px-4 py-3 text-sm">
          {t(locale, "catalog.verifyFirst")}{" "}
          <Link href="/account" className="font-semibold underline">
            {t(locale, "nav.account")}
          </Link>
        </p>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
        <aside className="space-y-6">
          <form onSubmit={applySearch} aria-label={t(locale, "catalog.filters")}>
            <Field label={t(locale, "catalog.search")} htmlFor="q">
              <TextInput
                id="q"
                type="search"
                value={draft.q}
                onChange={(event) => update("q", event.target.value)}
              />
            </Field>
            <Field label={t(locale, "catalog.category")} htmlFor="category">
              <SelectInput
                id="category"
                value={draft.category_id}
                onChange={(event) => update("category_id", event.target.value)}
              >
                <option value="">{t(locale, "catalog.any")}</option>
                {(categories.data ?? []).map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.parent_id ? `- ${category.name}` : category.name}
                  </option>
                ))}
              </SelectInput>
            </Field>
            <Field label={t(locale, "lots.city")} htmlFor="stock-city">
              <TextInput
                id="stock-city"
                value={draft.stock_city}
                onChange={(event) => update("stock_city", event.target.value)}
              />
            </Field>
            <Field label={t(locale, "catalog.condition")} htmlFor="grade">
              <SelectInput
                id="grade"
                value={draft.grade}
                onChange={(event) => update("grade", event.target.value as Draft["grade"])}
              >
                <option value="">{t(locale, "catalog.any")}</option>
                {(["A", "B", "C"] as const).map((grade) => (
                  <option key={grade} value={grade}>
                    {t(locale, `grade.${grade}`)}
                  </option>
                ))}
              </SelectInput>
            </Field>
            <Field label={t(locale, "catalog.maxPrice")} htmlFor="max-price">
              <TextInput
                id="max-price"
                type="number"
                min={0}
                inputMode="numeric"
                value={draft.max_price}
                onChange={(event) => update("max_price", event.target.value)}
              />
            </Field>
            <Field label={t(locale, "catalog.minDiscount")} htmlFor="min-discount">
              <TextInput
                id="min-discount"
                type="number"
                min={0}
                max={100}
                inputMode="numeric"
                value={draft.min_discount}
                onChange={(event) => update("min_discount", event.target.value)}
              />
            </Field>
            <Field label={t(locale, "catalog.sort")} htmlFor="sort">
              <SelectInput
                id="sort"
                value={draft.sort}
                onChange={(event) => update("sort", event.target.value as Draft["sort"])}
              >
                {(["newest", "price_low", "price_high", "discount", "pieces"] as const).map(
                  (sort) => (
                    <option key={sort} value={sort}>
                      {t(locale, `catalog.sort.${sort}`)}
                    </option>
                  ),
                )}
              </SelectInput>
            </Field>
            <Button type="submit" className="w-full">
              {t(locale, "catalog.apply")}
            </Button>
          </form>

          <section>
            <h2 className="text-sm font-semibold">{t(locale, "catalog.photoSearch")}</h2>
            <label className="mt-2 inline-flex min-h-touch cursor-pointer items-center text-sm font-semibold text-accent underline">
              {t(locale, "catalog.choosePhoto")}
              <input
                type="file"
                accept="image/jpeg,image/png,image/webp"
                className="sr-only"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  event.target.value = "";
                  if (file) void searchPhoto(file);
                }}
              />
            </label>
            {photoResult ? (
              <Button variant="ghost" size="sm" onClick={() => setPhotoResult(null)}>
                {t(locale, "catalog.clearPhoto")}
              </Button>
            ) : null}
          </section>

          <section>
            <h2 className="text-sm font-semibold">{t(locale, "catalog.saved")}</h2>
            <ul className="mt-2 space-y-1 text-sm">
              {(saved.data ?? []).map((row) => (
                <li key={row.id} className="flex items-center justify-between gap-2">
                  <button
                    type="button"
                    className="min-h-touch text-left font-semibold underline"
                    onClick={() =>
                      void action.run(async () => {
                        setPhotoResult(await market.runSavedSearch(token, row.id));
                        await saved.reload();
                      })
                    }
                  >
                    {row.name}
                    {row.new_matches > 0
                      ? ` (${t(locale, "catalog.newMatches", { count: row.new_matches })})`
                      : ""}
                  </button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() =>
                      void action.run(async () => {
                        await market.removeSavedSearch(token, row.id);
                        await saved.reload();
                      })
                    }
                  >
                    {t(locale, "photos.remove")}
                  </Button>
                </li>
              ))}
            </ul>
            <form
              className="mt-2 flex gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                if (!saveName.trim()) return;
                void action.run(async () => {
                  await market.saveSearch(token, saveName.trim(), filters);
                  setSaveName("");
                  await saved.reload();
                });
              }}
            >
              <TextInput
                id="save-name"
                aria-label={t(locale, "catalog.saveName")}
                placeholder={t(locale, "catalog.saveName")}
                value={saveName}
                onChange={(event) => setSaveName(event.target.value)}
              />
              <Button type="submit" variant="secondary" disabled={action.busy}>
                {t(locale, "catalog.save")}
              </Button>
            </form>
          </section>
          <ActionError message={action.error} />
        </aside>

        <section aria-live="polite" aria-busy={results.loading}>
          <Loaded resource={{ ...results, data: shown }} locale={locale} rows={6}>
            {(data) =>
              data.items.length === 0 ? (
                <EmptyState
                  title={t(locale, "state.emptyTitle")}
                  description={t(locale, "catalog.none")}
                />
              ) : (
                <>
                  <p className="mb-3 text-sm text-ink-soft">
                    {t(locale, "catalog.count", { count: data.total })}
                    {data.note ? ` ${data.note}` : ""}
                  </p>
                  <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                    {data.items.map((item) => (
                      <li key={item.lot.id}>
                        <LotCard item={item} token={token} locale={locale} />
                      </li>
                    ))}
                  </ul>
                  {!photoResult && data.total > 24 ? (
                    <div className="mt-6 flex items-center gap-3">
                      <Button
                        variant="secondary"
                        disabled={offset === 0}
                        onClick={() => setOffset(Math.max(0, offset - 24))}
                      >
                        {t(locale, "catalog.previous")}
                      </Button>
                      <Button
                        variant="secondary"
                        disabled={offset + 24 >= data.total}
                        onClick={() => setOffset(offset + 24)}
                      >
                        {t(locale, "catalog.next")}
                      </Button>
                    </div>
                  ) : null}
                </>
              )
            }
          </Loaded>
        </section>
      </div>
    </>
  );
}

export default function CatalogPage() {
  return <RoleShell>{(session) => <CatalogContent session={session} />}</RoleShell>;
}
