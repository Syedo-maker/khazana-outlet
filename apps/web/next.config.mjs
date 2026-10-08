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
        ],
      },
    ];
  },
};

export default nextConfig;
