"""Tes konfigurasi: default pack doktrin dan pembacaan environment."""

from __future__ import annotations

from swarmfold.config import Settings


def test_defaults_are_business_pack() -> None:
    settings = Settings.from_env({})

    assert settings.pack == "business"
    assert settings.audience == "pemilik usaha kecil"
    assert settings.domain == "usaha"


def test_pack_and_persona_from_env() -> None:
    settings = Settings.from_env(
        {
            "SWARMFOLD_PACK": "generic",
            "SWARMFOLD_AUDIENCE": "analis data",
            "SWARMFOLD_DOMAIN": "riset",
        }
    )

    assert (settings.pack, settings.audience, settings.domain) == (
        "generic",
        "analis data",
        "riset",
    )


def test_public_dict_has_pack_without_secret() -> None:
    settings = Settings.from_env({"SWARMFOLD_API_KEY": "kunci-uji"})

    public = settings.public_dict()

    assert public["pack"] == "business"
    assert public["domain"] == "usaha"
    assert "kunci-uji" not in str(public)
