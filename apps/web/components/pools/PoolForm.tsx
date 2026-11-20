"use client";

import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Field, SelectInput, TextArea, TextInput } from "@/components/ui/Field";
import { t, type Locale } from "@/lib/i18n";
import type { PaymentMethod, PoolLine, PoolMembership } from "@/lib/market";

const METHODS: PaymentMethod[] = ["jazzcash", "easypaisa", "bank_transfer", "cod"];

/** Sizes, colours and delivery for one member's place in a pool. */
export function PoolForm({
  idPrefix,
  available,
  defaultPhone,
  locale,
  submitLabel,
  busy,
  onSubmit,
}: {
  idPrefix: string;
  available: PoolLine[];
  defaultPhone: string;
  locale: Locale;
  submitLabel: string;
  busy: boolean;
  onSubmit: (membership: PoolMembership) => void;
}) {
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [address, setAddress] = useState("");
  const [phone, setPhone] = useState(defaultPhone);
  const [method, setMethod] = useState<PaymentMethod>("jazzcash");

  const lines = available
    .map((line) => ({
      size: line.size,
      color: line.color,
      pieces: Number.parseInt(quantities[`${line.size}|${line.color}`] ?? "", 10) || 0,
    }))
    .filter((line) => line.pieces > 0);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (lines.length === 0) return;
    onSubmit({
      lines,
      delivery_address: address,
      delivery_phone: phone,
      payment_method: method,
    });
  };

  return (
    <form onSubmit={submit}>
      <div className="mb-3 space-y-2">
        {available.map((line) => {
          const key = `${line.size}|${line.color}`;
          const id = `${idPrefix}-${line.size}-${line.color}`;
          return (
            <div key={key} className="grid grid-cols-[1fr_6rem] items-center gap-3 text-sm">
              <label htmlFor={id}>
                {line.size} · {line.color}{" "}
                <span className="text-ink-faint">({line.pieces})</span>
              </label>
              <TextInput
                id={id}
                inputMode="numeric"
                value={quantities[key] ?? ""}
                onChange={(event) =>
                  setQuantities((current) => ({ ...current, [key]: event.target.value }))
                }
              />
            </div>
          );
        })}
      </div>
      <Field label={t(locale, "pools.address")} htmlFor={`${idPrefix}-address`}>
        <TextArea
          id={`${idPrefix}-address`}
          rows={2}
          value={address}
          onChange={(event) => setAddress(event.target.value)}
        />
      </Field>
      <Field label={t(locale, "pools.phone")} htmlFor={`${idPrefix}-phone`}>
        <TextInput
          id={`${idPrefix}-phone`}
          inputMode="tel"
          value={phone}
          onChange={(event) => setPhone(event.target.value)}
        />
      </Field>
      <Field label={t(locale, "pools.method")} htmlFor={`${idPrefix}-method`}>
        <SelectInput
          id={`${idPrefix}-method`}
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
        loading={busy}
        disabled={lines.length === 0 || address.trim().length < 5}
      >
        {submitLabel}
      </Button>
      <p className="mt-2 text-xs text-ink-faint">{t(locale, "pools.private")}</p>
    </form>
  );
}
