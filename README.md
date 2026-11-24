# FMS Arms Sales Notifications — Streamlit dashboard

Same view as the Claude dashboard: total number of notices, last publication date, and a
**Show** menu that lists either the latest batch of notices or every notice for one country.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

On first start the app clones the public repo
[AttacheArmement/defense-monitor-data](https://github.com/AttacheArmement/defense-monitor-data)
next to `app.py` (it needs `git`). It then runs `git pull` at most every 6 hours, so the morning
update shows up on its own. To use a copy you already have, set `FMS_REPO_DIR=/path/to/defense-monitor-data`.

## Deploy (Streamlit Community Cloud)

Push these five files to a GitHub repo (`packages.txt` makes sure `git` is installed on the server), then create an app at share.streamlit.io pointing at
`app.py`. Nothing else is needed: the data repo is public.

## Files

- `app.py` — the page
- `fms_data.py` — loads the JSON notices, groups country names, works out values
- `requirements.txt` — Python packages
- `packages.txt` — system packages (git)

## How values are shown

- **New sale:** total estimated value of the notice.
- **Enhancement/upgrade:** only the value this notice adds, read from the paragraph about the
  current transmittal: the stated value of the new items (or MDE + non-MDE added up), otherwise
  the stated case increase. The "How the value was found" column says which.
- **Amendment:** notified total minus the prior case value given in the text.
- Shown as "Not stated" when the text gives no figure (24 of 284 enhancements/amendments today).

Country names are grouped (e.g. "Republic of Korea" → South Korea, all TECRO variants → Taiwan
(TECRO), NSPA/NCIA → NATO). The original name is kept in `country_as_published`.

These notices are proposals to Congress, not signed or delivered sales.
