"use client";

import { useCallback, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Badge, Card, CardBody, CardHeader, CardTitle, Stat } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";
import { ApiError, api, type Me } from "@/lib/api";
import { DEFAULT_LOCALE, t } from "@/lib/i18n";
import { clearTokens, getAccessToken } from "@/lib/session";

type AiStatus = Awaited<ReturnType<typeof api.aiStatus>>;

/**
 * The Phase 1 home screen.
 *
 * There is no catalogue yet, so this page does the one thing worth doing now:
 * it proves the whole stack end to end. It authenticates against the API,
 * reads the AI gateway status, and exercises every one of the three states the
 * design system provides, so loading, error and empty are real code rather
 * than a promise.
 */
export default function HomePage() {
  const locale = DEFAULT_LOCALE;
  const [me, setMe] = useState<Me | null>(null);
  const [aiStatus, setAiStatus] = useState<AiStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [signedOut, setSignedOut] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const status = await api.aiStatus();
      setAiStatus(status);

      const token = getAccessToken();
      if (!token) {
        setMe(null);
        setSignedOut(true);
        return;
      }

      setMe(await api.me(token));
      setSignedOut(false);
    } catch (cause) {
      if (cause instanceof ApiError && cause.needsSignIn) {
        clearTokens();
        setMe(null);
        setSignedOut(true);
        return;
      }
      setError(cause instanceof Error ? cause.message : t(locale, "error.network"));
    } finally {
      setLoading(false);
    }
  }, [locale]);

  useEffect(() => {
    void load();
  }, [load]);

  const signOut = useCallback(async () => {
    const token = getAccessToken();
    if (token) {
      try {
        await api.signOut(token);
      } catch {
        // Clearing the local tokens matters more than the server round trip
        // succeeding, so a failure here is not surfaced.
      }
    }
    clearTokens();
    setMe(null);
    setSignedOut(true);
  }, []);

  return (
    <AppShell
      locale={locale}
      onSignOut={me ? signOut : undefined}
      userLabel={me?.user.full_name}
    >
      <div className="mb-6">
        <h1 className="text-3xl font-semibold tracking-tight">Phase 1 foundation</h1>
        <p className="mt-2 max-w-prose text-ink-soft">
          Repository, schema, authentication, this design system, the AI gateway
          and the seed data. The marketplace itself arrives in Phase 3 and the
          AI features in Phase 2.
        </p>
      </div>

      {loading ? (
        <Skeleton rows={3} />
      ) : error ? (
        <ErrorState
          title={t(locale, "state.errorTitle")}
          message={error}
          onRetry={() => void load()}
          retryLabel={t(locale, "state.retry")}
        />
      ) : (
        <div className="grid gap-6 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Session</CardTitle>
            </CardHeader>
            <CardBody>
              {me ? (
                <dl className="space-y-2 text-sm">
                  <div className="flex justify-between gap-4">
                    <dt className="text-ink-faint">Name</dt>
                    <dd className="font-semibold">{me.user.full_name}</dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-ink-faint">Phone</dt>
                    <dd className="font-semibold">{me.user.phone}</dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-ink-faint">Role</dt>
                    <dd>
                      <Badge tone={me.is_admin ? "accent" : "neutral"}>{me.user.role}</Badge>
                    </dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-ink-faint">Brands</dt>
                    <dd className="font-semibold">{me.brand_ids.length}</dd>
                  </div>
                </dl>
              ) : signedOut ? (
                <EmptyState
                  title="Not signed in"
                  description="Sign in with your mobile number to see your account."
                  action={
                    <Button onClick={() => (window.location.href = "/login")}>
                      {t(locale, "login.title")}
                    </Button>
                  }
                />
              ) : null}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>AI gateway</CardTitle>
            </CardHeader>
            <CardBody>
              {aiStatus ? (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    <Stat
                      label="Mode"
                      value={aiStatus.mode}
                      note={aiStatus.mode === "offline" ? "Using recorded fixtures" : "Live API"}
                    />
                    <Stat
                      label="Daily cap"
                      value={`$${aiStatus.daily_limit_usd}`}
                      note="Enforced before each call"
                    />
                  </div>
                  <p className="mt-4 text-xs font-semibold uppercase tracking-wide text-ink-faint">
                    Features
                  </p>
                  <ul className="mt-2 flex flex-wrap gap-2">
                    {Object.entries(aiStatus.features).map(([name, enabled]) => (
                      <li key={name}>
                        {/* The label carries the state, not just the colour,
                            so this is readable without colour vision. */}
                        <Badge tone={enabled ? "ok" : "danger"}>
                          {name.replaceAll("_", " ")}: {enabled ? "on" : "off"}
                        </Badge>
                      </li>
                    ))}
                  </ul>
                  <p className="mt-4 text-xs text-ink-faint">
                    Default model {aiStatus.default_model}, bulk model {aiStatus.bulk_model}.
                  </p>
                </>
              ) : (
                <EmptyState title={t(locale, "state.emptyTitle")} />
              )}
            </CardBody>
          </Card>
        </div>
      )}
    </AppShell>
  );
}
