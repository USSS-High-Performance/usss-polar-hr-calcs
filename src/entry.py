"""Cloudflare Worker entrypoint.

The only module that depends on the Workers runtime. It reads settings from
the Worker env, wires the Workers fetch into the API client and runs the sync
on the cron trigger configured in wrangler.jsonc.
"""

import logging
import sys
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint
from workers import fetch as workers_fetch

from polar_hr_calcs.config import Settings, env_flag
from polar_hr_calcs.smartabase import SmartabaseClient
from polar_hr_calcs.sync import run_sync


def configure_logging() -> None:
    # In a Worker stdout becomes console.log and stderr becomes console.error, so
    # send INFO to stdout and keep only warnings and errors on stderr.
    info = logging.StreamHandler(sys.stdout)
    info.addFilter(lambda record: record.levelno < logging.WARNING)
    errors = logging.StreamHandler(sys.stderr)
    errors.setLevel(logging.WARNING)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", handlers=[info, errors])


configure_logging()
log = logging.getLogger("polar_hr_calcs")


class Default(WorkerEntrypoint):
    async def scheduled(self, controller, env, ctx):
        await self.run()

    async def fetch(self, request):
        # Local testing only. wrangler's --test-scheduled route does not work for
        # Python Workers, so `npm run dev` sets ALLOW_MANUAL_TRIGGER and this
        # handler runs the job on /__scheduled. Deployed, it is always a 404.
        if env_flag(self.env, "ALLOW_MANUAL_TRIGGER") and urlparse(request.url).path == "/__scheduled":
            await self.run()
            return Response("Ran scheduled event")
        return Response("Not found", status=404)

    async def run(self) -> None:
        # an exception here marks the run as failed in the Workers dashboard
        try:
            settings = Settings.from_env(self.env)
            client = SmartabaseClient(
                settings.sb_url, settings.sb_username, settings.sb_password, fetch=workers_fetch
            )
            result = await run_sync(client, settings.athlete_group, dry_run=settings.dry_run)
            log.info("Run complete: %s", result.summary())
        except Exception:
            log.exception("Polar HR calcs failed.")
            raise
