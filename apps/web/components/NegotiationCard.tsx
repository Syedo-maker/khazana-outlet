"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { ActionError } from "@/components/Feedback";
import { type Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Field, SelectInput, TextArea, TextInput } from "@/components/ui/Field";
import { dateTime, pkr } from "@/lib/format";
import { useAction } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { market, type CatalogDetail, type Negotiation, type PaymentMethod } from "@/lib/market";

const METHODS: PaymentMethod[] = ["jazzcash", "easypaisa", "bank_transfer", "cod"];

/** Bargain over a whole lot. The bot answers inside the brand's own band. */
export function NegotiationCard({ detail, session }: { detail: CatalogDetail; session: Session }) {
  const { token, locale, me } = session;
  const router = useRouter();
  const action = useAction();
  const [negotiation, setNegotiation] = useState<Negotiation | null>(null);
  const [message, setMessage] = useState("");
  const [offer, setOffer] = useState("");
  const [address, setAddress] = useState("");
  const [phone, setPhone] = useState(me.user.phone);
  const [method, setMethod] = useState<PaymentMethod>("jazzcash");

  const send = (event: FormEvent) => {
    event.preventDefault();
    const value = Number.parseInt(offer, 10);
    const body = { message, offer_pkr: Number.isFinite(value) && value > 0 ? value : undefined };
    void action.run(async () => {
      const next = negotiation
        ? await market.replyNegotiation(token, negotiation.id, body)
        : await market.startNegotiation(token, { ...body, lot_id: detail.lot.id });
      setNegotiation(next);
      setMessage("");
      setOffer("");
    });
  };

  const accept = () =>
    void action.run(async () => {
      if (negotiation) setNegotiation(await market.acceptNegotiation(token, negotiation.id));
    });

  const placeOrder = (event: FormEvent) => {
    event.preventDefault();
    void action.run(async () => {
      if (!negotiation) return;
      const done = await market.orderNegotiation(token, negotiation.id, {
        delivery_address: address,
        delivery_phone: phone,
        payment_method: method,
      });
      if (done.order_id) router.push(`/orders/${done.order_id}`);
    });
  };

  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle as="h2">{t(locale, "bargain.title")}</CardTitle>
      </CardHeader>
      <CardBody>
        <p className="mb-3 text-sm text-ink-soft">{t(locale, "bargain.explain")}</p>

        {negotiation ? (
          <ul className="mb-3 space-y-2" aria-live="polite">
            {negotiation.messages.map((line, index) => (
              <li
                key={`${line.created_at}-${index}`}
                className={`rounded px-3 py-2 text-sm ${
                  line.role === "buyer" ? "ms-8 bg-brand text-white" : "me-8 bg-surface-sunk"
                }`}
              >
                <p dir="auto" className="whitespace-pre-line">
                  {line.body}
                </p>
              </li>
            ))}
          </ul>
        ) : null}

        {negotiation?.status === "agreed" && negotiation.agreed_price_pkr !== null ? (
          <form onSubmit={placeOrder}>
            <p className="mb-3 text-sm font-semibold">
              {t(locale, "bargain.agreed", {
                price: pkr(negotiation.agreed_price_pkr),
                until: dateTime(negotiation.agreed_until),
              })}
            </p>
            <Field label={t(locale, "pools.address")} htmlFor="bargain-address">
              <TextArea
                id="bargain-address"
                rows={2}
                value={address}
                onChange={(event) => setAddress(event.target.value)}
              />
            </Field>
            <Field label={t(locale, "pools.phone")} htmlFor="bargain-phone">
              <TextInput
                id="bargain-phone"
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
              />
            </Field>
            <Field label={t(locale, "pools.method")} htmlFor="bargain-method">
              <SelectInput
                id="bargain-method"
                value={method}
                onChange={(event) => setMethod(event.target.value as PaymentMethod)}
              >
                {METHODS.map((value) => (
                  <option key={value} value={value}>
                    {t(locale, `payment.method.${value}`)}
                  </option>
                ))}
              </SelectInput>
            </Field>
            <Button
              type="submit"
              className="w-full"
              loading={action.busy}
              disabled={address.trim().length < 5}
            >
              {t(locale, "bargain.order")}
            </Button>
          </form>
        ) : negotiation === null || negotiation.status === "open" ? (
          <form onSubmit={send}>
            <Field label={t(locale, "bargain.offer")} htmlFor="bargain-offer">
              <TextInput
                id="bargain-offer"
                inputMode="numeric"
                value={offer}
                onChange={(event) => setOffer(event.target.value)}
              />
            </Field>
            <Field label={t(locale, "bargain.message")} htmlFor="bargain-message">
              <TextInput
                id="bargain-message"
                dir="auto"
                value={message}
                onChange={(event) => setMessage(event.target.value)}
              />
            </Field>
            <div className="flex flex-wrap gap-2">
              <Button type="submit" loading={action.busy} disabled={!message.trim() && !offer}>
                {t(locale, "bargain.send")}
              </Button>
              {negotiation ? (
                <Button variant="secondary" onClick={accept} loading={action.busy}>
                  {t(locale, "bargain.accept", { price: pkr(negotiation.asking_price_pkr) })}
                </Button>
              ) : null}
            </div>
          </form>
        ) : (
          <p className="text-sm text-ink-soft">{t(locale, "bargain.closed")}</p>
        )}
        <ActionError message={action.error} />
      </CardBody>
    </Card>
  );
}
