FROM node:22-alpine

# Pin the relay client so local webhook transport is reproducible and does not
# execute an unreviewed moving package version on every container start.
RUN npm install --global smee-client@5.0.0

COPY entrypoint.sh /usr/local/bin/specforge-smee
RUN chmod 0755 /usr/local/bin/specforge-smee

ENTRYPOINT ["/usr/local/bin/specforge-smee"]
