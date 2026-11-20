"use client";

import { useCallback } from "react";

import { ActionError } from "@/components/Feedback";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Field, SelectInput } from "@/components/ui/Field";
import { dateTime, pkr } from "@/lib/format";
import { useAction, useResource } from "@/lib/hooks";
import { t, type Locale } from "@/lib/i18n";
import { market } from "@/lib/market";

type Choice = "inherit" | "on" | "off";

function toChoice(value: boolean | null): Choice {
  if (value === null) return "inherit";
  return value ? "on" : "off";
}

function fromChoice(choice: Choice): boolean | null {
  if (choice === "inherit") return null;
  return choice === "on";
}

/**
 * The brand's per lot switches for the bargaining bot and the markdown agent,
 * and every automatic price change on this lot.
 */
export function LotAgents({
  lotId,
  token,
  locale,
  bargaining,
  markdown,
  onChanged,
}: {
  lotId: string;
  token: string;
  locale: Locale;
  bargaining: boolean | null;
  markdown: boolean | null;
  onChanged: () => Promise<void>;
}) {
  const action = useAction();
  const history = useResource(useCallback(() => market.priceHistory(token, lotId), [token, lotId]));

  const set = (field: "bargaining_enabled" | "auto_markdown_enabled", choice: Choice) =>
    void action.run(async () => {
      await market.setLotAgents(token, lotId, { [field]: fromChoice(choice) });
      await onChanged();
      await history.reload();
    });

  const options = (["inherit", "on", "off"] as Choice[]).map((choice) => (
    <option key={choice} value={choice}>
      {t(locale, `agents.${choice}`)}
    </option>
  ));

  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle as="h2">{t(locale, "agents.title")}</CardTitle>
      </CardHeader>
      <CardBody>
        <p className="mb-3 text-sm text-ink-soft">{t(locale, "agents.explain")}</p>
        <div className="grid gap-3 md:grid-cols-2">
          <Field label={t(locale, "agents.bargaining")} htmlFor="agent-bargaining">
            <SelectInput
              id="agent-bargaining"
              value={toChoice(bargaining)}
              disabled={action.busy}
              onChange={(event) => set("bargaining_enabled", event.target.value as Choice)}
            >
              {options}
            </SelectInput>
          </Field>
          <Field label={t(locale, "agents.markdown")} htmlFor="agent-markdown">
            <SelectInput
              id="agent-markdown"
              value={toChoice(markdown)}
              disabled={action.busy}
              onChange={(event) => set("auto_markdown_enabled", event.target.value as Choice)}
            >
              {options}
            </SelectInput>
          </Field>
        </div>
        <ActionError message={action.error} />

        {(history.data ?? []).length > 0 ? (
          <>
            <h3 className="mb-2 mt-4 text-sm font-semibold">{t(locale, "agents.history")}</h3>
            <ul className="divide-y divide-line text-sm">
              {(history.data ?? []).map((move) => (
                <li key={`${move.at}-${move.action}`} className="py-2">
                  <span className="text-ink-faint">{dateTime(move.at)}</span>{" "}
                  {move.action === "lot.marked_down" &&
                  typeof move.before?.lot_price_pkr === "number" &&
                  typeof move.after?.lot_price_pkr === "number"
                    ? t(locale, "agents.markedDown", {
                        before: pkr(move.before.lot_price_pkr),
                        after: pkr(move.after.lot_price_pkr),
                      })
                    : t(locale, "agents.switched")}
                  {move.note ? <span className="block text-ink-soft">{move.note}</span> : null}
                </li>
              ))}
            </ul>
          </>
        ) : null}
      </CardBody>
    </Card>
  );
}
