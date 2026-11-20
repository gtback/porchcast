"""UPS Tracking API client (OAuth client credentials).

Written from UPS's OpenAPI specs (github.com/UPS-API/api-documentation,
``Tracking.yaml`` and ``OAuthClientCredentials.yaml``), read 2026-11-20.
Details and open questions are in docs/carriers.md on the plan branch.
"""

from collections.abc import Callable, Mapping
import datetime as dt
import time
from typing import Any, Final
import uuid

import aiohttp

from .base import (
    AuthError,
    Carrier,
    CarrierError,
    Eta,
    Event,
    NotFoundError,
    RateLimitedError,
    Status,
    TrackingResult,
)

PRODUCTION_URL: Final = "https://onlinetools.ups.com"
SANDBOX_URL: Final = "https://wwwcie.ups.com"
TOKEN_PATH: Final = "/security/v1/oauth/token"  # noqa: S105
TRACK_PATH: Final = "/api/track/v1/details/{number}"
TRANSACTION_SOURCE: Final = "porchcast"
TIMEOUT: Final = aiohttp.ClientTimeout(total=30)
# Refresh the token this long before UPS says it expires.
TOKEN_MARGIN: Final = 60.0

# Status.type values. UPS's spec doesn't list them; these are the long-standing
# Track API types. Out for delivery is type "I" with code "OT".
_PRE_TRANSIT_TYPES: Final = {"M", "MV"}
_IN_TRANSIT_TYPES: Final = {"I", "P"}
_EXCEPTION_TYPES: Final = {"X", "RS"}
_OUT_FOR_DELIVERY_CODES: Final = {"OT", "OF"}
_WINDOW_TYPES: Final = {"EDW", "CDW", "IDW"}


class UpsClient:
    """Track UPS packages. One instance per set of credentials."""

    @property
    def carrier(self) -> Carrier:
        """UPS."""
        return Carrier.UPS

    def __init__(
        self,
        session: aiohttp.ClientSession,
        client_id: str,
        client_secret: str,
        *,
        sandbox: bool = False,
        tz: dt.tzinfo = dt.UTC,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create a client.

        ``tz`` is the time zone UPS's local times (delivery windows) are read
        in: the household's.
        """
        self._session = session
        self._auth = aiohttp.encode_basic_auth(client_id, client_secret)
        self._base = SANDBOX_URL if sandbox else PRODUCTION_URL
        self._tz = tz
        self._clock = clock
        self._token: str | None = None
        self._token_expires = 0.0

    async def async_validate(self) -> None:
        """Fetch a token, to check the credentials."""
        self._token = None
        await self._async_token()

    async def async_track(self, number: str) -> TrackingResult:
        """Return the current tracking result for ``number``."""
        status, body = await self.async_fetch(number)
        return parse_track_response(status, body, self._tz)

    async def async_fetch(self, number: str) -> tuple[int, dict[str, Any]]:
        """Return the raw Track API response (HTTP status, JSON body)."""
        response = await self._async_get_track(number)
        if response.status == 401:
            # The token may have been revoked early; get a new one, once.
            self._token = None
            response = await self._async_get_track(number)
        return response.status, response.body

    async def _async_token(self) -> str:
        if self._token is not None and self._clock() < self._token_expires:
            return self._token
        try:
            async with self._session.post(
                self._base + TOKEN_PATH,
                data={"grant_type": "client_credentials"},
                headers={"Authorization": self._auth, "Accept": "application/json"},
                timeout=TIMEOUT,
            ) as resp:
                status = resp.status
                retry_after = resp.headers.get("Retry-After")
                body = await _json(resp)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CarrierError(f"UPS token request failed: {err}") from err
        if status == 429:
            raise RateLimitedError("UPS token quota exceeded", _seconds(retry_after))
        if status in (400, 401, 403):
            raise AuthError(f"UPS rejected the credentials: {_error_text(body)}")
        if status != 200 or not isinstance(body.get("access_token"), str):
            raise CarrierError(f"UPS token request returned HTTP {status}")
        self._token = body["access_token"]
        expires_in = _seconds(body.get("expires_in")) or 0.0
        self._token_expires = self._clock() + max(expires_in - TOKEN_MARGIN, 0.0)
        return self._token

    async def _async_get_track(self, number: str) -> _Response:
        token = await self._async_token()
        try:
            async with self._session.get(
                self._base + TRACK_PATH.format(number=number),
                params={
                    "locale": "en_US",
                    "returnSignature": "false",
                    "returnMilestones": "false",
                    "returnPOD": "false",
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "transId": uuid.uuid4().hex,
                    "transactionSrc": TRANSACTION_SOURCE,
                },
                timeout=TIMEOUT,
            ) as resp:
                status = resp.status
                if status == 429:
                    raise RateLimitedError(
                        "UPS rate limit", _seconds(resp.headers.get("Retry-After"))
                    )
                return _Response(status, await _json(resp))
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CarrierError(f"UPS tracking request failed: {err}") from err


class _Response:
    __slots__ = ("body", "status")

    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status = status
        self.body = body


async def _json(resp: aiohttp.ClientResponse) -> dict[str, Any]:
    try:
        body = await resp.json(content_type=None)
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _seconds(value: Any) -> float | None:
    try:
        return float(value)
    except TypeError, ValueError:
        return None


def _error_text(body: Mapping[str, Any]) -> str:
    errors = _dict(body.get("response")).get("errors")
    if isinstance(errors, list) and errors:
        first = _dict(errors[0])
        return f"{first.get('code', '?')} {first.get('message', '')}".strip()
    return "no details"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[dict[str, Any]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _str(value: Any) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def parse_track_response(
    status: int, body: Mapping[str, Any], tz: dt.tzinfo
) -> TrackingResult:
    """Turn a Track API response into a ``TrackingResult``, or raise."""
    if status == 404:
        raise NotFoundError(f"UPS has no data: {_error_text(body)}")
    if status == 403:
        raise AuthError(f"UPS refused tracking: {_error_text(body)}")
    if status == 401:
        raise AuthError("UPS rejected the token twice")
    if status != 200:
        raise CarrierError(f"UPS returned HTTP {status}: {_error_text(body)}")

    shipments = _list(_dict(body.get("trackResponse")).get("shipment"))
    packages = _list(shipments[0].get("package")) if shipments else []
    if not packages:
        warnings = _list(shipments[0].get("warnings")) if shipments else []
        detail = (
            f"{warnings[0].get('code', '?')} {warnings[0].get('message', '')}".strip()
            if warnings
            else "no package in response"
        )
        raise NotFoundError(f"UPS has no data: {detail}")
    package = packages[0]

    activities = _list(package.get("activity"))
    latest = activities[0] if activities else {}
    current = _dict(package.get("currentStatus")) or _dict(latest.get("status"))
    normalized = _status(current)
    last_event = _event(latest, tz) if latest else None

    eta: Eta | None = None
    delivered_at: dt.datetime | None = None
    delivered_location: str | None = None
    if normalized is Status.DELIVERED:
        delivered_at = _delivered_at(package, tz) or (
            last_event.time if last_event else None
        )
        delivered_location = _str(
            _dict(package.get("deliveryInformation")).get("location")
        )
    else:
        eta = _eta(package, tz)

    return TrackingResult(
        carrier=Carrier.UPS,
        status=normalized,
        description=_str(current.get("description"))
        or _str(_dict(latest.get("status")).get("description")),
        eta=eta,
        last_event=last_event,
        delivered_at=delivered_at,
        delivered_location=delivered_location,
    )


def _status(status: Mapping[str, Any]) -> Status:
    kind = (_str(status.get("type")) or "").upper()
    code = (_str(status.get("code")) or "").upper()
    description = (_str(status.get("description")) or "").lower()
    if kind == "D":
        return Status.DELIVERED
    if kind in _EXCEPTION_TYPES:
        return Status.EXCEPTION
    if code in _OUT_FOR_DELIVERY_CODES or "out for delivery" in description:
        return Status.OUT_FOR_DELIVERY
    if kind in _PRE_TRANSIT_TYPES:
        return Status.PRE_TRANSIT
    if kind in _IN_TRANSIT_TYPES:
        return Status.IN_TRANSIT
    return Status.UNKNOWN


def _date(value: Any) -> dt.date | None:
    text = _str(value)
    if text is None or len(text) != 8 or not text.isdigit():
        return None
    try:
        return dt.date(int(text[:4]), int(text[4:6]), int(text[6:]))
    except ValueError:
        return None


def _time(value: Any) -> dt.time | None:
    text = _str(value)
    if text is None or not text.isdigit() or len(text) > 6:
        return None
    # UPS sometimes drops the leading zero ("74700" for 07:47:00).
    text = text.zfill(6)
    try:
        return dt.time(int(text[:2]), int(text[2:4]), int(text[4:]))
    except ValueError:
        return None


def _offset(value: Any) -> dt.tzinfo | None:
    """Parse a ``-05:00`` style offset."""
    text = _str(value)
    if text is None or len(text) != 6 or text[0] not in "+-" or text[3] != ":":
        return None
    try:
        hours, minutes = int(text[1:3]), int(text[4:])
    except ValueError:
        return None
    sign = -1 if text[0] == "-" else 1
    return dt.timezone(sign * dt.timedelta(hours=hours, minutes=minutes))


def _location(location: Mapping[str, Any]) -> str | None:
    address = _dict(location.get("address"))
    city = _str(address.get("city"))
    parts = [city.title() if city else None, _str(address.get("stateProvince"))]
    country = _str(address.get("countryCode")) or _str(address.get("country"))
    if country and country != "US":
        parts.append(country)
    return ", ".join(p for p in parts if p) or None


def _event(activity: Mapping[str, Any], tz: dt.tzinfo) -> Event | None:
    status = _dict(activity.get("status"))
    text = _str(status.get("description"))
    if text is None:
        return None
    when: dt.datetime | None = None
    day, clock = _date(activity.get("date")), _time(activity.get("time"))
    if day is not None and clock is not None:
        when = dt.datetime.combine(
            day, clock, tzinfo=_offset(activity.get("gmtOffset")) or tz
        )
    return Event(
        text=text, location=_location(_dict(activity.get("location"))), time=when
    )


def _delivery_dates(package: Mapping[str, Any]) -> dict[str, dt.date]:
    dates: dict[str, dt.date] = {}
    for entry in _list(package.get("deliveryDate")):
        kind, day = _str(entry.get("type")), _date(entry.get("date"))
        if kind and day:
            dates.setdefault(kind.upper(), day)
    return dates


def _delivered_at(package: Mapping[str, Any], tz: dt.tzinfo) -> dt.datetime | None:
    day = _delivery_dates(package).get("DEL")
    times = _dict(package.get("deliveryTime"))
    clock = _time(times.get("endTime"))
    if day is None or clock is None or _str(times.get("type")) != "DEL":
        return None
    return dt.datetime.combine(day, clock, tzinfo=tz)


def _eta(package: Mapping[str, Any], tz: dt.tzinfo) -> Eta | None:
    """Rescheduled date over scheduled, plus a window or commit time if given."""
    dates = _delivery_dates(package)
    day = dates.get("RDD") or dates.get("SDD")
    if day is None:
        return None
    times = _dict(package.get("deliveryTime"))
    kind = (_str(times.get("type")) or "").upper()
    start, end = _time(times.get("startTime")), _time(times.get("endTime"))
    if kind in _WINDOW_TYPES and start is not None and end is not None:
        return Eta(
            dt.datetime.combine(day, start, tzinfo=tz),
            dt.datetime.combine(day, end, tzinfo=tz),
        )
    if kind == "CMT" and end is not None:
        return Eta(day, dt.datetime.combine(day, end, tzinfo=tz))
    return Eta(day, day)
