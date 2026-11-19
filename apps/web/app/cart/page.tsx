"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useState, type FormEvent } from "react";

import { ActionError, Loaded, PageHeader } from "@/components/Feedback";
import { RoleShell, type Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Field, SelectInput, TextArea, TextInput } from "@/components/ui/Field";
import { EmptyState } from "@/components/ui/States";
import { pkr } from "@/lib/format";
import { useAction, useResource } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { market, type PaymentMethod } from "@/lib/market";

const METHODS: PaymentMethod[] = ["jazzcash", "easypaisa", "bank_transfer", "cod"];

function CartContent({ session }: { session: Session }) {
  const { token, locale, me } = session;
  const router = useRouter();
  const action = useAction();
  const [cityOverride, setCityOverride] = useState<string | null>(null);
  const [address, setAddress] = useState("");
  const [phone, setPhone] = useState(me.user.phone);
  const [method, setMethod] = useState<PaymentMethod>("jazzcash");

  const cart = useResource(
    useCallback(() => market.cart(token, cityOverride ?? undefined), [token, cityOverride]),
  );
  const city = cityOverride ?? cart.data?.delivery_city ?? "";

  const checkout = (event: FormEvent) => {
    event.preventDefault();
    void action.run(async () => {
      const orders = await market.checkout(token, {
        delivery_city: city,
        delivery_address: address,
        delivery_phone: phone,
        payment_method: method,
      });
      const [only] = orders;
      router.push(only && orders.length === 1 ? `/orders/${only.id}` : "/orders");
    });
  };

  return (
    <>
      <PageHeader title={t(locale, "cart.title")} subtitle={t(locale, "cart.subtitle")} />
      <Loaded resource={cart} locale={locale}>
        {(data) =>
          data.items.length === 0 ? (
            <EmptyState
              title={t(locale, "cart.empty")}
              action={
                <Link href="/catalog" className="font-semibold text-accent underline">
                  {t(locale, "nav.catalog")}
                </Link>
              }
            />
          ) : (
            <div className="grid gap-6 lg:grid-cols-[1fr_24rem]">
              <ul className="space-y-3">
                {data.items.map((item) => (
                  <li key={item.lot_id}>
                    <Card>
                      <CardBody className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <h2 className="font-semibold">
                            {item.title ?? t(locale, "cart.unavailable")}
                          </h2>
                          {item.seller_name ? (
                            <p className="text-sm text-ink-soft">{item.seller_name}</p>
                          ) : null}
                          {item.pieces ? (
                            <p className="mt-1 text-sm">
                              {t(locale, "cart.line", {
                                pieces: item.pieces,
                                goods: pkr(item.subtotal_pkr ?? 0),
                                shipping: pkr(item.shipping_pkr ?? 0),
                              })}
                            </p>
                          ) : null}
                          {item.problem ? (
                            <p className="mt-1 text-sm font-semibold text-danger">{item.problem}</p>
                          ) : null}
                        </div>
                        <div className="text-right">
                          {item.total_pkr ? (
                            <p className="font-semibold">{pkr(item.total_pkr)}</p>
                          ) : null}
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() =>
                              void action.run(async () => {
                                await market.removeCartItem(token, item.lot_id);
                                await cart.reload();
                              })
                            }
                          >
                            {t(locale, "photos.remove")}
                          </Button>
                        </div>
                      </CardBody>
                    </Card>
                  </li>
                ))}
              </ul>

              <Card>
                <CardHeader>
                  <CardTitle as="h2">{t(locale, "cart.checkout")}</CardTitle>
                </CardHeader>
                <CardBody>
                  <form onSubmit={checkout}>
                    <Field label={t(locale, "cart.city")} htmlFor="city">
                      <TextInput
                        id="city"
                        required
                        value={city}
                        onChange={(event) => setCityOverride(event.target.value)}
                      />
                    </Field>
                    <Field label={t(locale, "cart.address")} htmlFor="address">
                      <TextArea
                        id="address"
                        required
                        minLength={5}
                        value={address}
                        onChange={(event) => setAddress(event.target.value)}
                      />
                    </Field>
                    <Field
                      label={t(locale, "login.phone")}
                      htmlFor="phone"
                      hint={t(locale, "login.phoneHint")}
                    >
                      <TextInput
                        id="phone"
                        hasHint
                        required
                        inputMode="tel"
                        value={phone}
                        onChange={(event) => setPhone(event.target.value)}
                      />
                    </Field>
                    <Field label={t(locale, "cart.payWith")} htmlFor="method">
                      <SelectInput
                        id="method"
                        value={method}
                        onChange={(event) => setMethod(event.target.value as PaymentMethod)}
                      >
                        {METHODS.map((option) => (
                          <option key={option} value={option}>
                            {t(locale, `payment.method.${option}`)}
                          </option>
                        ))}
                      </SelectInput>
                    </Field>
                    <p className="mb-3 text-lg font-semibold">
                      {t(locale, "cart.total", { amount: pkr(data.total_pkr) })}
                    </p>
                    <Button
                      type="submit"
                      className="w-full"
                      loading={action.busy}
                      disabled={data.items.some((item) => item.problem)}
                    >
                      {t(locale, "cart.place")}
                    </Button>
                    <ActionError message={action.error} />
                  </form>
                </CardBody>
              </Card>
            </div>
          )
        }
      </Loaded>
    </>
  );
}

export default function CartPage() {
  return (
    <RoleShell allow={["reseller"]}>{(session) => <CartContent session={session} />}</RoleShell>
  );
}
