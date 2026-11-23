"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

import { ApiError } from "./api";
import { DEFAULT_LOCALE, directionFor, isLocale, type Locale } from "./i18n";

const LOCALE_KEY = "khazana.locale";
const listeners = new Set<() => void>();

function storedLocale(): Locale {
  try {
    const value = window.localStorage.getItem(LOCALE_KEY);
    return value && isLocale(value) ? value : DEFAULT_LOCALE;
  } catch {
    return DEFAULT_LOCALE;
  }
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The chosen language, remembered on this device. */
export function useLocale(): Locale {
  const locale = useSyncExternalStore(subscribe, storedLocale, () => DEFAULT_LOCALE);

  useEffect(() => {
    document.documentElement.lang = locale === "ur" ? "ur" : "en";
    document.documentElement.dir = directionFor(locale);
  }, [locale]);

  return locale;
}

export function setLocale(locale: Locale): void {
  try {
    window.localStorage.setItem(LOCALE_KEY, locale);
  } catch {
    // Blocked storage only means the choice is not remembered.
  }
  listeners.forEach((listener) => listener());
}

export function errorMessage(cause: unknown): string {
  return cause instanceof ApiError ? cause.message : "That did not work. Try again.";
}

/** Load data, with the three states every screen has to show. */
export function useResource<T>(load: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const latest = useRef(0);

  const reload = useCallback(async () => {
    const request = ++latest.current;
    setLoading(true);
    setError(null);
    try {
      const result = await load();
      if (request === latest.current) setData(result);
    } catch (cause) {
      if (request === latest.current) setError(errorMessage(cause));
    } finally {
      if (request === latest.current) setLoading(false);
    }
  }, [load]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, error, loading, reload, setData };
}

/** Run one user action, keeping its busy state and its error together. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async (work: () => Promise<unknown>): Promise<boolean> => {
    setBusy(true);
    setError(null);
    try {
      await work();
      return true;
    } catch (cause) {
      setError(errorMessage(cause));
      return false;
    } finally {
      setBusy(false);
    }
  }, []);

  return { busy, error, run, setError };
}
