from types import SimpleNamespace

import pytest

from polar_hr_calcs.config import ConfigError, Settings, env_flag

ENV = {"SB_USERNAME": "u", "SB_PASSWORD": "secret", "SB_URL": "x.smartabase.com", "SB_ATHLETE_GROUP": "g"}


def test_from_env_reads_settings_and_hides_password():
    settings = Settings.from_env(SimpleNamespace(**ENV, DRY_RUN="True"))
    assert settings.athlete_group == "g" and settings.dry_run
    assert "secret" not in repr(settings)


def test_from_env_reports_all_missing_settings():
    with pytest.raises(ConfigError, match="SB_PASSWORD, SB_URL"):
        Settings.from_env(SimpleNamespace(SB_USERNAME="u", SB_ATHLETE_GROUP="g"))


@pytest.mark.parametrize(
    ("value", "expected"), [("true", True), (" TRUE ", True), ("false", False), (None, False)]
)
def test_env_flag(value, expected):
    assert env_flag(SimpleNamespace(FLAG=value), "FLAG") is expected
    assert env_flag(SimpleNamespace(), "FLAG") is False
