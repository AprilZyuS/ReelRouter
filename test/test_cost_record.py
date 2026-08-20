import pytest

from video.schemas import CostRecord, CostSource


def test_estimated_cost_record_has_no_reported_cost():
    cost = CostRecord(
        estimated_usd=0.24,
        reported_usd=None,
        source=CostSource.ESTIMATED,
    )

    assert cost.estimated_usd == 0.24
    assert cost.reported_usd is None


def test_provider_reported_cost_requires_a_value():
    with pytest.raises(ValueError, match="reported_usd"):
        CostRecord(
            estimated_usd=0.24,
            reported_usd=None,
            source=CostSource.PROVIDER_REPORTED,
        )


def test_estimated_cost_cannot_claim_a_reported_value():
    with pytest.raises(ValueError, match="预估成本"):
        CostRecord(
            estimated_usd=0.24,
            reported_usd=0.24,
            source=CostSource.ESTIMATED,
        )