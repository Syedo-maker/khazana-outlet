"use client";

import { useEffect, useState, type ReactNode } from "react";

import { ADMIN_NAV, AppShell, BRAND_NAV, RESELLER_NAV } from "@/components/AppShell";
import { ErrorState, Skeleton } from "@/components/ui/States";
import { ApiError, api, type Me } from "@/lib/api";
import { errorMessage, useLocale } from "@/lib/hooks";
import { type Locale, t } from "@/lib/i18n";
import { clearTokens, getAccessToken, getRefreshToken, saveTokens } from "@/lib/session";

export type Role = Me["user"]["role"];
export type Session = { me: Me; token: string; locale: Locale };

const NAV_BY_ROLE = { reseller: RESELLER_NAV, brand: BRAND_NAV, admin: ADMIN_NAV };

/**
 * Who is signed in, refreshing an expired access token when the refresh token
 * still works. Null means nobody is, and the caller sends the person to /login.
 * Pages outside RoleShell use it too, so an expired session is never shown as
 * a server or network error.
 */
export async function loadSession(): Promise<{ me: Me; token: string } | null> {
  const token = getAccessToken();
  if (token) {
    try {
      return { me: await api.me(token), token };
    } catch (cause) {
      if (!(cause instanceof ApiError) || !cause.needsSignIn) throw cause;
    }
  }

  const refreshToken = getRefreshToken();
  if (!refreshToken) return null;
  try {
    const pair = await api.refresh(refreshToken);
    saveTokens(pair);
    return { me: await api.me(pair.access_token), token: pair.access_token };
  } catch {
    clearTokens();
    return null;
  }
}

/**
 * The frame around every signed in screen.
 *
 * It resolves who is signed in, chooses their navigation and refuses a screen
 * meant for another role. The server enforces all of this as well, so this
 * exists to send people to the right place rather than to protect anything.
 */
export function RoleShell({
  allow,
  children,
}: {
  allow?: Role[];
  children: (session: Session) => ReactNode;
}) {
  const locale = useLocale();
  const [session, setSession] = useState<{ me: Me; token: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    loadSession()
      .then((result) => {
        if (!active) return;
        if (result) setSession(result);
        else window.location.replace("/login");
      })
      .catch((cause: unknown) => {
        if (active) setError(errorMessage(cause));
      });
    return () => {
      active = false;
    };
  }, []);

  const nav = session ? NAV_BY_ROLE[session.me.user.role] : [];

  return (
    <AppShell locale={locale} nav={nav} userLabel={session?.me.user.full_name}>
      {error ? (
        <ErrorState title={t(locale, "state.errorTitle")} message={error} />
      ) : !session ? (
        <Skeleton rows={5} />
      ) : allow && !allow.includes(session.me.user.role) ? (
        <ErrorState
          title={t(locale, "access.deniedTitle")}
          message={t(locale, "access.deniedBody")}
        />
      ) : (
        children({ ...session, locale })
      )}
    </AppShell>
  );
}
