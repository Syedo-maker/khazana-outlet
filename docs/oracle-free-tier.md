# Running the pilot on Oracle Cloud Always Free

A step by step guide to putting Khazana Outlet on one free Oracle Cloud ARM
machine, with HTTPS and no domain to buy. It takes about an hour, most of it
waiting. Everything here stays inside Oracle's Always Free allowance; the one
thing that costs is set out in step 1.

For showing the demo from your own laptop instead, see
[Running from a laptop for a demo](#running-from-a-laptop-for-a-demo) at the end.

## What you get

- One `VM.Standard.A1.Flex` machine: 2 OCPU (ARM, Ampere), 12 GB of memory, a
  50 GB boot volume. Always Free allows up to 4 OCPU, 24 GB and 200 GB of
  block storage in total, so this uses half.
- The whole stack from `docker-compose.prod.yml`, measured at about 650 MB of
  memory at its peak under load (see "Measured" below), so 12 GB leaves a
  great deal of room.
- 10 TB of outbound traffic a month, which a pilot will not come near.

## 1. The Oracle account

1. Sign up at the Oracle Cloud website for a Free Tier account.
2. **It asks for a card.** Oracle places a small temporary hold to verify it
   and does not charge for Always Free resources. This is the one point in the
   guide that needs a payment card, and the reason the guide marks it.
3. **Choose the home region carefully: it cannot be changed later**, and Always
   Free compute can only be created there. Pick one close to Pakistan with ARM
   capacity, for example UAE East (Dubai), Saudi Arabia West (Jeddah) or India
   West (Mumbai). Popular regions run out of free ARM capacity; see step 3 if
   that happens.

Optional, but worth knowing: an Always Free account can have an idle machine
reclaimed. Oracle's rule is that a machine whose CPU, network and memory use
all stay under 20 percent over seven days may be stopped. A quiet pilot could
meet that. Upgrading the account to Pay As You Go removes the rule and still
costs nothing while you stay inside the Always Free limits; if you do it, set
a budget alert of USD 1 in the console so any mistake is caught at once.

## 2. The network

In the console: **Networking, Virtual cloud networks, Start VCN Wizard,
Create VCN with Internet Connectivity.** Accept the defaults. Then open the
web ports:

1. Open the new VCN, then **Security Lists, Default Security List,** then
   **Add Ingress Rules**.
2. Add three rules, each with source CIDR `0.0.0.0/0`:
   - TCP, destination port 80
   - TCP, destination port 443
   - UDP, destination port 443 (HTTP/3)

Port 22 for SSH is already open. Leave everything else closed.

## 3. The machine

1. **Compute, Instances, Create instance.**
2. **Image:** Canonical Ubuntu 24.04. Check it says *aarch64*.
3. **Shape:** Ampere, `VM.Standard.A1.Flex`, 2 OCPU and 12 GB. It shows the
   "Always Free eligible" label.
4. **Networking:** the VCN from step 2, its public subnet, and *Assign a public
   IPv4 address*.
5. **SSH keys:** let it generate a pair and download the private key, or paste
   your own public key.
6. Create. If it says **"Out of capacity"**, try another availability domain in
   the same form, or try again in a few hours. This is common and is not your
   fault.

Note the public IP address once it is running, for example `203.0.113.10`.

## 4. Sign in and prepare it

From your laptop:

```bash
ssh -i path/to/private.key ubuntu@203.0.113.10
```

Oracle's Ubuntu images also block ports in the machine's own firewall, in
addition to the security list. Open 80 and 443 there and keep the rule across
reboots:

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p udp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

Install Docker and Git, and let your user run Docker:

```bash
sudo apt-get update && sudo apt-get install -y git ca-certificates curl
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
exit
```

Sign in again so the group change applies, and check:

```bash
docker run --rm hello-world
```

## 5. An address with HTTPS, without buying a domain

Caddy gets a free Let's Encrypt certificate automatically, but it needs a host
name, not a bare IP. Two free options:

- **sslip.io, nothing to sign up for.** The name `203-0-113-10.sslip.io`
  already points at `203.0.113.10`: write your IP with dashes in place of
  dots. This is the quickest.
- **DuckDNS, a free account.** A name like `khazana-pilot.duckdns.org` that you
  point at the IP. Use it if a brand finds the sslip.io name odd, or if Let's
  Encrypt's limits for sslip.io are ever reached.

Check the name resolves to your machine before going on:

```bash
getent hosts 203-0-113-10.sslip.io
```

## 6. The code and the settings

```bash
git clone https://github.com/Syedo-maker/khazana-outlet.git
cd khazana-outlet
cp .env.production.example .env.production
nano .env.production
```

Fill in, at least:

| Setting | Value |
| --- | --- |
| `DOMAIN` | `203-0-113-10.sslip.io`, your name from step 5 |
| `SECRET_KEY`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD` | Each a new random value: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `ANTHROPIC_API_KEY` | Your key, or leave it empty and set `AI_ENABLED=false` |
| `ALERT_EMAIL_TO` and the `SMTP_` settings | See "Alerts by email" in [deployment.md](deployment.md) |

The pilot defaults are already in the file: cash on delivery paid to the
brand, invite links instead of SMS, WhatsApp, voice and photo search off, and
an AI cap of USD 1 a day. The file stays on the server; it is git ignored.

## 7. Start it

The published release images are built for both amd64 and arm64 from the
release after 1.0.0 onward. Until that release exists, build on the machine,
which takes about ten minutes the first time:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

Once an arm64 release is published, set `IMAGE_PREFIX=ghcr.io/syedo-maker/khazana`
and `VERSION` in `.env.production` and use `pull` then `up -d` instead.

Watch it come up, then check it answers over HTTPS:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production ps
curl -fsS https://203-0-113-10.sslip.io/api/ready
```

The API refuses to start with an unsafe setting and says which one in
`docker compose ... logs api`.

## 8. First data and the first admin

A fresh database is empty, which is right for real brands. Load the product
categories, then create yourself as the admin. The second command prints a
single use sign in link:

```bash
dc="docker compose -f docker-compose.prod.yml --env-file .env.production"
$dc exec api python -m khazana.manage load-categories
$dc exec api python -m khazana.manage create-admin --phone 03001234567 --name "Your name"
```

Open the link in your own browser. It works once and expires after
`INVITE_TTL_HOURS` (72). For a fresh link later:

```bash
$dc exec api python -m khazana.manage login-link --phone 03001234567
```

From the admin panel, **Invites** makes a link for each brand and reseller,
with a button that opens your WhatsApp with the message ready to send. Never
run `khazana.seed` on this server: it is sample data for demos.

## 9. Keeping it running

- **Updates:** `git pull`, then the same `up -d --build`. The migrate step
  upgrades the database first.
- **Backups:** written nightly to `./backups` on the machine, kept 14 days.
  Copy them off it, for example to Oracle Object Storage, which Always Free
  includes (20 GB): install `rclone`, configure an Object Storage remote, and
  run `rclone copy ./backups remote:khazana-backups` from cron. Until then a
  lost machine is lost data.
- **Alerts:** a failed job, a stale backup, the API down, a full disk, the AI
  budget reached or a server error each send one email (see deployment.md).

## Measured

On the staging stack, this laptop (x86_64, Docker Desktop), 2026-11-28, with
the memory limits in `docker-compose.prod.yml`. ARM uses about the same.

| Service | Limit | Idle | Peak, 20 users with no pauses |
| --- | --- | --- | --- |
| api, 2 workers | 1 GB | 248 MB | 259 MB |
| db, PostgreSQL 16 | 2 GB | 110 MB | 175 MB |
| scheduler | 384 MB | 73 MB | 90 MB (171 MB during the nightly demo reseed) |
| web | 384 MB | 77 MB | 77 MB |
| caddy | 128 MB | 44 MB | 43 MB |
| redis | 192 MB | 8 MB | 9 MB |
| backup | 256 MB | 1 MB | 1 MB |
| **Total** | **4.4 GB** | **0.56 GB** | **0.65 GB** |

The load run answered 101 requests a second with no errors, catalogue p95
285 ms, search p95 266 ms, lot page p95 404 ms, inside the 500 ms budget. The
limits leave 7.6 GB of the 12 GB free; nothing needed trimming beyond two API
workers in place of three, one per OCPU.

## Running from a laptop for a demo

To show a brand the demo from your own machine, with a public HTTPS address
and no account anywhere, use a Cloudflare quick tunnel:

1. Install Docker Desktop and start it.
2. `copy .env.staging.example .env.staging` (a demo: sample accounts only,
   login codes on screen, reset nightly).
3. In PowerShell from the repository: `.\scripts\tunnel.ps1 -Seed`

It prints an address like `https://three-random-words.trycloudflare.com` that
works from any phone. The address changes every time, the tunnel has no uptime
guarantee, and the laptop must stay awake, so it is for demos only. Stop it
with `.\scripts\tunnel.ps1 -Down`.
