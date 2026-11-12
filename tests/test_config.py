"""Tes konfigurasi: default pack doktrin dan pembacaan environment."""

from __future__ import annotations

import pytest

from swarmfold.config import ConfigError, Settings


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


def test_pack_is_forced_only_when_env_sets_it() -> None:
    assert Settings.from_env({}).pack_forced is False
    assert Settings.from_env({"SWARMFOLD_PACK": "generic"}).pack_forced is True
    assert Settings.from_env({"SWARMFOLD_PACK": "business"}).pack_forced is True


def test_sampling_defaults_are_none() -> None:
    settings = Settings.from_env({})

    assert (settings.temperature, settings.top_p, settings.seed) == (None, None, None)


def test_sampling_from_env_accepts_zero_seed() -> None:
    settings = Settings.from_env(
        {"SWARMFOLD_TEMPERATURE": "0.2", "SWARMFOLD_TOP_P": "0.9", "SWARMFOLD_SEED": "0"}
    )

    assert (settings.temperature, settings.top_p, settings.seed) == (0.2, 0.9, 0)


@pytest.mark.parametrize(
    "env",
    [
        {"SWARMFOLD_TEMPERATURE": "3"},
        {"SWARMFOLD_TEMPERATURE": "-1"},
        {"SWARMFOLD_TEMPERATURE": "nan"},
        {"SWARMFOLD_TEMPERATURE": "inf"},
        {"SWARMFOLD_TOP_P": "1.5"},
        {"SWARMFOLD_TOP_P": "-inf"},
        {"SWARMFOLD_SEED": "-2"},
        {"SWARMFOLD_TEMPERATURE": "hangat"},
    ],
)
def test_sampling_out_of_range_is_rejected(env: dict) -> None:
    with pytest.raises(ConfigError):
        Settings.from_env(env)


def test_public_dict_records_sampling_without_secret() -> None:
    settings = Settings.from_env({"SWARMFOLD_API_KEY": "kunci-uji", "SWARMFOLD_SEED": "7"})

    public = settings.public_dict()

    assert public["seed"] == 7
    assert public["temperature"] is None
    assert "kunci-uji" not in str(public)


def test_max_tokens_from_env_reaches_public_dict() -> None:
    assert Settings.from_env({}).max_tokens is None

    settings = Settings.from_env({"SWARMFOLD_MAX_TOKENS": "8192"})

    assert settings.max_tokens == 8192
    assert settings.public_dict()["max_tokens"] == 8192


@pytest.mark.parametrize("nilai", ["0", "-5", "banyak"])
def test_max_tokens_out_of_range_is_rejected(nilai: str) -> None:
    with pytest.raises(ConfigError):
        Settings.from_env({"SWARMFOLD_MAX_TOKENS": nilai})
