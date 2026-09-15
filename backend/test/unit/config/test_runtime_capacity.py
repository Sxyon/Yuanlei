import pytest

from yuxi.config import get_int_env


def test_get_int_env_reads_configured_value(monkeypatch):
    monkeypatch.setenv("CAPACITY_VALUE", "50")

    assert get_int_env("CAPACITY_VALUE", 10) == 50


@pytest.mark.parametrize("value", ["", "abc", "0", "-1"])
def test_get_int_env_rejects_invalid_or_non_positive_value(monkeypatch, value):
    monkeypatch.setenv("CAPACITY_VALUE", value)

    with pytest.raises(RuntimeError, match="CAPACITY_VALUE"):
        get_int_env("CAPACITY_VALUE", 10)


def test_get_int_env_accepts_zero_when_boundary_allows_it(monkeypatch):
    monkeypatch.setenv("CAPACITY_VALUE", "0")

    assert get_int_env("CAPACITY_VALUE", 10, minimum=0) == 0
