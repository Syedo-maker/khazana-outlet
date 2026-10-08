/**
 * Token storage for the Phase 1 shell.
 *
 * Honest limitation, stated here rather than discovered later: tokens are held
 * in memory and mirrored to sessionStorage so a page refresh does not sign the
 * user out. sessionStorage is readable by any script on the origin, so this is
 * acceptable for an invitation only B2B beta and is not the final answer.
 *
 * Phase 3 moves the refresh token to an httpOnly, Secure, SameSite cookie set
 * by the API, which is the only way to keep it away from page scripts. That
 * change is isolated to this file and lib/api.ts by design.
 */

import type { TokenPair } from "./api";

const ACCESS_KEY = "khazana.access";
const REFRESH_KEY = "khazana.refresh";

let accessToken: string | null = null;

function storage(): Storage | null {
  // Private browsing, blocked site data and server rendering all make this
  // throw or be undefined, so every access is guarded.
  try {
    if (typeof window === "undefined") return null;
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function saveTokens(pair: TokenPair): void {
  accessToken = pair.access_token;
  const store = storage();
  if (!store) return;
  try {
    store.setItem(ACCESS_KEY, pair.access_token);
    store.setItem(REFRESH_KEY, pair.refresh_token);
  } catch {
    // Out of quota or blocked. The in memory token still works for this page.
  }
}

export function getAccessToken(): string | null {
  if (accessToken) return accessToken;
  const store = storage();
  if (!store) return null;
  try {
    accessToken = store.getItem(ACCESS_KEY);
  } catch {
    accessToken = null;
  }
  return accessToken;
}

export function getRefreshToken(): string | null {
  const store = storage();
  if (!store) return null;
  try {
    return store.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
}

export function clearTokens(): void {
  accessToken = null;
  const store = storage();
  if (!store) return;
  try {
    store.removeItem(ACCESS_KEY);
    store.removeItem(REFRESH_KEY);
  } catch {
    // Nothing useful to do; the in memory token is already gone.
  }
}
