FROM postgres:16-bookworm

# pgBackRest must live inside the Postgres container because archive_command
# runs as a Postgres child process. A sidecar cannot serve WAL archiving.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends pgbackrest; \
    rm -rf /var/lib/apt/lists/*

RUN install -d -o postgres -g postgres -m 0750 \
      /var/lib/pgbackrest /var/log/pgbackrest /etc/pgbackrest

COPY postgresql.conf.append /etc/postgresql/conf.d/10-odoo.conf
RUN chown postgres:postgres /etc/postgresql/conf.d/10-odoo.conf

USER postgres
