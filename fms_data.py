"""Load FMS Arms Sales Notifications from the AttacheArmement/defense-monitor-data repo.

Reads the JSON notice files directly (no database needed), groups country-name variants,
and works out the value each notice offers:
  - new sales: total estimated value
  - enhancements/upgrades and amendments: the value this notice adds, from the official text
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pandas as pd

REPO_URL = "https://github.com/AttacheArmement/defense-monitor-data"
DEFAULT_DIR = Path(os.environ.get("FMS_REPO_DIR", Path(__file__).parent / "defense-monitor-data"))


# --------------------------------------------------------------------------- repo
def sync_repo(repo_dir: Path = DEFAULT_DIR) -> str:
    """Clone the repo if missing, otherwise pull the latest commit. Returns the short commit id."""
    if (repo_dir / ".git").exists():
        subprocess.run(["git", "-C", str(repo_dir), "pull", "--ff-only", "-q"], check=False)
    else:
        subprocess.run(["git", "clone", "-q", "--depth", "1", REPO_URL, str(repo_dir)], check=True)
    out = subprocess.run(["git", "-C", str(repo_dir), "log", "-1", "--format=%h %cI"],
                         capture_output=True, text=True, check=False)
    return out.stdout.strip()


# --------------------------------------------------------------------------- countries
_FIX = {
    "Republic of Korea": "South Korea", "Korea": "South Korea",
    "Arab Republic of Egypt": "Egypt", "Commonwealth of Australia": "Australia",
    "Royal Kingdom of the Netherlands": "Netherlands", "Slovak Republic": "Slovakia",
    "Republic of Türkiye": "Türkiye (Turkey)", "Republic of Turkey": "Türkiye (Turkey)",
    "Turkey": "Türkiye (Turkey)", "Sultanate of Oman": "Oman",
    "Federal Republic of Nigeria": "Nigeria", "Kingdom of Saudi Arabia": "Saudi Arabia",
}


def normalize_country(raw: str | None) -> str:
    if not raw:
        return "Not identified"
    s = raw.strip()
    if re.search(r"Taipei|Taiwan|TECRO", s):
        return "Taiwan (TECRO)"
    if re.match(r"(NATO|North Atlantic Treaty)", s):
        return "NATO (NSPA / NCIA)"
    s = re.sub(r"\s*\(.*$", "", s)                       # drop parentheticals
    s = re.sub(r",.*$", "", s)                           # drop ", Ministry of ..."
    s = re.sub(r"^(The )?Government of (the )?", "", s, flags=re.I)
    s = re.sub(r"^The ", "", s)
    s = re.sub(r" Guard$", "", s)
    if s in _FIX:
        return _FIX[s]
    s = re.sub(r"^(Kingdom of|Republic of) (the )?", "", s)
    s = re.sub(r"^the ", "", s)
    return s[:1].upper() + s[1:]


# --------------------------------------------------------------------------- values
_M = r"\$\s?([\d.,]+)\s*(million|billion|thousand)"


def _amt(n: str, u: str) -> int:
    return round(float(n.replace(",", "").rstrip(".")) * {"b": 1e9, "m": 1e6, "t": 1e3}[u[0].lower()])


def fmt_money(v) -> str:
    """$X.XM or $X.XXB; 'Not stated' when missing."""
    if v is None or pd.isna(v):
        return "Not stated"
    v = float(v)
    return f"${v / 1e9:.2f}B" if v >= 1e9 else f"${v / 1e6:.1f}M"


_RULES = [
    (r"(?:value|cost) of (?:the |these )?(?:new|newly|additional|added)\b[^.$]{0,60}? (?:is|are|will be) (?:approximately )?" + _M, 1, "Stated value of the added items"),
    (r"(?:value|cost) of (?:the |these )(?:new |additional |added )?(?:MDE and non-MDE |MDE |non-MDE )?(?:items|articles|equipment|MDE|non-MDE)?[^.$]{0,30}? (?:is|will be|are) (?:approximately )?" + _M, 1, "Stated value of the added items"),
    (r"increase[sd]? (?:the )?(?:estimated |total |overall |case |program )*(?:value|cost)?\s?by (?:approximately |an additional )?" + _M, 1, "Stated increase"),
    (r"(?:value|cost)[^.]{0,30}? (?:will |would )?increase[sd]? by (?:approximately )?" + _M, 1, "Stated increase"),
    (r"increase (?:in value )?from (?:approximately )?" + _M + r" to (?:approximately |a revised )?" + _M, 2, "Derived from stated old and new case values"),
    (r"result in an increase in (?:major defense equipment |MDE )?(?:\(MDE\) )?(?:costs? |value )?of (?:approximately )?" + _M, 1, "Stated increase"),
    (r"increase in (?:the )?(?:non-MDE |MDE |total |case )*(?:value|cost) by (?:approximately )?" + _M, 1, "Stated increase"),
    (r"(?:total )?program increase of (?:approximately )?" + _M, 1, "Stated increase"),
    (r"(?:estimated )?additional (?:MDE |non-MDE |total )?(?:value|cost) (?:is|of|will be) (?:approximately )?" + _M, 1, "Stated additional value"),
]


def _current_section(t: str) -> str:
    """The paragraph describing this transmittal (earlier transmittals are often recapped first)."""
    end = t.find("(iv)")
    end = end if end > 0 else len(t)
    starts = [m.start() for m in re.finditer(r"This (?:transmittal|notification)", t[:end])]
    if starts:
        return t[starts[-1]:end]
    i = t.rfind("(iii)", 0, end)
    return t[i:end] if i >= 0 else t[:end]


_NEW = r"(?:new|newly|added|additional)"
_IS = r"[^.$]{0,40}? (?:is|are|will be) (?:approximately )?"


def notice_increment(raw_text: str, notice_type: str, total):
    """Value added by an enhancement/upgrade or amendment, with a note saying how it was found."""
    t = re.sub(r"\s+", " ", raw_text or "")
    if notice_type == "amendment":
        m = re.search(r"threshold (?:at|of) (?:approximately )?" + _M, t, re.I)
        if m and total:
            prior = _amt(*m.groups())
            return total - prior, f"Derived: {fmt_money(total)} notified total minus {fmt_money(prior)} prior case value"
        return None, (f"Increment not stated; notified total {fmt_money(total)}" if total else "Not stated")

    sec = _current_section(t)
    # 1. one overall figure for the new items ("total value of the new items is $25 million")
    m = re.search(r"(?:value|cost) of (?:the |these )?" + _NEW + r" (?:items|articles)(?: and services)?" + _IS + _M, sec, re.I)
    if m:
        return _amt(*m.groups()[-2:]), "Stated value of the added items"
    # 2. MDE and non-MDE given separately -> add them up
    mde = re.search(r"(?:value|cost) of (?:the |these )?" + _NEW + r" (?:Major Defense Equipment|MDE)\b(?! and)" + _IS + _M, sec, re.I)
    non = re.search(r"(?:value|cost) of (?:the |these )?" + _NEW + r" non-(?:Major Defense Equipment|MDE)\b" + _IS + _M, sec, re.I)
    if mde or non:
        parts = [_amt(*x.groups()[-2:]) for x in (mde, non) if x]
        note = "Stated value of the added items" + (" (MDE + non-MDE)" if len(parts) == 2 else "")
        return sum(parts), note
    # 3. other wordings, current paragraph first, then the whole text
    for scope in (sec, t):
        for pattern, kind, note in _RULES:
            matches = list(re.finditer(pattern, scope, re.I))
            if matches:
                g = matches[-1].groups()
                if kind == 1:
                    return _amt(g[0], g[1]), note
                return _amt(g[2], g[3]) - _amt(g[0], g[1]), note
    m = re.search(r".*(?:remained|remains|was) (?:at )?" + _M + r".*?(?:will|would) increase to (?:approximately )?" + _M, t, re.I)
    if m and _amt(m.group(3), m.group(4)) > _amt(m.group(1), m.group(2)):
        return _amt(m.group(3), m.group(4)) - _amt(m.group(1), m.group(2)), "Derived from stated old and new case values"
    if re.search(r"(does not|will not|did not|no) (?:result in (?:a|an) )?(?:net )?increase", t, re.I):
        return None, "Not stated; the text says the case value does not increase"
    return None, "Increment not stated in the text"


# --------------------------------------------------------------------------- load
TYPE_LABEL = {"new_sale": "New sale", "enhancement_upgrade": "Enhancement/upgrade",
              "amendment": "Amendment", "correction": "Correction", "other": "Other"}


def _short(s: str | None, n: int = 120) -> str:
    if not s:
        return "No description available"
    s = s.strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def load_notices(repo_dir: Path = DEFAULT_DIR) -> pd.DataFrame:
    rows = []
    for f in sorted((repo_dir / "data" / "fms" / "notices").glob("*/*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        ntype = d.get("notice_type") or "other"
        total = d.get("total_value_usd")
        if ntype in ("enhancement_upgrade", "amendment"):
            value, note = notice_increment(d.get("raw_text"), ntype, total)
        elif ntype == "new_sale":
            value, note = total, ("" if total else "Not stated")
        else:
            value, note = None, ""
        rows.append({
            "document_number": d.get("document_number"),
            "publication_date": d.get("publication_date"),
            "country": normalize_country(d.get("country")),
            "country_as_published": d.get("country"),
            "transmittal": (d.get("transmittal_number") or "").replace("RSAT ", "") or "—",
            "type": TYPE_LABEL.get(ntype, ntype),
            "description": _short(d.get("items_summary")),
            "value_usd": value,
            "value_note": note,
            "html_url": d.get("html_url"),
            "pdf_url": d.get("pdf_url"),
        })
    df = pd.DataFrame(rows)
    df["publication_date"] = pd.to_datetime(df["publication_date"])
    df["value_usd"] = pd.to_numeric(df["value_usd"], errors="coerce")
    return df.sort_values(["publication_date", "document_number"], ascending=[False, True]).reset_index(drop=True)
