# The zero budget pilot: what has to be done by hand

Everything the code cannot do for you, in the order to do it. Each step says
whether it is free or what it costs. Nothing here has been signed up for,
registered or bought on your behalf.

| # | Step | Cost | Needs |
| --- | --- | --- | --- |
| 1 | Review the pull request into `develop` and merge it when satisfied | Free | Your GitHub account |
| 2 | Optional: publish a release, so the server can pull ready built arm64 images instead of building them | Free: Actions and the container registry cost nothing for a public repository | Your decision on a version number; tag it on `main` |
| 3 | Create an Oracle Cloud Free Tier account, choosing the home region carefully ([guide, step 1](oracle-free-tier.md#1-the-oracle-account)) | Free. Oracle puts a small temporary hold on a payment card to verify it and does not charge for Always Free resources | A payment card, a phone number, an email address |
| 4 | Optional: upgrade the Oracle account to Pay As You Go, so an idle pilot machine is not reclaimed, and set a USD 1 budget alert | Free while you stay inside the Always Free limits; a mistake outside them would be charged, which the budget alert catches | The card from step 3 |
| 5 | Create the network, open ports 80 and 443, create the 2 OCPU, 12 GB ARM machine ([steps 2 to 4](oracle-free-tier.md#2-the-network)) | Free | Nothing more |
| 6 | Choose the address: `<your-ip-with-dashes>.sslip.io`, or a DuckDNS name | Free. sslip.io needs no account; DuckDNS needs a free sign in | Nothing, or a DuckDNS sign in |
| 7 | Create a Gmail app password for alert emails ([deployment.md, Alerts by email](deployment.md#alerts-by-email)) | Free | A Google account with 2 Step Verification on |
| 8 | Decide the AI budget. Keep the cap at USD 1 a day, or set `AI_ENABLED=false` | Up to USD 1 a day, at most about USD 30 a month, with the cap. USD 0 with AI off. Also set a monthly spend limit in the Anthropic console as a second guard | Your existing Anthropic key |
| 9 | Fill in `.env.production` on the server and start the stack ([steps 6 and 7](oracle-free-tier.md#6-the-code-and-the-settings)) | Free | Steps 5 to 8 |
| 10 | Load the categories and create yourself as admin; open the printed link ([step 8](oracle-free-tier.md#8-first-data-and-the-first-admin)) | Free | Your mobile number |
| 11 | Set up off server backups: Oracle Object Storage and an `rclone` cron job | Free: Always Free includes 20 GB of Object Storage | About 20 minutes |
| 12 | Optional: an outside uptime monitor on `https://<your-address>/api/ready`, since the server cannot email you that it is down | Free plans exist (for example UptimeRobot or Healthchecks.io) | A free account with one of them |
| 13 | Read the beta privacy notice and terms (`/privacy`, `/terms`) and change anything that does not match how you will run the pilot | Free if you do it yourself. A lawyer's review before inviting real people is strongly advised and is the one cost worth paying; fees vary | Your time, or a lawyer |
| 14 | Agree each brand's pilot terms in writing: commission percentage, invoice due days (15 by default), that they ship cash on delivery with their own courier and enter the tracking number | Free, using a short letter or message both sides keep | Each brand's agreement |
| 15 | Set each brand's commission and policy in the admin panel after it registers | Free | Step 14 |
| 16 | Invite brands and resellers from Admin, Invites; send each link from your WhatsApp; verify each reseller's business under Verification | Free: click to chat links open your own WhatsApp, no Business API | Your phone |
| 17 | Each month, check Admin, Commission for the invoices issued on the 1st, and record each brand's payment with its bank reference | Free | A bank account to receive the commission |
| 18 | For demos away from the server: `.\scripts\tunnel.ps1 -Seed` on your laptop | Free: a Cloudflare quick tunnel needs no account | Docker Desktop |
| 19 | Before the pilot ends: decide whether to register a company and an NTN, which you will need for merchant accounts and for invoicing at scale. Get tax advice on commission income in the meantime | Free to register an individual NTN on FBR's IRIS portal; company registration and an accountant cost money and are a later decision | Your decision |
| 20 | Optional, later: a proper domain name in place of sslip.io | About USD 10 to 15 a year for a .com; a .pk costs a similar amount in rupees | A registrar account |

## What stays switched off, and what turning it on would need

| Feature | Switch | Needs, and cost |
| --- | --- | --- |
| SMS login codes | `SMS_LOGIN_ENABLED` | An SMS gateway; paid per message |
| Payments through the platform | `DEFAULT_SETTLEMENT_MODE=platform` per brand | A registered company and merchant accounts with JazzCash, Easypaisa or a card acquirer; fees per transaction |
| Integrated courier booking | none, follows settlement mode | A courier contract and API access |
| WhatsApp assistant | `WHATSAPP_ENABLED` | A verified WhatsApp Business account and a provider; paid per conversation |
| Voice notes | `SPEECH_TO_TEXT_ENABLED` | A speech to text service for Urdu and regional languages; paid per minute |
| Search by photo | `VISUAL_SEARCH_ENABLED` | An image embedding model at `EMBEDDING_SERVICE_URL`; a paid service or a GPU server |
