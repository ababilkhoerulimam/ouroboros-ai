"""Batas patch untuk loop evolusi.

Loop boleh mengubah prompt dan kode pipeline, tidak boleh mengubah tes, truth,
atau verifier — kalau boleh, satu-satunya cara menaikkan skor adalah menulis
ulang alat ukurnya.

Diff adalah keluaran model yang tidak dipercaya, jadi pemeriksaannya berlapis:

1. `check_scope` menolak path di luar `ALLOWED`, path terlarang, `..`, path
   absolut, berkas `.gitignore`/`.gitattributes`, diff biner, perubahan mode,
   rename, dan hunk raksasa.
2. `apply` menolak symlink di sepanjang path, path yang di-ignore git, dan
   worktree yang sudah kotor — lalu menerapkan dengan `git apply --check`
   lebih dulu, dan mengembalikan berkas yang tersentuh bila hasil akhirnya
   tidak sama dengan diff.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

#: Hanya dua akar ini yang boleh disentuh patch.
ALLOWED = ("prompts/", "src/swarmfold/")
#: Ditolak lebih dulu, karena `src/swarmfold_verify/` juga berawalan `src/`.
DENIED = (
    "src/swarmfold_verify/",
    "src/swarmfold_eval/",
    "tests/",
    "evals/",
    "Dockerfile",
    "compose.yaml",
    "pyproject.toml",
    ".git/",
)
#: Berkas yang mengubah cara git melihat berkas lain, sehingga pemeriksaan
#: `git status` sesudahnya tidak lagi bisa dipercaya.
FORBIDDEN_NAMES = (".gitignore", ".gitattributes", ".gitmodules")
#: Batas ukuran patch: satu perbaikan perilaku, bukan penulisan ulang berkas.
MAX_FILES = 3
MAX_TOTAL_LINES = 200
MAX_HUNK_LINES = 200

_HEADER_RE = re.compile(r"^diff --git a/(?P<a>\S+) b/(?P<b>\S+)$")
_MINUS_RE = re.compile(r"^--- (?:a/(?P<a>\S+)|(?P<null>/dev/null))$")
_PLUS_RE = re.compile(r"^\+\+\+ (?:b/(?P<b>\S+)|(?P<null>/dev/null))$")
_ABS_RE = re.compile(r"^(?:[A-Za-z]:|[\\/])")


class ScopeError(RuntimeError):
    """Diff keluar dari jangkauan patch atau tidak bisa diterapkan bersih."""


@dataclass(frozen=True)
class AppliedDiff:
    files: tuple[str, ...]
    added: int
    removed: int


@dataclass
class _Section:
    """Satu berkas dalam diff. Semua path yang disebut harus menunjuk berkas sama."""

    header: tuple[str, str]
    minus: str | None = None
    plus: str | None = None
    extra: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def paths(self) -> set[str]:
        nama = {self.header[0], self.header[1], *self.extra}
        nama.update(item for item in (self.minus, self.plus) if item)
        return {item for item in nama if item}


def _sections(diff: str) -> list[_Section]:
    hasil: list[_Section] = []
    sekarang: _Section | None = None
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            match = _HEADER_RE.match(line)
            if match is None:
                raise ScopeError(f"header diff tidak didukung: {line}")
            sekarang = _Section(header=(match.group("a"), match.group("b")))
            hasil.append(sekarang)
            continue
        if sekarang is None:
            if line.strip():
                raise ScopeError("diff tanpa header berkas")
            continue
        if line.startswith("--- "):
            match = _MINUS_RE.match(line)
            if match is None:
                sekarang.problems.append(f"baris --- tidak didukung: {line}")
            else:
                sekarang.minus = match.group("a")
        elif line.startswith("+++ "):
            match = _PLUS_RE.match(line)
            if match is None:
                sekarang.problems.append(f"baris +++ tidak didukung: {line}")
            else:
                sekarang.plus = match.group("b")
        elif line.startswith(("rename from ", "rename to ", "copy from ", "copy to ")):
            sekarang.extra.append(line.split(" ", 2)[2])
            sekarang.problems.append(f"rename/copy tidak didukung: {line}")
        elif line.startswith(("old mode", "new mode")):
            sekarang.problems.append(f"perubahan mode berkas: {line}")
        elif line.startswith("new file mode") and not line.strip().endswith("100644"):
            sekarang.problems.append(f"berkas baru bukan mode biasa: {line}")
        elif line.startswith(("Binary files", "GIT binary patch")):
            sekarang.problems.append("diff biner tidak didukung")
    return hasil


def _path_problem(path: str) -> str | None:
    if _ABS_RE.match(path):
        return f"path absolut: {path}"
    if any(char in path for char in ('"', "\\", "\t")):
        # Path berkutip/ber-escape dibaca berbeda oleh git dan oleh parser ini;
        # lebih aman ditolak daripada ditebak.
        return f"path berkutip atau ber-escape tidak didukung: {path}"
    if ".." in PurePosixPath(path).parts:
        return f"path keluar repo: {path}"
    if any(path.startswith(denied) for denied in DENIED):
        return f"path terlarang: {path}"
    if any(path.endswith(nama) for nama in FORBIDDEN_NAMES):
        return f"berkas pengatur git tidak boleh diubah: {path}"
    if not any(path.startswith(allowed) for allowed in ALLOWED):
        return f"path di luar jangkauan patch: {path}"
    return None


def _hunk_problems(diff: str) -> list[str]:
    masalah: list[str] = []
    panjang = 0
    for line in diff.splitlines():
        if line.startswith("@@"):
            if panjang > MAX_HUNK_LINES:
                masalah.append(f"hunk {panjang} baris melebihi batas {MAX_HUNK_LINES}")
            panjang = 0
            continue
        if line.startswith(("+", "-", " ")):
            panjang += 1
    if panjang > MAX_HUNK_LINES:
        masalah.append(f"hunk {panjang} baris melebihi batas {MAX_HUNK_LINES}")
    return masalah


def _counts(diff: str) -> tuple[int, int]:
    added = sum(1 for line in diff.splitlines() if line.startswith("+") and line[:3] != "+++")
    removed = sum(1 for line in diff.splitlines() if line.startswith("-") and line[:3] != "---")
    return added, removed


def _paths(diff: str) -> set[str]:
    paths: set[str] = set()
    for section in _sections(diff):
        paths.update(section.paths())
    return paths


def check_scope(diff: str) -> list[str]:
    """Daftar pelanggaran yang bisa diputuskan dari teks diff saja."""
    if not diff.strip():
        return ["diff kosong"]
    try:
        sections = _sections(diff)
    except ScopeError as error:
        return [str(error)]
    if not sections:
        return ["diff tanpa header berkas"]

    masalah: list[str] = []
    if not any(line.startswith("@@") for line in diff.splitlines()):
        masalah.append("diff tanpa hunk")
    for section in sections:
        masalah.extend(section.problems)
        paths = section.paths()
        if len(paths) > 1:
            # `git apply` mengikuti baris ---/+++, bukan header: satu section
            # yang menyebut dua berkas adalah cara menulis ke luar jangkauan.
            masalah.append(f"satu berkas menyebut beberapa path: {sorted(paths)}")
        for path in sorted(paths):
            problem = _path_problem(path)
            if problem:
                masalah.append(problem)

    added, removed = _counts(diff)
    if len(sections) > MAX_FILES:
        masalah.append(f"{len(sections)} berkas melebihi batas {MAX_FILES}")
    if added + removed > MAX_TOTAL_LINES:
        masalah.append(f"{added + removed} baris berubah melebihi batas {MAX_TOTAL_LINES}")
    masalah.extend(_hunk_problems(diff))
    return masalah


def _run_git(cwd: Path, *args: str, data: bytes | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            input=data,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ScopeError(f"git {args[0]} melebihi batas waktu") from error


def _porcelain(worktree: Path) -> set[str]:
    """Berkas yang berubah menurut git, termasuk yang untracked."""
    result = _run_git(worktree, "status", "--porcelain", "-z", "-uall")
    if result.returncode != 0:
        raise ScopeError(f"git status gagal: {result.stderr.decode('utf-8', 'replace').strip()}")
    files: set[str] = set()
    for record in result.stdout.split(b"\0"):
        if len(record) < 4:
            continue
        files.add(record[3:].decode("utf-8", "surrogateescape"))
    return files


def _symlink_in_path(root: Path, path: str) -> Path | None:
    current = root
    for part in PurePosixPath(path).parts:
        current = current / part
        if current.is_symlink():
            return current
    return None


def _worktree_problems(worktree: Path, paths: set[str]) -> list[str]:
    """Penjagaan yang butuh keadaan worktree, bukan teks diff."""
    root = Path(worktree)
    masalah: list[str] = []
    for path in sorted(paths):
        symlink = _symlink_in_path(root, path)
        if symlink is not None:
            masalah.append(f"path melewati symlink: {symlink.relative_to(root).as_posix()}")
        ignored = _run_git(root, "check-ignore", "--no-index", "-q", "--", path)
        if ignored.returncode == 0:
            masalah.append(f"path di-ignore git: {path}")
    if _porcelain(root):
        masalah.append("worktree harus bersih sebelum patch diterapkan")
    return masalah


def _rollback(worktree: Path, paths: set[str]) -> None:
    """Kembalikan berkas yang tersentuh ke keadaan sebelum apply."""
    for path in paths:
        target = Path(worktree) / path
        tracked = _run_git(worktree, "ls-files", "--error-unmatch", "--", path)
        if tracked.returncode == 0:
            _run_git(worktree, "checkout", "--", path)
        elif target.is_file():
            target.unlink()


def apply(worktree: Path, diff: str) -> AppliedDiff:
    """Terapkan diff di `worktree`, atau lempar `ScopeError` tanpa sisa."""
    masalah = check_scope(diff)
    if masalah:
        raise ScopeError("; ".join(masalah))
    paths = _paths(diff)
    masalah = _worktree_problems(worktree, paths)
    if masalah:
        raise ScopeError("; ".join(masalah))

    data = diff.encode("utf-8")
    periksa = _run_git(worktree, "apply", "--check", "--whitespace=nowarn", "-", data=data)
    if periksa.returncode != 0:
        raise ScopeError(f"git apply --check gagal: {periksa.stderr.decode('utf-8', 'replace').strip()}")
    hasil = _run_git(worktree, "apply", "--whitespace=nowarn", "-", data=data)
    if hasil.returncode != 0:
        _rollback(worktree, paths)
        raise ScopeError(f"git apply gagal: {hasil.stderr.decode('utf-8', 'replace').strip()}")

    berubah = _porcelain(worktree)
    if berubah != paths:
        _rollback(worktree, paths)
        raise ScopeError(
            f"berkas berubah tidak sama dengan diff: diff={sorted(paths)} nyata={sorted(berubah)}"
        )
    added, removed = _counts(diff)
    return AppliedDiff(files=tuple(sorted(paths)), added=added, removed=removed)
