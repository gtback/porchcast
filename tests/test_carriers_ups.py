"""Tests for the UPS client: parsing fixtures and the HTTP/token handling."""

import datetime as dt
from typing import Any

from aiohttp import ClientError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.porchcast.carriers.base import (
    AuthError,
    Carrier,
    CarrierError,
    Eta,
    Event,
    NotFoundError,
    RateLimitedError,
    RequestError,
    Status,
)
from custom_components.porchcast.carriers.ups import UpsClient, parse_track_response

from .common import UPS_NUMBER, UPS_TOKEN_URL, UPS_TRACK_URL, fixture

TZ = dt.timezone(dt.timedelta(hours=-5))
UTC_MINUS_5 = dt.timezone(dt.timedelta(hours=-5))


def _parse(name: str) -> Any:
    return parse_track_response(200, fixture(f"ups/{name}"), TZ)


def test_label_created() -> None:
    """A label with no scans yet is pre-transit, with no ETA or location."""
    result = _parse("label_created")
    assert result.carrier is Carrier.UPS
    assert result.status is Status.PRE_TRANSIT
    assert result.eta is None
    assert result.last_event == Event(
        text="Shipper created a label, UPS has not received the package yet.",
        location=None,
        time=dt.datetime(2026, 11, 20, 18, 30, tzinfo=TZ),
    )


def test_in_transit() -> None:
    """Scheduled date, end-of-day time: a one-day ETA; the latest scan wins."""
    result = _parse("in_transit")
    assert result.status is Status.IN_TRANSIT
    assert result.description == "Departed from Facility"
    assert result.eta == Eta(dt.date(2026, 11, 24), dt.date(2026, 11, 24))
    assert result.last_event == Event(
        text="Departed from Facility",
        location="Louisville, KY",
        time=dt.datetime(2026, 11, 21, 4, 5, tzinfo=UTC_MINUS_5),
    )
    assert result.delivered_at is None


def test_rescheduled_exception() -> None:
    """A rescheduled date replaces the scheduled one; type X is an exception."""
    result = _parse("rescheduled")
    assert result.status is Status.EXCEPTION
    assert result.eta == Eta(dt.date(2026, 11, 25), dt.date(2026, 11, 25))


def test_out_for_delivery_window() -> None:
    """Code OT is out for delivery; an estimated window gives both times."""
    result = _parse("out_for_delivery")
    assert result.status is Status.OUT_FOR_DELIVERY
    assert result.eta == Eta(
        dt.datetime(2026, 11, 24, 14, tzinfo=TZ),
        dt.datetime(2026, 11, 24, 18, tzinfo=TZ),
    )
    assert result.last_event is not None
    assert result.last_event.location == "Anytown, ST"


def test_delivered() -> None:
    """Delivered: time and place, and no ETA."""
    result = _parse("delivered")
    assert result.status is Status.DELIVERED
    assert result.eta is None
    assert result.delivered_at == dt.datetime(2026, 11, 24, 15, 10, tzinfo=TZ)
    assert result.delivered_location == "Front Door"


def test_commit_time() -> None:
    """A commit time is "by" that time on the scheduled day."""
    body = fixture("ups/in_transit")
    package = body["trackResponse"]["shipment"][0]["package"][0]
    package["deliveryTime"] = {"type": "CMT", "endTime": "103000"}
    result = parse_track_response(200, body, TZ)
    assert result.eta == Eta(
        dt.date(2026, 11, 24), dt.datetime(2026, 11, 24, 10, 30, tzinfo=TZ)
    )


def test_short_times_and_odd_values() -> None:
    """Times missing a leading zero parse; junk is ignored, not fatal."""
    body = fixture("ups/in_transit")
    package = body["trackResponse"]["shipment"][0]["package"][0]
    package["activity"][0]["time"] = "74700"
    package["activity"][0]["gmtOffset"] = "bogus"
    package["deliveryDate"] = [{"type": "SDD", "date": "2026-11-24"}, "junk"]
    result = parse_track_response(200, body, TZ)
    assert result.last_event is not None
    assert result.last_event.time == dt.datetime(2026, 11, 21, 7, 47, tzinfo=TZ)
    assert result.eta is None


def test_unknown_status_type() -> None:
    """A status type we don't know is unknown, not an error."""
    body = fixture("ups/in_transit")
    package = body["trackResponse"]["shipment"][0]["package"][0]
    package["currentStatus"] = {"type": "ZZ", "description": "Something new"}
    assert parse_track_response(200, body, TZ).status is Status.UNKNOWN


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (404, fixture("ups/not_found"), NotFoundError),
        (
            200,
            {"trackResponse": {"shipment": [{"warnings": [{"code": "TW0001"}]}]}},
            NotFoundError,
        ),
        (200, {}, NotFoundError),
        (400, fixture("ups/not_found"), RequestError),
        (403, {}, AuthError),
        (500, {}, CarrierError),
    ],
)
def test_error_responses(
    status: int, body: dict[str, Any], error: type[Exception]
) -> None:
    """Errors map to the normalized exceptions."""
    with pytest.raises(error):
        parse_track_response(status, body, TZ)


@pytest.fixture
async def client(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> UpsClient:
    """A UPS client on HA's (mocked) session, with a fake clock."""
    now = [0.0]
    client = UpsClient(
        async_get_clientsession(hass), "id", "secret", tz=TZ, clock=lambda: now[0]
    )
    client.now = now  # type: ignore[attr-defined]
    return client


async def test_track_fetches_and_caches_token(
    client: UpsClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """One token serves many requests until it nearly expires."""
    aioclient_mock.post(UPS_TOKEN_URL, json=fixture("ups/token"))
    aioclient_mock.get(UPS_TRACK_URL, json=fixture("ups/in_transit"))

    result = await client.async_track(UPS_NUMBER)
    assert result.status is Status.IN_TRANSIT
    await client.async_track(UPS_NUMBER)
    methods = [call[0].lower() for call in aioclient_mock.mock_calls]
    assert methods == ["post", "get", "get"]

    assert aioclient_mock.mock_calls[0][3]["Authorization"] == "Basic aWQ6c2VjcmV0"
    _, url, _, headers = aioclient_mock.mock_calls[1]
    assert headers["Authorization"] == "Bearer test-access-token"
    assert headers["transactionSrc"] == "porchcast"
    assert len(headers["transId"]) == 32
    assert url.query["returnSignature"] == "false"
    assert aioclient_mock.mock_calls[0][2] == {"grant_type": "client_credentials"}

    # expires_in is 14399 s; refresh a minute early.
    client.now[0] = 14399 - 30  # type: ignore[attr-defined]
    await client.async_track(UPS_NUMBER)
    assert [c[0].lower() for c in aioclient_mock.mock_calls][-2:] == ["post", "get"]


async def test_sandbox_url(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The sandbox flag uses UPS's test environment."""
    aioclient_mock.post(
        "https://wwwcie.ups.com/security/v1/oauth/token", json=fixture("ups/token")
    )
    client = UpsClient(async_get_clientsession(hass), "id", "secret", sandbox=True)
    await client.async_validate()
    assert aioclient_mock.call_count == 1


async def test_rejected_token_is_refreshed_once(
    client: UpsClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 401 on tracking gets a new token and retries; a second 401 is auth."""
    aioclient_mock.post(UPS_TOKEN_URL, json=fixture("ups/token"))
    aioclient_mock.get(UPS_TRACK_URL, status=401)
    with pytest.raises(AuthError):
        await client.async_track(UPS_NUMBER)
    assert [c[0].lower() for c in aioclient_mock.mock_calls] == [
        "post",
        "get",
        "post",
        "get",
    ]


@pytest.mark.parametrize(
    ("status", "error"),
    [(401, AuthError), (400, AuthError), (403, AuthError), (500, CarrierError)],
)
async def test_token_errors(
    client: UpsClient,
    aioclient_mock: AiohttpClientMocker,
    status: int,
    error: type[Exception],
) -> None:
    """Rejected credentials are an auth error; anything else is retryable."""
    aioclient_mock.post(UPS_TOKEN_URL, status=status, json=fixture("ups/token_invalid"))
    with pytest.raises(error):
        await client.async_validate()


async def test_rate_limited(
    client: UpsClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """429 carries the Retry-After the carrier sent."""
    aioclient_mock.post(UPS_TOKEN_URL, json=fixture("ups/token"))
    aioclient_mock.get(UPS_TRACK_URL, status=429, headers={"Retry-After": "120"})
    with pytest.raises(RateLimitedError) as err:
        await client.async_track(UPS_NUMBER)
    assert err.value.retry_after == 120


async def test_token_rate_limited(
    client: UpsClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 429 on the token endpoint is a rate limit too."""
    aioclient_mock.post(UPS_TOKEN_URL, status=429)
    with pytest.raises(RateLimitedError):
        await client.async_validate()


@pytest.mark.parametrize("exc", [ClientError("boom"), TimeoutError()])
async def test_network_errors(
    client: UpsClient, aioclient_mock: AiohttpClientMocker, exc: Exception
) -> None:
    """Network failures are carrier errors."""
    aioclient_mock.post(UPS_TOKEN_URL, json=fixture("ups/token"))
    aioclient_mock.get(UPS_TRACK_URL, exc=exc)
    with pytest.raises(CarrierError):
        await client.async_track(UPS_NUMBER)
    aioclient_mock.clear_requests()
    aioclient_mock.post(UPS_TOKEN_URL, exc=exc)
    with pytest.raises(CarrierError):
        await client.async_validate()


async def test_not_json(client: UpsClient, aioclient_mock: AiohttpClientMocker) -> None:
    """A non-JSON body (an HTML error page) is a carrier error."""
    aioclient_mock.post(UPS_TOKEN_URL, json=fixture("ups/token"))
    aioclient_mock.get(UPS_TRACK_URL, status=502, text="<html>Bad gateway</html>")
    with pytest.raises(CarrierError):
        await client.async_track(UPS_NUMBER)
