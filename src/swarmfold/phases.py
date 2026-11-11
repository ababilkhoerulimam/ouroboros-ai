"""Controller fase dan pemuat prompt.

Model memilih fase berikutnya sendiri lewat ``advance_phase``; controller di sini
yang memutuskan sah atau tidak (ARCHITECTURE.md §3, LANES.md §1). Tabel transisi
bersifat mengikat dan prasyarat satu baris berlaku untuk semua target di baris
itu, termasuk target mundur (mis. F3 -> F2 juga menuntut residual 0).

Keadaan controller disimpan di ``<run>/phase.json`` supaya run yang di-restart
tidak kehilangan fase aktif, daftar fase selesai, dan hitungan kembali.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .evidence import EvidenceStore
from .runtime import RunPaths, atomic_write_json, read_json

PHASES: tuple[str, ...] = ("F1", "F2", "F3", "F4", "F5", "F6", "F7")

# Fase aktif sebelum F1 dipilih. Nilai kosong, bukan nama fase, supaya
# `advance("F1")` tidak dianggap transisi ke fase yang sama.
START = ""

MAX_RETURNS = 2
_STATE_FILE = "phase.json"
_MODULES = ("style", "evidence", "loop", "tools", "report", "deepdive")

_LEGAL: dict[str, tuple[str, ...]] = {
    START: ("F1",),
    "F1": ("F2",),
    "F2": ("F3", "F4"),
    "F3": ("F2", "F4", "F5"),
    "F4": ("F5",),
    "F5": ("F3", "F6"),
    "F6": ("F2", "F3", "F5", "F7"),
    "F7": (),
}


@dataclass
class AdvanceResult:
    """Hasil satu percobaan transisi; ``allowed`` selalu berisi target sah saat itu."""

    ok: bool
    target: str
    allowed: list[str]
    reason: str


def _names(items: list[str] | tuple[str, ...]) -> str:
    return ", ".join(items) if items else "—"


class PhaseController:
    """Penjaga transisi fase: prasyarat, target mundur, dan batas osilasi."""

    def __init__(self, paths: RunPaths, store: EvidenceStore):
        self.paths = paths
        self.store = store
        self._state_file = paths.dir / _STATE_FILE
        self._last_reason = ""
        state = read_json(self._state_file, {})
        if not isinstance(state, dict):
            state = {}

        phase = state.get("phase")
        self._current: str = phase if phase in PHASES else START

        self._completed: dict[str, bool] = {}
        completed = state.get("completed")
        if isinstance(completed, dict):
            for name, ok in completed.items():
                if name in PHASES:
                    self._completed[name] = ok is True

        self._returns: dict[str, int] = {}
        returns = state.get("returns")
        if isinstance(returns, dict):
            for name, used in returns.items():
                if name in PHASES and isinstance(used, int) and not isinstance(used, bool):
                    self._returns[name] = max(0, used)

    # -- keadaan ------------------------------------------------------------

    @property
    def current(self) -> str:
        """Fase aktif, atau string kosong bila F1 belum dipilih."""
        return self._current

    def is_completed(self, phase: str) -> bool:
        return phase in self._completed

    def returns_used(self, phase: str) -> int:
        """Berapa kali controller sudah kembali ke ``phase``."""
        return self._returns.get(phase, 0)

    def mark_completed(self, phase: str, ok: bool = True) -> None:
        """Catat fase ditutup. ``ok=False`` berarti gagal atau tidak berlaku."""
        if phase not in PHASES:
            raise ValueError(f"fase tidak dikenal: {phase!r}; pilih {_names(PHASES)}")
        self._completed[phase] = bool(ok)
        self._save()

    # -- transisi -----------------------------------------------------------

    def force(self, target: str, reason: str = "") -> None:
        """Lompati prasyarat (dipakai controller untuk menjamin F7 tetap jalan)."""
        if target not in PHASES:
            raise ValueError(f"fase tidak dikenal: {target!r}; pilih {_names(PHASES)}")
        self._current = target
        self._last_reason = reason
        self._save()

    def allowed_targets(self) -> list[str]:
        """Target sah saat ini.

        Prasyarat hanya mengikat langkah maju. Langkah mundur tetap sah walau
        prasyarat belum terpenuhi: fase yang tidak bisa ditutup harus bisa
        dikembalikan, bukan dikurung tanpa jalan keluar.
        """
        if self._current == "F7":
            return []
        legal = list(_LEGAL[self._current])
        if self._current == START:
            return legal
        ready, _ = self._prerequisite()
        if ready:
            return legal
        here = PHASES.index(self._current)
        return [target for target in legal if PHASES.index(target) < here]

    def advance(self, target: str, reason: str = "") -> AdvanceResult:
        """Pindah ke ``target`` bila sah; penolakan menyebut prasyarat yang kurang."""
        allowed = self.allowed_targets()
        current = self._current

        if not isinstance(target, str) or target not in PHASES:
            return AdvanceResult(
                False, str(target), allowed, f"fase tidak dikenal: {target!r}; pilih {_names(PHASES)}"
            )
        if target == current:
            return AdvanceResult(False, target, allowed, f"{target} sudah fase aktif")
        if current == "F7":
            return AdvanceResult(
                False, target, allowed, "F7 fase terakhir; tidak ada transisi keluar dari F7"
            )
        if target not in _LEGAL[current]:
            return AdvanceResult(
                False,
                target,
                allowed,
                f"transisi {self._label(current)} -> {target} tidak ada di tabel; "
                f"target sah sekarang: {_names(allowed)}",
            )

        forward = current == START or PHASES.index(target) > PHASES.index(current)
        if forward:
            ready, why = self._prerequisite()
            if not ready:
                return AdvanceResult(False, target, allowed, why)

        if current != START and PHASES.index(target) < PHASES.index(current):
            used = self.returns_used(target)
            if used >= MAX_RETURNS:
                return AdvanceResult(
                    False,
                    target,
                    allowed,
                    f"batas kembali ke {target} tercapai: maksimum {MAX_RETURNS} kali per "
                    f"fase, sudah dipakai {used} kali",
                )
            self._returns[target] = used + 1

        self._current = target
        self._last_reason = reason
        self._save()
        return AdvanceResult(True, target, self.allowed_targets(), "")

    # -- prasyarat ----------------------------------------------------------

    def _prerequisite(self) -> tuple[bool, str]:
        """(terpenuhi, alasan) untuk baris tabel milik fase aktif."""
        phase = self._current
        if phase == START:
            return True, ""
        if phase == "F1":
            if self._completed.get("F1") is True:
                return True, ""
            return False, "F1 belum selesai dengan status ok; panggil mark_completed('F1')"
        if phase == "F2":
            if self.store.count("F2") >= 1:
                return True, ""
            return False, (
                "F2 belum punya temuan: butuh minimal 1 E-### terverifikasi di evidence/F2.json"
            )
        if phase == "F3":
            if self.store.has_residual_zero("F3"):
                return True, ""
            return False, (
                "F3 belum punya dekomposisi dengan residual 0; tulis finding dengan "
                "meta.residual == 0 di evidence/F3.json"
            )
        if phase == "F4":
            if "F4" in self._completed:
                return True, ""
            return False, (
                "F4 belum ditutup; tandai selesai atau tandai tidak berlaku lewat "
                "mark_completed('F4', ok=False)"
            )
        if phase == "F5":
            if self._has_scenario():
                return True, ""
            return False, (
                "F5 belum punya skenario: butuh finding terverifikasi dengan "
                "meta.kind == 'scenario' di evidence/F5.json"
            )
        if self._audit_complete():
            return True, ""
        return False, 'F6 belum selesai mengaudit; set "audit_complete": true di evidence/F6.json'

    def _has_scenario(self) -> bool:
        findings = self.store.load("F5").get("findings")
        if not isinstance(findings, list):
            return False
        for finding in findings:
            if not isinstance(finding, dict) or finding.get("verified") is not True:
                continue
            meta = finding.get("meta")
            if isinstance(meta, dict) and meta.get("kind") == "scenario":
                return True
        return False

    def _audit_complete(self) -> bool:
        return self.store.load("F6").get("audit_complete") is True

    # -- penyimpanan --------------------------------------------------------

    @staticmethod
    def _label(phase: str) -> str:
        return "start" if phase == START else phase

    def _save(self) -> None:
        atomic_write_json(
            self._state_file,
            {
                "phase": self._current,
                "completed": dict(self._completed),
                "returns": dict(self._returns),
                "last_reason": self._last_reason,
            },
        )


def _default_prompts_dir() -> Path:
    """``prompts/`` di root repo; jatuh ke cwd bila paket terpasang tanpa prompt."""
    packaged = Path(__file__).resolve().parents[2] / "prompts"
    if (packaged / "system.md").is_file():
        return packaged
    fallback = Path.cwd() / "prompts"
    if (fallback / "system.md").is_file():
        return fallback
    return packaged


class PromptLibrary:
    """Muat berkas prompt dari repo, bukan dari skill global di mesin."""

    def __init__(self, prompts_dir: Path | None = None):
        self.dir = Path(prompts_dir) if prompts_dir is not None else _default_prompts_dir()

    def system(self) -> str:
        return self._read(self.dir / "system.md")

    def phase(self, phase: str) -> str:
        if phase not in PHASES:
            raise ValueError(f"fase tidak dikenal: {phase!r}; pilih {_names(PHASES)}")
        return self._read(self.dir / "phases" / f"{phase}.md")

    def module(self, name: str) -> str:
        if name not in _MODULES:
            raise ValueError(f"modul tidak dikenal: {name!r}; pilih {_names(_MODULES)}")
        return self._read(self.dir / f"{name}.md")

    def state_block(
        self,
        *,
        phase: str,
        cell: int,
        evidence_count: int,
        allowed: list[str],
        phase_completed: list[str],
        cells_in_phase: int | None = None,
        evidence_in_phase: int | None = None,
        checkpoint_in: int | None = None,
        stalls: int = 0,
    ) -> str:
        """Blok state tiap turn, dalam bentuk key=value yang dibaca `loop.md`."""
        lines = [
            "## State",
            f"phase={phase}",
            f"cells_used={int(cell)}",
            f"cells_in_phase={int(cell if cells_in_phase is None else cells_in_phase)}",
            f"evidence_total={int(evidence_count)}",
            f"evidence_in_phase={int(evidence_count if evidence_in_phase is None else evidence_in_phase)}",
            f"checkpoint_in={int(checkpoint_in if checkpoint_in is not None else 0)}",
            f"legal_next={','.join(allowed) if allowed else 'none'}",
            f"stalls={int(stalls)}",
        ]
        if phase_completed:
            lines.append(f"phases_done={','.join(phase_completed)}")
        return "\n".join(lines)

    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"prompt tidak ditemukan: {path}") from exc
