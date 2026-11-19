"use client";

import type { ReactNode } from "react";

import { PageHeader } from "@/components/Feedback";
import { RoleShell, type Session } from "@/components/RoleShell";

/** The admin panel is an internal tool, so its own copy is English only. */
export function AdminPage({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: (session: Session) => ReactNode;
}) {
  return (
    <RoleShell allow={["admin"]}>
      {(session) => (
        <>
          <PageHeader title={title} subtitle={subtitle} />
          {children(session)}
        </>
      )}
    </RoleShell>
  );
}
