FROM node:22-alpine@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2

# Pin the relay client so local webhook transport is reproducible and does not
# execute an unreviewed moving package version on every container start.
RUN npm install --global smee-client@5.0.0

COPY entrypoint.sh /usr/local/bin/specforge-smee
RUN chmod 0755 /usr/local/bin/specforge-smee

USER node

ENTRYPOINT ["/usr/local/bin/specforge-smee"]
