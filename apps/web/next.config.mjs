const API_ORIGIN = new URL(process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").origin;

/**
 * Content Security Policy for the production build.
 *
 * The page may talk to itself and to the API, and nothing else: an injected
 * script cannot send a session token to another host, load code from one, or
 * frame the app. Inline scripts and styles stay allowed because Next.js emits
 * both; a nonce based policy is the next step if that ever matters more than
 * static rendering. The development server needs eval and a websocket for hot
 * reload, so the policy is only sent by the production build.
 */
const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  `img-src 'self' data: blob: ${API_ORIGIN}`,
  "font-src 'self' data:",
  `connect-src 'self' ${API_ORIGIN}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const PRODUCTION = process.env.NODE_ENV === "production";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Phone first audience on metered data: ship the smallest possible payload.
  productionBrowserSourceMaps: false,
  images: {
    // Lot photographs are served from object storage with a CDN in front.
    // Remote patterns are added in Phase 3 when the storage host is decided.
    remotePatterns: [],
    formats: ["image/webp"],
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
          ...(PRODUCTION ? [{ key: "Content-Security-Policy", value: CSP }] : []),
        ],
      },
    ];
  },
};

export default nextConfig;
