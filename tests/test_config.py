from decimal import Decimal

import pytest

from reconcile.config import ReconciliationConfig


def test_default_price_tolerance_is_decimal_safe() -> None:
    config = ReconciliationConfig()

    assert config.price_tolerance_rate == Decimal("0.02")


@pytest.mark.parametrize(
    "tolerance",
    [Decimal("-0.01"), Decimal("1"), Decimal("NaN"), Decimal("Infinity")],
)
def test_invalid_price_tolerance_is_rejected(tolerance: Decimal) -> None:
    with pytest.raises(ValueError, match="price_tolerance_rate"):
        ReconciliationConfig(price_tolerance_rate=tolerance)


def test_negative_money_precision_is_rejected() -> None:
    with pytest.raises(ValueError, match="money_decimal_places"):
        ReconciliationConfig(money_decimal_places=-1)


def test_invalid_money_rounding_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="money_rounding"):
        ReconciliationConfig(money_rounding="NOT_A_ROUNDING_MODE")
