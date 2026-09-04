"""Configuration values shared by reconciliation components."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True, slots=True)
class ReconciliationConfig:
    """Business policy settings for a reconciliation run."""

    price_tolerance_rate: Decimal = Decimal("0.02")
    money_decimal_places: int = 2
    money_rounding: str = ROUND_HALF_UP

    def __post_init__(self) -> None:
        if not Decimal("0") <= self.price_tolerance_rate < Decimal("1"):
            raise ValueError("price_tolerance_rate must be at least 0 and less than 1")
        if self.money_decimal_places < 0:
            raise ValueError("money_decimal_places must be non-negative")
