setup_common() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  export REPO_ROOT
  export PATH="$REPO_ROOT/scripts:$PATH"
}
