"""Tests for the model's rules (growth, caps, rounding, team, funnel steps). No data needed."""

import model

FULL = {"connect_step": True, "team": True, "carry_over": True}


def tiny_base(team=None):
    return {
        "funnel": FULL,
        "leads": {"A": 1000, "B": 500},
        "connect_rate": 0.8,
        "conversion": {"A": 0.10, "B": 0.95},
        "unassisted": {"A": 0.01, "B": 0.0},
        "self_pct": 0.25,
        "carry_pct": 0.015,
        "m1_share": 0.8,
        "productivity": {"new": 10.0, "old": 40.0},
        "team_next_month": team if team is not None else {"new": 0, "old": 10},
        "leads_m1": 1500,
        "leads_m2": 1000,
        "last_month_onboardings": 500,
    }


def test_round_half_up_matches_excel():
    assert model.round_half_up(2.5) == 3
    assert model.round_half_up(3.5) == 4
    assert model.round_half_up(2.49) == 2


def test_counts_are_rounded():
    plan = model.plan_inputs(tiny_base(), {"leads": {"A": 0.0005}})
    assert plan["leads"]["A"] == 1001  # 1000.5 rounds up


def test_rates_grow_relative_and_are_capped():
    plan = model.plan_inputs(tiny_base(), {"connect_rate": 0.10, "conversion": {"B": 0.10}})
    assert abs(plan["connect_rate"] - 0.88) < 1e-12   # 80% + 10% of 80%
    assert plan["conversion"]["B"] == 1.0             # 104.5% capped at 100%


def test_missing_growth_means_zero():
    plan = model.plan_inputs(tiny_base(), {})
    assert plan["leads"] == tiny_base()["leads"]
    assert plan["productivity"] == tiny_base()["productivity"]


def test_default_advisors_move_up_one_band():
    promotion = {"0-1 M": "1-2 M", "1-2 M": "2-3 M", "2-3 M": "3M+", "3M+": "3M+"}
    now = {"0-1 M": 2, "1-2 M": 3, "2-3 M": 4, "3M+": 5}
    assert model.default_advisors(now, promotion, "0-1 M", new_hires=6) == {
        "0-1 M": 6, "1-2 M": 2, "2-3 M": 3, "3M+": 9}


def test_team_size_never_changes_expected():
    small = model.forecast(model.plan_inputs(tiny_base({"new": 0, "old": 1}), {}), 0.2, "new")
    large = model.forecast(model.plan_inputs(tiny_base({"new": 0, "old": 100}), {}), 0.2, "new")
    assert small["expected_onboardings"] == large["expected_onboardings"] == small["funnel_total"]
    assert small["target"] == large["target"] and small["leads_needed"] == large["leads_needed"]
    assert small["team_short_for_forecast"] and not large["team_short_for_forecast"]


def test_advisors_needed_come_from_productivity():
    r = model.forecast(model.plan_inputs(tiny_base(), {}), 0.2, "new")
    # 10 advisors at 40 each: average productivity 40
    assert r["advisors_for_forecast"] == -(-r["advisor_needed"] // 40)
    assert r["advisors_required"] == -(-(600 * 0.75) // 40)          # target 600, 75% need one
    assert r["advisor_gap"] == r["advisors_required"] - 10
    assert r["extra_hires_needed"] == -(-max(0, 600 * 0.75 - 400) // 10)


def test_no_advisors_does_not_crash():
    r = model.forecast(model.plan_inputs(tiny_base({"new": 0, "old": 0}), {}), 0.2, "new")
    assert r["team_capacity"] == 0
    assert r["advisors_required"] == 0


def test_without_team_there_are_no_advisor_numbers():
    base = {**tiny_base({}), "productivity": {}, "self_pct": 0.0}
    r = model.forecast(model.plan_inputs(base, {}), 0.2, "new")
    assert r["team"] is False and "advisors_required" not in r


def test_lead_fields_follow_the_funnel():
    _, required = model.lead_fields({"connect_step": False, "team": False, "carry_over": True})
    assert "connected" not in required and "rm_code" not in required
    _, required = model.lead_fields(FULL)
    assert "connected" in required and "rm_code" in required and "lead_id" not in required


def test_clear_column_and_value_matches():
    assert model.match_column(["Lead Source", "Channel"], ["lead source", "source"]) == "Lead Source"
    assert model.match_column(["source", "Lead_Source"], ["lead source", "source"]) is None  # two
    meanings = {"Connected": ["same month connected"], "Not connected": ["no"]}
    assert model.match_value(" Same Month Connected ", meanings) == "Connected"
    assert model.match_value("Reached", meanings) is None
    assert model.match_value("1-2M", {"1-2 M": ["1-2 M"]}) == "1-2 M"


def test_two_conversion_routes_add_up():
    plan = model.plan_inputs(tiny_base(), {})
    r = model.forecast(plan, 0.2, "new")
    # A: 1000 x (0.8 x 0.10 + 0.01) = 90; B: 500 x 0.8 x 0.95 = 380
    assert round(r["same_month"]["A"]) == 90 and round(r["same_month"]["B"]) == 380
    # Doubling the unassisted route adds 1000 x 0.01 = 10 and does not need connection
    r2 = model.forecast(model.plan_inputs(tiny_base(), {"unassisted": {"A": 1.0}}), 0.2, "new")
    assert round(r2["same_month"]["A"] - r["same_month"]["A"]) == 10


def test_input_effects_are_each_change_alone():
    base = tiny_base()
    plan = model.plan_inputs(base, {"leads": {"A": 0.10}, "productivity": {"old": 0.25}})
    eff = model.input_effects(base, plan, 0.2, "new")
    assert round(eff["leads:A"]["output"]) == 9          # 100 more leads x 0.09 per lead
    assert eff["productivity:old"]["output"] == 0        # productivity never changes expected
    assert eff["productivity:old"]["team"] < 0           # ...it lowers the advisors needed
    assert eff["connect_rate"]["output"] == 0            # unchanged inputs do nothing
