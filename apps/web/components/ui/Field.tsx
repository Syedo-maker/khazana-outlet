import type { InputHTMLAttributes, ReactNode, Ref } from "react";

type FieldProps = {
  /** Required: an input without a label is not usable with a screen reader. */
  label: string;
  htmlFor: string;
  hint?: string;
  error?: string | null;
  children: ReactNode;
};

/**
 * Label, hint and error around one control.
 *
 * The hint and the error are wired to the input through aria-describedby by
 * the caller using the ids this component generates, which is the part most
 * hand rolled form markup gets wrong.
 */
export function Field({ label, htmlFor, hint, error, children }: FieldProps) {
  return (
    <div className="mb-4">
      <label htmlFor={htmlFor} className="mb-1 block text-sm font-semibold">
        {label}
      </label>
      {hint ? (
        <p id={`${htmlFor}-hint`} className="mb-1 text-xs text-ink-faint">
          {hint}
        </p>
      ) : null}
      {children}
      {error ? (
        <p
          id={`${htmlFor}-error`}
          // Announced the moment it appears, rather than only being visible.
          role="alert"
          className="mt-1 text-sm font-semibold text-danger"
        >
          {error}
        </p>
      ) : null}
    </div>
  );
}

type TextInputProps = InputHTMLAttributes<HTMLInputElement> & {
  id: string;
  hasHint?: boolean;
  hasError?: boolean;
  /**
   * Taken as a normal prop, which React 19 supports for function components.
   * Needed so a form can move focus to this input, for example after the OTP
   * step changes and the previous control disappears.
   */
  ref?: Ref<HTMLInputElement>;
};

export function TextInput({
  id,
  hasHint = false,
  hasError = false,
  className = "",
  ref,
  ...rest
}: TextInputProps) {
  const describedBy =
    [hasHint ? `${id}-hint` : null, hasError ? `${id}-error` : null]
      .filter(Boolean)
      .join(" ") || undefined;

  return (
    <input
      id={id}
      ref={ref}
      aria-invalid={hasError || undefined}
      aria-describedby={describedBy}
      className={
        "min-h-touch w-full rounded border bg-surface px-3 py-2 text-base " +
        "placeholder:text-ink-faint " +
        (hasError ? "border-danger " : "border-line ") +
        className
      }
      {...rest}
    />
  );
}
