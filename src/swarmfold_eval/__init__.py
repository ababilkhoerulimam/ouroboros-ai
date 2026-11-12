"""Perkakas loop evolusi: membatasi patch, mencatat varian, dan memutuskan.

Paket ini tidak menganalisis data dan tidak menilai run; ia mengatur proses
yang membandingkan dua versi sistem. Karena itu ia sendiri tidak boleh menjadi
sasaran patch (`patcher.DENIED`).
"""

from __future__ import annotations

__all__ = ["gate", "ledger", "patcher"]
