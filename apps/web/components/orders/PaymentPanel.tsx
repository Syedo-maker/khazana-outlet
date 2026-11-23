"use client";

import { useCallback, useState } from "react";

import { ActionError, Loaded } from "@/components/Feedback";
import type { Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Field, TextInput } from "@/components/ui/Field";
import { pkr } from "@/lib/format";
import { useAction, useResource } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { market, type OrderDetail } from "@/lib/market";

/** The buyer's side of paying for an order. */
export function PaymentPanel({
  order,
  session,
  onChanged,
}: {
  order: OrderDetail;
  session: Session;
  onChanged: () => Promise<void>;
}) {
  const { token, locale } = session;
  const action = useAction();
  const [reference, setReference] = useState("");
  const payment = useResource(
    useCallback(() => market.startPayment(token, order.id), [token, order.id]),
  );

  const act = (work: () => Promise<unknown>) =>
    void action.run(async () => {
      await work();
      await payment.reload();
      await onChanged();
    });

  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle as="h2">{t(locale, "payment.title")}</CardTitle>
      </CardHeader>
      <CardBody>
        <Loaded resource={payment} locale={locale} rows={2}>
          {(state) => (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={state.status === "failed" ? "danger" : "accent"}>
                  {t(locale, `payment.status.${state.status}`)}
                </Badge>
                <span className="text-sm">{pkr(state.amount_pkr)}</span>
                <span className="text-sm text-ink-soft">
                  {t(locale, `payment.method.${state.method}`)}
                </span>
              </div>
              {state.failure_reason ? (
                <p className="mt-2 text-sm text-danger">{state.failure_reason}</p>
              ) : null}
              {state.instructions ? <p className="mt-3 text-sm">{state.instructions}</p> : null}

              {state.action === "sandbox_wallet" ? (
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button
                    disabled={action.busy}
                    onClick={() =>
                      act(() => market.completeSandboxPayment(token, order.id, "succeeded"))
                    }
                  >
                    {t(locale, "payment.payNow")}
                  </Button>
                  <Button
                    variant="secondary"
                    disabled={action.busy}
                    onClick={() =>
                      act(() => market.completeSandboxPayment(token, order.id, "failed"))
                    }
                  >
                    {t(locale, "payment.simulateFailure")}
                  </Button>
                </div>
              ) : null}

              {state.action === "bank_transfer" ? (
                state.reference ? (
                  <p className="mt-3 text-sm">
                    {t(locale, "payment.referenceSent", { reference: state.reference })}
                  </p>
                ) : (
                  <form
                    className="mt-3 max-w-sm"
                    onSubmit={(event) => {
                      event.preventDefault();
                      act(() => market.submitBankReference(token, order.id, reference));
                    }}
                  >
                    <Field label={t(locale, "payment.reference")} htmlFor="bank-reference">
                      <TextInput
                        id="bank-reference"
                        required
                        minLength={4}
                        value={reference}
                        onChange={(event) => setReference(event.target.value)}
                      />
                    </Field>
                    <Button type="submit" disabled={action.busy}>
                      {t(locale, "payment.sendReference")}
                    </Button>
                  </form>
                )
              ) : null}
              <ActionError message={action.error} />
            </>
          )}
        </Loaded>
      </CardBody>
    </Card>
  );
}
