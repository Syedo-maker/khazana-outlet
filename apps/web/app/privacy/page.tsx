"use client";

import { LegalPage, type LegalSection } from "@/components/LegalPage";

// Keep in step with TERMS_VERSION in apps/api/src/khazana/legal.py.
const VERSION = "2026-11-beta";

const SECTIONS: LegalSection[] = [
  {
    heading: "This is a beta",
    body: (
      <p>
        Khazana Outlet is in a private, invite only beta. It is run by a small team, without a
        registered company yet, to test whether brands and resellers find it useful. This notice
        says what the beta collects, why, and what you can ask us to do with it. It will be
        replaced by a full privacy policy before any public launch, and you will be asked to accept
        the new version.
      </p>
    ),
  },
  {
    heading: "What we collect",
    body: (
      <ul className="list-disc space-y-1 ps-5">
        <li>Your mobile number and name, which identify your account.</li>
        <li>
          For resellers: your shop or business name, city, and anything you add to your business
          profile, such as an NTN or shop address.
        </li>
        <li>
          For brands: the brand&apos;s details, the verification documents you upload, your
          listings and their photographs, and your commercial settings.
        </li>
        <li>
          Orders: what was bought, the delivery address and phone number, the courier and tracking
          number, and what happened to the delivery.
        </li>
        <li>Messages you send to the assistant, and the drafts it writes for you.</li>
        <li>
          Technical records: sign in times, the network address and browser of each request, and
          an audit log of important actions, kept to protect accounts and investigate problems.
        </li>
      </ul>
    ),
  },
  {
    heading: "What we do not collect",
    body: (
      <p>
        We never take card, wallet or bank payments from buyers: in the beta, buyers pay the
        brand&apos;s own courier in cash on delivery. We use no advertising or tracking cookies.
        Your browser keeps your sign in and your language choice in its own storage on your
        device.
      </p>
    ),
  },
  {
    heading: "Who sees it",
    body: (
      <ul className="list-disc space-y-1 ps-5">
        <li>
          A brand sees a buyer&apos;s business name, delivery address and phone number once there
          is an order to send, because it needs them to deliver.
        </li>
        <li>Brands never see each other&apos;s data, and buyers never see a brand&apos;s commission.</li>
        <li>The Khazana team sees what it needs to verify accounts, review listings and settle problems.</li>
        <li>
          AI features send the text and photographs involved to Anthropic, the provider of the
          Claude models, to produce a draft. Anthropic processes them to answer and does not use
          them to train its models under its commercial terms. A person always reviews the draft.
        </li>
        <li>We do not sell or rent personal data to anyone.</li>
      </ul>
    ),
  },
  {
    heading: "Where it is kept, and for how long",
    body: (
      <p>
        The beta runs on a single server we operate, with a nightly backup on the same server.
        Data is kept for the length of the beta. When the beta ends, or when you ask, we delete
        your account and personal data within 30 days, except records we must keep by law or to
        settle an open dispute, and commission invoices, which a business keeps for its accounts.
      </p>
    ),
  },
  {
    heading: "What you can ask",
    body: (
      <p>
        You can ask to see the personal data we hold about you, to correct it, or to delete your
        account. Ask the Khazana team member who invited you. We reply within 14 days.
      </p>
    ),
  },
  {
    heading: "Security",
    body: (
      <p>
        Connections are encrypted, sign in links work once and expire, sessions can be ended from
        every device at once, and each brand&apos;s data is separated from every other brand&apos;s
        in the database. No system is perfectly secure; if we learn of a breach that affects you,
        we will tell you.
      </p>
    ),
  },
];

export default function PrivacyPage() {
  return (
    <LegalPage
      title="Privacy notice"
      version={VERSION}
      summaryKey="legal.privacySummary"
      sections={SECTIONS}
    />
  );
}
