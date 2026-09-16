setup_common() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  export REPO_ROOT
  export PATH="$REPO_ROOT/scripts:$PATH"
}

# File mode as three octal digits, on both GNU and BSD userlands.
#
# The GNU form must be tried first: GNU `stat -f '%Lp'` does not fail on an
# unrecognised format, it prints the format string itself and exits 0, so
# `stat -f ... || stat -c ...` silently yields "%Lp" on Linux.
file_perms() {
  stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"
}
