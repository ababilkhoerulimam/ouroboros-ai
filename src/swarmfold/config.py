"""Konfigurasi runtime dari environment.

Tidak ada nilai rahasia di dalam kode. API key hanya dibaca dari environment dan
tidak pernah ikut ke `repr`, log, atau artefak run.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL = "ag/gemini-3.8-flash-high"
#: Pack doktrin yang dipakai bila triage tidak punya pilihan lain. Data tanpa
#: sinyal bisnis dipindahkan triage ke pack ``generic``.
DEFAULT_PACK = "business"
DEFAULT_AUDIENCE = "pemilik usaha kecil"
DEFAULT_DOMAIN = "usaha"


class ConfigError(RuntimeError):
    """Konfigurasi wajib tidak lengkap atau tidak masuk akal."""


def _env_int(env: Mapping[str, str], name: str, default: int, minimum: int = 1) -> int:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} harus berupa angka bulat, bukan {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"{name} minimal {minimum}, bukan {value}")
    return value


def _env_float(
    env: Mapping[str, str],
    name: str,
    default: float | None = None,
    *,
    lo: float | None = None,
    hi: float | None = None,
) -> float | None:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} harus berupa angka, bukan {raw!r}") from exc
    if not math.isfinite(value):
        # `nan` lolos kedua perbandingan rentang di bawah, dan `json.dumps`
        # mengirimnya sebagai literal NaN yang bukan JSON sah.
        raise ConfigError(f"{name} harus berupa angka berhingga, bukan {raw!r}")
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        raise ConfigError(f"{name} harus di antara {lo} dan {hi}, bukan {value}")
    return value


def _env_optional_int(env: Mapping[str, str], name: str, minimum: int = 0) -> int | None:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} harus berupa angka bulat, bukan {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"{name} minimal {minimum}, bukan {value}")
    return value


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    base_url: str | None
    model: str
    max_cells: int
    cell_timeout_s: int
    stall_cells: int
    deepdive_every: int
    data_root: Path
    pack: str = DEFAULT_PACK
    audience: str = DEFAULT_AUDIENCE
    domain: str = DEFAULT_DOMAIN
    #: True bila operator mengunci pack lewat environment; triage tidak boleh
    #: menggantinya. False berarti pack dipilih triage per data.
    pack_forced: bool = False
    #: Parameter sampling. None berarti tidak dikirim sama sekali, sehingga
    #: default gateway yang berlaku; mengirim null ditolak sebagian gateway.
    temperature: float | None = None
    top_p: float | None = None
    seed: int | None = None
    #: Model untuk peran reviewer di loop evolusi. Kosong berarti worker dipakai.
    reviewer_model: str = ""
    #: Akar benchmark, pin verifier, dan ledger evolusi.
    eval_root: Path = Path("./evals")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        source = os.environ if env is None else env
        base_url = (source.get("SWARMFOLD_BASE_URL") or "").strip().rstrip("/") or None
        api_key = (source.get("SWARMFOLD_API_KEY") or "").strip() or None
        model = (source.get("SWARMFOLD_MODEL") or "").strip() or DEFAULT_MODEL
        data_root = Path((source.get("SWARMFOLD_DATA_ROOT") or "./runs").strip())
        pack = (source.get("SWARMFOLD_PACK") or "").strip()
        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            max_cells=_env_int(source, "SWARMFOLD_MAX_CELLS", 120),
            cell_timeout_s=_env_int(source, "SWARMFOLD_CELL_TIMEOUT_S", 300),
            stall_cells=_env_int(source, "SWARMFOLD_STALL_CELLS", 3),
            deepdive_every=_env_int(source, "SWARMFOLD_DEEPDIVE_EVERY", 10),
            data_root=data_root,
            pack=pack or DEFAULT_PACK,
            audience=(source.get("SWARMFOLD_AUDIENCE") or "").strip() or DEFAULT_AUDIENCE,
            domain=(source.get("SWARMFOLD_DOMAIN") or "").strip() or DEFAULT_DOMAIN,
            pack_forced=bool(pack),
            temperature=_env_float(source, "SWARMFOLD_TEMPERATURE", lo=0.0, hi=2.0),
            top_p=_env_float(source, "SWARMFOLD_TOP_P", lo=0.0, hi=1.0),
            seed=_env_optional_int(source, "SWARMFOLD_SEED"),
            reviewer_model=(source.get("SWARMFOLD_REVIEWER_MODEL") or "").strip(),
            eval_root=Path((source.get("SWARMFOLD_EVAL_ROOT") or "./evals").strip()),
        )

    def require_model(self) -> tuple[str, str]:
        """Kembalikan (base_url, api_key) atau gagal dengan pesan yang jelas."""
        missing = []
        if not self.base_url:
            missing.append("SWARMFOLD_BASE_URL")
        if not self.api_key:
            missing.append("SWARMFOLD_API_KEY")
        if missing:
            raise ConfigError(
                "konfigurasi model belum lengkap: " + ", ".join(missing) + " (lihat .env.example)"
            )
        assert self.base_url is not None and self.api_key is not None
        return self.base_url, self.api_key

    def public_dict(self) -> dict[str, object]:
        """Bagian konfigurasi yang aman ditulis ke status.json dan log."""
        return {
            "model": self.model,
            "max_cells": self.max_cells,
            "cell_timeout_s": self.cell_timeout_s,
            "stall_cells": self.stall_cells,
            "deepdive_every": self.deepdive_every,
            "pack": self.pack,
            "audience": self.audience,
            "domain": self.domain,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "seed": self.seed,
            "reviewer_model": self.reviewer_model,
            "base_url_configured": self.base_url is not None,
        }

    def __repr__(self) -> str:  # pragma: no cover - bentuk aman untuk log
        key_state = "set" if self.api_key else "unset"
        return (
            f"Settings(model={self.model!r}, base_url_configured={self.base_url is not None}, "
            f"api_key={key_state}, max_cells={self.max_cells})"
        )
