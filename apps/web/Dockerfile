# Khazana Outlet web app.
#
# Dependencies are installed from the lockfile before the source is copied, so
# editing a component does not reinstall npm packages.

ARG NODE_VERSION=20.18.1

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

ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build


# -------------------------------------------------------------- runtime
FROM node:${NODE_VERSION}-slim AS runtime

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build --chown=node:node /app/public ./public
COPY --from=build --chown=node:node /app/.next ./.next
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/package.json ./package.json

USER node

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail --silent http://localhost:3000/ || exit 1

CMD ["npm", "run", "start"]
