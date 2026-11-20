"""Constants for Porchcast."""

from enum import StrEnum
from typing import Final

DOMAIN: Final = "porchcast"
# Display name lives here only, so it is easy to change.
NAME: Final = "Porchcast"
TODO_LIST_NAME: Final = "Packages"


class Carrier(StrEnum):
    """Carriers Porchcast can track."""

    UPS = "ups"
    FEDEX = "fedex"
    USPS = "usps"


CARRIER_NAMES: Final[dict[Carrier, str]] = {
    Carrier.UPS: "UPS",
    Carrier.FEDEX: "FedEx",
    Carrier.USPS: "USPS",
}
