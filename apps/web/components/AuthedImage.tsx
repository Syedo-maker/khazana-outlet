"use client";

import { useEffect, useRef, useState } from "react";

import { fetchFile } from "@/lib/market";

/**
 * A photograph behind sign in.
 *
 * An image tag cannot send a bearer token, so the file is fetched and shown
 * from a temporary object URL. The box keeps its shape while loading, so the
 * page does not jump on a slow connection.
 *
 * Fetching waits until the box is about to scroll into view. A catalogue page
 * of twenty cards on 3G otherwise spends its first seconds downloading photos
 * nobody has scrolled to, and the native `loading="lazy"` cannot help because
 * the request is made by script, not by the image tag.
 */
export function AuthedImage({
  path,
  token,
  alt,
  className = "",
  size = "full",
}: {
  path: string;
  token: string;
  alt: string;
  className?: string;
  /** `thumb` asks for the 400 pixel copy, for cards and lists. */
  size?: "full" | "thumb";
}) {
  const box = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const [source, setSource] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const element = box.current;
    if (!element || visible) return;
    if (typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      // Start a little before the box arrives, so a steady scroll rarely
      // reaches an empty frame.
      { rootMargin: "300px 0px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [visible]);

  useEffect(() => {
    if (!visible) return;
    const controller = new AbortController();
    let objectUrl: string | null = null;
    setSource(null);
    setFailed(false);
    const url = size === "thumb" ? `${path}${path.includes("?") ? "&" : "?"}size=thumb` : path;
    fetchFile(url, token, controller.signal)
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
  }, [path, token, size, visible]);

  return (
    <div ref={box} className={`aspect-[3/4] overflow-hidden rounded bg-surface-sunk ${className}`}>
      {source ? (
        // eslint-disable-next-line @next/next/no-img-element -- a local object URL
        <img src={source} alt={alt} draggable={false} className="h-full w-full object-cover" />
      ) : failed ? (
        <span className="sr-only">{alt}</span>
      ) : null}
    </div>
  );
}
