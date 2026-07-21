FROM node:26-alpine@sha256:e88a35be04478413b7c71c455cd9865de9b9360e1f43456be5951032d7ac1a66

# Pin the relay client so local webhook transport is reproducible and does not
# execute an unreviewed moving package version on every container start.
RUN npm install --global smee-client@5.0.0

COPY entrypoint.sh /usr/local/bin/specforge-smee
RUN chmod 0755 /usr/local/bin/specforge-smee

USER node

ENTRYPOINT ["/usr/local/bin/specforge-smee"]
