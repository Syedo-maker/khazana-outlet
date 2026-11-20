"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useState, type FormEvent } from "react";

import { ActionError, PageHeader } from "@/components/Feedback";
import { RoleShell, type Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Field, SelectInput, TextInput } from "@/components/ui/Field";
import { pkr } from "@/lib/format";
import { useAction, useResource } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { market, type MixedLot, type MixedLotRequest } from "@/lib/market";

function MixedLotContent({ session }: { session: Session }) {
  const { token, locale } = session;
  const router = useRouter();
  const action = useAction();
  const categories = useResource(useCallback(() => market.categories(token), [token]));
  const [budget, setBudget] = useState("150000");
  const [pieces, setPieces] = useState("60");
  const [brands, setBrands] = useState("3");
  const [chosen, setChosen] = useState<string[]>([]);
  const [proposal, setProposal] = useState<MixedLot | null>(null);

  const request = (): MixedLotRequest => ({
    budget_pkr: Number.parseInt(budget, 10) || 0,
    target_pieces: Number.parseInt(pieces, 10) || 0,
    max_brands: Number.parseInt(brands, 10) || 3,
    category_ids: chosen,
  });

  const build = (event: FormEvent) => {
    event.preventDefault();
    void action.run(async () => setProposal(await market.buildMixedLot(token, request())));
  };

  const addAll = () =>
    void action.run(async () => {
      await market.mixedLotToCart(token, request());
      router.push("/cart");
    });

  const toggle = (id: string) =>
    setChosen((current) =>
      current.includes(id) ? current.filter((value) => value !== id) : [...current, id],
    );

  return (
    <>
      <PageHeader title={t(locale, "mixed.title")} subtitle={t(locale, "mixed.subtitle")} />
      <div className="grid gap-6 lg:grid-cols-[20rem_1fr]">
        <Card>
          <CardBody>
            <form onSubmit={build}>
              <Field label={t(locale, "mixed.budget")} htmlFor="budget">
                <TextInput
                  id="budget"
                  inputMode="numeric"
                  value={budget}
                  onChange={(event) => setBudget(event.target.value)}
                />
              </Field>
              <Field label={t(locale, "mixed.pieces")} htmlFor="pieces">
                <TextInput
                  id="pieces"
                  inputMode="numeric"
                  value={pieces}
                  onChange={(event) => setPieces(event.target.value)}
                />
              </Field>
              <Field label={t(locale, "mixed.brands")} htmlFor="brands">
                <SelectInput
                  id="brands"
                  value={brands}
                  onChange={(event) => setBrands(event.target.value)}
                >
                  {["2", "3", "4", "5", "6"].map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </SelectInput>
              </Field>
              <fieldset className="mb-4">
                <legend className="mb-1 text-sm font-semibold">
                  {t(locale, "mixed.categories")}
                </legend>
                <div className="max-h-48 space-y-1 overflow-y-auto text-sm">
                  {(categories.data ?? []).map((category) => (
                    <label key={category.id} className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={chosen.includes(category.id)}
                        onChange={() => toggle(category.id)}
                      />
                      {category.name}
                    </label>
                  ))}
                </div>
              </fieldset>
              <Button type="submit" className="w-full" loading={action.busy}>
                {t(locale, "mixed.build")}
              </Button>
              <ActionError message={action.error} />
            </form>
          </CardBody>
        </Card>

        <div>
          {proposal === null ? (
            <p className="rounded border border-line bg-surface px-4 py-10 text-center text-ink-soft">
              {t(locale, "mixed.explain")}
            </p>
          ) : (
            <Card>
              <CardHeader>
                <CardTitle as="h2">
                  {t(locale, proposal.brand_count === 1 ? "mixed.summaryOne" : "mixed.summary", {
                    pieces: proposal.pieces,
                    brands: proposal.brand_count,
                    amount: pkr(proposal.total_pkr),
                  })}
                </CardTitle>
              </CardHeader>
              <CardBody>
                {proposal.notes.map((note) => (
                  <p key={note} dir="auto" className="mb-2 text-sm font-semibold text-warn">
                    {note}
                  </p>
                ))}
                <ul className="mb-4 divide-y divide-line">
                  {proposal.components.map((part) => (
                    <li key={part.item.lot.id} className="py-3">
                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <Link
                          href={`/catalog/${part.item.lot.id}`}
                          className="font-semibold underline"
                        >
                          {part.item.lot.title}
                        </Link>
                        <span className="font-semibold">{pkr(part.total_pkr)}</span>
                      </div>
                      <p className="text-sm text-ink-soft">
                        {part.item.brand_name} ·{" "}
                        {t(locale, "mixed.part", {
                          pieces: part.pieces,
                          shipping: pkr(part.shipping_pkr),
                        })}
                      </p>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {part.lines.map((line) => (
                          <Badge key={`${line.size}-${line.color}`}>
                            {line.size} {line.color} × {line.pieces}
                          </Badge>
                        ))}
                      </div>
                      <p dir="auto" className="mt-1 text-xs text-ink-faint">
                        {part.reason}
                      </p>
                    </li>
                  ))}
                </ul>
                <Button
                  onClick={addAll}
                  loading={action.busy}
                  disabled={proposal.components.length === 0}
                >
                  {t(locale, "mixed.addAll")}
                </Button>
                <p className="mt-2 text-xs text-ink-faint">{t(locale, "mixed.separateOrders")}</p>
              </CardBody>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}

export default function MixedLotPage() {
  return (
    <RoleShell allow={["reseller"]}>{(session) => <MixedLotContent session={session} />}</RoleShell>
  );
}
