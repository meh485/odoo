# The restore drill needs kubectl (create and delete the scratch Cluster),
# psql (assert on the restored data) and curl (push metrics). No maintained
# image ships all three, so this one assembles them.
FROM alpine:3.21

ARG TARGETARCH
ARG KUBECTL_VERSION=v1.34.0

RUN apk add --no-cache bash curl postgresql-client ca-certificates \
 && arch="${TARGETARCH:-$(apk --print-arch)}" \
 && case "$arch" in amd64|x86_64) arch=amd64 ;; arm64|aarch64) arch=arm64 ;; esac \
 && curl -fsSL "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${arch}/kubectl" \
      -o /usr/local/bin/kubectl \
 && chmod 0755 /usr/local/bin/kubectl \
 && kubectl version --client

COPY scripts/restore-drill.sh /usr/local/bin/restore-drill.sh
RUN chmod 0755 /usr/local/bin/restore-drill.sh

# The chart runs this as a non-root user; the image itself needs no privilege.
USER 101
ENTRYPOINT ["/usr/local/bin/restore-drill.sh"]
