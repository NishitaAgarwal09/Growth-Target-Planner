"""The made-up sample data: it loads with automatic matching and runs the whole model.

These tests use only sample_data/ (no company data), so they also run in the public copy.
"""

from pathlib import Path

import pandas as pd
import pytest

import model

SAMPLE = Path(__file__).resolve().parent.parent / "sample_data"


@pytest.fixture(scope="module")
def loaded(cfg):
    raw = pd.read_csv(SAMPLE / "leads_sample.csv")
    team_raw = pd.read_csv(SAMPLE / "advisors_sample.csv")
    fields, required = model.lead_fields(cfg["funnel"])
    # Every column is found automatically, as in the app
    lead_map = {f: model.match_column(raw.columns, cfg["column_names"][f]) for f in fields}
    team_map = {f: model.match_column(team_raw.columns, cfg["column_names"][f])
                for f in model.ADVISOR_FIELDS}
    assert all(lead_map.values()) and all(team_map.values())
    # ...and every value is understood automatically
    meanings = {}
    for column, kind in [(lead_map["connected"], "connected"), (lead_map["converted"], "converted")]:
        labels, _ = model.distinct_labels(raw[column])
        meanings[kind] = {l: model.match_value(l, cfg["value_names"][kind]) for l in labels}
        assert all(meanings[kind].values())
    labels = {
        "connected_yes": [l for l, m in meanings["connected"].items()
                          if m == "Connected in the same month"],
        "connected_later": [l for l, m in meanings["connected"].items()
                            if m == "Connected in a later month"],
        "converted_same_month": [l for l, m in meanings["converted"].items()
                                 if m == "Onboarded in the same month"],
        "converted_later": [l for l, m in meanings["converted"].items()
                            if m == "Onboarded in a later month"],
        "not_converted": [l for l, m in meanings["converted"].items() if m == "Not onboarded"],
    }
    tenure, _ = model.distinct_labels(team_raw[team_map["tenure"]])
    tenure_map = {l: model.match_value(l, {b: [b] for b in cfg["tenure_bands"]}) for l in tenure}
    assert all(tenure_map.values())
    leads = model.prepare_leads(raw, lead_map, labels)
    advisors = model.prepare_advisors(team_raw, team_map, tenure_map)
    return raw, lead_map, leads, team_raw, advisors


def test_sample_has_three_months_and_three_sources(loaded):
    _, _, leads, _, _ = loaded
    assert leads["lead_month"].nunique() == 3
    assert sorted(leads["source"].unique()) == ["Google", "Meta", "Organic"]


def test_sample_passes_data_checks(loaded, cfg):
    raw, lead_map, leads, team_raw, advisors = loaded
    problems = (model.check_leads(raw, lead_map, leads, cfg)
                + model.check_advisors(team_raw, advisors, leads, cfg["tenure_bands"]))
    assert not any(level == "error" for level, _ in problems)


def test_sample_runs_the_whole_model(loaded, cfg):
    _, _, leads, _, advisors = loaded
    base = model.base_inputs(leads, advisors, cfg)
    plan = model.plan_inputs(base, {}, cfg["rate_cap"])
    r = model.forecast(plan, cfg["assumptions"]["target_growth"], cfg["new_hire_band"])
    # With 0% growth the model reproduces the last month's same-month results
    assert round(r["same_month_total"]) == base["same_month_onboardings"]
    assert r["gap"] > 0 and r["advisors_required"] > 0
    highs = model.recent_highs(leads, advisors, cfg["lead_sources"], cfg["tenure_bands"])
    assert model.lever_requirements(plan, r, highs)
    assert model.insights(leads, base, plan, r, highs, cfg["assumptions"]["target_growth"],
                          cfg["new_hire_band"], model.load_rules(), {})
