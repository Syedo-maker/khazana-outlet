# Week 6: Landing page, how to publish and collect signups

The page is `/landing/index.html`. It is a single file with no build step, no
external requests, no fonts to download and no framework. That is deliberate:
most of your audience is on an Android phone on mobile data, and every extra
request costs you signups.

## What the page does

- Explains the offer to brands and to resellers on one page, with separate
  sections so neither audience has to read the other one's pitch
- Answers the brand image objection directly, because that is the first thing
  a brand thinks about
- Collects name, business, WhatsApp number, city, category and a free text
  note, which are exactly the fields the week 2 and week 3 trackers need
- Validates the phone number as a Pakistani mobile, 11 digits starting 03
- Works in dark mode, at 320px width, and with the keyboard only
- Falls back to opening WhatsApp with the details prefilled if no form
  endpoint is configured, so you can share it before any backend exists

## Step 1: configure it

Open `/landing/index.html`, find the CONFIGURATION block near the bottom, and
set two values:

```js
var FORM_ENDPOINT = "";     // where signups are sent
var WHATSAPP_NUMBER = "";   // your number, for example 923001234567
```

Set `WHATSAPP_NUMBER` first. With only that set, the page is already usable:
on submit it opens WhatsApp with the signup details filled in and the person
presses send. Crude, but it works on day one and it costs nothing.

## Step 2: choose where the signups go

Three options, cheapest first.

### Option A: Google Sheet through Apps Script (free, recommended)

1. Create a Google Sheet with these headers in row 1: `submitted_at`, `role`,
   `name`, `org`, `phone`, `city`, `category`, `detail`, `source`
2. In the sheet, open Extensions, then Apps Script
3. Paste a short script that appends `e.postData.contents` as a row
4. Deploy as a web app, set access to anyone, copy the web app URL
5. Put that URL in `FORM_ENDPOINT`

The sheet becomes your live waiting list, and you can export it straight into
`../trackers/waiting-list.csv`.

### Option B: Formspree (free tier, no code)

1. Create a form at formspree.io, copy the endpoint
2. Put it in `FORM_ENDPOINT`
3. Signups arrive by email and in the Formspree dashboard

### Option C: your own endpoint

Only once Phase 1 has a backend. The page posts JSON, so a single route that
accepts a JSON body and writes a row is enough.

## Step 3: publish it

Any static host works because the page is one file.

| Host | Cost | Notes |
| --- | --- | --- |
| Cloudflare Pages | Free | Fast in Pakistan, free custom domain and HTTPS |
| Netlify | Free | Drag and drop the `landing` folder, done in a minute |
| Vercel | Free | Matches the Phase 1 stack, so you learn the tooling early |
| GitHub Pages | Free | Fine, but the repository must be public or on a paid plan |

Then point `khazanaoutlet.pk` at it and confirm HTTPS works.

## Step 4: test before you share the link

Do all of these on a real phone, not only on your laptop.

- [ ] Open on an Android phone on mobile data, not on wifi
- [ ] Submit the form, confirm the row arrives in the sheet or inbox
- [ ] Submit with an invalid phone number, confirm the error appears
- [ ] Submit with nothing filled in, confirm it does not send
- [ ] Press Tab from the top and confirm you can reach and use every field
- [ ] Check it in dark mode
- [ ] Check it at 320px width, for example on an older phone
- [ ] Ask two people who are not you to fill it in while you watch silently.
      Where they hesitate is where your copy is unclear.

## Step 5: drive traffic to it

The page does nothing on its own. In week 6 send it to:

- Every brand and reseller already interviewed in weeks 2 and 3
- Your WhatsApp status and your personal contacts
- The Facebook and WhatsApp reseller groups you found in week 3, in a post
  that asks rather than advertises
- Your LinkedIn, with a short note about what you are building and why
- Instagram bio, once the handle is registered

Target for the week: 50 waiting list entries, which is a Phase 0 exit
criterion. Track the source of each signup so you learn which channel works.

## Copy notes and one open decision

The page is written in English. For the reseller audience in particular,
Roman Urdu copy will almost certainly convert better, and the current project
rule is that everything in the repository is in English. If you want a Roman
Urdu version of the page, or a language toggle, say so and it will be built,
since that is your call to make and not a rule to work around quietly.

Two further copy rules that are already applied and worth keeping:

1. The page never uses the phrase "dead stock" where a brand can see it. It
   says surplus, previous season and over produced.
2. It makes no promise about price, timing or commission that you have not
   agreed with brands, because the first brand to quote your own landing page
   back at you in a negotiation will be the brand you most wanted to sign.
