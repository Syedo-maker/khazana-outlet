"use client";

import { useEffect, useState, type FormEvent } from "react";

import { ActionError } from "@/components/Feedback";
import { AuthedImage } from "@/components/AuthedImage";
import { type Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Field, TextInput } from "@/components/ui/Field";
import { useAction } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { market, type ResellKit } from "@/lib/market";

function CopyBlock({
  label,
  text,
  dir,
  copyLabel,
}: {
  label: string;
  text: string;
  dir?: "ltr" | "rtl";
  copyLabel: string;
}) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    void navigator.clipboard?.writeText(text).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    });
  };
  return (
    <div className="mb-4">
      <div className="mb-1 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{label}</h3>
        <Button variant="ghost" size="sm" onClick={copy}>
          {copied ? "✓" : copyLabel}
        </Button>
      </div>
      <p dir={dir} className="whitespace-pre-line rounded bg-surface-sunk px-3 py-2 text-sm">
        {text}
      </p>
    </div>
  );
}

/** The resell kit for a paid order: words to post, price tags and square photos. */
export function ResellKitPanel({ orderId, session }: { orderId: string; session: Session }) {
  const { token, locale } = session;
  const action = useAction();
  const [kit, setKit] = useState<ResellKit | null>(null);
  const [price, setPrice] = useState("");

  useEffect(() => {
    void market
      .resellKit(token, orderId)
      .then((existing) => {
        setKit(existing);
        if (existing) setPrice(String(existing.selling_price_pkr));
      })
      .catch(() => setKit(null));
  }, [token, orderId]);

  const generate = (event: FormEvent) => {
    event.preventDefault();
    const value = Number.parseInt(price, 10);
    if (!Number.isFinite(value) || value < 1) return;
    void action.run(async () => setKit(await market.makeResellKit(token, orderId, value)));
  };

  const copyLabel = t(locale, "kit.copy");

  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle as="h2">{t(locale, "kit.title")}</CardTitle>
      </CardHeader>
      <CardBody>
        <p className="mb-3 text-sm text-ink-soft">{t(locale, "kit.explain")}</p>
        <form onSubmit={generate} className="mb-4 flex items-end gap-2">
          <div className="flex-1">
            <Field label={t(locale, "kit.price")} htmlFor="kit-price">
              <TextInput
                id="kit-price"
                inputMode="numeric"
                value={price}
                onChange={(event) => setPrice(event.target.value)}
              />
            </Field>
          </div>
          <Button type="submit" className="mb-4" loading={action.busy}>
            {kit ? t(locale, "kit.remake") : t(locale, "kit.make")}
          </Button>
        </form>
        <ActionError message={action.error} />

        {kit ? (
          <>
            <CopyBlock label="English" text={kit.caption_en} copyLabel={copyLabel} />
            <CopyBlock label="Roman Urdu" text={kit.caption_ur_roman} copyLabel={copyLabel} />
            <CopyBlock label="اردو" text={kit.caption_ur} dir="rtl" copyLabel={copyLabel} />
            <CopyBlock
              label={t(locale, "kit.post")}
              text={`${kit.social_post}\n\n${kit.hashtags.join(" ")}`}
              copyLabel={copyLabel}
            />
            <CopyBlock
              label={t(locale, "kit.status")}
              text={kit.whatsapp_status}
              copyLabel={copyLabel}
            />
            <CopyBlock
              label={t(locale, "kit.catalogue")}
              text={kit.whatsapp_catalogue}
              copyLabel={copyLabel}
            />

            <h3 className="mb-2 text-sm font-semibold">{t(locale, "kit.tags")}</h3>
            <ul className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-3">
              {kit.price_tags.map((tag) => (
                <li
                  key={`${tag.size}-${tag.color}`}
                  className="rounded border border-dashed border-line p-3 text-center"
                >
                  <p className="text-xs text-ink-soft">
                    {tag.size} · {tag.color}
                  </p>
                  <p className="text-lg font-bold">{tag.price_en}</p>
                  <p dir="rtl" className="text-sm">
                    {tag.price_ur}
                  </p>
                  <Badge>{t(locale, "kit.pieces", { count: tag.pieces })}</Badge>
                </li>
              ))}
            </ul>

            {kit.photo_paths.length > 0 ? (
              <>
                <h3 className="mb-2 text-sm font-semibold">{t(locale, "kit.photos")}</h3>
                <ul className="grid grid-cols-3 gap-2">
                  {kit.photo_paths.map((path) => (
                    <li key={path}>
                      <AuthedImage path={path} token={token} alt={kit.lot_code} />
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </>
        ) : null}
      </CardBody>
    </Card>
  );
}
