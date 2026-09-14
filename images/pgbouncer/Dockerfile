FROM alpine:3.20

RUN set -eux; \
    apk add --no-cache pgbouncer bash; \
    install -d -o pgbouncer -g pgbouncer -m 0750 /etc/pgbouncer

COPY entrypoint.sh /usr/local/bin/pgbouncer-entrypoint.sh
RUN chmod 0755 /usr/local/bin/pgbouncer-entrypoint.sh

USER pgbouncer
EXPOSE 6432
ENTRYPOINT ["/usr/local/bin/pgbouncer-entrypoint.sh"]
