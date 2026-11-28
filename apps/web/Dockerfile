# Khazana Outlet web app.
#
# Dependencies are installed from the lockfile before the source is copied, so
# editing a component does not reinstall npm packages.

ARG NODE_VERSION=22.23.3

# ----------------------------------------------------------------- deps
FROM node:${NODE_VERSION}-slim AS deps

WORKDIR /app

# npm ci needs a lockfile and installs exactly what it pins. The fallback
# exists so a fresh clone without a lockfile still builds rather than failing
# with a message nobody expects.
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund


# ------------------------------------------------------------------ dev
FROM deps AS dev

ENV NODE_ENV=development \
    NEXT_TELEMETRY_DISABLED=1

# Create these before switching user, and own them as node.
#
# Compose declares /app/node_modules and /app/.next as anonymous volumes, so
# the Windows host copies never shadow the container's own. Docker seeds an
# anonymous volume from the image, ownership included, so a root owned
# directory in the image becomes a root owned volume that the unprivileged
# process cannot write to. Next.js then dies on its first write to
# .next/trace, which is what happened before this line existed.
RUN mkdir -p /app/.next && chown -R node:node /app

# The node image already has a node user at uid 1000.
USER node

EXPOSE 3000

CMD ["npm", "run", "dev"]


# ---------------------------------------------------------------- build
FROM deps AS build

COPY . .

# The browser calls the API at this address, and Next.js writes it into the
# JavaScript at build time, so it is a build argument, not a runtime setting.
# Production builds pass the public HTTPS address of the API.
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build


# -------------------------------------------------------------- runtime
FROM node:${NODE_VERSION}-slim AS runtime

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

# Upgraded at build time, because the base image is a snapshot. npm is not
# needed to run the standalone server, and every Node.js advisory the
# 2026-11-28 Trivy scan found was in npm's own bundled packages, so it is
# removed from the runtime image.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack \
    && rm -f /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack

# The standalone output: a server.js plus only the modules it imports. The
# static assets and the public folder are copied beside it, as Next.js
# expects. A fraction of the size of copying node_modules whole.
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public

USER node

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail --silent http://localhost:3000/ || exit 1

ENV HOSTNAME=0.0.0.0
CMD ["node", "server.js"]
