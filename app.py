"""FMS Arms Sales Notifications dashboard (Streamlit).

Run:  streamlit run app.py
"""
import streamlit as st

from fms_data import DEFAULT_DIR, fmt_money, load_notices, sync_repo

st.set_page_config(page_title="FMS Arms Sales Notifications", layout="wide")


@st.cache_data(ttl=6 * 3600, show_spinner="Loading the latest notices…")
def get_data():
    commit = sync_repo(DEFAULT_DIR)
    return load_notices(DEFAULT_DIR), commit


df, commit = get_data()

# ---------------------------------------------------------------- header
latest_date = df["publication_date"].max()
latest = df[df["publication_date"] == latest_date]
top = latest[(latest["type"] == "New sale") & latest["value_usd"].notna()].nlargest(1, "value_usd")

st.title("FMS Arms Sales Notifications")
lede = f"The latest batch, published {latest_date:%B %-d, %Y}, has {len(latest)} notices."
if not top.empty:
    t = top.iloc[0]
    lede += f" The largest new sale is {t.country}: {fmt_money(t.value_usd)}."
st.caption(lede)

c1, c2 = st.columns(2)
with c1:
    st.metric("Total notices since July 2011", f"{len(df):,}")
    st.caption("All Federal Register “Arms Sales Notification” notices, corrections included")
with c2:
    st.metric("Last publication date", f"{latest_date:%B %-d, %Y}")
    st.caption(f"{len(latest)} notices published that day")

# ---------------------------------------------------------------- picker
LATEST = f"Latest notices ({latest_date:%B %-d, %Y})"
counts = df["country"].value_counts()
countries = sorted(c for c in counts.index if c != "Not identified")
labels = {LATEST: None, **{f"{c} ({counts[c]})": c for c in countries}}
if "Not identified" in counts:
    labels[f"Country not identified ({counts['Not identified']})"] = "Not identified"

head_col, pick_col = st.columns([3, 2], vertical_alignment="bottom")
with pick_col:
    choice = st.selectbox("Show", list(labels), index=0)
country = labels[choice]

if country is None:
    view = latest.sort_values("value_usd", ascending=False, na_position="last")
    title = "Latest notices"
else:
    view = df[df["country"] == country]
    title = "Notices with no country identified" if country == "Not identified" else f"All notices: {country}"
with head_col:
    st.subheader(f"{title} · {len(view)} notice{'s' if len(view) != 1 else ''}")

# ---------------------------------------------------------------- table
has_value = view["type"].isin(["New sale", "Enhancement/upgrade", "Amendment"])
table = view.assign(
    published=view["publication_date"].dt.strftime("%Y-%m-%d"),
    value=[fmt_money(v) if ok else "—" for v, ok in zip(view["value_usd"], has_value)],
    # Link column shows the transmittal number, opens the Federal Register page
    link=view["html_url"] + "#" + view["transmittal"],
)[["published", "country", "link", "type", "description", "value", "value_note"]]

st.dataframe(
    table,
    hide_index=True,
    width="stretch",
    height=min(38 * (len(table) + 1) + 4, 700),
    column_config={
        "published": st.column_config.TextColumn("Published", width="small"),
        "country": st.column_config.TextColumn("Country"),
        "link": st.column_config.LinkColumn("Transmittal", display_text=r"#(.+)$", width="small"),
        "type": st.column_config.TextColumn("Type"),
        "description": st.column_config.TextColumn("Description", width="large"),
        "value": st.column_config.TextColumn("Value offered", width="small"),
        "value_note": st.column_config.TextColumn("How the value was found"),
    },
)

st.caption(
    "New sales show the total estimated value. Enhancements/upgrades and amendments show only the "
    "value the notice adds, taken from the official text. Country names are grouped "
    "(e.g. “Republic of Korea” → South Korea, TECRO → Taiwan). Transmittal numbers link to the notice "
    f"on the Federal Register. Data: AttacheArmement/defense-monitor-data @ {commit}."
)
