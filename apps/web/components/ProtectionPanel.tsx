"use client";

import { useRef, useState, type PointerEvent } from "react";

import { AuthedImage } from "@/components/AuthedImage";
import { ActionError } from "@/components/Feedback";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Field, SelectInput, TextInput } from "@/components/ui/Field";
import type { LotDetail, LotPhoto, Visibility } from "@/lib/api";
import { catalog } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import { type Locale, t } from "@/lib/i18n";
import { market, type Region } from "@/lib/market";

type Props = { lot: LotDetail; token: string; locale: Locale; onChanged: () => Promise<void> };

const fractionPercent = (value: number) => `${value * 100}%`;

/** Drag across the photograph to mark an area that must be hidden. */
function RegionPicker({
  path,
  token,
  alt,
  regions,
  onAdd,
}: {
  path: string;
  token: string;
  alt: string;
  regions: Region[];
  onAdd: (region: Region) => void;
}) {
  const frame = useRef<HTMLDivElement>(null);
  const [start, setStart] = useState<{ x: number; y: number } | null>(null);
  const [draft, setDraft] = useState<Region | null>(null);

  const point = (event: PointerEvent) => {
    const box = frame.current?.getBoundingClientRect();
    if (!box) return { x: 0, y: 0 };
    return {
      x: Math.min(1, Math.max(0, (event.clientX - box.left) / box.width)),
      y: Math.min(1, Math.max(0, (event.clientY - box.top) / box.height)),
    };
  };
  const regionFrom = (a: { x: number; y: number }, b: { x: number; y: number }): Region => ({
    x: Math.min(a.x, b.x),
    y: Math.min(a.y, b.y),
    width: Math.abs(a.x - b.x),
    height: Math.abs(a.y - b.y),
  });

  return (
    <div
      ref={frame}
      className="relative cursor-crosshair touch-none select-none"
      onPointerDown={(event) => {
        event.currentTarget.setPointerCapture(event.pointerId);
        setStart(point(event));
      }}
      onPointerMove={(event) => {
        if (start) setDraft(regionFrom(start, point(event)));
      }}
      onPointerUp={(event) => {
        if (start) {
          const region = regionFrom(start, point(event));
          if (region.width > 0.01 && region.height > 0.01) onAdd(region);
        }
        setStart(null);
        setDraft(null);
      }}
      onPointerCancel={() => {
        setStart(null);
        setDraft(null);
      }}
    >
      <AuthedImage path={path} token={token} alt={alt} />
      {[...regions, ...(draft ? [draft] : [])].map((region, index) => (
        <span
          key={index}
          className="absolute border-2 border-danger bg-danger/30"
          style={{
            left: fractionPercent(region.x),
            top: fractionPercent(region.y),
            width: fractionPercent(region.width),
            height: fractionPercent(region.height),
          }}
        />
      ))}
    </div>
  );
}

function PhotoReview({
  lot,
  photo,
  token,
  locale,
  onChanged,
}: Props & { photo: LotPhoto }) {
  const action = useAction();
  const [regions, setRegions] = useState<Region[]>([]);
  const base = `/lots/${lot.id}/photos/${photo.id}/image`;
  const canAccept =
    !photo.protection_reviewed && ["clear", "blurred"].includes(photo.protection_status);

  const review = (chosen: Region[] | null) =>
    void action.run(async () => {
      await market.reviewPhoto(token, lot.id, photo.id, chosen);
      setRegions([]);
      await onChanged();
    });

  return (
    <li className="border-t border-line pt-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold">{photo.kind}</span>
        <Badge tone={photo.protection_reviewed ? "ok" : "warn"}>
          {t(
            locale,
            photo.protection_reviewed ? "protection.reviewed" : "protection.notReviewed",
          )}
        </Badge>
        <Badge>{t(locale, `protection.${photo.protection_status}`)}</Badge>
      </div>
      {photo.protection_detail?.review_reasons?.map((reason) => (
        <p key={reason} className="mb-1 text-sm text-warn">
          {reason}
        </p>
      ))}
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <p className="mb-1 text-xs text-ink-faint">{t(locale, "protection.original")}</p>
          <RegionPicker
            path={base}
            token={token}
            alt={`${photo.kind}, original`}
            regions={regions}
            onAdd={(region) => setRegions((current) => [...current, region])}
          />
        </div>
        {photo.has_protected_copy ? (
          <div>
            <p className="mb-1 text-xs text-ink-faint">{t(locale, "protection.buyerView")}</p>
            <AuthedImage
              path={`${base}?variant=protected`}
              token={token}
              alt={`${photo.kind}, as buyers see it`}
            />
          </div>
        ) : null}
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {canAccept ? (
          <Button size="sm" disabled={action.busy} onClick={() => review(null)}>
            {t(locale, "protection.accept")}
          </Button>
        ) : null}
        <Button
          size="sm"
          variant="secondary"
          disabled={action.busy || regions.length === 0}
          onClick={() => review(regions)}
        >
          {t(locale, "protection.hideMarked", { count: regions.length })}
        </Button>
        {regions.length > 0 ? (
          <Button size="sm" variant="ghost" onClick={() => setRegions([])}>
            {t(locale, "protection.clearMarks")}
          </Button>
        ) : null}
        <Button size="sm" variant="ghost" disabled={action.busy} onClick={() => review([])}>
          {t(locale, "protection.noMark")}
        </Button>
      </div>
      <ActionError message={action.error} />
    </li>
  );
}

/** Who may see this lot, where it is sold, and what its photographs reveal. */
export function ProtectionPanel(props: Props) {
  const { lot, token, locale, onChanged } = props;
  const action = useAction();
  const [cities, setCities] = useState(lot.excluded_cities.join(", "));
  const unbranded = lot.visibility === "unbranded";

  const run = (work: () => Promise<unknown>) =>
    void action.run(async () => {
      await work();
      await onChanged();
    });

  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle as="h2">{t(locale, "protection.title")}</CardTitle>
      </CardHeader>
      <CardBody>
        <div className="grid gap-4 md:grid-cols-2">
          <Field label={t(locale, "protection.level")} htmlFor="visibility">
            <SelectInput
              id="visibility"
              value={lot.visibility}
              disabled={action.busy}
              onChange={(event) =>
                run(() => catalog.setVisibility(token, lot.id, event.target.value as Visibility))
              }
            >
              {(["public", "private", "unbranded"] as const).map((option) => (
                <option key={option} value={option}>
                  {t(locale, `visibility.${option}`)}
                </option>
              ))}
            </SelectInput>
          </Field>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              run(() =>
                market.setRegionLock(
                  token,
                  lot.id,
                  cities
                    .split(",")
                    .map((city) => city.trim())
                    .filter(Boolean),
                ),
              );
            }}
          >
            <Field
              label={t(locale, "protection.excluded")}
              htmlFor="excluded-cities"
              hint={t(locale, "protection.excludedHint")}
            >
              <TextInput
                id="excluded-cities"
                hasHint
                value={cities}
                onChange={(event) => setCities(event.target.value)}
              />
            </Field>
            <Button type="submit" variant="secondary" size="sm" disabled={action.busy}>
              {t(locale, "account.save")}
            </Button>
          </form>
        </div>

        {unbranded ? (
          <section className="mt-6">
            <h3 className="text-base font-semibold">{t(locale, "protection.photos")}</h3>
            <p className="mt-1 max-w-prose text-sm text-ink-soft">
              {t(locale, "protection.photosHelp")}
            </p>
            <Button
              className="mt-3"
              variant="secondary"
              loading={action.busy}
              onClick={() => run(() => market.scanPhotos(token, lot.id))}
            >
              {t(locale, "protection.scan")}
            </Button>
            <ul className="mt-4 space-y-4">
              {lot.photos.map((photo) => (
                <PhotoReview key={photo.id} {...props} photo={photo} />
              ))}
            </ul>
          </section>
        ) : null}
        <ActionError message={action.error} />
      </CardBody>
    </Card>
  );
}
