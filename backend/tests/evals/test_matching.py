import pytest

from app.evals.matching import (
    contains_text,
    extract_quantities,
    find_fact,
    matches_alternative,
    parse_expected_number,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Spend was ₹4,374,000 this quarter", "₹4,374,000"),
        ("Spend was ₹43,74,000 this quarter", "₹4,374,000"),  # Indian grouping
        ("Spend was INR 4374000", "₹4,374,000"),
        ("Spend was Rs. 43.74 lakh", "₹4,374,000"),
        ("about ₹43.7 lakh", "₹4,374,000"),  # rounding within 1%
        ("roughly ₹0.44 crore", "₹4,374,000"),
        ("₹4.37M spent", "₹4,374,000"),
        ("35% over budget", "35.0%"),
        ("35.0 percent over", "35.0%"),
        ("a variance of -30.0%", "30.0%"),  # signs are ignored
        ("30% under budget", "-30.0%"),
        ("it grew 54.2%", "54.2%"),
        ("there are 6 open positions", "6"),
    ],
)
def test_numbers_match_after_normalisation(text: str, expected: str) -> None:
    assert matches_alternative(text, expected)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Spend was ₹4,100,000", "₹4,374,000"),  # 6% off
        ("35 people work there", "35.0%"),  # percent needs a percent
        ("We are in 2026-Q3", "3"),  # "Q3" is not the number 3
        ("₹4,374", "₹4,374,000"),
    ],
)
def test_numbers_do_not_match(text: str, expected: str) -> None:
    assert not matches_alternative(text, expected)


def test_extract_quantities_scales_and_percent() -> None:
    quantities = extract_quantities("₹1.2 crore and 15% and 3k")
    assert [q.value for q in quantities] == [12_000_000, 15, 3000]
    assert [q.percent for q in quantities] == [False, True, False]
    assert quantities[0].money


def test_parse_expected_number_only_for_single_numbers() -> None:
    assert parse_expected_number("₹4,374,000") is not None
    assert parse_expected_number("Customer Portal") is None
    assert parse_expected_number("2026-Q3") is None


def test_text_match_is_case_insensitive_on_word_boundaries() -> None:
    assert contains_text("The **ML Forecasting** project", "Ml Forecasting")
    assert contains_text("repo fixture-org/data-pipeline", "data-pipeline")
    assert not contains_text("our database", "Data")
    assert contains_text("The Data department", "data")


def test_find_fact_returns_first_alternative_found() -> None:
    assert find_fact("Payments Gateway is late", ["payments-gateway", "Payments Gateway"]) == (
        "Payments Gateway"
    )
    assert find_fact("nothing here", ["x", "y"]) is None
