# syntax=docker/dockerfile:1
# Build context: MedicWebSite (one directory above this Dockerfile).
FROM node:22-bookworm-slim AS base
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libatomic1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV WRANGLER_SEND_METRICS=false \
    CLOUDFLARE_CF_FETCH_ENABLED=false \
    WRANGLER_WRITE_LOGS=false

FROM base AS build
COPY package.json package-lock.json .npmrc ./
# Wrangler and Vinext live in devDependencies and are required at runtime too.
RUN npm ci --include=dev --include=optional --no-audit --no-fund
COPY . .
# Use the project's Vite/Cloudflare pipeline. `vinext build` targets Node and
# does not emit the Worker configuration required by the existing npm start.
RUN node node_modules/vite/bin/vite.js build

FROM base AS runtime
ENV NODE_ENV=production
COPY --from=build --chown=node:node /app/package.json ./package.json
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/dist ./dist
COPY --from=build --chown=node:node /app/scripts/run-dual.mjs /app/scripts/sites-env.mjs ./scripts/
COPY --from=build --chown=node:node /app/docker-ver/start.mjs /app/docker-ver/healthcheck.mjs ./docker-ver/
RUN chown node:node /app
USER node
EXPOSE 3000 3001
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["node", "docker-ver/healthcheck.mjs"]
CMD ["node", "docker-ver/start.mjs"]
