"""Heart rate sample transforms."""

import csv
import io
import logging
import re
from typing import Any

log = logging.getLogger(__name__)

HEART_RATE_COLUMN = "Heart Rate"
PERCENT_COLUMN = "% of Max HR"


def add_percent_of_max_hr(hr_csv: str | None, max_hr: Any) -> str | None:
    """Add a % of Max HR column to the raw samples CSV.

    Returns None when the session cannot be transformed (blank samples, a
    missing or invalid max HR, or no Heart Rate column), so the caller can skip
    it without halting the rest of the run.
    """
    if not hr_csv or not hr_csv.strip():
        return None
    try:
        max_hr = float(max_hr)
    except (TypeError, ValueError):
        return None
    if max_hr <= 0:
        return None

    try:
        # samples arrive with <br> line breaks, convert back to newlines
        text = re.sub(r"<\s*br\s*/?>", "\n", hr_csv)
        reader = csv.DictReader(io.StringIO(text))
        if HEART_RATE_COLUMN not in (reader.fieldnames or []):
            log.warning("Heart Rate column not found in samples; skipping session.")
            return None

        # replace an existing % of Max HR column rather than duplicating it
        fieldnames = [f for f in reader.fieldnames if f != PERCENT_COLUMN] + [PERCENT_COLUMN]
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in reader:
            try:
                pct = round(float(row[HEART_RATE_COLUMN]) / max_hr * 100, 2)
                row[PERCENT_COLUMN] = f"{pct:g}"
            except (TypeError, ValueError):
                row[PERCENT_COLUMN] = ""
            writer.writerow(row)
        return out.getvalue().rstrip("\n")
    except Exception as e:  # one malformed session should not stop the run
        log.warning("Failed to transform heart rate samples: %s", e)
        return None
