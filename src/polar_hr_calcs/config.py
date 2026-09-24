"""Static configuration and runtime settings."""

from dataclasses import dataclass, field
from typing import Any

# Forms
SOURCE_FORM = "Polar Summary - Training"
TARGET_FORM = "Polar Summary - Training - HR R"

# Unique key present on both forms, used to prevent duplicate processing
ID_FIELD = "ID"

# Source form fields
HR_SAMPLES_FIELD = "Heart Rate Samples"
MAX_HR_FIELD = "Max HR - All Time"  # historical calc from Polar HR data

# Target form fields
HR_DATA_FIELD = "Polar HR Data"
FORMATTED_DATE_FIELD = "Formatted Date"

# Fields carried over unchanged from the source form to the target form
PASSTHROUGH_FIELDS = (
    "Detailed Sport Info",
    "Duration (txt)",
    "Heart Rate Maximum",
    "Edwards' TRiMP",
    "Z1 Mins",
    "Z2 Mins",
    "Z3 Mins",
    "Z4 Mins",
    "Z5 Mins",
)

# Both forms are pulled over this window (in days, ending today) and deduped
# on ID, so a run that is delayed or retried does not insert duplicates.
LOOKBACK_DAYS = 1

# Request sizing
USER_CHUNK_SIZE = 200  # userIds sent per eventsearch request
IMPORT_CHUNK_SIZE = 50  # events sent per eventsimport request

APP_ID = "usss-polar-hr-calcs"  # sent as X-APP-ID on every API request

REQUIRED_ENV = ("SB_USERNAME", "SB_PASSWORD", "SB_URL", "SB_ATHLETE_GROUP")


class ConfigError(RuntimeError):
    """Required configuration is missing."""


def env_flag(env: Any, name: str) -> bool:
    """Read an optional "true"/"false" setting from the Worker env."""
    return str(getattr(env, name, "") or "").strip().lower() == "true"


@dataclass(frozen=True)
class Settings:
    """Runtime settings, read from .env locally or Worker secrets when deployed."""

    sb_url: str
    sb_username: str
    sb_password: str = field(repr=False)
    athlete_group: str
    dry_run: bool = False  # log what would be inserted instead of inserting

    @classmethod
    def from_env(cls, env: Any) -> "Settings":
        missing = [name for name in REQUIRED_ENV if not getattr(env, name, None)]
        if missing:
            raise ConfigError(f"Missing {', '.join(missing)}. Set in .env locally or as Worker secrets.")
        return cls(
            sb_url=str(env.SB_URL),
            sb_username=str(env.SB_USERNAME),
            sb_password=str(env.SB_PASSWORD),
            athlete_group=str(env.SB_ATHLETE_GROUP),
            dry_run=env_flag(env, "DRY_RUN"),
        )
