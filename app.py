"""Growth Target Planner: the screens. All calculations live in model.py.

Run:  .venv\\Scripts\\streamlit.exe run app.py
"""

import io
import json
import os
import re
import shutil
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

import model

cfg = model.load_config()
LABELS = cfg["labels"]
BANDS = cfg["tenure_bands"]
ASSUME = cfg["assumptions"]

st.set_page_config(page_title=LABELS["app_name"], layout="wide")


# ---------------------------------------------------------------- saved setup
# The uploaded files and every choice are saved on this computer (inside the data folder,
# which Git ignores), so a reload or a new browser tab starts where you left off.
# In the public demo nothing is saved: each visitor's files stay in their own browser tab,
# and the made-up sample data is loaded on the first visit.

ROOT = Path(__file__).parent
SAVE_DIR = ROOT / "data" / ".saved_setup"
SAMPLE_DIR = ROOT / "sample_data"
SAMPLE_FILES = {"leads": "leads_sample.csv", "team": "advisors_sample.csv"}
SAVED_PREFIXES = ("setup_", "map_", "val_", "g_", "r_")
FILE_SLOTS = ("leads", "team")
PUBLIC_DEMO = bool(cfg.get("public_demo")) or os.environ.get("PLANNER_PUBLIC_DEMO") == "1"


def restore_saved():
    if st.session_state.get("_restored"):
        return
    st.session_state["_restored"] = True
    if PUBLIC_DEMO:
        load_sample()
        return
    try:
        saved = json.loads((SAVE_DIR / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    st.session_state["_saved_widgets"] = saved.get("widgets", {})
    st.session_state["scenarios"] = saved.get("scenarios", {})
    for key, value in saved.get("widgets", {}).items():
        st.session_state.setdefault(key, value)
    for slot, name in saved.get("files", {}).items():
        path = SAVE_DIR / f"{slot}__{name}"
        if path.exists():
            st.session_state[f"file_{slot}"] = {"name": name, "data": path.read_bytes()}


def save_state():
    if PUBLIC_DEMO:
        return
    current = {k: v for k, v in st.session_state.items()
               if isinstance(k, str) and k.startswith(SAVED_PREFIXES)
               and isinstance(v, (str, int, float, bool))}
    # Keep earlier choices for inputs that are not on screen in this run.
    widgets = {**st.session_state.get("_saved_widgets", {}), **current}
    files = {slot: st.session_state[f"file_{slot}"]["name"]
             for slot in FILE_SLOTS if st.session_state.get(f"file_{slot}")}
    payload = json.dumps({"widgets": widgets, "files": files,
                          "scenarios": st.session_state.get("scenarios", {})}, sort_keys=True)
    if payload == st.session_state.get("_saved_payload"):
        return
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    (SAVE_DIR / "state.json").write_text(payload, encoding="utf-8")
    st.session_state["_saved_payload"] = payload
    st.session_state["_saved_widgets"] = widgets


def store_file(slot, name, data):
    if not PUBLIC_DEMO:
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
        for old in SAVE_DIR.glob(f"{slot}__*"):
            old.unlink()
        (SAVE_DIR / f"{slot}__{name}").write_bytes(data)
    st.session_state[f"file_{slot}"] = {"name": name, "data": data}


def remove_file(slot):
    if not PUBLIC_DEMO:
        for old in SAVE_DIR.glob(f"{slot}__*"):
            old.unlink()
    st.session_state.pop(f"file_{slot}", None)


def load_sample():
    """Use the made-up sample files (see make_sample_data.py) with the default funnel."""
    for slot, name in SAMPLE_FILES.items():
        store_file(slot, name, (SAMPLE_DIR / name).read_bytes())
    st.session_state["setup_connect"] = cfg["funnel"]["connect_step"]
    st.session_state["setup_team"] = cfg["funnel"]["team"]
    st.session_state["setup_carry"] = cfg["funnel"]["carry_over"]


def start_over():
    if not PUBLIC_DEMO:
        shutil.rmtree(SAVE_DIR, ignore_errors=True)
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    if PUBLIC_DEMO:
        load_sample()
    st.session_state["_restored"] = True


restore_saved()
st.session_state.setdefault("setup_output", LABELS["output_name"])
st.session_state.setdefault("setup_team_name", LABELS["team_label"])
st.session_state.setdefault("setup_connect", cfg["funnel"]["connect_step"])
st.session_state.setdefault("setup_team", cfg["funnel"]["team"])
st.session_state.setdefault("setup_carry", cfg["funnel"]["carry_over"])


# ---------------------------------------------------------------- names and funnel

def singular(word):
    return (word[:-1] if word.endswith("s") else word).lower()


OUTPUT = st.session_state["setup_output"].strip() or LABELS["output_name"]   # e.g. "Onboardings"
TEAM = st.session_state["setup_team_name"].strip() or LABELS["team_label"]   # e.g. "Advisors"
OUTPUT_ONE = singular(OUTPUT)                                                # e.g. "onboarding"
TEAM_ONE = singular(TEAM)                                                    # e.g. "advisor"
A_TEAM_ONE = ("an " if TEAM_ONE[:1] in "aeiou" else "a ") + TEAM_ONE         # e.g. "an advisor"
FUNNEL = {"connect_step": st.session_state["setup_connect"],
          "team": st.session_state["setup_team"],
          "carry_over": st.session_state["setup_carry"]}


def own_words(text):
    """Use the names from the setup step in fixed texts that say 'advisor' or 'onboarding'."""
    for word, new in [("Advisors", TEAM), ("advisors", TEAM.lower()),
                      ("Advisor", TEAM_ONE.capitalize()), ("advisor", TEAM_ONE),
                      ("Onboardings", OUTPUT), ("onboardings", OUTPUT.lower()),
                      ("Onboarding", OUTPUT_ONE.capitalize()), ("onboarding", OUTPUT_ONE)]:
        text = re.sub(rf"\b{word}\b", new, text)
    return text


# ---------------------------------------------------------------- look and feel

# Page colours follow light or dark mode by themselves: CSS light-dark() picks the first colour
# in light mode and the second in dark mode, and switches the moment the theme changes.
BACKGROUND = "light-dark(#ffffff, #0e1117)"
LINE = "light-dark(#e6e6e3, #2d2f36)"
SURFACE = "light-dark(#f6f7f9, #161b26)"     # the belt's box, a step off the page colour
SHADOW = "light-dark(rgba(15,23,42,.08), rgba(0,0,0,.35))"
HOVER = "light-dark(#e8edf4, #232a38)"
ACCENT = "#2a78d6"
# Chart colours are fixed inside each chart, so they are chosen to read on both backgrounds.
# Categorical colours, always in this order (validated for colour-blind readers)
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
NEUTRAL = "#8a8985"
TEXT = "#8a8985"     # value labels: a mid grey that reads on white and on near-black

st.markdown(f"""
<style>
  .block-container {{ padding-top: 3rem; }}
  /* The belt's wrapper is the element that can stick while the page scrolls */
  [data-testid="stLayoutWrapper"]:has(> .st-key-belt) {{
    position: sticky; top: 3.75rem; z-index: 990; background: {BACKGROUND};
    padding: 0.35rem 0 0.6rem;
  }}
  /* The belt: one rounded box with the KPIs side by side, split by thin lines */
  .st-key-belt {{
    background: {SURFACE}; border: 1px solid {LINE}; border-radius: 14px;
    padding: 0.7rem 1.1rem 0.8rem; box-shadow: 0 4px 16px {SHADOW};
  }}
  .st-key-belt [data-testid="stColumn"] + [data-testid="stColumn"] {{
    border-left: 1px solid {LINE}; padding-left: 1rem;
  }}
  .st-key-belt [data-testid="stCaptionContainer"] p {{ font-size: 0.78rem; margin: 0; }}
  /* Keep the KPIs side by side on narrow screens too (wrapping onto a second row) */
  .st-key-belt [data-testid="stHorizontalBlock"] {{ flex-direction: row; flex-wrap: wrap;
                                                   row-gap: 0.6rem; }}
  .st-key-belt [data-testid="stColumn"] {{ flex: 1 1 7.5rem !important; min-width: 7.5rem;
                                          width: auto !important; }}
  header[data-testid="stHeader"] {{ background: {BACKGROUND}; }}
  .st-key-belt [data-testid="stMetricValue"] {{ font-size: 1.55rem; }}
  .st-key-belt [data-testid="stMetricLabel"] p {{ font-size: 0.8rem; }}
  /* Tab bar: a clear row of buttons; the open tab is filled in blue */
  .stTabs [role="tablist"] {{
    background: {SURFACE}; border: 1px solid {LINE}; border-radius: 12px;
    padding: 5px; gap: 6px; flex-wrap: wrap; margin: 0.9rem 0 1.1rem;
  }}
  .stTabs [role="tablist"]::before, .stTabs [role="tablist"]::after,
  .stTabs [data-testid="stTab"]::after,
  .stTabs .react-aria-SelectionIndicator {{ display: none !important; }}
  .stTabs [data-testid="stTab"] {{
    height: auto; padding: 0.5rem 1.1rem !important; border-radius: 8px;
    color: inherit !important; opacity: 0.8; transition: background .15s;
  }}
  .stTabs [data-testid="stTab"] p {{ font-size: 0.98rem; font-weight: 600; }}
  .stTabs [data-testid="stTab"]:hover {{ background: {HOVER}; opacity: 1; }}
  .stTabs [data-testid="stTab"][aria-selected="true"] {{
    background: {ACCENT}; color: #ffffff !important; opacity: 1;
    box-shadow: 0 2px 8px rgba(42,120,214,.35);
  }}
  /* Section headings inside the tabs get a blue marker, so each section stands out */
  [role="tabpanel"] h4, [role="tabpanel"] h5 {{
    border-left: 4px solid {ACCENT}; padding: 0.1rem 0 0.1rem 0.65rem !important;
  }}
  .st-key-suggest p, .st-key-suggest li {{ font-size: 0.85rem; line-height: 1.45; margin-bottom: 0.1rem; }}
  .st-key-suggest h6 {{ font-size: 0.72rem; padding: 0 0 0.25rem; text-transform: uppercase;
                       letter-spacing: 0.04em; opacity: 0.7; }}
  /* Plan tab: the two columns of sections become one when the window is narrow */
  @media (max-width: 1100px) {{
    .st-key-plan_sections > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] {{
      flex-direction: column;
    }}
    .st-key-plan_sections > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"]
      > [data-testid="stColumn"] {{ width: 100% !important; flex: 1 1 auto !important; }}
  }}
  @media (max-width: 640px) {{
    [data-testid="stLayoutWrapper"]:has(> .st-key-belt) {{ position: static; }}
    .st-key-belt [data-testid="stColumn"] + [data-testid="stColumn"] {{
      border-left: none; padding-left: 0;
    }}
  }}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------- formatting

def fmt_int(x):
    return f"{x:,.0f}"


def fmt_pct(x, signed=False):
    return f"{x * 100:+.1f}%" if signed else f"{x * 100:.1f}%"


def fmt_dec(x):
    return f"{x:,.1f}"


def month_label(period):
    return period.strftime("%b %Y")


def grid(items, render, n):
    """Lay items out row by row, so they keep their order when the screen is narrow."""
    for i in range(0, len(items), n):
        cols = st.columns(n)
        for col, item in zip(cols, items[i:i + n]):
            with col:
                render(item)


def keep_valid(key, options, default):
    """Widget arguments: the saved choice if it still fits, otherwise the default."""
    if key in st.session_state and st.session_state[key] not in options:
        del st.session_state[key]
    return {} if key in st.session_state else {"index": options.index(default)}


# ---------------------------------------------------------------- Setup tab

CHOOSE_COLUMN = "— choose a column —"
NOT_IN_DATA = "Not in my data"
CHOOSE_MEANING = "— choose —"
MAX_LABELS = 20     # more different values than this means the wrong column was picked

FIELD_HELP = {
    "lead_id": "A number or code for each lead. Optional: only used to spot duplicates.",
    "created_date": "When the lead was created. Its month is the lead month.",
    "source": f"Where the lead came from (up to {cfg['max_lead_sources']} sources).",
    "connected": "Whether the lead was reached.",
    "rm_code": f"The code of the {TEAM_ONE} working the lead. Blank = no {TEAM_ONE} (self conversion).",
    "converted": f"Whether and when the lead converted ({OUTPUT.lower()}).",
    "onboarding_date": f"The date of the {OUTPUT_ONE}. Blank if none.",
    "advisor_code": f"The {TEAM_ONE} code, matching the code on the leads.",
    "tenure": "How long the person has been in the team. Blank = has left.",
}
CONNECTED_MEANINGS = ["Connected in the same month", "Connected in a later month",
                      "Not connected"]
CONVERTED_MEANINGS = {"Onboarded in the same month": "converted_same_month",
                      "Onboarded in a later month": "converted_later",
                      "Not onboarded": "not_converted"}
LEFT = "Left / not counted"


@st.cache_data(show_spinner="Reading the file...")
def read_upload(data, name):
    buffer = io.BytesIO(data)
    buffer.name = name
    raw = model.read_table(buffer)
    raw.columns = [str(c) for c in raw.columns]
    return raw


@st.cache_data(show_spinner="Preparing the data...")
def prepare_cached(lead_bytes, lead_name, lead_map, value_labels,
                   team_bytes, team_name, team_map, tenure_map):
    leads = model.prepare_leads(read_upload(lead_bytes, lead_name), lead_map, value_labels)
    advisors = (model.prepare_advisors(read_upload(team_bytes, team_name), team_map, tenure_map)
                if team_bytes is not None else None)
    return leads, advisors


def show_problems(problems):
    """Errors are shown; warnings and notes go in a small panel. Returns True if any error."""
    errors = [t for level, t in problems if level == "error"]
    for text in errors:
        st.error(own_words(text))
    notes = [(level, t) for level, t in problems if level != "error"]
    if notes and not errors:
        with st.expander(f"{len(notes)} note{'s' if len(notes) > 1 else ''} about the data"):
            for level, text in notes:
                (st.warning if level == "warning" else st.info)(own_words(text))
    return bool(errors)


def file_slot(slot, title):
    """Upload box. A file uploaded earlier is kept until it is replaced or removed."""
    saved = st.session_state.get(f"file_{slot}")
    n = st.session_state.get(f"_upn_{slot}", 0)
    if saved:
        c = st.columns([5, 1], vertical_alignment="center")
        c[0].markdown(f"📄 **{saved['name']}**")
        if c[1].button("Remove", key=f"rm_{slot}", width="stretch"):
            remove_file(slot)
            st.rerun()
        with st.expander("Use a different file"):
            up = st.file_uploader(title, type=["csv", "xlsx", "xls"], key=f"up_{slot}_{n}")
    else:
        up = st.file_uploader(title, type=["csv", "xlsx", "xls"], key=f"up_{slot}_{n}")
    if up is not None and (not saved or up.getvalue() != saved["data"]):
        store_file(slot, up.name, up.getvalue())
        st.session_state[f"_upn_{slot}"] = n + 1
        st.rerun()
    saved = st.session_state.get(f"file_{slot}")
    if not saved:
        return None, None
    try:
        raw = read_upload(saved["data"], saved["name"])
    except Exception:
        st.error("This file could not be read. Save it as CSV or Excel (.xlsx) and upload it again.")
        return None, None
    if raw.empty:
        st.error("This file has no rows. Check that you uploaded the right file.")
        return None, None
    with st.expander(f"Preview: {len(raw):,} rows, {raw.shape[1]} columns"):
        st.dataframe(raw.head(5), hide_index=True)
    return raw, saved


def map_columns(raw, fields, required, prefix):
    """Columns whose names clearly match are chosen automatically; the rest are asked."""
    columns = list(raw.columns)
    options = [CHOOSE_COLUMN] + columns + [NOT_IN_DATA]
    auto = {f: model.match_column(columns, cfg["column_names"].get(f, [])) for f in fields}
    column_map = {}

    def widget(field):
        key = f"map_{prefix}_{field}"
        label = own_words(fields[field]) + ("" if field in required else " (optional)")
        choice = st.selectbox(label, options, key=key, help=FIELD_HELP[field],
                              **keep_valid(key, options, auto[field] or CHOOSE_COLUMN))
        column_map[field] = None if choice in (CHOOSE_COLUMN, NOT_IN_DATA) else choice

    asked = [f for f in fields if not auto[f]]
    matched = [f for f in fields if auto[f]]
    if asked:
        st.markdown("**Choose the column for each field**")
        grid(asked, widget, 2)
    if matched:
        with st.expander(f"✓ {len(matched)} column{'s' if len(matched) > 1 else ''} "
                         "matched automatically"):
            grid(matched, widget, 2)
    return column_map


def map_values(raw, column, title, meanings, auto_names, prefix, blank_note):
    """Values that clearly match are set automatically; the rest are asked.

    Returns {value: meaning}, or None while something is missing.
    """
    labels, blanks = model.distinct_labels(raw[column])
    if len(labels) > MAX_LABELS:
        st.error(f"The column **{column}** has {len(labels):,} different values. "
                 "Check that you picked the right column above.")
        return None
    if not labels:
        st.error(f"The column **{column}** is empty.")
        return None
    options = [CHOOSE_MEANING] + meanings
    auto = {l: model.match_value(l, auto_names) for l in labels}
    chosen = {}

    def widget(label):
        key = f"val_{prefix}_{column}_{label}"
        pick = st.selectbox(f"“{label}” means", options, key=key,
                            **keep_valid(key, options, auto[label] or CHOOSE_MEANING))
        if pick != CHOOSE_MEANING:
            chosen[label] = pick

    asked = [l for l in labels if not auto[l]]
    matched = [l for l in labels if auto[l]]
    if asked:
        st.markdown(f"**{title}**: what does each value in *{column}* mean?")
        grid(asked, widget, 3)
    if matched:
        with st.expander(f"✓ {title}: {len(matched)} value{'s' if len(matched) > 1 else ''} "
                         "understood automatically"):
            grid(matched, widget, 3)
            if blanks:
                st.caption(f"{blanks:,} blank values: {blank_note}.")
    missing = [l for l in labels if l not in chosen]
    if missing:
        st.error(f"Choose a meaning for: {', '.join(f'“{m}”' for m in missing)}.")
        return None
    return chosen


def setup_step():
    st.markdown("##### 1. What are you planning?")
    c = st.columns(2)
    c[0].text_input("The result you plan (plural)", key="setup_output", max_chars=30,
                    help="For example Onboardings, Enrolments, Sales.")
    c[1].text_input("The team that works the leads (plural)", key="setup_team_name",
                    max_chars=30, disabled=not FUNNEL["team"],
                    help="For example Advisors, Counsellors, Agents.")
    st.caption("What affects the result? Switch off what your business does not have.")
    st.toggle("Leads are contacted first (connect rate)", key="setup_connect")
    st.toggle(f"A team works the leads ({TEAM.lower()})", key="setup_team")
    st.toggle("Some leads convert in a later month (carry-over)", key="setup_carry")
    steps = ["Leads"] + (["Connected"] if FUNNEL["connect_step"] else []) + [OUTPUT]
    extras = ([f"worked by {TEAM.lower()}"] if FUNNEL["team"] else []) + \
             (["plus carry-over from earlier leads"] if FUNNEL["carry_over"] else [])
    st.caption(f"Your funnel: **{' → '.join(steps)}**" + (f", {', '.join(extras)}." if extras else "."))


def sample_download(slot, text, file_name):
    """What the file needs, with a made-up sample to download and copy the layout from."""
    path = SAMPLE_DIR / SAMPLE_FILES[slot]
    c = st.columns([3, 1.3], vertical_alignment="center")
    c[0].caption(text)
    if path.exists():
        c[1].download_button("Download a sample", data=path.read_bytes(), file_name=file_name,
                             mime="text/csv", icon=":material/download:", width="stretch",
                             key=f"dl_{slot}", help="A made-up file in the expected layout.")


def setup_tab():
    """Setup, upload, map and check. Returns (leads, advisors) when ready, else None."""
    top = st.columns([5, 1], vertical_alignment="center")
    if PUBLIC_DEMO:
        top[0].caption("Files you upload stay in this browser tab only. Nothing is stored.")
        top[1].button("Reset demo", on_click=start_over, width="stretch",
                      help="Go back to the sample data and default settings.")
    else:
        top[0].caption("Everything here is saved on this computer, so you can leave and come back.")
        top[1].button("Start over", on_click=start_over, width="stretch",
                      help="Remove the saved files and choices.")
    if not st.session_state.get("file_leads") and (SAMPLE_DIR / SAMPLE_FILES["leads"]).exists():
        st.button("Try it with made-up sample data", on_click=load_sample, type="primary",
                  icon=":material/science:")
    with st.container(border=True):
        setup_step()

    with st.container(border=True):
        st.markdown("##### 2. Lead file")
        lead_fields, lead_required = model.lead_fields(FUNNEL)
        sample_download("leads", "One row per lead, covering the last 3 months, with: Lead ID, "
                                 "created date, lead source, connected, advisor code, converted, "
                                 f"{OUTPUT_ONE} date. Not sure of the layout? Download the sample.",
                        "sample_leads.csv")
        lead_raw, lead_file = file_slot("leads", "Lead file: the last 3 months, one row per lead "
                                                 "(CSV or Excel)")
        ready = lead_raw is not None
        lead_map = value_labels = None
        if ready:
            lead_map = map_columns(lead_raw, lead_fields, lead_required, "leads")
            if show_problems(model.check_mapping(lead_map, lead_fields, lead_required)):
                ready = False
            else:
                names = cfg["value_names"]
                conn = {}
                if FUNNEL["connect_step"]:
                    conn = map_values(lead_raw, lead_map["connected"], "Connected", CONNECTED_MEANINGS,
                                      names["connected"], "conn", "treated as not connected")
                conv = map_values(lead_raw, lead_map["converted"], "Converted",
                                  list(CONVERTED_MEANINGS), names["converted"], "conv",
                                  "treated as not converted")
                if conn is None or conv is None:
                    ready = False
                else:
                    value_labels = {
                        "connected_yes": [l for l, m in conn.items() if m == CONNECTED_MEANINGS[0]],
                        "connected_later": [l for l, m in conn.items() if m == CONNECTED_MEANINGS[1]]}
                    for meaning, key in CONVERTED_MEANINGS.items():
                        value_labels[key] = [l for l, m in conv.items() if m == meaning]

    team_raw = team_file = team_map = tenure_map = None
    if FUNNEL["team"]:
        with st.container(border=True):
            st.markdown(f"##### 3. {TEAM} file")
            sample_download("team", f"One row per {TEAM_ONE}, as of the last month, with: code "
                                    "and tenure band (0-1 M, 1-2 M, 2-3 M, 3M+; blank if they "
                                    "have left).", f"sample_{TEAM.lower()}.csv")
            team_raw, team_file = file_slot("team", f"{TEAM} list as of last month, with tenure "
                                                    "(CSV or Excel)")
            if team_raw is None:
                ready = False
            else:
                team_map = map_columns(team_raw, model.ADVISOR_FIELDS, model.REQUIRED_ADVISOR_FIELDS,
                                       "adv")
                if show_problems(model.check_mapping(team_map, model.ADVISOR_FIELDS,
                                                     model.REQUIRED_ADVISOR_FIELDS)):
                    ready = False
                else:
                    band_names = {b: [b] for b in BANDS} | {LEFT: ["left", "exited"]}
                    tenure = map_values(team_raw, team_map["tenure"], "Tenure", BANDS + [LEFT],
                                        band_names, "ten", "treated as left (not counted)")
                    if tenure is None:
                        ready = False
                    else:
                        tenure_map = {l: b for l, b in tenure.items() if b != LEFT}

    if not ready:
        return None

    with st.container(border=True):
        st.markdown("##### Data checks")
        leads, advisors = prepare_cached(
            lead_file["data"], lead_file["name"], lead_map, value_labels,
            team_file["data"] if team_file else None, team_file["name"] if team_file else None,
            team_map, tenure_map)
        problems = model.check_leads(lead_raw, lead_map, leads, cfg)
        if FUNNEL["team"] and not any(level == "error" for level, _ in problems):
            problems += model.check_advisors(team_raw, advisors, leads, BANDS)
        if show_problems(problems):
            return None
        months = sorted(leads["lead_month"].dropna().unique())
        team_text = f" and {len(advisors):,} {TEAM.lower()}" if advisors is not None else ""
        st.success(f"Ready: {len(leads):,} leads from {month_label(months[0])} to "
                   f"{month_label(months[-1])}{team_text}.")
        return leads, advisors


# ---------------------------------------------------------------- layout

st.markdown(f"## {LABELS['app_name']}")
st.markdown(f"**Plan next month's {OUTPUT.lower()}.** Upload the last 3 months of leads and your "
            f"{TEAM_ONE} list: the planner forecasts next month's {OUTPUT.lower()}, shows the gap "
            f"to your target, and works out the leads, rates and {TEAM.lower()} needed to close it.")
if PUBLIC_DEMO:
    st.caption(":material/science: Demo with **made-up data**. Change any input on the **Plan** "
               "tab and watch the numbers move, or upload your own files on **Setup**.")
subtitle = st.empty()

GUIDE = [
    (":material/tune:", "1. Setup",
     f"Name what you plan and switch off steps you don't have. Upload 3 months of leads and the "
     f"{TEAM_ONE} list (or try the sample). Clear columns match automatically."),
    (":material/insights:", "2. History",
     "See where results come from last month and how connect and conversion rates moved."),
    (":material/edit_note:", "3. Plan",
     "Type a growth % for any input. The belt updates live, and **Effect** shows what each "
     "change adds."),
    (":material/compare_arrows:", "4. Decide",
     "Read the insights under the belt. On **Scenarios**, save plans, compare them, or let "
     "**Auto-plan** build one that hits the target."),
]
with st.expander(":material/help: How to use this planner",
                 expanded=not st.session_state.get("file_leads")):
    cols = st.columns(len(GUIDE))
    for col, (icon, title, text) in zip(cols, GUIDE):
        col.markdown(f"{icon} **{title}**  \n{text}")

belt = st.container(key="belt")
suggest_box = st.container(key="suggest")
tab_setup, tab_history, tab_plan, tab_scen = st.tabs(
    [":material/tune: Setup", ":material/insights: History", ":material/edit_note: Plan",
     ":material/compare_arrows: Scenarios"])

with tab_setup:
    data = setup_tab()

if data is None:
    with belt:
        st.info("Start in the **Setup** tab: describe your funnel and upload your files.")
    for tab in (tab_history, tab_plan, tab_scen):
        tab.info("Finish the **Setup** tab first.")
    save_state()
    st.stop()

leads, advisors = data
SOURCES = model.lead_sources(leads, cfg)
run_cfg = {**cfg, "lead_sources": SOURCES}
base = model.base_inputs(leads, advisors, run_cfg, FUNNEL)
TEAM_ON = bool(base["productivity"])
month_name = base["month"].strftime("%B %Y")
next_month_name = (base["month"] + 1).strftime("%B %Y")



# ---------------------------------------------------------------- charts

def colours(names):
    return alt.Scale(domain=list(names), range=SERIES[:len(names)])


def chart(c, height=230):
    st.altair_chart(c.properties(height=height), width="stretch")


def legend():
    return alt.Legend(title=None, orient="top", direction="horizontal")


# ---------------------------------------------------------------- History tab

with tab_history:
    months = [month_label(m) for m in sorted(leads["lead_month"].dropna().unique())]
    by_source = model.conversion_by_month(leads)
    by_source["Month"] = by_source["lead_month"].map(month_label)
    by_source["Source"] = by_source["source"]
    totals = model.monthly_totals(leads)
    totals["Month"] = totals["lead_month"].map(month_label)
    onb = model.onboardings_by_month(leads)
    onb["Month"] = onb["onboarding_month"].map(month_label)
    carry = model.carry_over_table(leads)
    carry["Month"] = carry["lead_month"].map(month_label)

    with st.container(border=True):
        # Last month's funnel, all sources or one
        head = st.columns([2, 3], vertical_alignment="center")
        head[0].markdown(f"#### {month_name}: from lead to {OUTPUT_ONE}")
        with head[1]:
            pick = st.segmented_control("Lead source", ["All sources"] + SOURCES, key="h_source",
                                        label_visibility="collapsed",
                                        **({} if "h_source" in st.session_state
                                           else {"default": "All sources"}))
        fc = model.funnel_counts(leads, source=None if pick in (None, "All sources") else pick)
        stages = [("Leads", fc["leads"])]
        if FUNNEL["connect_step"]:
            stages.append(("Connected in the same month", fc["connected"]))
        stages.append((f"{OUTPUT} in the same month", fc["same_month"]))
        funnel = pd.DataFrame(stages, columns=["Stage", "Count"])
        funnel["start"] = -funnel["Count"] / 2
        funnel["end"] = funnel["Count"] / 2
        # Shares of all leads: some conversions come from leads that were never connected,
        # so "share of the stage before" would mislead.
        funnel["of_leads"] = funnel["Count"] / funnel["Count"].iloc[0]
        funnel["Label"] = [fmt_int(c) + ("" if i == 0 else f"  ·  {fmt_pct(p)} of leads")
                           for i, (c, p) in enumerate(zip(funnel["Count"], funnel["of_leads"]))]
        order = list(funnel["Stage"])
        f_base = alt.Chart(funnel).encode(y=alt.Y("Stage:N", sort=order, title=None,
                                                  axis=alt.Axis(labelLimit=240)))
        chart(f_base.mark_bar(size=34, color=SERIES[0], cornerRadius=4).encode(
                  x=alt.X("start:Q", axis=None), x2="end:Q",
                  tooltip=["Stage:N", alt.Tooltip("Count:Q", format=",")])
              + f_base.mark_text(align="left", dx=8, color=TEXT).encode(x="end:Q", text="Label:N"),
              height=48 * len(funnel) + 20)
        note = []
        if FUNNEL["connect_step"]:
            note.append(f"Of the {fmt_int(fc['same_month'])} same-month {OUTPUT.lower()}, "
                        f"{fmt_int(fc['same_month_connected'])} came from connected leads and "
                        f"{fmt_int(fc['same_month_unassisted'])} were unassisted (not connected).")
        if FUNNEL["carry_over"] and fc["later"]:
            note.append(f"{fmt_int(fc['later'])} more converted in a later month so far.")
        if note:
            st.caption(" ".join(note))

    def leads_chart(_):
        st.markdown("**Leads by month and source**")
        chart(alt.Chart(by_source).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
            x=alt.X("Month:N", sort=months, title=None, axis=alt.Axis(labelAngle=0)),
            xOffset=alt.XOffset("Source:N", sort=SOURCES),
            y=alt.Y("leads:Q", title="Leads", axis=alt.Axis(format="~s")),
            color=alt.Color("Source:N", scale=colours(SOURCES), legend=legend()),
            tooltip=["Month:N", "Source:N", alt.Tooltip("leads:Q", title="Leads", format=",")]))

    def rate_lines(data, field, title, names, help_text=None, labels=False):
        st.markdown(f"**{title}**", help=help_text)
        base_c = alt.Chart(data).encode(
            x=alt.X("Month:N", sort=months, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y(f"{field}:Q", title=None, axis=alt.Axis(format=".0%")),
            color=alt.Color("Source:N", scale=colours(names),
                            legend=legend() if len(names) > 1 else None),
            tooltip=["Month:N", "Source:N", alt.Tooltip(f"{field}:Q", title=title, format=".1%")])
        layers = base_c.mark_line(point=alt.OverlayMarkDef(size=60), strokeWidth=2)
        if labels:
            layers += base_c.mark_text(dy=-12, color=TEXT).encode(
                text=alt.Text(f"{field}:Q", format=".1%"))
        chart(layers)

    def conversion_pct_chart(_):
        all_rows = totals.assign(Source="All sources")
        data = pd.concat([by_source[["Month", "Source", "conversion_of_leads"]],
                          all_rows[["Month", "Source", "conversion_of_leads"]]])
        rate_lines(data, "conversion_of_leads", "Conversion % of leads", SOURCES + ["All sources"],
                   f"Same-month {OUTPUT.lower()} ÷ leads, by lead month.")

    def connected_conversion_chart(_):
        rate_lines(by_source, "conversion", "Conversion of connected leads", SOURCES,
                   f"Same-month {OUTPUT.lower()} from leads connected that month, per connected "
                   "lead (measured against the overall connect rate, like the Plan input).")

    def unassisted_chart(_):
        rate_lines(by_source, "unassisted", "Unassisted conversion", SOURCES,
                   f"Same-month {OUTPUT.lower()} from leads NOT connected that month, as a share "
                   "of all leads.")

    def connect_chart(_):
        data = totals.assign(Source="All sources")
        rate_lines(data, "connect_pct", "Connect rate (same month)", ["All sources"],
                   "Leads connected in the month they were created ÷ leads.", labels=True)

    def onboardings_chart(_):
        st.markdown(f"**{OUTPUT} by {OUTPUT_ONE} date**")
        if TEAM_ON:
            long = onb.melt(id_vars=["Month", "self_pct", "onboarded"],
                            value_vars=["with_advisor", "self_conversion"],
                            var_name="kind", value_name="count")
            names = {"with_advisor": f"With {A_TEAM_ONE}", "self_conversion": "Self conversion"}
            long["Type"] = long["kind"].map(names)
            bars = alt.Chart(long).mark_bar().encode(
                x=alt.X("Month:N", sort=months, title=None, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("count:Q", title=None, stack=True),
                color=alt.Color("Type:N", scale=colours(list(names.values())), legend=legend()),
                order=alt.Order("kind:N", sort="descending"),
                tooltip=["Month:N", "Type:N", alt.Tooltip("count:Q", title=OUTPUT, format=","),
                         alt.Tooltip("self_pct:Q", title="Self conversion %", format=".1%")])
        else:
            bars = alt.Chart(onb).mark_bar(color=SERIES[0], cornerRadiusTopLeft=3,
                                           cornerRadiusTopRight=3).encode(
                x=alt.X("Month:N", sort=months, title=None, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("onboarded:Q", title=None),
                tooltip=["Month:N", alt.Tooltip("onboarded:Q", title=OUTPUT, format=",")])
        totals_text = alt.Chart(onb).mark_text(dy=-8, color=TEXT).encode(
            x=alt.X("Month:N", sort=months), y="onboarded:Q",
            text=alt.Text("onboarded:Q", format=","))
        chart(bars + totals_text)
        st.caption(f"The first month is low: {OUTPUT.lower()} from leads before the data are missing.")

    def carry_chart(_):
        st.markdown("**Carry-over: leads that converted in a later month**")
        long = carry.melt(id_vars=["Month", "leads", "later_pct_of_leads"],
                          value_vars=["onboarded_m1", "onboarded_m2", "onboarded_m3"],
                          var_name="lag", value_name="count")
        names = {"onboarded_m1": "Month +1", "onboarded_m2": "Month +2", "onboarded_m3": "Month +3"}
        long["When"] = long["lag"].map(names)
        chart(alt.Chart(long).mark_bar().encode(
            x=alt.X("Month:N", sort=months, title="Lead month", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("count:Q", title=None, stack=True),
            color=alt.Color("When:N", scale=colours(list(names.values())), legend=legend()),
            order=alt.Order("lag:N"),
            tooltip=["Month:N", "When:N", alt.Tooltip("count:Q", title=OUTPUT, format=","),
                     alt.Tooltip("later_pct_of_leads:Q", title="Later % of leads", format=".2%")]))
        st.caption("Recent lead months are still converting.")

    def productivity_chart(_):
        st.markdown(f"**{OUTPUT} per {TEAM_ONE}, {month_name}**")
        p = model.productivity_by_band(leads, advisors, BANDS)
        p["label"] = p["productivity"].map(fmt_dec)
        bars = alt.Chart(p).encode(
            x=alt.X("band:N", sort=BANDS, title="Tenure", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("productivity:Q", title=None),
            tooltip=[alt.Tooltip("band:N", title="Tenure"),
                     alt.Tooltip("advisors:Q", title=TEAM),
                     alt.Tooltip("onboardings_with_advisor:Q", title=OUTPUT, format=","),
                     alt.Tooltip("productivity:Q", title=f"Per {TEAM_ONE}", format=".1f")])
        chart(bars.mark_bar(color=SERIES[0], size=24, cornerRadiusTopLeft=3,
                            cornerRadiusTopRight=3)
              + bars.mark_text(dy=-8, color=TEXT).encode(text="label:N"))

    panels = [leads_chart, conversion_pct_chart]
    if FUNNEL["connect_step"]:
        panels += [connect_chart, connected_conversion_chart, unassisted_chart]
    panels.append(onboardings_chart)
    if FUNNEL["carry_over"]:
        panels.append(carry_chart)
    if TEAM_ON:
        panels.append(productivity_chart)
    def card(panel):
        with st.container(border=True):
            panel(None)

    grid(panels, card, 2)

    with st.expander("Show the numbers"):
        st.dataframe(pd.DataFrame({
            "Lead month": by_source["Month"], "Source": by_source["Source"],
            "Leads": by_source["leads"].map(fmt_int),
            "Connected (same month)": by_source["connected"].map(fmt_int),
            f"Same-month {OUTPUT.lower()}": by_source["same_month_onboarded"].map(fmt_int),
            "of which unassisted": by_source["same_month_unassisted"].map(fmt_int),
            f"Later {OUTPUT.lower()}": by_source["later_onboarded"].map(fmt_int),
            "Conversion % of leads": by_source["conversion_of_leads"].map(fmt_pct),
            "Conversion of connected": by_source["conversion"].map(fmt_pct),
            "Unassisted conversion": by_source["unassisted"].map(fmt_pct),
        }), hide_index=True, width="stretch")
        st.dataframe(pd.DataFrame({
            "Month": onb["Month"], OUTPUT: onb["onboarded"].map(fmt_int),
            "Self conversion": onb["self_conversion"].map(fmt_int),
            "Self %": onb["self_pct"].map(fmt_pct),
        }), hide_index=True, width="stretch")


# ---------------------------------------------------------------- Plan tab

def growth_input(key, label, default=0.0):
    """A typed growth %, with +/- buttons in steps of 5."""
    return st.number_input(f"Growth % for {label}", key=key, step=5.0, format="%.1f",
                           min_value=-100.0, max_value=1000.0, label_visibility="collapsed",
                           **({} if key in st.session_state else {"value": float(default)})) / 100


ROW = [2.3, 1.1, 1.6, 1.1, 1.1]
EFFECT_HELP = (f"What this change alone does to expected {{output}} next month, compared with "
               f"keeping last month's value. Team inputs show the change in {TEAM.lower()} "
               "needed for the target instead.")


def section(title, rows, base_head=None, effect=True):
    with st.container(border=True):
        st.markdown(f"**{title}**")
        head = st.columns(ROW)
        for col, text in zip(head, ["", base_head or f"{month_name[:3]}", "Growth %", "Planned"]):
            col.caption(text)
        if effect:
            head[4].caption("Effect", help=EFFECT_HELP.format(output=OUTPUT.lower()))
        for row in rows:
            row()


growth = {"leads": {}, "conversion": {}, "unassisted": {}, "productivity": {}}
effect_slots = {}      # model input key -> the empty cell where its effect is shown


def input_row(label, base_value, fmt, key, planned_fn, store, default=0.0, help=None,
              effect_key=None):
    def render():
        c = st.columns(ROW, vertical_alignment="center")
        c[0].markdown(label, help=help)
        c[1].markdown(fmt(base_value))
        with c[2]:
            g = growth_input(key, label, default)
        c[3].markdown(f"**{fmt(planned_fn(g))}**")
        if effect_key:
            effect_slots[effect_key] = c[4].empty()
        store(g)
    return render


def effect_text(e):
    """'+41' (results), '-1 advisor' (team inputs) or a dash when the change does nothing."""
    out = round(e["output"])
    if out:
        return f":{'green' if out > 0 else 'red'}[{out:+,d}]"
    if e["team"]:
        n = e["team"]
        word = TEAM_ONE if abs(n) == 1 else TEAM.lower()
        return f":{'green' if n < 0 else 'red'}[{n:+d} {word}]"
    return ":gray[–]"


def rate(value, g):
    return min(cfg["rate_cap"], value * (1 + g))


def put(*path):
    def store(g):
        target = growth
        for p in path[:-1]:
            target = target[p]
        target[path[-1]] = g
    return store


with tab_plan:
    st.caption("Type a growth % (for example 7.5), or use − and + to move in steps of 5. "
               "Rates grow relative to their base and never go above 100%. **Effect** shows what "
               "each change alone adds next month.")
    plan_total = st.empty()
    left, right = st.container(key="plan_sections").columns(2, gap="medium")
    with left:
        section("Leads", [
            input_row(f"{s}", base["leads"][s], fmt_int, f"g_leads_{s}",
                      lambda g, b=base["leads"][s]: model.round_half_up(b * (1 + g)),
                      put("leads", s), effect_key=f"leads:{s}")
            for s in SOURCES])
        rate_rows = []
        if FUNNEL["connect_step"]:
            rate_rows.append(input_row("Connect rate", base["connect_rate"], fmt_pct, "g_connect",
                                       lambda g: rate(base["connect_rate"], g),
                                       put("connect_rate"), effect_key="connect_rate",
                                       help="Leads connected in the month they were created."))
        rate_rows += [input_row(f"{s} conversion", base["conversion"][s], fmt_pct, f"g_conv_{s}",
                                lambda g, b=base["conversion"][s]: rate(b, g), put("conversion", s),
                                effect_key=f"conversion:{s}",
                                help=("Same-month conversion of connected leads." if
                                      FUNNEL["connect_step"] else "Same-month conversion of leads."))
                      for s in SOURCES]
        if FUNNEL["connect_step"]:
            rate_rows += [input_row(f"{s} unassisted", base["unassisted"][s], fmt_pct,
                                    f"g_unas_{s}", lambda g, b=base["unassisted"][s]: rate(b, g),
                                    put("unassisted", s), effect_key=f"unassisted:{s}",
                                    help="Same-month conversions from leads not connected that "
                                         "month, as a share of all leads.")
                          for s in SOURCES]
        section("Rates", rate_rows)
    with right:
        if TEAM_ON:
            section(TEAM, [
                input_row("Self conversion", base["self_pct"], fmt_pct, "g_self",
                          lambda g: rate(base["self_pct"], g), put("self_pct"),
                          effect_key="self_pct",
                          help=f"Share of {OUTPUT.lower()} that need no {TEAM_ONE}.")]
                + [input_row(f"Productivity {b}", base["productivity"][b], fmt_dec, f"g_prod_{b}",
                             lambda g, v=base["productivity"][b]: v * (1 + g),
                             put("productivity", b), effect_key=f"productivity:{b}",
                             help=f"{OUTPUT} per {TEAM_ONE} per month.")
                   for b in BANDS])
        if FUNNEL["carry_over"]:
            section("Carry-over", [
                input_row("% of leads", base["carry_pct"], fmt_pct, "g_carry",
                          lambda g: rate(base["carry_pct"], g), put("carry_pct"),
                          effect_key="carry_pct",
                          help="Assumption: leads that convert in month +1 or +2."),
                input_row("Share in month +1", base["m1_share"], fmt_pct, "g_m1",
                          lambda g: rate(base["m1_share"], g), put("m1_share"),
                          effect_key="m1_share",
                          help="The rest arrives in month +2.")], base_head="Assumed")
            carry_planned = rate(base["carry_pct"], growth.get("carry_pct", 0.0))
            if not ASSUME["carry_over_min"] <= carry_planned <= ASSUME["carry_over_max"] + 1e-12:
                st.warning(f"Carry-over {fmt_pct(carry_planned)} is outside the usual "
                           f"{fmt_pct(ASSUME['carry_over_min'])}–{fmt_pct(ASSUME['carry_over_max'])}.")

        holder = {}
        section("Target", [input_row(
            f"{OUTPUT} target", base["last_month_onboardings"], fmt_int, "g_target",
            lambda g: model.round_half_up(base["last_month_onboardings"] * (1 + g)),
            lambda g: holder.update(target=g), default=ASSUME["target_growth"] * 100)],
            effect=False)
        target_growth = holder["target"]


# ---------------------------------------------------------------- calculate

plan = model.plan_inputs(base, growth, cfg["rate_cap"])
r = model.forecast(plan, target_growth, cfg["new_hire_band"])

effects = model.input_effects(base, plan, target_growth, cfg["new_hire_band"], cfg["rate_cap"])
for key, slot in effect_slots.items():
    slot.markdown(effect_text(effects[key]))
together = round(effects["_all"]["output"])
if together:
    plan_total.markdown(f"All your changes together: **{together:+,d}** {OUTPUT.lower()} next "
                        "month (changes that work together can add a little more than the effects "
                        "added up).")


# ---------------------------------------------------------------- belt and suggestions

with belt:
    st.caption(f":material/calendar_month: **{next_month_name}** plan · based on {month_name}, "
               "the last month in your lead file")
    k = st.columns(5 if TEAM_ON else 4)
    # Short labels so the cards still fit at half-screen width; the details are in the (?) help.
    k[0].metric("Last month", fmt_int(base["last_month_onboardings"]),
                help=f"{OUTPUT} in {month_name}, counted by {OUTPUT_ONE} date.")
    k[1].metric("Expected", fmt_int(r["expected_onboardings"]),
                delta=fmt_pct(r["growth_vs_last_month"], signed=True),
                help=f"Expected {OUTPUT.lower()} in {next_month_name}; the change is vs last month.")
    k[2].metric("Target", fmt_int(r["target"]), delta=fmt_pct(target_growth, signed=True),
                delta_color="off", help="Target, and its growth vs last month.")
    short = r["gap"] > 0.5
    k[3].metric("Gap", fmt_int(abs(r["gap"])), delta="short" if short else "met",
                delta_color="inverse" if short else "normal", delta_arrow="off",
                help="Target minus expected.")
    if TEAM_ON:
        k[4].metric(TEAM, fmt_int(r["advisors_required"]),
                    delta=f"{r['advisor_gap']:+,d} vs {r['total_advisors']}",
                    delta_color="inverse", delta_arrow="off",
                    help=f"{TEAM} needed for the target: {OUTPUT.lower()} that need {A_TEAM_ONE} "
                         f"÷ average productivity of next month's team ({r['total_advisors']}, "
                         "everyone moved up one tenure band).")

TONE = {"warn": ("orange", ":material/warning:"), "good": ("green", ":material/check_circle:"),
        "info": ("blue", ":material/insights:")}


def insight_card(item):
    colour, icon = TONE[item["tone"]]
    with st.container(border=True):
        st.markdown(f":{colour}[{icon}] **{item['title']}**  \n{item['text']}")


with suggest_box:
    try:
        rules = model.load_rules()
    except Exception as e:
        st.error(f"suggestions.yaml could not be read: {e}")
        rules = {}
    words = {"output": OUTPUT.lower(), "Output": OUTPUT, "team": TEAM.lower(), "Team": TEAM,
             "team_one": TEAM_ONE, "a_team_one": A_TEAM_ONE}
    highs = model.recent_highs(leads, advisors if TEAM_ON else None, SOURCES, BANDS)
    items = model.insights(leads, base, plan, r, highs, target_growth, cfg["new_hire_band"],
                           rules, words, cfg["rate_cap"])
    if items:
        st.markdown("###### Insights")
        grid(items, insight_card, 3)


# ---------------------------------------------------------------- Scenarios tab

CURRENT = "Current plan"
AUTO = "Auto-plan"
MAX_SCENARIOS = 6
# Plan input (model path) -> the growth % widget on the Plan tab
WIDGET_KEYS = {"leads": "g_leads_{}", "connect_rate": "g_connect", "conversion": "g_conv_{}",
               "unassisted": "g_unas_{}", "self_pct": "g_self", "productivity": "g_prod_{}",
               "carry_pct": "g_carry", "m1_share": "g_m1"}


def widget_key(item):
    pattern = WIDGET_KEYS[item["path"][0]]
    return pattern.format(item["path"][1]) if len(item["path"]) == 2 else pattern


def current_values():
    """The growth % typed on the Plan tab (and the target growth), as saved in a scenario."""
    return {k: float(v) for k, v in st.session_state.items()
            if isinstance(k, str) and k.startswith("g_") and isinstance(v, (int, float))}


def growth_from_values(values):
    """Growth dict and target growth for a saved scenario."""
    g = {}
    for item in model.plan_input_list(model.plan_inputs(base, {}, cfg["rate_cap"])):
        model.growth_set(g, item["path"], values.get(widget_key(item), 0.0) / 100)
    return g, values.get("g_target", ASSUME["target_growth"] * 100) / 100


def save_scenario():
    scenarios = st.session_state.setdefault("scenarios", {})
    name = (st.session_state.get("scn_name") or "").strip() or f"Scenario {len(scenarios) + 1}"
    if name in (CURRENT,) or (name not in scenarios and len(scenarios) >= MAX_SCENARIOS):
        st.session_state["_scn_msg"] = ("warning", f"Keep up to {MAX_SCENARIOS} scenarios, and "
                                                   f"don't use the name “{CURRENT}”.")
        return
    scenarios[name] = current_values()
    st.session_state["scn_pick"] = name
    st.session_state["scn_name"] = ""
    st.session_state["_scn_msg"] = ("success", f"Saved “{name}”.")


def use_scenario(name):
    """Put a scenario's growth % into the Plan tab."""
    values = st.session_state.get("scenarios", {}).get(name, {})
    for key in [k for k in st.session_state if isinstance(k, str) and k.startswith("g_")]:
        del st.session_state[key]                     # back to defaults first
    for key, value in values.items():
        st.session_state[key] = value
    st.session_state["_scn_msg"] = ("success", f"“{name}” is now in the Plan tab.")


def delete_scenario(name):
    st.session_state.get("scenarios", {}).pop(name, None)
    st.session_state.pop("scn_pick", None)


def section_title(title, caption=None, help=None):
    st.markdown(f"#### {title}", help=help)
    if caption:
        st.caption(caption)


def lever_fmt(kind):
    return {"rate": fmt_pct, "decimal": fmt_dec}.get(kind, fmt_int)


# The auto-plan button only sets a flag; the plan is built here, once the data is ready.
if st.session_state.pop("_do_auto", False):
    keep = {k: v for k, v in growth.items() if k in ("self_pct", "productivity", "carry_pct",
                                                    "m1_share")}
    auto = model.auto_plan(base, target_growth, highs, cfg["new_hire_band"], cfg["rate_cap"],
                           keep=keep)
    values = current_values()
    start = model.plan_inputs(base, {}, cfg["rate_cap"])
    for item in model.plan_input_list(start):
        if item["group"] in ("leads", "rates"):
            path = item["path"]
            g = auto["growth"][path[0]][path[1]] if len(path) == 2 else auto["growth"][path[0]]
            values[widget_key(item)] = round(g * 100, 4)
    st.session_state.setdefault("scenarios", {})[AUTO] = values
    st.session_state["scn_pick"] = AUTO
    if not auto["reachable"]:
        st.session_state["_scn_msg"] = ("error", "The target is out of reach even with every "
                                                 "lever far beyond its best recent month.")
    elif auto["within_recent"]:
        st.session_state["_scn_msg"] = ("success", "Auto-plan reaches the target with every "
                                                   "lever within its best recent month.")
    else:
        st.session_state["_scn_msg"] = ("warning", "Auto-plan reaches the target, but only by "
                                                   "pushing levers beyond their best recent "
                                                   "months.")

with tab_scen:
    scenarios = st.session_state.setdefault("scenarios", {})
    lead_months = sorted(leads["lead_month"].dropna().unique())
    span = f"{lead_months[0].strftime('%b')}–{lead_months[-1].strftime('%b %Y')}"
    within_help = (f"**✓ Within**: the planned value is no higher than the best month in your data "
                   f"({span}). You have done it before, so it is realistic.\n\n"
                   f"**▲ Above**: higher than any month in your data. It would be a new level, so "
                   "treat it as a stretch and name what will make it happen.")
    untested_help = ("Share of this version's extra results (compared with last month) that comes "
                     f"from inputs planned above every month in your data ({span}). 0% means "
                     "everything is within what you have already achieved.")

    # 1. What a scenario is, and the two ways to make one
    section_title("Scenarios: compare versions of your plan",
                  "A scenario is a saved copy of every growth % on the Plan tab. Keep a few "
                  "versions, for example a safe plan and a stretch plan, and compare them here.")
    steps = st.columns(3)
    for col, (icon, text) in zip(steps, [
            (":material/edit_note:", "**1.** Set the growth % on the **Plan** tab."),
            (":material/bookmark_add:", "**2.** Save it below with a name, or let **Auto-plan** "
                                        "build one that hits the target."),
            (":material/compare_arrows:", "**3.** Compare them. **Use in Plan** switches the Plan "
                                          "tab to any saved version.")]):
        col.markdown(f"{icon} {text}")

    make = st.columns(2, gap="medium")
    with make[0].container(border=True):
        st.markdown(":material/bookmark_add: **Save the plan you have now**")
        st.caption("Saves the growth % currently on the Plan tab under a name you choose.")
        s = st.columns([3, 1.2], vertical_alignment="bottom")
        s[0].text_input("Name for this version", key="scn_name",
                        placeholder="e.g. Safe plan, Stretch plan", max_chars=30)
        s[1].button("Save", on_click=save_scenario, width="stretch")
    with make[1].container(border=True):
        st.markdown(":material/auto_awesome: **Let the planner build one**")
        st.caption("Moves leads, connect rate and conversion back towards their best recent "
                   "months, all by the same share, until expected = target. It is saved as "
                   f"“{AUTO}”; your team and carry-over inputs stay as they are.")
        st.button("Auto-plan to hit the target", type="primary", icon=":material/auto_awesome:",
                  on_click=lambda: st.session_state.update(_do_auto=True), width="stretch")
    if "_scn_msg" in st.session_state:
        level, text = st.session_state.pop("_scn_msg")
        getattr(st, level)(text)

    # 2. Compare
    section_title("Compare",
                  f"“{CURRENT}” is what is on the Plan tab right now (not saved). The others are "
                  "your saved versions.")
    if not scenarios:
        st.info("No saved versions yet. Save the plan you have now, or press Auto-plan, and it "
                "will appear here next to the current plan.", icon=":material/info:")
    compare = {CURRENT: (growth, target_growth)}
    compare.update({name: growth_from_values(v) for name, v in scenarios.items()})
    rows = pd.DataFrame(model.compare_scenarios(leads, base, compare, highs, cfg["new_hire_band"],
                                                cfg["rate_cap"]))
    names = list(rows["name"])
    rows["Label"] = [f"{fmt_int(e)} · " + ("met" if g <= 0.5 else f"{fmt_int(g)} short")
                     for e, g in zip(rows["expected"], rows["gap"])]
    rows["top"] = rows[["expected", "target"]].max(axis=1)
    bars = alt.Chart(rows).encode(
        x=alt.X("name:N", sort=names, title=None, axis=alt.Axis(labelAngle=0, labelLimit=160)),
        tooltip=[alt.Tooltip("name:N", title="Scenario"),
                 alt.Tooltip("expected:Q", title=f"Expected {OUTPUT.lower()}", format=",.0f"),
                 alt.Tooltip("target:Q", title="Target", format=",.0f"),
                 alt.Tooltip("gap:Q", title="Gap", format=",.0f")])
    exp_bars = bars.mark_bar(size=36, color=SERIES[0], cornerRadiusTopLeft=4,
                             cornerRadiusTopRight=4).encode(
        y=alt.Y("expected:Q", title=None, axis=alt.Axis(format="~s")))
    target_ticks = bars.mark_tick(color=NEUTRAL, thickness=3, size=56).encode(y="target:Q")
    labels = bars.mark_text(dy=-10, color=TEXT).encode(y="top:Q", text="Label:N")
    chart(exp_bars + target_ticks + labels, height=240)
    st.caption(f"Bars: expected {OUTPUT.lower()}. Grey line: that version's target.")

    kind = {CURRENT: "On the Plan tab now", AUTO: "Built by Auto-plan"}
    table = pd.DataFrame({
        "Version": rows["name"],
        "What it is": rows["name"].map(lambda n: kind.get(n, "Saved by you")),
        f"Expected {OUTPUT.lower()}": rows["expected"].map(fmt_int),
        "vs last month": rows["growth"].map(lambda v: fmt_pct(v, signed=True)),
        "Target": rows["target"].map(fmt_int),
        "Gap": rows["gap"].map(lambda v: "met" if v <= 0.5 else fmt_int(v)),
        "Leads": rows["leads"].map(fmt_int),
    })
    if TEAM_ON:
        table[f"{TEAM} needed"] = [f"{fmt_int(a)} ({g:+d})" for a, g in
                                   zip(rows["advisors"], rows["advisor_gap"])]
    table["Uplift above recent months"] = rows["untested"].map(lambda v: f"{v * 100:.0f}%")
    st.dataframe(table, hide_index=True, width="stretch", height=35 * (len(table) + 1) + 3,
                 column_config={"Uplift above recent months":
                                st.column_config.TextColumn(help=untested_help)})

    # 3. One saved version in detail
    if scenarios:
        section_title("Look inside a saved version",
                      "What it changes compared with last month, and whether each change is "
                      "within or above your best recent month. Use in Plan puts it on the Plan "
                      "tab.", help=within_help)
        options = list(scenarios)
        d = st.columns([2, 1, 1], vertical_alignment="bottom")
        pick = d[0].selectbox("Saved version", options, key="scn_pick",
                              **keep_valid("scn_pick", options, options[-1]))
        d[1].button("Use in Plan", on_click=use_scenario, args=(pick,),
                    icon=":material/edit_note:", width="stretch",
                    help="Replaces the growth % on the Plan tab with this scenario's.")
        d[2].button("Delete", on_click=delete_scenario, args=(pick,), icon=":material/delete:",
                    width="stretch")
        g, tg = growth_from_values(scenarios[pick])
        splan = model.plan_inputs(base, g, cfg["rate_cap"])
        start = model.plan_inputs(base, {}, cfg["rate_cap"])
        lines = []
        for item in model.plan_input_list(splan):
            before, after = model._get(start, item["path"]), model._get(splan, item["path"])
            if abs(after - before) < 1e-12:
                continue
            fmt = lever_fmt(item["kind"])
            best = model._best(highs, item["path"])
            within = best is None or after <= best + 1e-9
            lines.append({"Input": item["label"], "Last month": fmt(before), "Planned": fmt(after),
                          "Change": f"{after / before - 1:+.1%}" if before else "",
                          "Best recent": fmt(best) if best is not None else "–",
                          "vs recent months": "✓ Within" if within else "▲ Above"})
        if lines:
            st.dataframe(pd.DataFrame(lines), hide_index=True, width="stretch",
                         height=35 * (len(lines) + 1) + 3,
                         column_config={"vs recent months":
                                        st.column_config.TextColumn(help=within_help),
                                        "Best recent": st.column_config.TextColumn(
                                            help=f"The best month in your data ({span}).")})
        else:
            st.caption("This scenario keeps every input at last month's value.")
        st.caption(f"Target growth in this scenario: {fmt_pct(tg, signed=True)}.")


save_state()
