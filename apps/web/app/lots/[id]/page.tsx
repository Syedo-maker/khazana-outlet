"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AppShell, BRAND_NAV } from "@/components/AppShell";
import { ManifestEditor } from "@/components/ManifestEditor";
import { Badge, Card, CardBody, CardHeader, CardTitle, Stat } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Field, TextInput } from "@/components/ui/Field";
import { ErrorState, Skeleton } from "@/components/ui/States";
import {
  ApiError,
  catalog,
  type ApprovalEntry,
  type LotDetail,
  type LotStatus,
  type PhotoKind,
  type Readiness,
} from "@/lib/api";
import { DEFAULT_LOCALE, type Locale, t } from "@/lib/i18n";
import { getAccessToken } from "@/lib/session";

const TONES: Record<LotStatus, "neutral" | "ok" | "warn" | "danger" | "accent"> = {
  draft: "neutral",
  pending_approval: "warn",
  approved: "accent",
  live: "ok",
  paused: "warn",
  sold: "neutral",
  withdrawn: "neutral",
  expired: "danger",
};

const PHOTO_KINDS: PhotoKind[] = [
  "full_lot",
  "front",
  "back",
  "label",
  "size_spread",
  "defect",
  "packaging",
];

/** Statuses in which the brand may still change the listing. */
const EDITABLE: LotStatus[] = ["draft", "pending_approval"];

function pkr(amount: number): string {
  return `${amount.toLocaleString("en-PK")} PKR`;
}

/**
 * One lot: the readiness checklist, the manifest editor, the photographs and
 * the lifecycle actions.
 *
 * The actions shown are driven by the lot's status rather than always being
 * present and failing on press. The server owns the state machine and will
 * refuse an illegal move anyway, but offering a button that cannot work is a
 * worse way to find that out.
 */
export default function LotPage() {
  const locale: Locale = DEFAULT_LOCALE;
  const params = useParams<{ id: string }>();
  const lotId = params.id;

  const [token, setToken] = useState<string | null>(null);
  const [lot, setLot] = useState<LotDetail | null>(null);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [trail, setTrail] = useState<ApprovalEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [rejectNote, setRejectNote] = useState("");
  const [photoKind, setPhotoKind] = useState<PhotoKind>("front");

  const load = useCallback(async () => {
    setError(null);
    const current = getAccessToken();
    setToken(current);
    if (!current) {
      setError(t(locale, "error.network"));
      return;
    }
    try {
      const [detail, ready, history] = await Promise.all([
        catalog.getLot(current, lotId),
        catalog.readiness(current, lotId),
        catalog.approvalTrail(current, lotId),
      ]);
      setLot(detail);
      setReadiness(ready);
      setTrail(history);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not load this lot.");
    }
  }, [lotId, locale]);

  useEffect(() => {
    void load();
  }, [load]);

  /** Run one lifecycle action, then reload everything it could have changed. */
  const act = useCallback(
    async (work: (accessToken: string) => Promise<unknown>) => {
      const current = getAccessToken();
      if (!current) return;
      setBusy(true);
      setActionError(null);
      try {
        await work(current);
        await load();
      } catch (cause) {
        setActionError(cause instanceof ApiError ? cause.message : "That did not work.");
      } finally {
        setBusy(false);
      }
    },
    [load],
  );

  if (error) {
    return (
      <AppShell nav={BRAND_NAV} locale={locale}>
        <ErrorState
          title={t(locale, "state.errorTitle")}
          message={error}
          onRetry={() => void load()}
          retryLabel={t(locale, "state.retry")}
        />
      </AppShell>
    );
  }

  if (!lot || !token) {
    return (
      <AppShell nav={BRAND_NAV} locale={locale}>
        <Skeleton rows={6} />
      </AppShell>
    );
  }

  const editable = EDITABLE.includes(lot.status);

  return (
    <AppShell nav={BRAND_NAV} locale={locale}>
      <nav className="mb-4">
        <Link href="/lots" className="text-sm font-semibold text-accent underline">
          {t(locale, "lot.back")}
        </Link>
      </nav>

      <header className="mb-6">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={TONES[lot.status]}>{t(locale, `status.${lot.status}`)}</Badge>
          <Badge>{t(locale, `visibility.${lot.visibility}`)}</Badge>
          <span className="font-mono text-xs text-ink-faint">{lot.lot_code}</span>
        </div>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">{lot.title}</h1>
        <p className="mt-1 text-sm text-ink-soft">{t(locale, `grade.${lot.condition_grade}`)}</p>
      </header>

      <dl className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label={t(locale, "lots.pieces")} value={String(lot.total_pieces)} />
        <Stat label={t(locale, "lots.price")} value={pkr(lot.lot_price_pkr)} />
        <Stat
          label={t(locale, "lots.perPiece")}
          value={pkr(Math.round(lot.price_per_piece_pkr))}
          note={`${Math.round(lot.discount_percent)}% ${t(locale, "lots.discount").toLowerCase()}`}
        />
        <Stat label={t(locale, "lots.city")} value={lot.stock_city} />
      </dl>

      {/* The checklist. Everything outstanding at once, not one error at a time. */}
      {readiness ? (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle as="h2">{t(locale, "readiness.title")}</CardTitle>
          </CardHeader>
          <CardBody>
            {readiness.ready ? (
              <p className="text-sm font-semibold text-ok">{t(locale, "readiness.ready")}</p>
            ) : (
              <>
                <h3 className="text-sm font-semibold text-danger">
                  {t(locale, "readiness.blockers")}
                </h3>
                <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
                  {readiness.blockers.map((blocker) => (
                    <li key={blocker}>{blocker}</li>
                  ))}
                </ul>
              </>
            )}
            {readiness.warnings.length > 0 ? (
              <>
                <h3 className="mt-4 text-sm font-semibold text-warn">
                  {t(locale, "readiness.warnings")}
                </h3>
                <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-ink-soft">
                  {readiness.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </>
            ) : null}
          </CardBody>
        </Card>
      ) : null}

      <div className="mb-6">
        <ManifestEditor
          lotId={lot.id}
          lotTotalPieces={lot.total_pieces}
          lines={lot.manifest_lines}
          token={token}
          locale={locale}
          editable={editable}
          onSaved={() => void load()}
        />
      </div>

      <Card className="mb-6">
        <CardHeader>
          <CardTitle as="h2">{t(locale, "photos.title")}</CardTitle>
        </CardHeader>
        <CardBody>
          {lot.photos.length === 0 ? (
            <p className="text-sm text-ink-soft">{t(locale, "photos.none")}</p>
          ) : (
            <ul className="space-y-2">
              {lot.photos.map((photo) => (
                <li
                  key={photo.id}
                  className="flex items-center justify-between gap-3 border-b border-line/60 pb-2 text-sm"
                >
                  <span>
                    <span className="font-semibold">{photo.sort_order}.</span> {photo.kind}
                    <span className="ml-2 text-ink-faint">
                      {photo.width} &times; {photo.height}
                      {photo.bytes_stored
                        ? `, ${Math.round(photo.bytes_stored / 1024)} KB`
                        : null}
                    </span>
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={!editable || busy}
                    onClick={() =>
                      void act((accessToken) =>
                        catalog.removePhoto(accessToken, lot.id, photo.id),
                      )
                    }
                  >
                    {t(locale, "photos.remove")}
                  </Button>
                </li>
              ))}
            </ul>
          )}

          {editable ? (
            <div className="mt-4 flex flex-wrap items-end gap-3">
              <Field label={t(locale, "photos.kind")} htmlFor="photo-kind">
                <select
                  id="photo-kind"
                  value={photoKind}
                  onChange={(event) => setPhotoKind(event.target.value as PhotoKind)}
                  className="min-h-touch rounded border border-line bg-surface px-3 py-2 text-base"
                >
                  {PHOTO_KINDS.map((kind) => (
                    <option key={kind} value={kind}>
                      {kind}
                    </option>
                  ))}
                </select>
              </Field>

              <label className="mb-4 inline-flex min-h-touch cursor-pointer items-center rounded px-3 text-sm font-semibold text-accent underline">
                {t(locale, "photos.add")}
                <input
                  type="file"
                  className="sr-only"
                  accept="image/jpeg,image/png,image/webp"
                  disabled={busy}
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.target.value = "";
                    if (file) {
                      void act((accessToken) =>
                        catalog.addPhoto(accessToken, lot.id, file, photoKind),
                      );
                    }
                  }}
                />
              </label>
            </div>
          ) : null}
        </CardBody>
      </Card>

      <Card className="mb-6">
        <CardHeader>
          <CardTitle as="h2">{t(locale, "trail.title")}</CardTitle>
        </CardHeader>
        <CardBody>
          {actionError ? (
            <p role="alert" className="mb-3 text-sm font-semibold text-danger">
              {actionError}
            </p>
          ) : null}

          <div className="flex flex-wrap gap-2">
            {lot.status === "draft" ? (
              <Button
                disabled={busy || !readiness?.ready}
                onClick={() => void act((accessToken) => catalog.submit(accessToken, lot.id))}
              >
                {t(locale, "actions.submit")}
              </Button>
            ) : null}

            {lot.status === "pending_approval" ? (
              <>
                <Button
                  disabled={busy}
                  onClick={() => void act((accessToken) => catalog.approve(accessToken, lot.id))}
                >
                  {t(locale, "actions.approve")}
                </Button>
                <Button
                  variant="danger"
                  disabled={busy || rejectNote.trim().length < 10}
                  onClick={() =>
                    void act((accessToken) =>
                      catalog.reject(accessToken, lot.id, rejectNote.trim()),
                    )
                  }
                >
                  {t(locale, "actions.reject")}
                </Button>
              </>
            ) : null}

            {lot.status === "live" ? (
              <Button
                variant="secondary"
                disabled={busy}
                onClick={() => void act((accessToken) => catalog.pause(accessToken, lot.id))}
              >
                {t(locale, "actions.pause")}
              </Button>
            ) : null}

            {lot.status === "paused" ? (
              <Button
                disabled={busy}
                onClick={() => void act((accessToken) => catalog.resume(accessToken, lot.id))}
              >
                {t(locale, "actions.resume")}
              </Button>
            ) : null}

            {lot.status !== "withdrawn" && lot.status !== "sold" ? (
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() => void act((accessToken) => catalog.withdraw(accessToken, lot.id))}
              >
                {t(locale, "actions.withdraw")}
              </Button>
            ) : null}
          </div>

          {lot.status === "pending_approval" ? (
            <div className="mt-4 max-w-prose">
              <Field
                label={t(locale, "actions.rejectReason")}
                htmlFor="reject-note"
                hint="At least 10 characters, so whoever prepared the listing can act on it."
              >
                <TextInput
                  id="reject-note"
                  hasHint
                  value={rejectNote}
                  onChange={(event) => setRejectNote(event.target.value)}
                />
              </Field>
            </div>
          ) : null}

          {trail.length === 0 ? (
            <p className="mt-4 text-sm text-ink-soft">{t(locale, "trail.empty")}</p>
          ) : (
            <ol className="mt-4 space-y-2 text-sm">
              {trail.map((entry) => (
                <li key={entry.id} className="border-l-2 border-line pl-3">
                  <span className="font-semibold">{t(locale, `action.${entry.action}`)}</span>
                  <span className="ml-2 text-ink-faint">
                    {new Date(entry.created_at).toLocaleString("en-PK")}
                  </span>
                  {entry.note ? <p className="text-ink-soft">{entry.note}</p> : null}
                </li>
              ))}
            </ol>
          )}
        </CardBody>
      </Card>
    </AppShell>
  );
}
