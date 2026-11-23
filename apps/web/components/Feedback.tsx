import type { ReactNode } from "react";

import { Badge } from "@/components/ui/Card";
import { ErrorState, Skeleton } from "@/components/ui/States";
import { type Locale, t } from "@/lib/i18n";
import type { OrderStatus } from "@/lib/market";

export function ActionError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" className="mt-2 text-sm font-semibold text-danger">
      {message}
    </p>
  );
}

export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle ? <p className="mt-1 text-sm text-ink-soft">{subtitle}</p> : null}
      </div>
      {action}
    </header>
  );
}

/** Loading and failure for a section, so each page states them only once. */
export function Loaded<T>({
  resource,
  locale,
  rows = 4,
  children,
}: {
  resource: { data: T | null; error: string | null; reload: () => Promise<void> };
  locale: Locale;
  rows?: number;
  children: (data: T) => ReactNode;
}) {
  if (resource.error) {
    return (
      <ErrorState
        title={t(locale, "state.errorTitle")}
        message={resource.error}
        onRetry={() => void resource.reload()}
        retryLabel={t(locale, "state.retry")}
      />
    );
  }
  if (resource.data === null) return <Skeleton rows={rows} />;
  return <>{children(resource.data)}</>;
}

const ORDER_TONES: Record<OrderStatus, "neutral" | "ok" | "warn" | "danger" | "accent"> = {
  created: "neutral",
  awaiting_payment: "warn",
  paid: "accent",
  preparing: "accent",
  shipped: "accent",
  delivered: "accent",
  confirmed: "ok",
  disputed: "danger",
  cancelled: "neutral",
  refunded: "neutral",
};

export function OrderBadge({ status, locale }: { status: OrderStatus; locale: Locale }) {
  return <Badge tone={ORDER_TONES[status]}>{t(locale, `order.status.${status}`)}</Badge>;
}
