export function pkr(amount: number): string {
  return `${Math.round(amount).toLocaleString("en-PK")} PKR`;
}

export function dateTime(value: string | null | undefined): string {
  if (!value) return "";
  return new Date(value).toLocaleString("en-PK", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}
