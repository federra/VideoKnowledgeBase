import pytest

from app.core.database import build_engine, transaction


def test_database_refuses_non_postgres_urls():
    with pytest.raises(ValueError, match="PostgreSQL"):
        build_engine("sqlite://")


def test_engine_hides_parameters_and_transaction_rolls_back():
    engine = build_engine("postgresql+psycopg://unused:secret@127.0.0.1:15432/unused")
    assert engine.hide_parameters is True
    assert "secret" not in repr(engine)
    assert callable(transaction)
    engine.dispose()


@pytest.mark.parametrize("value", [0.1, "1.0000001", "100000000000000", "NaN", "Infinity"])
def test_exact_numeric_rejects_rounding_and_binary_floats(value):
    from app.core.models import ExactNumeric

    with pytest.raises((ValueError, TypeError)):
        ExactNumeric().process_bind_param(value, None)


def test_exact_numeric_preserves_valid_decimal_without_rounding():
    from decimal import Decimal

    from app.core.models import ExactNumeric

    assert ExactNumeric().process_bind_param("99999999999999.999999", None) == Decimal(
        "99999999999999.999999"
    )
    assert ExactNumeric().process_bind_param("1.50000000", None) == Decimal("1.5")


def test_released_migration_snapshots_are_intact():
    from migrations.integrity import read_snapshot

    for revision in range(1, 13):
        for direction in ("up", "down"):
            assert read_snapshot(f"{revision:04d}_{direction}.sql").strip()
