"""The boundary between the marketplace and a delivery company.

As with payments, only a sandbox exists until there is a courier contract and
its integration documents. A real courier implements `CourierProvider`, and is
switched on by a row in the couriers table.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from ..config import get_settings
from ..core.errors import Conflict, Unauthenticated, ValidationFailed
from ..models.enums import ShipmentStatus

SANDBOX_CODE = "sandbox"


@dataclass(frozen=True, slots=True)
class BookingRequest:
    order_code: str
    origin_city: str
    destination_city: str
    delivery_address: str
    delivery_phone: str
    cartons: int
    weight_kg: int
    collect_pkr: int


@dataclass(frozen=True, slots=True)
class Booking:
    tracking_number: str
    label_pdf: bytes


@dataclass(frozen=True, slots=True)
class TrackingUpdate:
    event_id: str
    tracking_number: str
    status: ShipmentStatus
    location: str | None
    note: str | None
    payload: dict[str, Any]


class CourierProvider(Protocol):
    code: str

    def book(self, request: BookingRequest) -> Booking: ...
    def parse_callback(self, body: bytes, signature: str | None) -> TrackingUpdate: ...


def simple_pdf(lines: list[str]) -> bytes:
    """A one page text PDF, enough for a shipping label."""

    def escape(text: str) -> str:
        ascii_text = text.encode("ascii", "replace").decode()
        return ascii_text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    commands = ["BT", "/F1 14 Tf", "50 780 Td", "20 TL"]
    for line in lines:
        commands.append(f"({escape(line)}) Tj T*")
    commands.append("ET")
    stream = "\n".join(commands).encode()

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, content in enumerate(objects, start=1):
        offsets.append(len(output))
        output += b"%d 0 obj\n%s\nendobj\n" % (number, content)

    xref_at = len(output)
    output += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        output += b"%010d 00000 n \n" % offset
    output += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_at,
    )
    return bytes(output)


class SandboxCourier:
    code = SANDBOX_CODE

    def book(self, request: BookingRequest) -> Booking:
        tracking = f"SBX{uuid.uuid4().hex[:12].upper()}"
        # The sender is always the platform. A label travels through many hands
        # and must not reveal who supplied an unbranded lot.
        lines = [
            "SANDBOX LABEL - NOT A REAL SHIPMENT",
            f"Tracking: {tracking}",
            f"Order: {request.order_code}",
            "",
            f"From: Khazana Outlet fulfilment, {request.origin_city}",
            f"To: {request.delivery_address}, {request.destination_city}",
            f"Phone: {request.delivery_phone}",
            f"Cartons: {request.cartons}   Weight: {request.weight_kg} kg",
        ]
        if request.collect_pkr:
            lines.append(f"COLLECT ON DELIVERY: {request.collect_pkr:,} PKR")
        return Booking(tracking_number=tracking, label_pdf=simple_pdf(lines))

    def sign(self, body: bytes) -> str:
        key = f"{get_settings().secret_key}:courier:{self.code}".encode()
        return hmac.new(key, body, hashlib.sha256).hexdigest()

    def build_callback(
        self, *, tracking_number: str, status: ShipmentStatus, location: str | None = None
    ) -> tuple[bytes, str]:
        body = json.dumps(
            {
                "event_id": f"trk_{uuid.uuid4().hex}",
                "tracking_number": tracking_number,
                "status": status.value,
                "location": location,
            },
            sort_keys=True,
        ).encode()
        return body, self.sign(body)

    def parse_callback(self, body: bytes, signature: str | None) -> TrackingUpdate:
        if not signature or not hmac.compare_digest(self.sign(body), signature):
            raise Unauthenticated("The tracking callback signature is not valid.")
        try:
            payload = json.loads(body)
            return TrackingUpdate(
                event_id=str(payload["event_id"]),
                tracking_number=str(payload["tracking_number"]),
                status=ShipmentStatus(payload["status"]),
                location=payload.get("location"),
                note=payload.get("note"),
                payload=payload,
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise ValidationFailed("The tracking callback could not be read.") from exc


_SANDBOX = SandboxCourier()


def sandbox_courier() -> SandboxCourier:
    if get_settings().is_production:
        raise Conflict("The sandbox courier is not available in production.")
    return _SANDBOX


def provider_for(code: str) -> CourierProvider:
    if code == SANDBOX_CODE:
        return sandbox_courier()
    raise Conflict(f"Courier {code} has no integration yet.")
