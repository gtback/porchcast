"""Constants for Porchcast."""

from typing import Final

from .carriers.base import Carrier

DOMAIN: Final = "porchcast"
# Display name lives here only, so it is easy to change.
NAME: Final = "Porchcast"
TODO_LIST_NAME: Final = "Packages"


CARRIER_NAMES: Final[dict[Carrier, str]] = {
    Carrier.UPS: "UPS",
    Carrier.FEDEX: "FedEx",
    Carrier.USPS: "USPS",
}

# Config entry data: one key per configured carrier, each holding these keys.
CONF_CLIENT_ID: Final = "client_id"
CONF_CLIENT_SECRET: Final = "client_secret"  # noqa: S105
CONF_SANDBOX: Final = "sandbox"

EVENT_ETA_CHANGED: Final = "porchcast_eta_changed"
EVENT_STATUS_CHANGED: Final = "porchcast_status_changed"
EVENT_DELIVERED: Final = "porchcast_delivered"
