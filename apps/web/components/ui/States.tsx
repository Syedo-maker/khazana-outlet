import type { ReactNode } from "react";

import { Button } from "./Button";

/**
 * Loading, empty and error states, built once.
 *
 * Every data driven screen in this application has all three. A screen that
 * renders nothing while it waits, or a blank area when there is no data, is
 * the most common way an otherwise finished interface feels broken.
 */

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div aria-busy="true" aria-live="polite" className="space-y-3">
      <span className="sr-only">Loading</span>
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={index}
          className="h-12 animate-pulse rounded bg-surface-sunk"
          // Varying widths so it reads as content rather than as a grid of
          // identical grey bars.
          style={{ width: `${100 - index * 7}%` }}
        />
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div role="status" className="rounded-lg border border-dashed border-line px-6 py-12 text-center">
      <h3 className="text-base font-semibold">{title}</h3>
      {description ? <p className="mx-auto mt-2 max-w-prose text-sm text-ink-soft">{description}</p> : null}
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  );
}

export function ErrorState({
  title,
  message,
  onRetry,
  retryLabel = "Try again",
}: {
  title: string;
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-danger bg-[#fdecec] px-4 py-4 text-ink"
    >
      <h3 className="text-base font-semibold text-danger">{title}</h3>
      <p className="mt-1 text-sm">{message}</p>
      {onRetry ? (
        <Button variant="secondary" size="sm" className="mt-3" onClick={onRetry}>
          {retryLabel}
        </Button>
      ) : null}
    </div>
  );
}
