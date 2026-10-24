"""Create a made-up lead file and advisor list with the same columns as the real export.

Nothing here comes from company data: volumes, rates and codes are invented, chosen only so the
files behave like a real funnel (rising Meta volume, falling connect rate, better conversion on
Google and Organic, carry-over into later months, a team with tenure bands and leavers).

Run:  .venv\\Scripts\\python.exe make_sample_data.py
Writes sample_data/leads_sample.csv and sample_data/advisors_sample.csv.
"""

import calendar
import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

OUT = Path(__file__).parent / "sample_data"
SEED = 2026
MONTHS = [(2026, 1), (2026, 2), (2026, 3)]
EXPORT_DATE = datetime(2026, 4, 25)          # later conversions after this are not known yet

LEADS_PER_MONTH = {                           # Meta grows fast, the others steadily
    "Google": [4200, 4700, 4400],
    "Meta": [3600, 5100, 7800],
    "Organic": [2500, 2800, 3200],
}
CONNECT = [0.90, 0.85, 0.77]                  # falling as volume grows
FUTURE_CONNECT_SHARE = 0.07                   # of connected leads, reached the next month
SAME_MONTH_CONV = {                           # of leads connected that month
    "Google": [0.085, 0.095, 0.125],
    "Meta": [0.022, 0.018, 0.040],
    "Organic": [0.160, 0.165, 0.150],
}
UNASSISTED = {                                # of all leads: converted without being
    "Google": [0.002, 0.006, 0.030],          # connected that month (rising, like a new
    "Meta": [0.0003, 0.001, 0.004],           # self-serve route)
    "Organic": [0.006, 0.012, 0.030],
}
UNASSISTED_NO_ADVISOR = 0.9                   # most unassisted conversions have no advisor
LATER_CONV = 0.013                            # of all leads, converting in a later month
LATER_LAG = [(1, 0.76), (2, 0.20), (3, 0.04)]
SELF_SHARE = [0.10, 0.14, 0.29]               # converted leads with no advisor, by month
NO_ADVISOR = 0.12                             # unconverted leads never assigned

# Team as of the last month: (band, people). Blank tenure = has left.
TEAM = [("0-1 M", 4), ("1-2 M", 6), ("2-3 M", 5), ("3M+", 11), ("", 5)]
BAND_START = {"0-1 M": 2, "1-2 M": 1, "2-3 M": 0, "3M+": 0, "": 0}   # first month index active
BAND_LAST = {"": 1}                                                   # leavers stop after month 1
BAND_WEIGHT = {"0-1 M": 0.45, "1-2 M": 0.85, "2-3 M": 1.0, "3M+": 1.05, "": 0.9}


def random_time(rng, start, end):
    return start + timedelta(seconds=rng.randint(0, int((end - start).total_seconds())))


def month_bounds(year, month):
    last = calendar.monthrange(year, month)[1]
    return datetime(year, month, 1), datetime(year, month, last, 23, 59, 59)


def add_months(year, month, n):
    m = month - 1 + n
    return year + m // 12, m % 12 + 1


def make_team(rng):
    rows, code = [], 7001
    for band, n in TEAM:
        for _ in range(n):
            rows.append({"Advisor emp code": code, "Tenure": band})
            code += rng.randint(1, 4)
    return pd.DataFrame(rows)


def main():
    rng = random.Random(SEED)
    team = make_team(rng)
    leads, lead_id = [], 300000

    for mi, (year, month) in enumerate(MONTHS):
        start, end = month_bounds(year, month)
        active = [(r["Advisor emp code"], BAND_WEIGHT[r["Tenure"]]) for _, r in team.iterrows()
                  if BAND_START[r["Tenure"]] <= mi <= BAND_LAST.get(r["Tenure"], 99)]
        codes, weights = zip(*active)
        for source, volumes in LEADS_PER_MONTH.items():
            for _ in range(volumes[mi]):
                lead_id += rng.randint(1, 3)
                created = random_time(rng, start, end)
                connected = rng.random() < CONNECT[mi]
                status = ("No" if not connected else
                          "future month connected" if rng.random() < FUTURE_CONNECT_SHARE
                          else "same month connected")
                converted, onboarded = "Not converted", None
                not_reached = 1 - CONNECT[mi] * (1 - FUTURE_CONNECT_SHARE)
                unassisted = False
                if status == "same month connected" and rng.random() < SAME_MONTH_CONV[source][mi]:
                    converted = "same month conversion"
                    onboarded = random_time(rng, created, end)
                elif (status != "same month connected"
                      and rng.random() < UNASSISTED[source][mi] / not_reached):
                    converted, unassisted = "same month conversion", True
                    onboarded = random_time(rng, created, end)
                elif rng.random() < LATER_CONV:
                    lag = rng.choices([l for l, _ in LATER_LAG], [w for _, w in LATER_LAG])[0]
                    y, m = add_months(year, month, lag)
                    when = random_time(rng, *month_bounds(y, m))
                    if when <= EXPORT_DATE:
                        converted, onboarded = "future month conversion", when
                if unassisted:
                    rm = None if rng.random() < UNASSISTED_NO_ADVISOR else rng.choices(codes, weights)[0]
                elif onboarded is not None:
                    rm = None if rng.random() < SELF_SHARE[mi] else rng.choices(codes, weights)[0]
                else:
                    rm = None if rng.random() < NO_ADVISOR else rng.choices(codes, weights)[0]
                leads.append({
                    "Lead ID": lead_id,
                    "Created Date": created.strftime("%Y-%m-%d %H:%M:%S"),
                    "Lead Source": source,
                    "Connected": status,
                    "Total Calls Done": rng.randint(0, 3) if not connected else rng.randint(1, 8),
                    "RM Employee Code": rm,
                    "Converted": converted,
                    "Onboarding Date": onboarded.strftime("%Y-%m-%d %H:%M:%S") if onboarded else None,
                })

    df = pd.DataFrame(leads).sort_values("Created Date").reset_index(drop=True)
    # A few realistic data issues, so the data checks have something to report
    df.loc[df.sample(4, random_state=SEED).index, "Lead ID"] = df["Lead ID"].iloc[:4].values
    not_conv = df[df["Converted"] == "Not converted"].sample(2, random_state=SEED).index
    df.loc[not_conv, "Onboarding Date"] = df.loc[not_conv, "Created Date"]
    df["RM Employee Code"] = df["RM Employee Code"].astype("Int64")

    OUT.mkdir(exist_ok=True)
    df.to_csv(OUT / "leads_sample.csv", index=False)
    team.to_csv(OUT / "advisors_sample.csv", index=False)
    print(f"Wrote {len(df):,} leads and {len(team)} advisors to {OUT}")


if __name__ == "__main__":
    main()
