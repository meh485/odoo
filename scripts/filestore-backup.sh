#!/usr/bin/env sh
# Snapshot the Odoo filestore to object storage with restic.
#
# The filestore is the second store Odoo keeps: attachments live on the
# filesystem, so a database-only backup restores a tenant whose invoices and
# images are all gone.
set -eu

: "${RESTIC_REPOSITORY:?missing RESTIC_REPOSITORY}"
: "${RESTIC_PASSWORD_FILE:?missing RESTIC_PASSWORD_FILE}"
: "${AWS_SHARED_CREDENTIALS_FILE:?missing AWS_SHARED_CREDENTIALS_FILE}"
: "${TENANT:?missing TENANT}"

CREDENTIALS_DIR="${CREDENTIALS_DIR:-/etc/aws-credentials}"
FILESTORE_DIR="${FILESTORE_DIR:-/var/lib/odoo}"
KEEP_DAILY="${KEEP_DAILY:-7}"
KEEP_WEEKLY="${KEEP_WEEKLY:-4}"
KEEP_MONTHLY="${KEEP_MONTHLY:-6}"

# restic reads S3 credentials through the AWS SDK chain. Pointing it at a file
# keeps the key out of the container environment and out of kubectl describe.
mkdir -p "$(dirname "$AWS_SHARED_CREDENTIALS_FILE")"
{
  printf '[default]\n'
  printf 'aws_access_key_id=%s\n' "$(cat "${CREDENTIALS_DIR}/ACCESS_KEY_ID")"
  printf 'aws_secret_access_key=%s\n' "$(cat "${CREDENTIALS_DIR}/ACCESS_SECRET_KEY")"
} > "$AWS_SHARED_CREDENTIALS_FILE"
chmod 600 "$AWS_SHARED_CREDENTIALS_FILE"

# restic exits non-zero when the repository does not exist yet.
if ! restic cat config >/dev/null 2>&1; then
  echo "initialising the restic repository for ${TENANT}"
  restic init
fi

echo "backing up ${FILESTORE_DIR} for ${TENANT}"
restic backup "$FILESTORE_DIR" --tag filestore --host "$TENANT" --verbose

# Scoped to this tag and hostname: an unscoped forget in a shared repository
# could remove another tenant's snapshots.
echo "applying the retention policy"
restic forget \
  --tag filestore \
  --host "$TENANT" \
  --keep-daily "$KEEP_DAILY" \
  --keep-weekly "$KEEP_WEEKLY" \
  --keep-monthly "$KEEP_MONTHLY" \
  --prune

echo "filestore backup complete for ${TENANT}"