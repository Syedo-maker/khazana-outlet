# Browser end to end tests

Playwright tests that drive the real web app against the real API, in a phone
sized Chromium. They cover the money path from checkout to confirmed delivery,
and that one reseller cannot open another's order.

## Run them

The stack has to be running with fresh seed data, because each run buys one
of the seeded brand's lots:

```powershell
.\scripts\dev.ps1 up
.\scripts\dev.ps1 seed --reset
.\scripts\dev.ps1 e2e
```

`e2e` runs on the host's Node rather than in a container, so the browser
reaches the web app and the API at the same `localhost` addresses a person's
browser does. The first run downloads Chromium, about 150 MB.

To use a Chromium that is already installed, set `CHROMIUM_PATH` to its
executable before running.

CI runs the same tests in the `Browser end to end` job, against the same
compose stack.

## Signing in

Each test signs in through the real login page with the development OTP code
the page shows. The API allows five codes an hour per phone number, so the
tests reuse one API token per phone per run. Running the suite many times in
an hour against the same database will hit that limit; reseed, or wait.
