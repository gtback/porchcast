#!/usr/bin/env python3
"""Look up a real tracking number with the real carrier API. Owner's machine only.

Never run this in a cloud session: carrier APIs are blocked there, and it needs
real credentials.

Usage:
    uv run scripts/live_check.py <tracking number> [--sandbox] [--save NAME]

Credentials come from `.env` in the repo root (gitignored):

    UPS_CLIENT_ID=...
    UPS_CLIENT_SECRET=...

It prints the normalized result and the raw response. `--save NAME` writes the
response, scrubbed, to `tests/fixtures/ups/NAME.json`: the tracking number
becomes UPS's sample number, and names, addresses, reference numbers,
signatures and photos are removed; cities become placeholders. Read the file
before committing it anyway.
"""

import argparse
import asyncio
import datetime as dt
import json
import os
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SAMPLE_NUMBER = "1Z999AA10123456784"
# Keys whose whole value is personal or useless in a fixture.
DROP_KEYS = {
    "packageAddress",
    "referenceNumber",
    "paymentInformation",
    "alternateTrackingNumber",
    "userRelation",
    "receivedBy",
    "signature",
    "deliveryPhoto",
    "pod",
    "accessPointInformation",
    "name",
    "attentionName",
}
ADDRESS_KEEP = {"countryCode", "country"}


def scrub(body: Any, number: str) -> Any:
    """Return a copy of a carrier response that is safe for a public repo."""
    cities: dict[str, str] = {}

    def walk(value: Any) -> Any:
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for key, item in value.items():
                if key in DROP_KEYS:
                    continue
                if key == "address" and isinstance(item, dict):
                    out[key] = address(item)
                elif key == "slic":
                    out[key] = "0000"
                else:
                    out[key] = walk(item)
            return out
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, str):
            return value.replace(number, SAMPLE_NUMBER)
        return value

    def address(value: dict[str, Any]) -> dict[str, Any]:
        out = {k: v for k, v in value.items() if k in ADDRESS_KEEP}
        city = value.get("city")
        if isinstance(city, str) and city:
            out["city"] = cities.setdefault(city, f"CITY {len(cities) + 1}")
        if value.get("stateProvince"):
            out["stateProvince"] = "ST"
        return out

    return walk(body)


def read_env(path: Path) -> dict[str, str]:
    """Parse KEY=value lines; the environment wins."""
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and not key.startswith("#"):
                values[key.strip()] = value.strip().strip("'\"")
    return {**values, **{k: v for k, v in os.environ.items() if k in values}}


async def main() -> int:
    """Look the number up and print (and maybe save) the result."""
    import aiohttp  # noqa: PLC0415

    from custom_components.porchcast.carriers.base import CarrierError  # noqa: PLC0415
    from custom_components.porchcast.carriers.ups import (  # noqa: PLC0415
        UpsClient,
        parse_track_response,
    )
    from custom_components.porchcast.tracking import (  # noqa: PLC0415
        find_tracking_number,
    )

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("number")
    parser.add_argument("--sandbox", action="store_true", help="UPS test environment")
    parser.add_argument("--save", metavar="NAME", help="write a scrubbed fixture")
    args = parser.parse_args()

    tracking = find_tracking_number(args.number)
    if tracking is None:
        print(f"Not a tracking number Porchcast recognizes: {args.number}")
        return 1
    carriers = ", ".join(tracking.carriers)
    print(f"Number {tracking.number}, carriers to try: {carriers}")
    if "ups" not in tracking.carriers:
        print("Only UPS is supported so far; force it with ups:<number>.")
        return 1

    env = read_env(ROOT / ".env")
    if not env.get("UPS_CLIENT_ID") or not env.get("UPS_CLIENT_SECRET"):
        print("Set UPS_CLIENT_ID and UPS_CLIENT_SECRET in .env")
        return 1

    tz = dt.datetime.now().astimezone().tzinfo or dt.UTC
    async with aiohttp.ClientSession() as session:
        client = UpsClient(
            session,
            env["UPS_CLIENT_ID"],
            env["UPS_CLIENT_SECRET"],
            sandbox=args.sandbox,
            tz=tz,
        )
        try:
            status, body = await client.async_fetch(tracking.number)
        except CarrierError as err:
            print(f"Error: {type(err).__name__}: {err}")
            return 1

    print(f"HTTP {status}")
    print(json.dumps(body, indent=2))
    try:
        print(parse_track_response(status, body, tz))
    except CarrierError as err:
        print(f"Normalized: {type(err).__name__}: {err}")

    if args.save:
        path = ROOT / "tests/fixtures/ups" / f"{args.save}.json"
        path.write_text(json.dumps(scrub(body, tracking.number), indent=2) + "\n")
        print(f"Saved {path.relative_to(ROOT)}; read it before committing.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
