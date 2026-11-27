"use client";

import { LegalPage, type LegalSection } from "@/components/LegalPage";

// Keep in step with TERMS_VERSION in apps/api/src/khazana/legal.py.
const VERSION = "2026-11-beta";

const SECTIONS: LegalSection[] = [
  {
    heading: "A beta, by invitation",
    body: (
      <p>
        Khazana Outlet is a private beta that connects brands selling surplus stock with verified
        resellers. Access is by invitation only. The service is provided as it is, may change or
        stop at any time, and may have mistakes. By using it you accept these terms.
      </p>
    ),
  },
  {
    heading: "Who sells, who pays",
    body: (
      <ul className="list-disc space-y-1 ps-5">
        <li>
          Each sale is between the brand and the reseller. Khazana Outlet lists the stock, records
          the order and helps when something goes wrong; it is not the seller.
        </li>
        <li>
          In the beta the reseller pays the brand&apos;s own courier in cash on delivery. Khazana
          Outlet never receives or holds the buyer&apos;s money.
        </li>
        <li>
          The brand is responsible for the goods matching the listing and its manifest, for
          delivery, and for any refund it agrees to.
        </li>
        <li>
          A reseller may refuse a delivery at the door; the order is then cancelled and nothing is
          owed.
        </li>
      </ul>
    ),
  },
  {
    heading: "Problems with an order",
    body: (
      <p>
        A reseller can report a problem within the time shown on the order after delivery. The
        Khazana team looks at what both sides say and records the outcome, including any refund
        the brand makes directly to the reseller. The team&apos;s decision is about the record on
        the platform; it does not replace either side&apos;s rights under the law.
      </p>
    ),
  },
  {
    heading: "Commission",
    body: (
      <p>
        A brand pays Khazana Outlet the commission rate agreed with it on each order the reseller
        confirms, less any refund it made. The commission is invoiced on the first of each month
        for the month before and is due by the date on the invoice. Nothing is owed on cancelled
        or fully refunded orders.
      </p>
    ),
  },
  {
    heading: "Accounts and verification",
    body: (
      <ul className="list-disc space-y-1 ps-5">
        <li>An invite link is for the person it was sent to. Do not share it.</li>
        <li>
          The Khazana team verifies every reseller business and every brand before they can trade,
          and may suspend an account that breaks these terms or puts others at risk.
        </li>
        <li>Give true details. Listing counterfeit, stolen or prohibited goods is not allowed.</li>
      </ul>
    ),
  },
  {
    heading: "AI drafts",
    body: (
      <p>
        Some features write drafts with AI: listing text, prices inside a brand&apos;s own band,
        captions and answers. Drafts can be wrong. A brand approves every listing before it goes
        live, and AI never decides a payment, an approval or a ban. When the daily AI budget is
        used up, the features work by hand until the next day.
      </p>
    ),
  },
  {
    heading: "Liability",
    body: (
      <p>
        To the extent the law allows, Khazana Outlet is not liable for losses from a sale between
        a brand and a reseller, from goods, delivery or payment between them, or from the beta
        being unavailable. Nothing in these terms limits liability that cannot be limited by law.
      </p>
    ),
  },
  {
    heading: "Changes and law",
    body: (
      <p>
        These terms will change before any public launch, and you will be asked to accept the new
        version. They are governed by the laws of Pakistan.
      </p>
    ),
  },
];

export default function TermsPage() {
  return (
    <LegalPage
      title="Beta terms of use"
      version={VERSION}
      summaryKey="legal.termsSummary"
      sections={SECTIONS}
    />
  );
}
