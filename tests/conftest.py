"""Shared setup for the tests.

Two kinds of data:
- the real company data in data/ (never committed). Tests that use it are skipped without it.
- the made-up sample data in sample_data/ (committed), used by test_sample_data.py.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import model  # noqa: E402

REAL_DATA = ROOT / "data" / "leads_jul-sep_clean.csv"


@pytest.fixture(scope="session")
def sample():
    """The real data (answer-key tests). Skipped when data/ is not on this computer."""
    if not REAL_DATA.exists():
        pytest.skip("real data not found in data/")
    from check_against_excel import load_sample
    return load_sample()


@pytest.fixture(scope="session")
def cfg():
    return model.load_config()


@pytest.fixture(scope="session")
def base(sample):
    cfg, leads, advisors = sample
    return model.base_inputs(leads, advisors, cfg)


@pytest.fixture(scope="session")
def default_team(base):
    return base["team_next_month"]


@pytest.fixture(scope="session")
def result(base, cfg):
    """All growth at 0%, target growth from config (+20%)."""
    plan = model.plan_inputs(base, {}, cfg["rate_cap"])
    return model.forecast(plan, cfg["assumptions"]["target_growth"], cfg["new_hire_band"])
