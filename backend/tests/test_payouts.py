import sqlite3
from contextlib import closing

import pytest

from backend.models import PayoutLine, Policy
from backend.payout_rules import work_out_payout


def policy(plan="economy", add_ons=(), travelers=1, trip_cost=2000.0):
    return Policy.model_validate(
        {
            "policy_id": "POL-1",
            "customer_id": "CUS-1",
            "plan": plan,
            "add_ons": list(add_ons),
            "purchased_on": "2026-01-01",
            "sold_through": "direct",
            "trip": {
                "destination": "Lisbon",
                "departs_on": "2026-02-01",
                "returns_on": "2026-02-10",
                "trip_cost": trip_cost,
            },
            "travelers": [f"Traveler {n}" for n in range(travelers)],
            "status": "active",
        }
    )


def api_line(description, amount, kind="expense", **fields):
    return {
        "description": description,
        "amount": amount,
        "quantity": 1,
        "kind": kind,
        "nights": 0,
        "hours": 0,
    } | fields


def line(amount, kind="expense", description="Line", **fields):
    return PayoutLine.model_validate(api_line(description, amount, kind, **fields))


def payout(benefit, lines, paid_by_others=0.0, **plan):
    return work_out_payout(policy(**plan), benefit, lines, paid_by_others)


@pytest.mark.parametrize(
    ("plan", "add_ons", "kind", "quantity", "limit"),
    [
        ("economy", (), "item", 1, 150.0),
        ("economy", (), "item", 3, 450.0),
        ("premium", (), "item", 1, 300.0),
        ("first", (), "electronics", 1, 500.0),
        ("premium", ("electronics_plus",), "electronics", 1, 1200.0),
        ("premium", ("electronics_plus",), "electronics", 2, 2400.0),
    ],
)
def test_each_item_is_limited(plan, add_ons, kind, quantity, limit):
    calculation, paid = payout(
        "passport",
        [line(5000.0, kind, "Camera", quantity=quantity)],
        plan=plan,
        add_ons=add_ons,
    )
    assert calculation[0].step == f"Camera, limited to ${limit:,.2f}"
    assert calculation[0].amount == limit


def test_an_amount_under_its_limit_is_paid_in_full():
    calculation, paid = payout("trip_delay", [line(80.0, "item", "Bag")])
    assert [(s.step, s.amount) for s in calculation] == [("Bag", 80.0)]
    assert paid == 80.0


def test_hotels_are_limited_per_room_and_night():
    calculation, paid = payout(
        "trip_delay", [line(2000.0, "hotel", nights=1)], plan="first", travelers=3
    )
    assert calculation[0].amount == 700.0
    assert paid == 700.0


def test_meals_without_receipts_are_limited_per_traveler_and_day():
    calculation, _ = payout(
        "trip_delay",
        [line(500.0, "meals_without_receipts", hours=30)],
        plan="first",
        travelers=2,
    )
    assert calculation[0].amount == 140.0


def test_cash_is_paid_up_to_100_in_all():
    calculation, paid = payout(
        "trip_delay", [line(80.0, "cash"), line(60.0, "cash"), line(20.0)]
    )
    assert [(s.step, s.amount) for s in calculation] == [
        ("Line", 20.0),
        ("Cash, up to $100 in all", 100.0),
    ]
    assert paid == 120.0


def test_what_others_paid_comes_off():
    calculation, paid = payout("trip_delay", [line(250.0)], paid_by_others=75.0)
    assert calculation[-1].step == "Less what others have paid or refunded"
    assert calculation[-1].amount == -75.0
    assert paid == 175.0


@pytest.mark.parametrize(
    ("benefit", "paid"),
    [
        ("baggage", 450.0),
        ("emergency_medical", 450.0),
        ("trip_delay", 500.0),
        ("passport", 250.0),
    ],
)
def test_the_deductible_is_only_for_baggage_and_emergency_medical(benefit, paid):
    assert payout(benefit, [line(500.0)], plan="premium")[1] == paid


def test_the_deductible_is_never_more_than_is_left():
    calculation, paid = payout("baggage", [line(60.0)])
    assert calculation[-1].amount == -60.0
    assert paid == 0.0


def test_a_plan_without_a_deductible_shows_none():
    calculation, paid = payout("baggage", [line(60.0)], plan="first")
    assert [s.step for s in calculation] == ["Line"]
    assert paid == 60.0


def test_the_benefit_maximum_caps_the_payout():
    calculation, paid = payout("trip_delay", [line(900.0)])
    assert calculation[-1].step == "Less the amount over the maximum of $300"
    assert calculation[-1].amount == -600.0
    assert paid == 300.0


@pytest.mark.parametrize("benefit", ["trip_cancellation", "trip_interruption"])
def test_a_trip_is_paid_no_more_than_it_cost(benefit):
    _, paid = payout(benefit, [line(4000.0)], plan="first", trip_cost=2500.0)
    assert paid == 2500.0


def test_a_payout_is_never_below_zero():
    calculation, paid = payout("trip_delay", [line(50.0)], paid_by_others=80.0)
    assert calculation[-1].step == "Nothing is left to pay"
    assert calculation[-1].amount == 30.0
    assert paid == 0.0


def body(policy_id, benefit, lines, paid_by_others=0):
    return {
        "policy_id": policy_id,
        "benefit": benefit,
        "lines": lines,
        "paid_by_others": paid_by_others,
    }


SUITCASE = body(
    "POL-2007",
    "baggage",
    [
        api_line("Hard-shell suitcase", 239.99, "item"),
        api_line("Three T-shirts", 74.97, "item", quantity=3),
    ],
    paid_by_others=100,
)


def test_calculate_payout(client):
    response = client.post("/api/payouts", json=SUITCASE)
    assert response.status_code == 200
    assert response.json() == {
        "calculation": [
            {"step": "Hard-shell suitcase, limited to $150.00", "amount": 150.0},
            {"step": "Three T-shirts", "amount": 74.97},
            {"step": "Less what others have paid or refunded", "amount": -100.0},
            {"step": "Less the deductible", "amount": -100.0},
        ],
        "payout": 24.97,
        "needs_sign_off": False,
    }


def hospital(amount):
    return body("POL-2006", "emergency_medical", [api_line("Hospital bill", amount)])


def test_a_large_payout_needs_sign_off(client):
    response = client.post("/api/payouts", json=hospital(1200.0)).json()
    assert response["payout"] == 1200.0
    assert response["needs_sign_off"] is True


def test_exactly_the_limit_needs_no_sign_off(client):
    assert not client.post("/api/payouts", json=hospital(1000.0)).json()[
        "needs_sign_off"
    ]
    assert client.post("/api/payouts", json=hospital(1000.01)).json()["needs_sign_off"]


def test_the_limit_comes_from_the_settings(client, database):
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("UPDATE settings SET payout_approval_limit = 500")
    assert client.post("/api/payouts", json=hospital(600.0)).json()["needs_sign_off"]


def test_an_unknown_policy_is_not_found(client):
    response = client.post("/api/payouts", json=SUITCASE | {"policy_id": "POL-9999"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Policy POL-9999 not found"


@pytest.mark.parametrize(
    "change",
    [
        {"quantity": 0},
        {"kind": "jewelry"},
        {"amount": -1},
    ],
)
def test_an_invalid_line_is_refused(client, change):
    lines = [api_line("Suitcase", 200.0, "item") | change]
    response = client.post("/api/payouts", json=body("POL-2007", "baggage", lines))
    assert response.status_code == 422


def test_every_field_of_a_line_is_needed(client):
    incomplete = api_line("Meals", 90.0, "meals_without_receipts")
    del incomplete["hours"]
    response = client.post(
        "/api/payouts", json=body("POL-2007", "trip_delay", [incomplete])
    )
    assert response.status_code == 422


def test_an_unknown_benefit_is_refused(client):
    response = client.post("/api/payouts", json=SUITCASE | {"benefit": "pets"})
    assert response.status_code == 422
