"""Verifier deterministik untuk run analisis.

Paket ini sengaja terpisah dari `swarmfold`: ia menilai hasil, bukan
menghasilkannya. Loop evolusi tidak boleh menyentuhnya, dan skor selalu
dihitung dari salinan yang di-pin (lihat `pins.py`).
"""

from __future__ import annotations

__all__ = ["cases", "checks", "cli", "generate", "pins", "scorer", "truth"]
