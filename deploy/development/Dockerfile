FROM node:26.6.0-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM caddy:2.11.7-alpine
COPY deploy/development/Caddyfile /etc/caddy/Caddyfile
COPY --from=frontend /build/dist /srv
