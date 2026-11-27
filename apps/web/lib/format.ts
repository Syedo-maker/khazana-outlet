/**
 * Wrap text in Unicode isolate marks so it reads left to right even inside a
 * right to left Urdu sentence. Without them "2027-02-28" shows as "28-02-2027"
 * and an amount followed by a percentage swaps places. The marks are invisible.
 */
export function ltr(text: string): string {
  return `\u2066${text}\u2069`;
}

export function pkr(amount: number): string {
  return ltr(`${Math.round(amount).toLocaleString("en-PK")} PKR`);
}

export function dateTime(value: string | null | undefined): string {
  if (!value) return "";
  return ltr(
    new Date(value).toLocaleString("en-PK", {
      dateStyle: "medium",
      timeStyle: "short",
    }),
  );
}

/** A calendar date in Pakistan time, for invoices and periods. */
export function day(value: string | Date | null | undefined): string {
  if (!value) return "";
  return ltr(
    new Date(value).toLocaleDateString("en-PK", { dateStyle: "medium", timeZone: "Asia/Karachi" }),
  );
}
