"""Polar HR calcs: enrich Polar heart rate sessions in Teamworks AMS (Smartabase).

New "Polar Summary - Training" sessions have their raw heart rate samples
converted to % of the athlete's all time max HR, then are inserted as events
on the "Polar Summary - Training - HR R" form.

Everything in this package is plain Python so it can be unit tested outside
the Workers runtime. The Cloudflare specific entrypoint lives in src/entry.py.
"""
