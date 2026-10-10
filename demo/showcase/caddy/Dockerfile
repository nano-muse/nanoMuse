# The public face of the showcase: Caddy with the Cloudflare DNS module (for the wildcard
# certificate the per-session hostnames need), the Cloudflare IP-ranges module (so that behind
# Cloudflare's proxy the visitor's address is still the visitor's), the built MobileGym with
# the nanoMuse app installed and pointed at the gateway (as /phone.html), and the page around
# the phone (site/page/, with MobileGym's own gesture keys and State Builder) at /.
#
# Build context is the repository root (see docker-compose.yml), so the nanoMuse app module can
# be copied straight from demo/mobilegym/apps/nanoMuse, and the page from demo/showcase/site.

FROM node:22-bookworm-slim AS site
ARG MOBILEGYM_REPO=https://github.com/Purewhiter/mobilegym.git
ARG MOBILEGYM_REF=main
ARG NANOMUSE_DEMO=/api/demo
# where the phone's media (MobileGym's companion dataset: app images, launcher widgets, icon
# themes) comes from: /cdn on this origin (the gateway serves ./data/mobilegym-data there), or
# MobileGym's own CDN, https://cdn.mobilegym.dev, when the dataset is not downloaded
ARG MOBILEGYM_CDN_BASE=/cdn
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git clone --depth 1 --branch "${MOBILEGYM_REF}" "${MOBILEGYM_REPO}" mobilegym
COPY demo/mobilegym/apps/nanoMuse mobilegym/apps/nanoMuse
# the showcase's one change to MobileGym's seed (张伟's 微信 message invites to a hike, for the
# page's weather line); the build fails if upstream's sentence is no longer there as expected
COPY demo/mobilegym/patch-seed.sh /src/patch-seed.sh
RUN sh /src/patch-seed.sh /src/mobilegym
WORKDIR /src/mobilegym
# modern-screenshot renders the phone's screenshot in the tab (the nanoMuse module's only
# extra dependency); --no-save keeps MobileGym's lockfile as upstream has it
RUN npm ci --no-audit --no-fund \
 && npm install --no-save --no-audit --no-fund modern-screenshot@^4.7.0 \
 && VITE_NANOMUSE_DEMO="${NANOMUSE_DEMO}" VITE_CDN_BASE="${MOBILEGYM_CDN_BASE}" npm run build \
 && mv dist/index.html dist/phone.html
# the page at /, with MobileGym's own chrome (gesture keys, State Builder, power) composed in
COPY demo/showcase/site/page /src/site/page
COPY demo/showcase/site/compose.mjs /src/site/compose.mjs
RUN node /src/site/compose.mjs /src/mobilegym /src/site/page dist

FROM caddy:2-builder AS caddy-build
# a Go module mirror for networks where proxy.golang.org is slow, e.g. GOPROXY=https://goproxy.cn,direct
ARG GOPROXY=https://proxy.golang.org,direct
ENV GOPROXY=${GOPROXY}
RUN xcaddy build \
    --with github.com/caddy-dns/cloudflare \
    --with github.com/WeidiDeng/caddy-cloudflare-ip

FROM caddy:2
COPY --from=caddy-build /usr/bin/caddy /usr/bin/caddy
COPY --from=site /src/mobilegym/dist /srv/site
