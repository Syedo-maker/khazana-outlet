"use client";

import { useId, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { TextInput } from "@/components/ui/Field";
import {
  ApiError,
  catalog,
  type ManifestImport,
  type ManifestLine,
  type ManifestLineOut,
} from "@/lib/api";
import { type Locale, t } from "@/lib/i18n";

type Props = {
  lotId: string;
  lotTotalPieces: number;
  lines: ManifestLineOut[];
  token: string;
  locale: Locale;
  /** False once the lot is past draft, when the manifest is fixed. */
  editable: boolean;
  onSaved: () => void;
};

type Row = { key: string; size: string; color: string; pieces: string };

let rowCounter = 0;
function newKey(): string {
  rowCounter += 1;
  return `row-${rowCounter}`;
}

function toRows(lines: ManifestLineOut[]): Row[] {
  if (lines.length === 0) {
    return [{ key: newKey(), size: "", color: "", pieces: "" }];
  }
  return lines.map((line) => ({
    key: line.id,
    size: line.size,
    color: line.color,
    pieces: String(line.pieces),
  }));
}

/**
 * The manifest editor.
 *
 * The whole design follows from one rule: the lines have to add up to the lot
 * total, and a brand should never discover that they do not after pressing
 * save. So the running total is always on screen, the difference is stated in
 * pieces rather than as a colour, and save is refused locally when it would
 * fail at the server anyway.
 *
 * The totals line is an aria-live region. Someone using a screen reader is
 * the person most likely to type a piece count into the wrong row, and a
 * number that only changes visually tells them nothing.
 *
 * Rows are keyed by a generated id rather than by index, because a React list
 * keyed by index loses the focused input whenever a row above it is removed.
 */
export function ManifestEditor({
  lotId,
  lotTotalPieces,
  lines,
  token,
  locale,
  editable,
  onSaved,
}: Props) {
  const baseId = useId();
  const fileRef = useRef<HTMLInputElement>(null);
  const [rows, setRows] = useState<Row[]>(() => toRows(lines));
  const [saving, setSaving] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [proposal, setProposal] = useState<ManifestImport | null>(null);

  const total = useMemo(
    () => rows.reduce((sum, row) => sum + (Number.parseInt(row.pieces, 10) || 0), 0),
    [rows],
  );
  const difference = total - lotTotalPieces;
  const balanced = difference === 0 && total > 0;

  const filled = rows.filter(
    (row) => row.size.trim() !== "" && row.color.trim() !== "" && row.pieces.trim() !== "",
  );
  const canSave = editable && balanced && filled.length === rows.length && rows.length > 0;

  function update(key: string, patch: Partial<Row>): void {
    setSaved(false);
    setRows((current) =>
      current.map((row) => (row.key === key ? { ...row, ...patch } : row)),
    );
  }

  function addRow(): void {
    setSaved(false);
    setRows((current) => [...current, { key: newKey(), size: "", color: "", pieces: "" }]);
  }

  function removeRow(key: string): void {
    setSaved(false);
    setRows((current) =>
      current.length === 1 ? current : current.filter((row) => row.key !== key),
    );
  }

  async function save(): Promise<void> {
    setSaving(true);
    setError(null);
    const payload: ManifestLine[] = rows.map((row) => ({
      size: row.size.trim(),
      color: row.color.trim(),
      pieces: Number.parseInt(row.pieces, 10) || 0,
    }));
    try {
      await catalog.setManifest(token, lotId, payload);
      setSaved(true);
      onSaved();
    } catch (cause) {
      // The server checks the same rule and knows about duplicates and the
      // line limit, so its message is better than anything guessed here.
      setError(cause instanceof ApiError ? cause.message : "Could not save the manifest.");
    } finally {
      setSaving(false);
    }
  }

  async function importFile(file: File): Promise<void> {
    setImporting(true);
    setError(null);
    try {
      const outcome = await catalog.importManifest(token, lotId, file);
      setProposal(outcome);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not read that file.");
    } finally {
      setImporting(false);
      // Clear the input so selecting the same file again still fires onChange.
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  function acceptProposal(): void {
    if (!proposal) return;
    setRows(
      proposal.rows.map((row) => ({
        key: newKey(),
        size: row.size,
        color: row.color,
        pieces: String(row.pieces),
      })),
    );
    setProposal(null);
    setSaved(false);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t(locale, "manifest.title")}</CardTitle>
      </CardHeader>
      <CardBody>
        <p className="mb-4 max-w-prose text-sm text-ink-soft">{t(locale, "manifest.intro")}</p>

        {proposal ? (
          <div className="mb-4 rounded-lg border border-accent bg-accent-subtle px-4 py-3">
            <p className="text-sm font-semibold">
              {t(locale, "manifest.importReview", {
                count: proposal.rows.length,
                pieces: proposal.total_pieces,
              })}
            </p>
            {proposal.warnings.length > 0 ? (
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
                {proposal.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            ) : null}
            <div className="mt-3 flex flex-wrap gap-2">
              <Button size="sm" onClick={acceptProposal}>
                {t(locale, "manifest.importAccept")}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setProposal(null)}>
                {t(locale, "manifest.importDiscard")}
              </Button>
            </div>
          </div>
        ) : null}

        <div className="overflow-x-auto">
          <table className="w-full min-w-[32rem] border-collapse text-sm">
            <thead>
              <tr className="border-b border-line text-left">
                <th scope="col" className="pb-2 pr-3 font-semibold">
                  {t(locale, "manifest.size")}
                </th>
                <th scope="col" className="pb-2 pr-3 font-semibold">
                  {t(locale, "manifest.colour")}
                </th>
                <th scope="col" className="pb-2 pr-3 font-semibold">
                  {t(locale, "manifest.pieces")}
                </th>
                <th scope="col" className="pb-2">
                  <span className="sr-only">{t(locale, "manifest.removeLine")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={row.key} className="border-b border-line/60">
                  <td className="py-2 pr-3">
                    <label className="sr-only" htmlFor={`${baseId}-size-${row.key}`}>
                      {`${t(locale, "manifest.size")} ${index + 1}`}
                    </label>
                    <TextInput
                      id={`${baseId}-size-${row.key}`}
                      value={row.size}
                      disabled={!editable}
                      inputMode="text"
                      autoComplete="off"
                      onChange={(event) => update(row.key, { size: event.target.value })}
                    />
                  </td>
                  <td className="py-2 pr-3">
                    <label className="sr-only" htmlFor={`${baseId}-colour-${row.key}`}>
                      {`${t(locale, "manifest.colour")} ${index + 1}`}
                    </label>
                    <TextInput
                      id={`${baseId}-colour-${row.key}`}
                      value={row.color}
                      disabled={!editable}
                      autoComplete="off"
                      onChange={(event) => update(row.key, { color: event.target.value })}
                    />
                  </td>
                  <td className="py-2 pr-3">
                    <label className="sr-only" htmlFor={`${baseId}-pieces-${row.key}`}>
                      {`${t(locale, "manifest.pieces")} ${index + 1}`}
                    </label>
                    <TextInput
                      id={`${baseId}-pieces-${row.key}`}
                      value={row.pieces}
                      disabled={!editable}
                      // A numeric keypad on Android, which is what most
                      // brands will be using to type these in.
                      inputMode="numeric"
                      pattern="[0-9]*"
                      onChange={(event) =>
                        update(row.key, { pieces: event.target.value.replace(/[^0-9]/g, "") })
                      }
                    />
                  </td>
                  <td className="py-2 align-middle">
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={!editable || rows.length === 1}
                      onClick={() => removeRow(row.key)}
                      aria-label={`${t(locale, "manifest.removeLine")} ${index + 1}`}
                    >
                      &times;
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* The running total. Announced, not merely shown. */}
        <div
          aria-live="polite"
          className="mt-4 flex flex-wrap items-baseline justify-between gap-2 rounded-lg bg-surface-sunk px-4 py-3"
        >
          <p className="text-sm">
            <span className="font-semibold">{t(locale, "manifest.total")}:</span> {total}
            <span className="text-ink-faint">
              {" / "}
              {lotTotalPieces} {t(locale, "manifest.lotTotal").toLowerCase()}
            </span>
          </p>
          <p className={`text-sm font-semibold ${balanced ? "text-ok" : "text-danger"}`}>
            {balanced
              ? t(locale, "manifest.balanced")
              : difference < 0
                ? t(locale, "manifest.short", { count: Math.abs(difference) })
                : t(locale, "manifest.over", { count: difference })}
          </p>
        </div>

        {error ? (
          <p role="alert" className="mt-3 text-sm font-semibold text-danger">
            {error}
          </p>
        ) : null}
        {saved ? (
          <p role="status" className="mt-3 text-sm font-semibold text-ok">
            {t(locale, "manifest.saved")}
          </p>
        ) : null}

        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="secondary" size="sm" disabled={!editable} onClick={addRow}>
            {t(locale, "manifest.addLine")}
          </Button>
          <Button size="sm" disabled={!canSave || saving} onClick={save}>
            {t(locale, "manifest.save")}
          </Button>

          <label
            className={
              "inline-flex min-h-touch cursor-pointer items-center rounded px-3 text-sm " +
              "font-semibold text-accent underline " +
              (editable && !importing ? "" : "pointer-events-none opacity-50")
            }
          >
            {importing ? t(locale, "manifest.importing") : t(locale, "manifest.import")}
            <input
              ref={fileRef}
              type="file"
              className="sr-only"
              accept=".csv,.tsv,.txt,.xlsx"
              disabled={!editable || importing}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void importFile(file);
              }}
            />
          </label>
        </div>
      </CardBody>
    </Card>
  );
}
