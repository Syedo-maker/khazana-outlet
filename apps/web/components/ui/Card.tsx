import type { ReactNode } from "react";

/**
 * Composable rather than configured.
 *
 * `<Card><CardHeader>...</CardHeader><CardBody>...</CardBody></Card>` instead
 * of a Card that takes a title prop, a headerVariant and a content node. The
 * second shape always grows a tenth prop.
 */

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <section
      className={`rounded-lg border border-line bg-surface-alt shadow-card ${className}`}
    >
      {children}
    </section>
  );
}

export function CardHeader({ children }: { children: ReactNode }) {
  return <header className="border-b border-line px-4 py-3">{children}</header>;
}

export function CardTitle({ children, as: Tag = "h2" }: { children: ReactNode; as?: "h2" | "h3" }) {
  return <Tag className="text-lg font-semibold">{children}</Tag>;
}

export function CardBody({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`px-4 py-4 ${className}`}>{children}</div>;
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "ok" | "warn" | "danger" | "accent";
}) {
  const tones = {
    neutral: "bg-surface-sunk text-ink-soft",
    ok: "bg-brand-subtle text-ok",
    warn: "bg-accent-subtle text-warn",
    danger: "bg-[#fdecec] text-danger",
    accent: "bg-accent-subtle text-accent",
  } as const;

  return (
    <span
      className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-semibold ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

/**
 * A labelled statistic.
 *
 * `tone` never carries meaning on its own: the label and value always say what
 * the number is, so the component is readable without colour vision.
 */
export function Stat({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note?: string;
}) {
  return (
    <div className="rounded-lg border border-line bg-surface px-4 py-3">
      <dt className="text-xs font-semibold uppercase tracking-wide text-ink-faint">{label}</dt>
      <dd className="mt-1 text-2xl font-semibold">{value}</dd>
      {note ? <p className="mt-1 text-xs text-ink-faint">{note}</p> : null}
    </div>
  );
}
