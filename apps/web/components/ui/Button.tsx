import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  /**
   * Shows a busy state and blocks the click. Separate from `disabled` because
   * the two mean different things to a screen reader: busy is temporary,
   * disabled is not available.
   */
  loading?: boolean;
  loadingLabel?: string;
  children: ReactNode;
};

const base =
  "inline-flex items-center justify-center gap-2 min-h-touch rounded px-4 py-2 " +
  "text-sm font-semibold transition-colors disabled:opacity-60 " +
  "disabled:cursor-not-allowed";

const variants: Record<Variant, string> = {
  primary: "bg-brand text-white hover:bg-brand-hover border border-brand",
  secondary: "bg-transparent text-ink border border-line hover:bg-surface-alt",
  ghost: "bg-transparent text-ink hover:bg-surface-alt border border-transparent",
  danger: "bg-danger text-white hover:opacity-90 border border-danger",
};

const sizes: Record<Size, string> = {
  sm: "min-h-touch px-3 text-xs",
  md: "",
};

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  loadingLabel = "Working",
  disabled,
  className = "",
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      // An explicit type, because the HTML default is "submit" and a button
      // inside a form without one submits it by accident.
      type={rest.type ?? "button"}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={`${base} ${variants[variant]} ${sizes[size]} ${className}`}
      {...rest}
    >
      {loading ? (
        <>
          <span
            aria-hidden="true"
            className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"
          />
          <span>{loadingLabel}</span>
        </>
      ) : (
        children
      )}
    </button>
  );
}
