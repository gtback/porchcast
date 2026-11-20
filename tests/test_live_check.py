"""Tests for the fixture scrubber in scripts/live_check.py (never run live)."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from .common import fixture

REAL = "1ZREAL0000000000001"


def _script() -> ModuleType:
    path = Path(__file__).parent.parent / "scripts/live_check.py"
    spec = importlib.util.spec_from_file_location("live_check", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scrub_removes_personal_data() -> None:
    """Numbers, names, addresses and signatures don't survive scrubbing."""
    body = fixture("ups/delivered")
    shipment = body["trackResponse"]["shipment"][0]
    shipment["inquiryNumber"] = REAL
    package = shipment["package"][0]
    package["trackingNumber"] = REAL
    package["packageAddress"] = [
        {"type": "DESTINATION", "name": "A PERSON", "address": {"city": "HOMETOWN"}}
    ]
    package["referenceNumber"] = [{"number": "ORDER-1"}]
    package["deliveryInformation"]["receivedBy"] = "A PERSON"
    package["deliveryInformation"]["signature"] = {"image": "base64"}
    package["activity"][0]["location"]["address"].update(
        addressLine1="1 Main St", postalCode="00000", city="HOMETOWN"
    )
    package["activity"][0]["status"]["description"] = f"Delivered {REAL}"

    scrubbed = _script().scrub(body, REAL)
    text = json.dumps(scrubbed)
    for secret in (REAL, "A PERSON", "HOMETOWN", "ORDER-1", "1 Main St", "00000"):
        assert secret not in text
    package = scrubbed["trackResponse"]["shipment"][0]["package"][0]
    assert package["trackingNumber"] == "1Z999AA10123456784"
    assert package["activity"][0]["location"]["address"] == {
        "countryCode": "US",
        "country": "US",
        "city": "CITY 1",
        "stateProvince": "ST",
    }
    assert package["deliveryInformation"] == {"location": "Front Door"}


def test_scrub_replaces_every_returned_number() -> None:
    """Other packages' numbers in a shipment are anonymized too."""
    other = "1ZOTHER000000000002"
    body = fixture("ups/in_transit")
    shipment = body["trackResponse"]["shipment"][0]
    shipment["inquiryNumber"] = REAL
    first = shipment["package"][0]
    first["trackingNumber"] = REAL
    second = json.loads(json.dumps(first))
    second["trackingNumber"] = other
    second["activity"][0]["status"]["description"] = f"Moved with {other}"
    shipment["package"].append(second)

    text = json.dumps(_script().scrub(body, REAL))
    assert REAL not in text
    assert other not in text
    assert "1ZSAMPLE0000000001" in text
    assert "1Z999AA10123456784" in text
