"""Guards for repository-level things that nothing else would notice breaking,
like a documented command pointing at a file that was never committed.
"""
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = REPO_ROOT / "Makefile"
README = REPO_ROOT / "README.md"


def _tracked_files() -> set[str]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    return set(result.stdout.split())


def test_the_kind_cluster_config_is_committed():
    # `make cluster` is the first command in the README. If its config is not
    # tracked, a fresh clone cannot create a cluster at all.
    match = re.search(r"kind create cluster --config (\S+)", MAKEFILE.read_text())
    assert match, "the cluster target no longer names a kind config"
    assert match.group(1) in _tracked_files(), (
        f"{match.group(1)} is not tracked by git, so a fresh clone cannot create "
        "the cluster"
    )


def test_the_readme_documents_every_make_target_it_needs():
    text = README.read_text()
    for target in ("make cluster", "make platform", "make seed", "make test", "make e2e"):
        assert target in text, f"README does not mention {target}"
