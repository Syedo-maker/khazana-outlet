"use client";

import { useEffect, useState } from "react";

import { fetchFile } from "@/lib/market";

/**
 * A photograph behind sign in.
 *
 * An image tag cannot send a bearer token, so the file is fetched and shown
 * from a temporary object URL. The box keeps its shape while loading, so the
 * page does not jump on a slow connection.
 */
export function AuthedImage({
  path,
  token,
  alt,
  className = "",
}: {
  path: string;
  token: string;
  alt: string;
  className?: string;
}) {
  const [source, setSource] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | null = null;
    setSource(null);
    setFailed(false);
    fetchFile(path, token, controller.signal)
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        setSource(objectUrl);
      })
      .catch((cause: unknown) => {
        if (!(cause instanceof DOMException && cause.name === "AbortError")) setFailed(true);
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path, token]);

  return (
    <div className={`aspect-[3/4] overflow-hidden rounded bg-surface-sunk ${className}`}>
      {source ? (
        // eslint-disable-next-line @next/next/no-img-element -- a local object URL
        <img src={source} alt={alt} draggable={false} className="h-full w-full object-cover" />
      ) : failed ? (
        <span className="sr-only">{alt}</span>
      ) : null}
    </div>
  );
}
