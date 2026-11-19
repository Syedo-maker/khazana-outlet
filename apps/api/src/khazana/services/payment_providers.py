"""The boundary between the marketplace and whoever moves the money.

Only sandbox providers exist. A real JazzCash or Easypaisa adapter needs the
merchant's integration documents, signature rules and callback formats, none of
which exist until the company has merchant accounts. Writing one from guesses
would produce code that looks finished and handles money wrongly, so each real
adapter will implement `PaymentProvider` when those documents arrive.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from ..config import get_settings
from ..core.errors import Conflict, Unauthenticated, ValidationFailed
from ..models import Order, Payment
from ..models.enums import PaymentMethod

SIGNATURE_HEADER = "x-sandbox-signature"
Outcome = Literal["succeeded", "failed"]


@dataclass(frozen=True, slots=True)
class Checkout:
    """What the buyer has to do next."""

    action: Literal["sandbox_wallet", "bank_transfer", "cash_on_delivery"]
    instructions: str


@dataclass(frozen=True, slots=True)
class ProviderEvent:
    event_id: str
    reference: str
    outcome: Outcome
    amount_pkr: int
    payload: dict[str, Any]


class PaymentProvider(Protocol):
    name: str

    def new_reference(self, order: Order) -> str | None: ...
    def checkout(self, payment: Payment, order: Order) -> Checkout: ...
    def parse_callback(self, body: bytes, signature: str | None) -> ProviderEvent: ...


class SandboxWalletProvider:
    """Stands in for a mobile wallet, with properly signed callbacks."""

    def __init__(self, name: str, label: str) -> None:
        self.name = name
        self.label = label

    def new_reference(self, order: Order) -> str:
        return f"SBX-{uuid.uuid4().hex[:20].upper()}"

    def checkout(self, payment: Payment, order: Order) -> Checkout:
        return Checkout(
            action="sandbox_wallet",
            instructions=f"Sandbox {self.label} payment. No real money moves.",
        )

    def _key(self) -> bytes:
        return f"{get_settings().secret_key}:{self.name}".encode()

    def sign(self, body: bytes) -> str:
        return hmac.new(self._key(), body, hashlib.sha256).hexdigest()

    def build_callback(
        self, *, reference: str, outcome: Outcome, amount_pkr: int
    ) -> tuple[bytes, str]:
        body = json.dumps(
            {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "reference": reference,
                "outcome": outcome,
                "amount_pkr": amount_pkr,
            },
            sort_keys=True,
        ).encode()
        return body, self.sign(body)

    def parse_callback(self, body: bytes, signature: str | None) -> ProviderEvent:
        # The signature is checked on the raw bytes, before anything is parsed.
        if not signature or not hmac.compare_digest(self.sign(body), signature):
            raise Unauthenticated("The payment callback signature is not valid.")
        try:
            payload = json.loads(body)
            outcome = payload["outcome"]
            if outcome not in ("succeeded", "failed"):
                raise ValueError(outcome)
            return ProviderEvent(
                event_id=str(payload["event_id"]),
                reference=str(payload["reference"]),
                outcome=outcome,
                amount_pkr=int(payload["amount_pkr"]),
                payload=payload,
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise ValidationFailed("The payment callback could not be read.") from exc


class BankTransferProvider:
    name = "bank_transfer"

    def new_reference(self, order: Order) -> None:
        # The buyer supplies this from their bank's receipt.
        return None

    def checkout(self, payment: Payment, order: Order) -> Checkout:
        settings = get_settings()
        return Checkout(
            action="bank_transfer",
            instructions=(
                f"Transfer {payment.amount_pkr:,} PKR to {settings.bank_account_title}, "
                f"IBAN {settings.bank_account_iban}, quoting {order.order_code}. "
                "Then enter your bank's transaction reference here."
            ),
        )

    def parse_callback(self, body: bytes, signature: str | None) -> ProviderEvent:
        raise Conflict("Bank transfers are confirmed by an admin, not by a callback.")


class CashOnDeliveryProvider:
    name = "cash_on_delivery"

    def new_reference(self, order: Order) -> str:
        return f"COD-{order.order_code}"

    def checkout(self, payment: Payment, order: Order) -> Checkout:
        return Checkout(
            action="cash_on_delivery",
            instructions=f"Pay the courier {payment.amount_pkr:,} PKR on delivery.",
        )

    def parse_callback(self, body: bytes, signature: str | None) -> ProviderEvent:
        raise Conflict("Cash on delivery is recorded when the courier delivers.")


_WALLETS: dict[PaymentMethod, SandboxWalletProvider] = {
    PaymentMethod.JAZZCASH: SandboxWalletProvider("sandbox_jazzcash", "JazzCash"),
    PaymentMethod.EASYPAISA: SandboxWalletProvider("sandbox_easypaisa", "Easypaisa"),
}
_BANK = BankTransferProvider()
_COD = CashOnDeliveryProvider()


def provider_for(method: PaymentMethod) -> PaymentProvider:
    if method == PaymentMethod.BANK_TRANSFER:
        return _BANK
    if method == PaymentMethod.COD:
        return _COD
    wallet = _WALLETS.get(method)
    if wallet is None:
        raise Conflict("That payment method is not available.")
    if get_settings().is_production:
        raise Conflict("This wallet is not connected to a live payment provider yet.")
    return wallet


def wallet_named(name: str) -> SandboxWalletProvider:
    for wallet in _WALLETS.values():
        if wallet.name == name:
            if get_settings().is_production:
                break
            return wallet
    raise Conflict("That payment provider is not available.")
