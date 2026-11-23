"use client";

import { fetchFile } from "@/lib/market";

export function AuthedDocumentLink({
  token,
  documentId,
  label,
}: {
  token: string;
  documentId: string;
  label: string;
}) {
  return (
    <button
      type="button"
      className="min-h-touch text-left font-semibold text-accent underline"
      onClick={() => {
        void fetchFile(`/admin/documents/${documentId}`, token).then((file) => {
          window.open(URL.createObjectURL(file), "_blank", "noopener");
        });
      }}
    >
      {label}
    </button>
  );
}
