// Load test for the catalogue and search, the two reads every reseller makes.
//
// Run against a stack with seed data and OTP_DEV_ECHO on (development or
// staging, never production):
//
//   .\scripts\dev.ps1 loadtest              50 users browsing, with pauses
//   .\scripts\dev.ps1 loadtest THINK=0 VUS=20   capacity: no pauses
//
// or directly, from the repository root:
//
//   docker run --rm -i --network host -v "${PWD}/loadtest:/scripts" \
//     -e BASE_URL=http://localhost:8000 grafana/k6:1.4.2 run /scripts/catalog-search.js
//
// One reseller signs in once in setup() and every virtual user shares that
// token. Signing in per user would hit the OTP limit of five codes an hour per
// number, which is the point of that limit, not something to load test.
//
// The thresholds are the budget for a buyer on a slow phone connection: the
// server's share of a page has to be small, because the network takes most of
// it. Results are recorded in docs/performance.md.

import http from "k6/http";
import { check, group, sleep } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const PHONE = __ENV.PHONE || "03020000000";

export const options = {
  scenarios: {
    browsing: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: __ENV.RAMP || "30s", target: Number(__ENV.VUS || 50) },
        { duration: __ENV.HOLD || "1m", target: Number(__ENV.VUS || 50) },
        { duration: "15s", target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    "http_req_duration{name:catalog}": ["p(95)<500"],
    "http_req_duration{name:search}": ["p(95)<500"],
    "http_req_duration{name:lot}": ["p(95)<500"],
  },
};

const QUERIES = ["lawn", "kurta", "shirt", "jeans", "kids", "unstitched", "winter", "cotton"];
const SORTS = ["newest", "price_low", "discount"];
// THINK=0 removes the pauses between requests, which turns the browsing test
// into a capacity test: how many requests a second before the budget breaks.
const THINK = Number(__ENV.THINK ?? 1);
const pause = (seconds) => sleep(seconds * THINK);

export function setup() {
  const headers = { "Content-Type": "application/json" };
  const sent = http.post(`${BASE_URL}/auth/otp/request`, JSON.stringify({ phone: PHONE }), {
    headers,
  });
  check(sent, { "otp requested": (r) => r.status === 200 || r.status === 202 });
  const code = sent.json("dev_code");
  if (!code) {
    throw new Error(`No dev_code in the OTP response (status ${sent.status}). Is OTP_DEV_ECHO on?`);
  }
  const verified = http.post(
    `${BASE_URL}/auth/otp/verify`,
    JSON.stringify({ phone: PHONE, code }),
    { headers },
  );
  const token = verified.json("access_token");
  if (!token) throw new Error(`Sign in failed: ${verified.status} ${verified.body}`);

  const first = http.get(`${BASE_URL}/catalog?limit=50`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const items = first.json("items") || [];
  return { token, lotIds: items.map((item) => item.lot.id) };
}

export default function (data) {
  const params = (name) => ({
    headers: { Authorization: `Bearer ${data.token}` },
    tags: { name },
  });

  group("browse", () => {
    const offset = Math.floor(Math.random() * 3) * 20;
    const list = http.get(`${BASE_URL}/catalog?limit=20&offset=${offset}`, params("catalog"));
    check(list, { "catalog 200": (r) => r.status === 200 });
  });
  pause(Math.random() * 2 + 1);

  group("search", () => {
    const q = QUERIES[Math.floor(Math.random() * QUERIES.length)];
    const sort = SORTS[Math.floor(Math.random() * SORTS.length)];
    const found = http.get(
      `${BASE_URL}/catalog/search?q=${encodeURIComponent(q)}&sort=${sort}&limit=20`,
      params("search"),
    );
    check(found, { "search 200": (r) => r.status === 200 });
  });
  pause(Math.random() * 2 + 1);

  if (data.lotIds.length) {
    group("open a lot", () => {
      const id = data.lotIds[Math.floor(Math.random() * data.lotIds.length)];
      const lot = http.get(`${BASE_URL}/catalog/${id}`, params("lot"));
      check(lot, { "lot 200": (r) => r.status === 200 });
    });
  }
  pause(Math.random() * 3 + 1);
}
