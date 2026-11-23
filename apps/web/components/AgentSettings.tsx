"use client";

import { useState, type FormEvent } from "react";

import { ActionError } from "@/components/Feedback";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Field, TextInput } from "@/components/ui/Field";
import { useAction } from "@/lib/hooks";
import { t, type Locale } from "@/lib/i18n";
import { market, type BrandPolicy } from "@/lib/market";

type NumberField =
  | "bargain_floor_percent"
  | "bargain_step_percent"
  | "markdown_step_percent"
  | "markdown_interval_days"
  | "markdown_floor_percent";

const NUMBERS: NumberField[] = [
  "bargain_floor_percent",
  "bargain_step_percent",
  "markdown_floor_percent",
  "markdown_step_percent",
  "markdown_interval_days",
];

/**
 * The brand's own limits for the bargaining bot and the markdown agent, and
 * the switch for pooled orders. Each is off until the brand turns it on.
 */
export function AgentSettings({
  brandId,
  policy,
  token,
  locale,
  onSaved,
}: {
  brandId: string;
  policy: BrandPolicy;
  token: string;
  locale: Locale;
  onSaved: () => Promise<void>;
}) {
  const action = useAction();
  const [values, setValues] = useState<Record<NumberField, string>>(() =>
    Object.fromEntries(
      NUMBERS.map((name) => [name, policy[name] === null ? "" : String(policy[name])]),
    ) as Record<NumberField, string>,
  );

  const toggle = (key: "allow_bargaining" | "allow_auto_markdown" | "allow_pooled_orders") =>
    void action.run(async () => {
      await market.updatePolicy(token, brandId, { [key]: !policy[key] });
      await onSaved();
    });

  const save = (event: FormEvent) => {
    event.preventDefault();
    const changes: Partial<BrandPolicy> = {};
    for (const name of NUMBERS) {
      const raw = values[name].trim();
      const parsed = raw === "" ? null : Number(raw);
      if (parsed !== null && Number.isNaN(parsed)) continue;
      if (parsed === null && (name === "bargain_floor_percent" || name === "markdown_floor_percent")) {
        Object.assign(changes, { [name]: null });
      } else if (parsed !== null) {
        Object.assign(changes, { [name]: parsed });
      }
    }
    void action.run(async () => {
      await market.updatePolicy(token, brandId, changes);
      await onSaved();
    });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle as="h2">{t(locale, "agents.settings")}</CardTitle>
      </CardHeader>
      <CardBody>
        <p className="mb-3 text-sm text-ink-soft">{t(locale, "agents.settingsExplain")}</p>
        {(["allow_bargaining", "allow_auto_markdown", "allow_pooled_orders"] as const).map(
          (key) => (
            <label key={key} className="flex min-h-touch items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={policy[key]}
                disabled={action.busy}
                onChange={() => toggle(key)}
              />
              {t(locale, `agents.${key}`)}
            </label>
          ),
        )}
        <form onSubmit={save} className="mt-4 grid gap-3 md:grid-cols-2">
          {NUMBERS.map((name) => (
            <Field key={name} label={t(locale, `agents.${name}`)} htmlFor={`policy-${name}`}>
              <TextInput
                id={`policy-${name}`}
                inputMode="decimal"
                value={values[name]}
                onChange={(event) =>
                  setValues((current) => ({ ...current, [name]: event.target.value }))
                }
              />
            </Field>
          ))}
          <div className="md:col-span-2">
            <Button type="submit" variant="secondary" loading={action.busy}>
              {t(locale, "account.save")}
            </Button>
          </div>
        </form>
        <ActionError message={action.error} />
      </CardBody>
    </Card>
  );
}
