"""Growth Target Planner: all calculations (no Streamlit code here, so it can be tested).

Flow:
  1. load_config()                      read config.yaml
  2. prepare_leads() / prepare_advisors()
                                        turn the uploaded tables into standard columns,
                                        using the column mapping and value labels the user chose
  3. history tables                     totals by month, source, tenure band
  4. base_inputs()                      last month's actuals = the starting point of the plan
  5. plan_inputs()                      base x (1 + growth %)
  6. forecast()                         expected onboardings, target, and the leads and advisors
                                        each one needs

The funnel can be switched on or off step by step (config "funnel"): the connect step, a team
(advisors) working the leads, and carry-over from earlier months.
"""

import math
import re
import warnings
from pathlib import Path

import pandas as pd
from ruamel.yaml import YAML

CONFIG_PATH = Path(__file__).parent / "config.yaml"

# Fields the model needs. The user maps each one to a column in their file.
LEAD_FIELDS = {
    "lead_id": "Lead ID",
    "created_date": "Created date",
    "source": "Lead source",
    "connected": "Connected",
    "rm_code": "Advisor code on the lead",
    "converted": "Converted",
    "onboarding_date": "Onboarding date",
}
ADVISOR_FIELDS = {
    "advisor_code": "Advisor code",
    "tenure": "Tenure band",
}
REQUIRED_ADVISOR_FIELDS = list(ADVISOR_FIELDS)


def lead_fields(funnel):
    """The lead fields used by this funnel, and which of them are required.

    Lead ID is only used to check for duplicates, so it is never required.
    """
    fields = {k: v for k, v in LEAD_FIELDS.items()
              if not (k == "connected" and not funnel["connect_step"])
              and not (k == "rm_code" and not funnel["team"])}
    return fields, [k for k in fields if k != "lead_id"]


# Kept for callers that use the full funnel.
REQUIRED_LEAD_FIELDS = [k for k in LEAD_FIELDS if k != "lead_id"]


# ---------------------------------------------------------------- automatic matching
# A column or value is only matched when it clearly is the same thing: names are compared
# after ignoring case, spaces and punctuation (so "Lead Source" = "lead_source" = "LEAD SOURCE").

def normalise(text):
    return re.sub(r"[^a-z0-9+]", "", str(text).lower())


def match_column(columns, names):
    """The one column whose name is in `names`, or None if there is no clear single match."""
    wanted = {normalise(n) for n in names}
    found = [c for c in columns if normalise(c) in wanted]
    return found[0] if len(found) == 1 else None


def match_value(value, meanings):
    """meanings: {meaning: [names]}. Returns the meaning whose names include `value`, or None."""
    v = normalise(value)
    hits = [m for m, names in meanings.items() if v in {normalise(n) for n in names}]
    return hits[0] if len(hits) == 1 else None


# ---------------------------------------------------------------- config

def load_config(path=CONFIG_PATH):
    with open(path, encoding="utf-8") as f:
        return YAML(typ="safe").load(f)


# ---------------------------------------------------------------- loading

def read_table(file_or_path):
    """Read a CSV or Excel file (path or uploaded file) into a table."""
    name = str(getattr(file_or_path, "name", file_or_path)).lower()
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(file_or_path)
    return pd.read_csv(file_or_path)


def _code_to_text(series):
    """Advisor codes may arrive as 123, 123.0 or ' 123 '. Make them all '123'; blank stays blank."""
    def clean(v):
        if pd.isna(v):
            return pd.NA
        s = str(v).strip()
        if s == "":
            return pd.NA
        try:
            f = float(s)
            if f.is_integer():
                return str(int(f))
        except ValueError:
            pass
        return s
    return series.map(clean).astype("string")


def _to_date(series):
    """Read dates; anything that is not a date becomes blank (the data checks count these)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return pd.to_datetime(series, errors="coerce")


def _label(series):
    """Trim spaces so ' No ' and 'No' count as the same label."""
    return series.astype("string").str.strip()


def _as_list(v):
    return [v] if isinstance(v, str) else list(v)


def distinct_labels(series):
    """The different (trimmed, non-blank) values in a column, sorted, and the number of blanks."""
    labels = _label(series)
    blank = labels.isna() | (labels == "")
    return sorted(labels[~blank].unique().tolist()), int(blank.sum())


def prepare_leads(raw, column_map, value_labels):
    """Return the lead table with standard columns.

    column_map:   {field key from LEAD_FIELDS: column name in the file}. "connected" and
                  "rm_code" may be missing when the funnel has no connect step or no team:
                  then every lead counts as connected, and no lead has an advisor.
    value_labels: {"connected_yes": [labels meaning connected in the lead's month],
                   "connected_later": [labels meaning connected in a later month] (optional),
                   "converted_same_month": [labels meaning onboarded in the lead's month],
                   "converted_later": [labels meaning onboarded in a later month],
                   "not_converted": [labels meaning not onboarded]}
    """
    created = _to_date(raw[column_map["created_date"]])
    onboarded_on = _to_date(raw[column_map["onboarding_date"]])
    converted = _label(raw[column_map["converted"]])
    same = _as_list(value_labels["converted_same_month"])
    later = _as_list(value_labels["converted_later"])
    if column_map.get("connected"):
        status = _label(raw[column_map["connected"]])
        connected = status.isin(_as_list(value_labels["connected_yes"])).fillna(False).astype(bool)
        connected_any = connected | status.isin(
            _as_list(value_labels.get("connected_later", []))).fillna(False).astype(bool)
    else:
        connected = connected_any = pd.Series(True, index=raw.index)
    if column_map.get("rm_code"):
        rm_code = _code_to_text(raw[column_map["rm_code"]])
    else:
        rm_code = pd.Series(pd.NA, index=raw.index, dtype="string")

    out = pd.DataFrame({
        "lead_month": created.dt.to_period("M"),
        "source": _label(raw[column_map["source"]]),
        "connected": connected,            # connected in the lead's own month
        "connected_any": connected_any,    # connected in any month
        "rm_code": rm_code,
        "onboarded": converted.isin(same + later).fillna(False).astype(bool),
        "same_month": converted.isin(same).fillna(False).astype(bool),
        "onboarding_month": onboarded_on.dt.to_period("M"),
    })
    out["self_conversion"] = out["onboarded"] & out["rm_code"].isna()
    return out


def prepare_advisors(raw, column_map, tenure_map):
    """Return the advisor table with standard columns.

    tenure_map: {label in the file: tenure band from config}. Labels not in the map
                (including blank) mean the advisor has left and are excluded.
    """
    tenure = _label(raw[column_map["tenure"]])
    out = pd.DataFrame({
        "advisor_code": _code_to_text(raw[column_map["advisor_code"]]),
        "band": tenure.map(tenure_map),
    })
    return out[out["band"].notna()].reset_index(drop=True)


# ---------------------------------------------------------------- data checks
# Each check returns a list of (level, message). level is "error" (the plan cannot be built),
# "warning" (the plan is built but something looks off) or "info". Messages show counts only.

def lead_sources(leads, cfg):
    """Lead sources found in the data: the ones named in config first, then any others."""
    found = leads["source"].dropna().unique().tolist()
    named = [s for s in cfg["lead_sources"] if s in found]
    return named + sorted(s for s in found if s not in cfg["lead_sources"])


def check_mapping(column_map, fields, required):
    """Every required field has a column, and no column is used twice."""
    problems = []
    for key in required:
        if not column_map.get(key):
            problems.append(("error", f"Choose a column for **{fields[key]}**. The plan needs it."))
    used = [c for c in column_map.values() if c]
    for col in sorted({c for c in used if used.count(c) > 1}):
        names = ", ".join(fields[k] for k, v in column_map.items() if v == col)
        problems.append(("error", f"The column **{col}** is chosen for more than one field "
                                  f"({names}). Each field needs its own column."))
    return problems


def _n(count, one, many=None):
    return f"{count:,} {one if count == 1 else (many or one + 's')}"


def _blank(raw_column):
    text = _label(raw_column.astype("string"))
    return text.isna() | (text == "")


def check_leads(raw, column_map, leads, cfg):
    """Plain-language checks on the prepared lead table."""
    out = []
    created_blank = _blank(raw[column_map["created_date"]])
    if leads["lead_month"].notna().sum() == 0:
        out.append(("error", f"None of the values in **{column_map['created_date']}** could be read "
                             "as a date. Check that you picked the created date column."))
        return out
    unreadable = int((leads["lead_month"].isna() & ~created_blank).sum())
    if unreadable:
        out.append(("warning", f"{_n(unreadable, 'lead')} have a created date that could not be read "
                               "as a date. They are left out."))
    if created_blank.sum():
        out.append(("warning", f"{_n(int(created_blank.sum()), 'lead')} have no created date. "
                               "They are left out."))

    months = leads["lead_month"].dropna().nunique()
    if months < 2:
        out.append(("error", "The lead file covers only one month. The plan needs at least two "
                             "(ideally three) months of leads for carry-over."))
    elif months < 3:
        out.append(("warning", "The lead file covers only two months. Three months are recommended."))

    max_sources = cfg["max_lead_sources"]
    sources = leads["source"].dropna().unique()
    if len(sources) > max_sources:
        out.append(("error", f"The lead source column has {len(sources)} different values. "
                             f"Version 1 supports up to {max_sources} lead sources. Check that you "
                             "picked the right column."))
    blank_source = int(_blank(raw[column_map["source"]]).sum())
    if blank_source:
        out.append(("warning", f"{_n(blank_source, 'lead')} have no lead source and are not "
                               "counted in any source."))

    ob_blank = _blank(raw[column_map["onboarding_date"]])
    ob_unreadable = int((leads["onboarding_month"].isna() & ~ob_blank).sum())
    if ob_unreadable:
        out.append(("warning", f"{_n(ob_unreadable, 'lead')} have an onboarding date that could "
                               "not be read as a date."))
    no_date = int((leads["onboarded"] & leads["onboarding_month"].isna()).sum())
    if no_date:
        out.append(("warning", f"{_n(no_date, 'onboarded lead')} have no onboarding date, so they "
                               "are not counted in onboardings by onboarding date."))
    date_not_onb = int((~leads["onboarded"] & leads["onboarding_month"].notna()).sum())
    if date_not_onb:
        out.append(("info", f"{_n(date_not_onb, 'lead')} have an onboarding date but are marked as "
                            "not onboarded. They are not counted as onboardings."))
    both = leads["onboarding_month"].notna() & leads["lead_month"].notna()
    before = int((leads.loc[both, "onboarding_month"] < leads.loc[both, "lead_month"]).sum())
    if before:
        out.append(("warning", f"{_n(before, 'lead')} were onboarded in a month before the lead "
                               "was created."))

    if column_map.get("lead_id"):
        dup = int(raw[column_map["lead_id"]].dropna().duplicated().sum())
        if dup:
            out.append(("warning", f"{_n(dup, 'Lead ID')} appear more than once. Each row is "
                                   "still counted as a lead."))
    if leads["onboarded"].sum() == 0:
        out.append(("error", "No lead is marked as onboarded. Check the Converted values."))
    return out


def check_advisors(raw, advisors, leads, bands):
    """Plain-language checks on the prepared advisor table."""
    out = []
    if advisors.empty:
        out.append(("error", "No advisor has a tenure band. Check the tenure values."))
        return out
    left = len(raw) - len(advisors)
    if left:
        out.append(("info", f"{_n(left, 'person', 'people')} on the advisor list have a blank or "
                            "'left' tenure and are not counted."))
    dup = int(advisors["advisor_code"].dropna().duplicated().sum())
    if dup:
        out.append(("warning", f"{_n(dup, 'advisor code')} appear more than once on the advisor list."))
    counts = advisors["band"].value_counts()
    empty = [b for b in bands if counts.get(b, 0) == 0]
    if empty:
        out.append(("warning", f"No advisors in tenure band {', '.join(empty)}, so its "
                               "productivity is 0."))
    month = base_month(leads)
    on = leads[leads["onboarded"] & (leads["onboarding_month"] == month) & leads["rm_code"].notna()]
    unknown = int((~on["rm_code"].isin(advisors["advisor_code"])).sum())
    if unknown:
        out.append(("warning", f"{_n(unknown, 'onboarding')} in {month.strftime('%B %Y')} are "
                               "credited to advisor codes that are not on the advisor list (or have "
                               "no tenure). They are not counted in productivity."))
    return out


# ---------------------------------------------------------------- history

def base_month(leads):
    """The last lead month in the data (September in the sample). It is the base for planning."""
    return leads["lead_month"].max()


COUNT_COLUMNS = ["leads", "connected", "connected_any", "same_month_onboarded",
                 "same_month_connected", "same_month_unassisted", "later_onboarded"]


def monthly_by_source(leads):
    """By lead month and source: leads, connected (same month / any month), same-month
    onboardings split into connected and unassisted (lead not connected that month), later."""
    df = leads.assign(later=leads["onboarded"] & ~leads["same_month"],
                      sm_connected=leads["same_month"] & leads["connected"],
                      sm_unassisted=leads["same_month"] & ~leads["connected"])
    t = (df.groupby(["lead_month", "source"])
           .agg(leads=("source", "size"), connected=("connected", "sum"),
                connected_any=("connected_any", "sum"),
                same_month_onboarded=("same_month", "sum"),
                same_month_connected=("sm_connected", "sum"),
                same_month_unassisted=("sm_unassisted", "sum"),
                later_onboarded=("later", "sum"))
           .reset_index())
    return _add_rates(t)


def monthly_totals(leads):
    """Same as monthly_by_source, all sources together."""
    t = monthly_by_source(leads).groupby("lead_month")[COUNT_COLUMNS].sum().reset_index()
    return _add_rates(t)


def conversion_by_month(leads):
    """The two conversion routes by lead month and source, defined like the plan inputs:
    conversion   = same-month onboardings of connected leads ÷ (leads × month's connect rate)
    unassisted   = same-month onboardings of leads not connected that month ÷ leads
    so that leads × (connect × conversion + unassisted) = the source's same-month onboardings."""
    t = monthly_by_source(leads)
    connect = monthly_totals(leads).set_index("lead_month")["connect_pct"]
    reach = t["leads"] * t["lead_month"].map(connect)
    t["conversion"] = (t["same_month_connected"] / reach).where(reach > 0, 0.0)
    t["unassisted"] = t["same_month_unassisted"] / t["leads"]
    return t


def _add_rates(t):
    t["connect_pct"] = t["connected"] / t["leads"]              # connected in the same month
    t["connect_any_pct"] = t["connected_any"] / t["leads"]      # connected in any month
    t["conversion_of_leads"] = t["same_month_onboarded"] / t["leads"]
    return t


def onboardings_by_month(leads):
    """Onboardings counted by onboarding date (how the target is counted), with self conversion %.

    Only months that are inside the lead data are shown: onboardings after the last lead month
    are incomplete (later leads are not in the file).
    """
    on = leads[leads["onboarded"] & leads["onboarding_month"].notna()]
    months = sorted(leads["lead_month"].dropna().unique())
    on = on[on["onboarding_month"].isin(months)]
    t = (on.groupby("onboarding_month")
           .agg(onboarded=("onboarded", "size"), self_conversion=("self_conversion", "sum"))
           .reindex(months, fill_value=0))
    t.index.name = "onboarding_month"
    t["with_advisor"] = t["onboarded"] - t["self_conversion"]
    t["self_pct"] = t["self_conversion"] / t["onboarded"]
    return t.reset_index()


def carry_over_table(leads, max_lag=3):
    """For each lead month: leads onboarded 1, 2, 3 months after the lead month."""
    on = leads[leads["onboarded"] & leads["onboarding_month"].notna()].copy()
    on["lag"] = (on["onboarding_month"] - on["lead_month"]).map(lambda d: d.n)
    t = pd.DataFrame({"lead_month": sorted(leads["lead_month"].dropna().unique())})
    t["leads"] = t["lead_month"].map(leads.groupby("lead_month").size())
    for lag in range(1, max_lag + 1):
        counts = on[on["lag"] == lag].groupby("lead_month").size()
        t[f"onboarded_m{lag}"] = t["lead_month"].map(counts).fillna(0).astype(int)
    later = t[[f"onboarded_m{lag}" for lag in range(1, max_lag + 1)]].sum(axis=1)
    t["later_pct_of_leads"] = later / t["leads"]
    t["m1_share_of_later"] = (t["onboarded_m1"] / later).where(later > 0)
    return t


def productivity_by_band(leads, advisors, bands, month=None):
    """Onboardings (by onboarding date, in `month`) credited to advisors in each tenure band,
    divided by the number of advisors in that band. Blank tenure is already excluded."""
    month = month if month is not None else base_month(leads)
    on = leads[leads["onboarded"] & (leads["onboarding_month"] == month) & leads["rm_code"].notna()]
    band_of = advisors.set_index("advisor_code")["band"]
    credited = on["rm_code"].map(band_of).value_counts()
    t = pd.DataFrame({"band": bands})
    t["advisors"] = t["band"].map(advisors["band"].value_counts()).fillna(0).astype(int)
    t["onboardings_with_advisor"] = t["band"].map(credited).fillna(0).astype(int)
    t["productivity"] = (t["onboardings_with_advisor"] / t["advisors"]).where(t["advisors"] > 0, 0.0)
    return t


# ---------------------------------------------------------------- plan inputs

def round_half_up(x):
    """Round like Excel's ROUND (2.5 -> 3), not Python's round (2.5 -> 2)."""
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


def carry_over(leads_m1, leads_m2, carry_pct, m1_share):
    """Onboardings next month from leads created 1 and 2 months earlier."""
    return leads_m1 * carry_pct * m1_share + leads_m2 * carry_pct * (1 - m1_share)


def default_advisors(advisors_now, promotion, new_hire_band, new_hires=0):
    """Next month's team: everyone moves up one band, new hires join the newest band."""
    plan = {band: 0 for band in advisors_now}
    for band, count in advisors_now.items():
        plan[promotion[band]] += count
    plan[new_hire_band] += new_hires
    return plan


def base_inputs(leads, advisors, cfg, funnel=None):
    """Last month's actuals (the base month) used as the starting point for each plan input.

    advisors is None when the funnel has no team. The team next month is the current team
    moved up one tenure band (it is not an input).
    """
    funnel = funnel or cfg["funnel"]
    team = funnel["team"] and advisors is not None
    month = base_month(leads)
    sources = cfg["lead_sources"]
    bands = cfg["tenure_bands"] if team else []
    a = cfg["assumptions"]

    last = leads[leads["lead_month"] == month]
    leads_by_source = last.groupby("source").size().reindex(sources, fill_value=0)
    total_leads = int(leads_by_source.sum())
    connect_rate = last["connected"].sum() / total_leads if total_leads else 0.0
    by_source = monthly_by_source(last).set_index("source").reindex(sources, fill_value=0)

    # Two routes to a same-month onboarding: through a connected lead, or unassisted
    conversion, unassisted = {}, {}
    for s in sources:
        reach = leads_by_source[s] * connect_rate
        conversion[s] = by_source.loc[s, "same_month_connected"] / reach if reach else 0.0
        unassisted[s] = (by_source.loc[s, "same_month_unassisted"] / leads_by_source[s]
                         if leads_by_source[s] else 0.0)

    onb = onboardings_by_month(leads).set_index("onboarding_month").loc[month]
    leads_per_month = leads.groupby("lead_month").size()
    if team:
        prod = productivity_by_band(leads, advisors, bands, month).set_index("band")
        productivity = {b: float(prod.loc[b, "productivity"]) for b in bands}
        advisors_now = {b: int(prod.loc[b, "advisors"]) for b in bands}
        team_next = default_advisors(advisors_now, cfg["promotion"], cfg["new_hire_band"])
    else:
        productivity, advisors_now, team_next = {}, {}, {}

    return {
        "month": month,
        "funnel": dict(funnel),
        "leads": {s: int(leads_by_source[s]) for s in sources},
        "connect_rate": float(connect_rate),
        "conversion": {s: float(v) for s, v in conversion.items()},
        "unassisted": {s: float(v) for s, v in unassisted.items()},
        "self_pct": float(onb["self_pct"]) if team and onb["onboarded"] else 0.0,
        "carry_pct": a["carry_over_pct"] if funnel["carry_over"] else 0.0,
        "m1_share": a["carry_over_m1_share"],
        "productivity": productivity,
        "advisors": advisors_now,
        "team_next_month": team_next,
        "last_month_onboardings": int(onb["onboarded"]),
        "same_month_onboardings": int(last["same_month"].sum()),
        "leads_m1": int(leads_per_month.get(month, 0)),
        "leads_m2": int(leads_per_month.get(month - 1, 0)),
        "leads_m3": int(leads_per_month.get(month - 2, 0)),
    }


def plan_inputs(base, growth, cap=1.0):
    """Planned value = base x (1 + growth %).

    growth: {"leads": {source: g}, "connect_rate": g, "conversion": {source: g},
             "unassisted": {source: g}, "self_pct": g, "carry_pct": g, "m1_share": g,
             "productivity": {band: g}}
            Anything missing means 0% growth.
    Counts are rounded to whole numbers; rates are capped at `cap` (100%).
    The team is not an input: it is next month's team from base_inputs().
    """
    def g(key, sub=None):
        v = growth.get(key, {} if sub is not None else 0.0)
        return v.get(sub, 0.0) if sub is not None else v

    def rate(value, pct):
        return min(cap, value * (1 + pct))

    return {
        "leads": {s: round_half_up(v * (1 + g("leads", s))) for s, v in base["leads"].items()},
        "connect_rate": rate(base["connect_rate"], g("connect_rate")),
        "conversion": {s: rate(v, g("conversion", s)) for s, v in base["conversion"].items()},
        "unassisted": {s: rate(v, g("unassisted", s)) for s, v in base["unassisted"].items()},
        "self_pct": rate(base["self_pct"], g("self_pct")),
        "carry_pct": rate(base["carry_pct"], g("carry_pct")),
        "m1_share": rate(base["m1_share"], g("m1_share")),
        "productivity": {b: v * (1 + g("productivity", b)) for b, v in base["productivity"].items()},
        "advisors": dict(base["team_next_month"]),
        "funnel": base["funnel"],
        "leads_m1": base["leads_m1"],
        "leads_m2": base["leads_m2"],
        "last_month_onboardings": base["last_month_onboardings"],
    }


# ---------------------------------------------------------------- forecast and target

def per_lead(plan, source):
    """Same-month onboardings per lead: connected route plus unassisted route."""
    return plan["connect_rate"] * plan["conversion"][source] + plan["unassisted"][source]


def forecast(plan, target_growth, new_hire_band):
    """Next month's expected onboardings, the target, and the leads and advisors each needs.

    Expected onboardings come from the leads and rates only. Advisors never change them:
    the number of advisors needed is worked out from productivity.
    """
    same_month = {s: plan["leads"][s] * per_lead(plan, s) for s in plan["leads"]}
    same_month_total = sum(same_month.values())
    carry = carry_over(plan["leads_m1"], plan["leads_m2"], plan["carry_pct"], plan["m1_share"])
    expected = same_month_total + carry

    target = round_half_up(plan["last_month_onboardings"] * (1 + target_growth))
    total_leads = sum(plan["leads"].values())
    same_month_needed = max(0.0, target - carry)
    onb_per_lead = same_month_total / total_leads if total_leads else 0.0
    leads_needed = same_month_needed / onb_per_lead if onb_per_lead else 0.0

    out = {
        "same_month": same_month,
        "same_month_total": same_month_total,
        "carry_over": carry,
        "funnel_total": expected,
        "expected_onboardings": expected,
        "growth_vs_last_month": (expected / plan["last_month_onboardings"] - 1
                                 if plan["last_month_onboardings"] else 0.0),
        "target": target,
        "gap": target - expected,
        "same_month_needed": same_month_needed,
        "total_leads": total_leads,
        "leads_needed": leads_needed,
        "extra_leads": leads_needed - total_leads,
        "team": bool(plan["advisors"]),
    }
    if not plan["advisors"]:
        return out

    # Team: next month's team (everyone moved up a band) and its productivity
    self_onb = expected * plan["self_pct"]
    advisor_needed = expected - self_onb
    team_capacity = sum(plan["advisors"][b] * plan["productivity"][b] for b in plan["advisors"])
    total_advisors = sum(plan["advisors"].values())
    avg_productivity = team_capacity / total_advisors if total_advisors else 0.0

    def advisors_for(onboardings):
        return math.ceil(onboardings / avg_productivity) if avg_productivity else 0

    advisor_onb_at_target = target * (1 - plan["self_pct"])
    new_hire_productivity = plan["productivity"][new_hire_band]
    extra_hires = (math.ceil(max(0.0, advisor_onb_at_target - team_capacity) / new_hire_productivity)
                   if new_hire_productivity else 0)
    out.update({
        "self_onboardings": self_onb,
        "advisor_needed": advisor_needed,
        "team_capacity": team_capacity,
        "total_advisors": total_advisors,
        "avg_productivity": avg_productivity,
        "advisors_for_forecast": advisors_for(advisor_needed),
        "team_short_for_forecast": team_capacity < advisor_needed,
        "advisor_onboardings_at_target": advisor_onb_at_target,
        "advisors_required": advisors_for(advisor_onb_at_target),
        "advisor_gap": advisors_for(advisor_onb_at_target) - total_advisors,
        "extra_hires_needed": extra_hires,
    })
    return out


# ---------------------------------------------------------------- suggestions

RULES_PATH = Path(__file__).parent / "suggestions.yaml"


def load_rules(path=RULES_PATH):
    with open(path, encoding="utf-8") as f:
        return YAML(typ="safe").load(f)


def recent_highs(leads, advisors, sources, bands):
    """The highest monthly value of each input in the data: the 'recent trend' a plan is checked against.

    Productivity only has the base month (tenure is as of that month).
    """
    by_source = conversion_by_month(leads)
    totals = monthly_totals(leads).set_index("lead_month")
    src = by_source.groupby("source")
    onb = onboardings_by_month(leads)
    highs = {
        "leads": {s: int(src["leads"].max().get(s, 0)) for s in sources},
        "connect_rate": float(totals["connect_pct"].max()),
        "conversion": {s: float(src["conversion"].max().get(s, 0.0)) for s in sources},
        "unassisted": {s: float(src["unassisted"].max().get(s, 0.0)) for s in sources},
        "self_pct": float(onb.loc[onb["onboarded"] > 0, "self_pct"].max()),
        "total_leads": int(totals["leads"].max()),
        "productivity": {},
    }
    if advisors is not None:
        prod = productivity_by_band(leads, advisors, bands).set_index("band")["productivity"]
        highs["productivity"] = {b: float(prod[b]) for b in bands}
    return highs




class _Blank(dict):
    """Leave unknown {placeholders} as they are instead of failing."""
    def __missing__(self, key):
        return "{" + key + "}"


def _count(x):
    return f"{x:,.0f}"


def _pct(x):
    return f"{x * 100:.1f}%"


# ---------------------------------------------------------------- plan inputs, one by one

def plan_input_list(plan):
    """Every plan input as {key, path, label, kind, group}. `key` is a short text id,
    `path` says where it sits in the plan, `kind` is count, rate or decimal."""
    connect = plan["funnel"]["connect_step"]
    out = [{"key": f"leads:{s}", "path": ("leads", s), "label": f"{s} leads",
            "kind": "count", "group": "leads"} for s in plan["leads"]]
    if connect:
        out.append({"key": "connect_rate", "path": ("connect_rate",), "label": "Connect rate",
                    "kind": "rate", "group": "rates"})
    for s in plan["conversion"]:
        out.append({"key": f"conversion:{s}", "path": ("conversion", s),
                    "label": f"{s} conversion" + (" (connected)" if connect else ""),
                    "kind": "rate", "group": "rates"})
    if connect:
        for s in plan["unassisted"]:
            out.append({"key": f"unassisted:{s}", "path": ("unassisted", s),
                        "label": f"{s} unassisted conversion", "kind": "rate", "group": "rates"})
    if plan["advisors"]:
        out.append({"key": "self_pct", "path": ("self_pct",), "label": "Self conversion",
                    "kind": "rate", "group": "team"})
        for b in plan["productivity"]:
            out.append({"key": f"productivity:{b}", "path": ("productivity", b),
                        "label": f"Productivity {b}", "kind": "decimal", "group": "team"})
    if plan["funnel"]["carry_over"]:
        out.append({"key": "carry_pct", "path": ("carry_pct",), "label": "Carry-over %",
                    "kind": "rate", "group": "carry"})
        out.append({"key": "m1_share", "path": ("m1_share",), "label": "Carry-over month +1 share",
                    "kind": "rate", "group": "carry"})
    return out


def _get(plan, path):
    return plan[path[0]][path[1]] if len(path) == 2 else plan[path[0]]


def _set(plan, path, value):
    new = {k: (dict(v) if isinstance(v, dict) else v) for k, v in plan.items()}
    if len(path) == 2:
        new[path[0]][path[1]] = value
    else:
        new[path[0]] = value
    return new


def input_effects(base, plan, target_growth, new_hire_band, cap=1.0):
    """What each planned change does on its own, compared with last month's values.

    Returns {key: {"output": change in expected results, "team": change in advisors needed
    for the target (None without a team)}}, plus "_all" for all changes together.
    """
    start = plan_inputs(base, {}, cap)
    r0 = forecast(start, target_growth, new_hire_band)

    def effect(r):
        return {"output": r["expected_onboardings"] - r0["expected_onboardings"],
                "team": (r["advisors_required"] - r0["advisors_required"]) if r["team"] else None}

    out = {item["key"]: effect(forecast(_set(start, item["path"], _get(plan, item["path"])),
                                        target_growth, new_hire_band))
           for item in plan_input_list(plan)}
    out["_all"] = effect(forecast(plan, target_growth, new_hire_band))
    return out


def above_recent(plan, highs):
    """Inputs planned above their best month in the data: [{key, label, planned, high, ...}]."""
    out = []
    for item in plan_input_list(plan):
        high = highs.get(item["path"][0])
        if isinstance(high, dict):
            high = high.get(item["path"][1]) if len(item["path"]) == 2 else None
        if high is None:
            continue
        value = _get(plan, item["path"])
        if value > high + 1e-9:
            out.append({**item, "planned": value, "high": high})
    return out


# ---------------------------------------------------------------- reaching the target
# Every number here comes from forecast() on a changed plan, so it always matches the
# main forecast (including the 100% cap on rates).

def lever_requirements(plan, result, highs, cap=1.0):
    """What each lever must reach ON ITS OWN to close the gap to target.

    Returns a list of {lever, kind, current, required, change, best, status}, where status is
    "seen" (reached in a recent month), "above" (above any recent month) or "impossible"
    (a rate would have to go above 100%). Empty when the target is already met.
    """
    gap = result["same_month_needed"] - result["same_month_total"]
    if result["gap"] <= 0.5 or gap <= 1e-9:     # met (a gap under half a unit shows as 0)
        return []
    out = []

    def add(lever, kind, current, required, best):
        if kind == "rate" and required > cap + 1e-12:
            status = "impossible"
        else:
            status = "seen" if required <= best + 1e-9 else "above"
        out.append({"lever": lever, "kind": kind, "current": current, "required": required,
                    "change": required / current - 1 if current else float("inf"),
                    "best": best, "status": status})

    add("All leads", "count", result["total_leads"], result["leads_needed"],
        highs.get("total_leads", result["total_leads"]))
    if plan["funnel"]["connect_step"]:
        connected_route = sum(plan["leads"][s] * plan["conversion"][s] for s in plan["leads"])
        if connected_route > 0:
            unassisted_total = sum(plan["leads"][s] * plan["unassisted"][s] for s in plan["leads"])
            add("Connect rate", "rate", plan["connect_rate"],
                (result["same_month_needed"] - unassisted_total) / connected_route,
                highs["connect_rate"])
    for s in plan["leads"]:
        if per_lead(plan, s) > 0:
            add(f"{s} leads", "count", plan["leads"][s],
                plan["leads"][s] + gap / per_lead(plan, s), highs["leads"][s])
        reach = plan["leads"][s] * plan["connect_rate"]
        if reach > 0:
            add(f"{s} conversion", "rate", plan["conversion"][s],
                plan["conversion"][s] + gap / reach, highs["conversion"][s])
    order = {"seen": 0, "above": 1, "impossible": 2}
    return sorted(out, key=lambda x: (order[x["status"]], x["change"]))


def source_efficiency(plan):
    """Same-month onboardings per 1,000 leads, by source, at the planned rates."""
    return {s: 1000 * per_lead(plan, s) for s in plan["leads"]}


def mix_shift(plan, target_growth, new_hire_band, from_source, to_source, share):
    """Move `share` of one source's leads to another (same total leads).

    Returns {moved, uplift, expected}.
    """
    moved = round_half_up(plan["leads"][from_source] * share)
    new = _set(_set(plan, ("leads", from_source), plan["leads"][from_source] - moved),
               ("leads", to_source), plan["leads"][to_source] + moved)
    before = forecast(plan, target_growth, new_hire_band)["expected_onboardings"]
    expected = forecast(new, target_growth, new_hire_band)["expected_onboardings"]
    return {"moved": moved, "expected": expected, "uplift": expected - before}


def funnel_counts(leads, month=None, source=None):
    """Leads -> connected (same month) -> converted in the same month, for one lead month.
    Same-month conversions are split into connected and unassisted."""
    month = month if month is not None else base_month(leads)
    d = leads[leads["lead_month"] == month]
    if source:
        d = d[d["source"] == source]
    return {"leads": len(d), "connected": int(d["connected"].sum()),
            "same_month": int(d["same_month"].sum()),
            "same_month_connected": int((d["same_month"] & d["connected"]).sum()),
            "same_month_unassisted": int((d["same_month"] & ~d["connected"]).sum()),
            "later": int((d["onboarded"] & ~d["same_month"]).sum())}


# ---------------------------------------------------------------- leadership insights

RULES_PATH = Path(__file__).parent / "suggestions.yaml"


def load_rules(path=RULES_PATH):
    with open(path, encoding="utf-8") as f:
        return YAML(typ="safe").load(f)


def rate_trends(leads, plan):
    """First and last month of each rate in the data: [{label, path, first, last, first_month}]."""
    months = sorted(leads["lead_month"].dropna().unique())
    if len(months) < 2:
        return []
    totals = monthly_totals(leads).set_index("lead_month")
    conv = conversion_by_month(leads).set_index(["lead_month", "source"])
    out = []
    if plan["funnel"]["connect_step"]:
        out.append({"label": "Connect rate", "path": ("connect_rate",),
                    "first": totals.loc[months[0], "connect_pct"],
                    "last": totals.loc[months[-1], "connect_pct"]})
    for s in plan["conversion"]:
        if (months[0], s) in conv.index and (months[-1], s) in conv.index:
            out.append({"label": f"{s} conversion", "path": ("conversion", s),
                        "first": conv.loc[(months[0], s), "conversion"],
                        "last": conv.loc[(months[-1], s), "conversion"]})
    for tr in out:
        tr["first_month"] = months[0].strftime("%B")
    return out


def insights(leads, base, plan, result, highs, target_growth, new_hire_band, rules, words,
             cap=1.0, max_items=6):
    """A short leadership briefing: [{"kind", "tone", "title", "text"}].

    tone is "good", "warn" or "info". The wording comes from suggestions.yaml ("insights");
    the numbers are worked out here.
    """
    templates = rules.get("insights", {})
    gap = result["gap"]
    expected = result["expected_onboardings"]
    found = {}

    def say(kind, tone, **values):
        if kind in templates:
            v = _Blank({**words, **values})
            found[kind] = {"kind": kind, "tone": tone,
                           "title": templates[kind]["title"].format_map(v),
                           "text": templates[kind]["text"].format_map(v)}

    # Outlook against the target
    if gap > 0.5:
        share = expected / result["target"] if result["target"] else 1.0
        say("outlook_short", "warn", pct_of_target=f"{share * 100:.0f}%", gap=_count(gap),
            expected=_count(expected), target=_count(result["target"]))
    else:
        say("outlook_met", "good", expected=_count(expected), target=_count(result["target"]))

    # The rate that fell most in the data, and what getting it back is worth
    worst = None
    for tr in rate_trends(leads, plan):
        if tr["first"] > 0 and tr["last"] < tr["first"] * 0.9:
            worth = forecast(_set(plan, tr["path"], tr["first"]), target_growth,
                             new_hire_band)["expected_onboardings"] - expected
            if worth > 0.5 and (worst is None or worth > worst[1]):
                worst = (tr, worth)
    if worst:
        tr, worth = worst
        say("trend", "warn", rate=tr["label"], first=_pct(tr["first"]), last=_pct(tr["last"]),
            first_month=tr["first_month"], worth=_count(worth))

    # The quickest single lever: one already reached in a recent month
    if gap > 0.5:
        reqs = lever_requirements(plan, result, highs, cap)
        seen = [x for x in reqs if x["status"] == "seen"]
        if seen:
            x = seen[0]
            fmt = _pct if x["kind"] == "rate" else _count
            say("best_lever", "good", lever=x["lever"], current=fmt(x["current"]),
                required=fmt(x["required"]), best=fmt(x["best"]), gap=_count(gap))
        elif reqs:
            say("no_easy_lever", "warn", gap=_count(gap))

    # How much of the planned growth rests on assumptions above recent months
    effects = input_effects(base, plan, target_growth, new_hire_band, cap)
    total = effects["_all"]["output"]
    risky = [x for x in above_recent(plan, highs) if effects[x["key"]]["output"] > 0.5]
    if total > 0.5 and risky:
        at_risk = min(total, sum(effects[x["key"]]["output"] for x in risky))
        names = [x["label"] for x in risky]
        listed = ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
        say("risk", "warn", risk_share=f"{at_risk / total * 100:.0f}%", names=listed,
            total_effect=_count(total))

    # Where the planned growth comes from
    growth = [(x, effects[x["key"]]["output"]) for x in plan_input_list(plan)
              if effects[x["key"]]["output"] > 0.5]
    if total > 0.5 and growth:
        top, top_effect = max(growth, key=lambda g: g[1])
        say("growth_driver", "info", top_input=top["label"], top_effect=_count(top_effect),
            top_share=f"{min(1, top_effect / total) * 100:.0f}%", total_effect=_count(total))

    # Lead mix: the weakest source by results per lead
    eff = source_efficiency(plan)
    if len(eff) >= 2:
        weak, strong = min(eff, key=eff.get), max(eff, key=eff.get)
        if eff[strong] > eff[weak] * 1.5:
            total_leads = sum(plan["leads"].values()) or 1
            same = result["same_month_total"] or 1
            m = mix_shift(plan, target_growth, new_hire_band, weak, strong, 0.30)
            say("mix", "info", weak=weak, strong=strong,
                weak_lead_share=f"{plan['leads'][weak] / total_leads * 100:.0f}%",
                weak_result_share=f"{result['same_month'][weak] / same * 100:.0f}%",
                mix_uplift=_count(m["uplift"]))

    # Team
    if result["team"]:
        common = dict(team_size=_count(result["total_advisors"]),
                      advisors_for_forecast=_count(result["advisors_for_forecast"]),
                      advisors_required=_count(result["advisors_required"]),
                      advisor_gap=f"{result['advisor_gap']:+,d}",
                      extra_hires=_count(result["extra_hires_needed"]))
        if result["team_short_for_forecast"]:
            say("team_short", "warn", **common)
        elif result["advisor_gap"] > 0:
            say("team_target", "info", **common)
        else:
            say("team_ok", "good", **common)

    order = rules.get("insight_order", list(templates))
    return [found[k] for k in order if k in found][:max_items]


# ---------------------------------------------------------------- scenarios and auto-plan

def _best(highs, path):
    high = highs.get(path[0])
    if isinstance(high, dict):
        return high.get(path[1]) if len(path) == 2 else None
    return high


def growth_set(growth, path, value):
    """Put one growth % into a growth dict shaped like plan_inputs() expects."""
    if len(path) == 2:
        growth.setdefault(path[0], {})[path[1]] = value
    else:
        growth[path[0]] = value


def auto_plan(base, target_growth, highs, new_hire_band, cap=1.0, keep=None):
    """Build a plan that reaches the target, using the funnel levers (leads, connect rate,
    conversion, unassisted conversion) and starting from last month's values.

    Step 1: move every lever part of the way back to its best recent month, all by the same
    share of its headroom, until the target is reached. Step 2 (only if all levers at their
    best are still not enough): grow every lever by the same extra % beyond its best.

    keep: growth values for the other inputs (team, carry-over), kept as they are.
    Returns {"growth", "expected", "target", "reachable", "within_recent", "changes"}.
    """
    keep = keep or {}
    start = plan_inputs(base, keep, cap)
    levers = [x for x in plan_input_list(start) if x["group"] in ("leads", "rates")]
    headroom = {}
    for x in levers:
        now, best = _get(start, x["path"]), _best(highs, x["path"])
        headroom[x["key"]] = max(0.0, best / now - 1) if now and best else 0.0

    def build(level, extra=0.0):
        growth = {k: (dict(v) if isinstance(v, dict) else v) for k, v in keep.items()}
        for x in levers:
            g = level * headroom[x["key"]]
            growth_set(growth, x["path"], (1 + g) * (1 + extra) - 1)
        plan = plan_inputs(base, growth, cap)
        return growth, forecast(plan, target_growth, new_hire_band)

    def search(make):
        """Smallest setting in [0, 1] (scaled by `make`) that reaches the target."""
        lo, hi = 0.0, 1.0
        for _ in range(40):
            mid = (lo + hi) / 2
            growth, r = make(mid)
            lo, hi = (lo, mid) if r["gap"] <= 0 else (mid, hi)
        return make(hi)

    growth, r = build(0.0)
    reachable, within = True, True
    if r["gap"] > 0:
        growth, r = build(1.0)
        if r["gap"] <= 0:
            growth, r = search(lambda t: build(t))
        else:
            within = False
            max_extra = 5.0                              # up to +500% beyond the best months
            growth, r = build(1.0, max_extra)
            if r["gap"] > 0:
                reachable = False
            else:
                growth, r = search(lambda t: build(1.0, t * max_extra))

    plan = plan_inputs(base, growth, cap)
    changes = []
    for x in levers:
        before, after = _get(start, x["path"]), _get(plan, x["path"])
        best = _best(highs, x["path"])
        if abs(after - before) > 1e-12:
            changes.append({**x, "from": before, "to": after,
                            "growth": after / before - 1 if before else 0.0, "best": best,
                            "within": best is not None and after <= best + 1e-9})
    return {"growth": growth, "expected": r["expected_onboardings"], "target": r["target"],
            "reachable": reachable, "within_recent": within and reachable, "changes": changes}


def compare_scenarios(leads, base, scenarios, highs, new_hire_band, cap=1.0):
    """Key numbers for each named scenario: {name: (growth, target_growth)} -> list of dicts."""
    rows = []
    for name, (growth, target_growth) in scenarios.items():
        plan = plan_inputs(base, growth, cap)
        r = forecast(plan, target_growth, new_hire_band)
        effects = input_effects(base, plan, target_growth, new_hire_band, cap)
        uplift = effects["_all"]["output"]
        untested = sum(max(0.0, effects[x["key"]]["output"]) for x in above_recent(plan, highs))
        rows.append({
            "name": name, "expected": r["expected_onboardings"], "target": r["target"],
            "gap": r["gap"], "growth": r["growth_vs_last_month"], "leads": r["total_leads"],
            "advisors": r.get("advisors_required"), "advisor_gap": r.get("advisor_gap"),
            "untested": min(1.0, untested / uplift) if uplift > 0.5 else 0.0,
        })
    return rows
