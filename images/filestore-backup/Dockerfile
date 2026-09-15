# restic already ships the binary and a shell; this image only adds the backup
# script and runs it as a non-root user.
FROM ghcr.io/restic/restic:0.19.1

USER root
COPY scripts/filestore-backup.sh /usr/local/bin/filestore-backup.sh
RUN chmod 0755 /usr/local/bin/filestore-backup.sh

USER 101
ENTRYPOINT ["/usr/local/bin/filestore-backup.sh"]