"""Helpers shared by the tests."""

import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures"
UPS_NUMBER = "1Z999AA10123456784"
UPS_TOKEN_URL = "https://onlinetools.ups.com/security/v1/oauth/token"
UPS_TRACK_URL = f"https://onlinetools.ups.com/api/track/v1/details/{UPS_NUMBER}"
UPS_DATA = {"ups": {"client_id": "id", "client_secret": "secret", "sandbox": False}}


def fixture(name: str) -> dict[str, Any]:
    """Load a recorded or synthetic carrier response, e.g. ``ups/in_transit``."""
    data = json.loads((FIXTURES / f"{name}.json").read_text())
    assert isinstance(data, dict)
    return data
