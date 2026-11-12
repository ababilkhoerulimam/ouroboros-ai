"""Tes batas patch.

Yang diuji: diff di luar `ALLOWED` ditolak sebelum menyentuh worktree, satu
berkas tidak bisa menyamar sebagai berkas lain, path yang di-ignore git tidak
bisa dipakai menulis di luar pandangan `git status`, dan diff yang diterima
menghasilkan `git status` yang persis sama dengan daftar berkas di diff.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from swarmfold_eval import patcher


def _git(repo: Path, *args: str) -> str:
    """Jalankan git tanpa penerjemahan baris baru: patch harus byte-identik."""
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, timeout=30, check=False
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout.decode("utf-8", "surrogateescape")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "uji@contoh")
    _git(repo, "config", "user.name", "uji")
    _git(repo, "config", "core.autocrlf", "false")
    (repo / ".gitignore").write_bytes(b"prompts/tmp/\n")
    (repo / "prompts").mkdir()
    (repo / "prompts" / "style.md").write_bytes(b"lama\n")
    (repo / "src" / "swarmfold").mkdir(parents=True)
    (repo / "src" / "swarmfold" / "loop.py").write_bytes(b"x = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "awal")
    return repo


def _diff_files(repo: Path, changes: dict[str, str]) -> str:
    for path, isi in changes.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(isi.encode("utf-8"))
    diff = _git(repo, "diff", "--no-color")
    _git(repo, "checkout", "--", ".")
    return diff


def _patch(path: str, lama: str = "lama", baru: str = "baru") -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1 +1 @@\n"
        f"-{lama}\n"
        f"+{baru}\n"
    )


def test_scope_accepts_prompt_and_pipeline() -> None:
    assert patcher.check_scope(_patch("prompts/style.md")) == []
    assert patcher.check_scope(_patch("src/swarmfold/loop.py")) == []


@pytest.mark.parametrize(
    "path",
    ["src/swarmfold_verify/scorer.py", "src/swarmfold_eval/patcher.py", "tests/test_loop.py"],
)
def test_scope_rejects_verifier_path(path: str) -> None:
    masalah = patcher.check_scope(_patch(path))
    assert any("terlarang" in item for item in masalah)


@pytest.mark.parametrize("path", ["evals/truth/trend-01.json", "evals/pins/verify.lock.json"])
def test_scope_rejects_tests_and_truth(path: str) -> None:
    masalah = patcher.check_scope(_patch(path))
    assert any("terlarang" in item for item in masalah)


def test_scope_rejects_parent_traversal() -> None:
    masalah = patcher.check_scope(_patch("prompts/../../etc/passwd"))
    assert any("keluar repo" in item for item in masalah)


def test_scope_rejects_absolute_path() -> None:
    masalah = patcher.check_scope(_patch("C:/Windows/System32/drivers/etc/hosts"))
    assert any("absolut" in item for item in masalah)


def test_scope_rejects_outside_allowed_root() -> None:
    masalah = patcher.check_scope(_patch("README.md"))
    assert any("luar jangkauan" in item for item in masalah)


def test_scope_rejects_inconsistent_paths() -> None:
    """Header boleh menyebut satu berkas sementara `+++` menunjuk berkas lain."""
    diff = (
        "diff --git a/prompts/style.md b/prompts/style.md\n"
        "--- a/prompts/style.md\n"
        "+++ b/src/swarmfold_verify/scorer.py\n"
        "@@ -1 +1 @@\n"
        "-lama\n"
        "+PWNED\n"
    )
    masalah = patcher.check_scope(diff)
    assert any("beberapa path" in item for item in masalah)
    assert any("terlarang" in item for item in masalah)


def test_scope_rejects_rename() -> None:
    diff = (
        "diff --git a/prompts/style.md b/prompts/style.md\n"
        "rename from prompts/style.md\n"
        "rename to src/swarmfold_verify/scorer.py\n"
    )
    assert any("rename" in item for item in patcher.check_scope(diff))


def test_scope_rejects_quoted_path() -> None:
    diff = (
        'diff --git a/prompts/"style.md" b/prompts/"style.md"\n'
        '--- a/prompts/"style.md"\n'
        '+++ b/prompts/"style.md"\n'
        "@@ -1 +1 @@\n-lama\n+baru\n"
    )
    assert patcher.check_scope(diff)


def test_scope_rejects_gitignore_file() -> None:
    masalah = patcher.check_scope(_patch("prompts/.gitignore"))
    assert any("pengatur git" in item for item in masalah)


def test_scope_rejects_huge_hunk() -> None:
    baris = "\n".join(f"+baris {index}" for index in range(patcher.MAX_HUNK_LINES + 1))
    diff = (
        "diff --git a/prompts/style.md b/prompts/style.md\n"
        "--- a/prompts/style.md\n"
        "+++ b/prompts/style.md\n"
        "@@ -1,1 +1,300 @@\n"
        "-lama\n"
        f"{baris}\n"
    )
    assert any("melebihi batas" in item for item in patcher.check_scope(diff))


def test_scope_rejects_too_many_files() -> None:
    diff = "".join(_patch(f"prompts/berkas-{index}.md") for index in range(patcher.MAX_FILES + 1))
    assert any("berkas melebihi batas" in item for item in patcher.check_scope(diff))


def test_scope_rejects_mode_change() -> None:
    diff = (
        "diff --git a/prompts/style.md b/prompts/style.md\n"
        "old mode 100644\n"
        "new mode 100755\n"
    )
    assert any("mode" in item for item in patcher.check_scope(diff))


def test_scope_rejects_empty_diff() -> None:
    assert patcher.check_scope("   \n") == ["diff kosong"]


def test_apply_changes_only_diff_files(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    diff = _diff_files(repo, {"prompts/style.md": "baru\n"})

    hasil = patcher.apply(repo, diff)

    assert hasil.files == ("prompts/style.md",)
    assert (hasil.added, hasil.removed) == (1, 1)
    assert (repo / "prompts" / "style.md").read_text(encoding="utf-8") == "baru\n"


def test_porcelain_matches_diff_set(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    diff = _diff_files(repo, {"prompts/style.md": "baru\n", "src/swarmfold/loop.py": "x = 2\n"})

    hasil = patcher.apply(repo, diff)

    status = _git(repo, "status", "--porcelain")
    berubah = {line[3:].strip() for line in status.splitlines()}
    assert berubah == set(hasil.files) == {"prompts/style.md", "src/swarmfold/loop.py"}


def test_apply_rejects_before_touching_worktree(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    with pytest.raises(patcher.ScopeError):
        patcher.apply(repo, _patch("src/swarmfold_verify/scorer.py"))

    assert _git(repo, "status", "--porcelain") == ""


def test_apply_refuses_dirty_worktree(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    diff = _diff_files(repo, {"prompts/style.md": "baru\n"})
    (repo / "src" / "swarmfold" / "loop.py").write_text("x = 99\n", encoding="utf-8")

    with pytest.raises(patcher.ScopeError, match="bersih"):
        patcher.apply(repo, diff)


def test_apply_refuses_ignored_path(tmp_path: Path) -> None:
    """Berkas yang di-ignore git tidak muncul di `git status`, jadi harus ditolak."""
    repo = _repo(tmp_path)
    diff = (
        "diff --git a/prompts/tmp/x.md b/prompts/tmp/x.md\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/prompts/tmp/x.md\n"
        "@@ -0,0 +1 @@\n"
        "+isi\n"
    )
    assert patcher.check_scope(diff) == []

    with pytest.raises(patcher.ScopeError, match="ignore"):
        patcher.apply(repo, diff)


@pytest.mark.skipif(os.name == "nt", reason="symlink butuh hak khusus di Windows")
def test_apply_refuses_symlink(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    luar = tmp_path / "luar"
    luar.mkdir()
    (repo / "prompts" / "pintu").symlink_to(luar, target_is_directory=True)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "symlink")
    diff = (
        "diff --git a/prompts/pintu/x.md b/prompts/pintu/x.md\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/prompts/pintu/x.md\n"
        "@@ -0,0 +1 @@\n"
        "+isi\n"
    )

    with pytest.raises(patcher.ScopeError, match="symlink"):
        patcher.apply(repo, diff)
