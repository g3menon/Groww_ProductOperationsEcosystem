"""
Phase 4: Rebuild the RAG chunk index and structured MF metrics index.

Hybrid scraping strategy:
  - SOURCE 1 (AMFI): plain-text NAVAll.txt over HTTPS for nav / nav_date / scheme_code
    (no browser needed).
  - SOURCE 2 (Groww): Playwright + headless Chromium for everything else
    (AUM, expense ratio, returns, holdings, fund managers, advanced ratios, etc).
    Groww fund pages are React SPAs — static HTTP HTML returns empty shells, so
    Playwright is mandatory for these fields.

Outputs (preserved for backend compatibility):
  - backend/app/rag/index/mf_metrics.json — list of MFFundMetrics-shaped records
    (validated against app.schemas.rag.MFFundMetrics so the existing
    metrics_store can load it without code changes).
  - backend/app/rag/index/chunks.json — list of DocumentChunk-shaped records
    so app.rag.retrieve can search them via BM25 + Gemini embeddings.

Usage:
  python scripts/rebuild_index.py
      Fixture-only (no network). Loads the bundled fixture metrics + corpus.

  python scripts/rebuild_index.py --use-fixture
      Same as default (explicit).

  python scripts/rebuild_index.py --scrape
      Fetch AMFI + Playwright scrape all 6 Groww fund pages.

  SKIP_PLAYWRIGHT_MF=true python scripts/rebuild_index.py --scrape
      AMFI only (skip the Playwright pass entirely; useful for diagnosing AMFI
      issues, or for environments without Chromium).

  python scripts/rebuild_index.py --scrape --embed
      Scrape + generate Gemini embeddings (requires GEMINI_API_KEY).

Deployment notes:
  - Dockerfile already installs Chromium and `playwright install chromium`.
  - The launch args below ('--no-sandbox --disable-dev-shm-usage --disable-gpu')
    are required for Railway / Docker compatibility.
  - This script is invoked at container startup or via cron, NOT on every
    request.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import random
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("rebuild_index")
logging.basicConfig(level=logging.INFO, format="%(message)s")


# ---------------------------------------------------------------------------
# Hardcoded fund URLs (per product spec — do NOT construct from names).
# ---------------------------------------------------------------------------

FUND_URLS: list[str] = [
    "https://groww.in/mutual-funds/motilal-oswal-most-focused-midcap-30-fund-direct-growth",
    "https://groww.in/mutual-funds/motilal-oswal-most-focused-multicap-35-fund-direct-growth",
    "https://groww.in/mutual-funds/motilal-oswal-nifty-midcap-150-index-fund-direct-growth",
    "https://groww.in/mutual-funds/hdfc-large-and-mid-cap-fund-direct-growth",
    "https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth",
    "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
]

AMFI_NAV_URL = "https://www.amfiindia.com/spages/NAVAll.txt"

PAGE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

PLAYWRIGHT_LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
]

# Substring tokens (lowercase) used to match AMFI scheme names per fund slug.
# AMFI scheme names sometimes diverge from Groww URL slugs (e.g. Motilal
# "Multicap 35" was renamed to "Flexi Cap"; HDFC "Equity Fund" is now
# legally "HDFC Flexi Cap Fund"). Hints don't include "growth" because some
# AMFI growth schemes omit it from the name (e.g. "Motilal Oswal Nifty Midcap
# 150 Index Fund - Direct Plan"); IDCW/Dividend variants are filtered out
# explicitly by the matcher below.
_AMFI_NAME_HINTS: dict[str, tuple[tuple[str, ...], ...]] = {
    "motilal-oswal-most-focused-midcap-30-fund-direct-growth": (
        ("motilal oswal", "midcap", "direct"),
        ("motilal oswal", "mid cap", "direct"),
    ),
    "motilal-oswal-most-focused-multicap-35-fund-direct-growth": (
        ("motilal oswal", "flexi", "direct"),
        ("motilal oswal", "multicap", "direct"),
        ("motilal oswal", "multi cap", "direct"),
    ),
    "motilal-oswal-nifty-midcap-150-index-fund-direct-growth": (
        ("motilal oswal", "nifty midcap 150", "index", "direct"),
        ("motilal oswal", "midcap 150", "index", "direct"),
        ("motilal oswal", "mid cap 150", "index", "direct"),
    ),
    "hdfc-large-and-mid-cap-fund-direct-growth": (
        ("hdfc", "large and mid", "direct"),
        ("hdfc", "large & mid", "direct"),
    ),
    "hdfc-equity-fund-direct-growth": (
        ("hdfc", "flexi cap", "direct"),
        ("hdfc", "equity fund", "direct"),
    ),
    "hdfc-large-cap-fund-direct-growth": (
        ("hdfc", "large cap", "direct"),
        ("hdfc", "top 100", "direct"),
    ),
}

# Substrings that disqualify a scheme name from being a "growth (default)"
# variant. Applied unconditionally — if any of these appears, we never match.
_AMFI_DISQUALIFIERS: tuple[str, ...] = (
    "idcw",
    "dividend",
    "payout",
    "reinvest",
    "bonus",
)


# ---------------------------------------------------------------------------
# Path helpers + manifest loader (preserves existing function signatures so
# nothing imported by other modules breaks).
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _ensure_imports() -> None:
    """Make ``backend/`` importable for opt-in ``app.*`` imports (embed path)."""
    backend = _repo_root() / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))


_MANIFEST_PATH = _repo_root() / "scripts" / "sources_manifest.json"
_FIXTURE_CORPUS_PATH = _repo_root() / "backend" / "app" / "rag" / "fixtures" / "mf_corpus.json"
_FIXTURE_METRICS_PATH = _repo_root() / "backend" / "app" / "rag" / "fixtures" / "mf_metrics.json"
_INDEX_DIR = _repo_root() / "backend" / "app" / "rag" / "index"
_CHUNKS_PATH = _INDEX_DIR / "chunks.json"
_METRICS_PATH = _INDEX_DIR / "mf_metrics.json"


def _load_manifest() -> list[dict]:
    if not _MANIFEST_PATH.exists():
        raise SystemExit(f"sources_manifest.json not found at {_MANIFEST_PATH}")
    raw = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    return raw


def _slug_from_url(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1].lower()


def _manifest_for(url: str, manifest: list[dict]) -> dict:
    """Return the manifest entry for ``url`` (matches doc_id + title back to
    sources_manifest.json so backend lookups by doc_id remain stable)."""
    for entry in manifest:
        if entry.get("url") == url:
            return entry
    slug = _slug_from_url(url)
    return {
        "doc_id": slug,
        "url": url,
        "title": _title_from_slug(slug),
        "doc_type": "mutual_fund_page",
    }


def _title_from_slug(slug: str) -> str:
    parts = [p for p in slug.split("-") if p]
    return " ".join(p.capitalize() for p in parts)


# ---------------------------------------------------------------------------
# AMFI flat-file source — plain HTTPS, no browser.
# ---------------------------------------------------------------------------


def fetch_amfi_text(timeout: float = 20.0) -> str:
    """Fetch the AMFI NAVAll.txt report. Synchronous urllib (stdlib only)."""
    req = urllib.request.Request(
        AMFI_NAV_URL,
        headers={
            "User-Agent": PAGE_USER_AGENT,
            "Accept": "text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="replace")


def parse_amfi_text(text: str) -> list[dict]:
    """Parse AMFI semicolon-delimited rows. Fields per line:
        0=scheme_code, 1=isin_div_payout, 2=isin_div_reinvest,
        3=scheme_name, 4=nav, 5=nav_date.
    """
    rows: list[dict] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or ";" not in line or line.lower().startswith("scheme code"):
            continue
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 6:
            continue
        scheme_code = parts[0]
        scheme_name = parts[3]
        nav = _parse_float(parts[4])
        nav_date = _parse_amfi_date(parts[5])
        if not scheme_code or not scheme_name or nav is None or nav_date is None:
            continue
        rows.append(
            {
                "scheme_code": scheme_code,
                "scheme_name": scheme_name,
                "nav": nav,
                "nav_date": nav_date,
            }
        )
    return rows


def match_amfi_for_fund(slug: str, amfi_rows: list[dict]) -> dict | None:
    """Best-effort substring match against AMFI scheme names for one slug.

    Strategy: try each hint group in order; for each group return the
    shortest scheme name that contains every hint, isn't an IDCW/Dividend
    variant, and respects the direct/regular distinction.
    """
    hint_groups = _AMFI_NAME_HINTS.get(slug)
    if not hint_groups:
        return None
    for group in hint_groups:
        best: dict | None = None
        best_score = float("inf")  # prefer shortest matching scheme name
        for row in amfi_rows:
            name_lower = row["scheme_name"].lower()
            if not all(h in name_lower for h in group):
                continue
            if any(d in name_lower for d in _AMFI_DISQUALIFIERS):
                continue
            if "direct" in group and "regular" in name_lower:
                continue
            if "regular" in group and "direct" in name_lower:
                continue
            score = len(name_lower)
            if score < best_score:
                best_score = score
                best = row
        if best is not None:
            return best
    return None


# ---------------------------------------------------------------------------
# Playwright scrape — Groww fund page extraction.
# ---------------------------------------------------------------------------


async def scrape_fund(url: str) -> dict:
    """Scrape a Groww fund page with Playwright, return all extracted fields.

    Each call launches its own browser to keep failures isolated. The launch
    args are required for Railway / Docker compatibility.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=PLAYWRIGHT_LAUNCH_ARGS)
        try:
            context = await browser.new_context(
                user_agent=PAGE_USER_AGENT,
                extra_http_headers={"Referer": "https://groww.in/"},
            )
            page = await context.new_page()
            page.set_default_timeout(30000)
            await page.goto(url, wait_until="networkidle")
            await page.wait_for_selector("h1", timeout=15000)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            await asyncio.sleep(2)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)
            # Some pages defer the holdings table until a third scroll.
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1)
            data = await extract_all_fields(page, url)
        finally:
            await browser.close()
    return data


async def extract_all_fields(page: Any, url: str) -> dict:
    """Run every extractor against ``page`` and aggregate the results.

    Each individual extractor is wrapped in its own try/except so a single
    selector miss never aborts the whole page.
    """
    out: dict[str, Any] = {"source_url": url}

    out["scheme_name"] = (
        await _safe_inner_text(page, "h1")
        or await _safe_inner_text(page, "h1.contentPrimary")
    )

    out.update(await _extract_min_investments(page))
    out["returns"] = await _extract_returns_block(page)
    out["rankings"] = await _extract_returns_and_rankings(page)
    out["calculator_returns"] = await _extract_calculator_returns(page)
    out["holdings"] = await _extract_holdings(page)
    out["fund_managers"] = await _extract_fund_managers(page)
    out.update(await _extract_fund_details(page))
    out["fund_house"] = (
        await _safe_inner_text(page, "a.fundHouse_link__7hVTZ")
        or await _safe_inner_text(page, "div.fundHouse_fundHouseHeader__PQmyq a")
    )
    out["advanced_ratios"] = await _extract_advanced_ratios(page)
    out["exit_load"] = await _extract_exit_load(page)
    return out


async def _safe_inner_text(page: Any, selector: str) -> str | None:
    try:
        el = await page.query_selector(selector)
        if el is None:
            return None
        txt = await el.inner_text()
        txt = (txt or "").strip()
        return txt or None
    except Exception:
        return None


async def _extract_min_investments(page: Any) -> dict:
    out: dict[str, Any] = {"min_sip": None, "min_lumpsum": None}
    try:
        el = await page.query_selector('div[class*="minInvestments"]')
        if el is None:
            return out
        text = (await el.inner_text()) or ""
    except Exception:
        return out
    out["min_sip"] = _amount_for_label(text, ("SIP",))
    out["min_lumpsum"] = _amount_for_label(text, ("One Time", "Lumpsum", "Lump Sum"))
    return out


async def _extract_returns_block(page: Any) -> dict[str, str]:
    """Read the small "1D / 1Y / 3Y / 5Y / All" returns strip near the top."""
    out: dict[str, str] = {}
    try:
        container = await page.query_selector("div.returnStats_returnStatsContainer__1eiLp")
        if container is None:
            return out
        text = (await container.inner_text()) or ""
    except Exception:
        return out
    # Lines tend to alternate: "1D\n+0.45%\n1Y\n18.50%\n..." or be space-joined.
    pattern = re.compile(
        r"(1D|1W|1M|3M|6M|YTD|1Y|2Y|3Y|5Y|10Y|All\s*Time|All)\s*[:\-]?\s*"
        r"(-?\+?[\d.,]+\s*%)",
        re.IGNORECASE,
    )
    for label, value in pattern.findall(text):
        key = _normalize_period_key(label)
        if key:
            out.setdefault(key, _normalize_pct(value))
    return out


async def _extract_returns_and_rankings(page: Any) -> dict:
    """Read the returns-vs-category-vs-rank table."""
    out: dict[str, dict[str, str]] = {"3y": {}, "5y": {}, "10y": {}}
    try:
        container = await page.query_selector('div[class*="returnsAndRankings"]')
        if container is None:
            return {}
        text = (await container.inner_text()) or ""
    except Exception:
        return {}
    pattern = re.compile(
        r"(3Y|5Y|10Y)\s*[:\-]?\s*(-?\+?[\d.,]+\s*%)?\s*"
        r"(?:Category(?:\s*Avg(?:erage)?)?\s*[:\-]?\s*(-?\+?[\d.,]+\s*%))?\s*"
        r"(?:Rank\s*[:\-]?\s*(\d+)\s*(?:of|/)\s*(\d+))?",
        re.IGNORECASE,
    )
    for m in pattern.finditer(text):
        label, fund_ret, cat_ret, rank, total = m.groups()
        key = label.lower()
        bucket = out.setdefault(key, {})
        if fund_ret:
            bucket["fund_return"] = _normalize_pct(fund_ret)
        if cat_ret:
            bucket["category_average"] = _normalize_pct(cat_ret)
        if rank and total:
            bucket["rank"] = f"{rank}/{total}"
    return {k: v for k, v in out.items() if v}


async def _extract_calculator_returns(page: Any) -> dict[str, str]:
    """Read the default 1Y / 3Y / 5Y / 10Y values from the return calculator."""
    out: dict[str, str] = {}
    try:
        container = await page.query_selector("div.returnCalculator_calculatorContainer__HYJfu")
        if container is None:
            return out
    except Exception:
        return out
    for period in ("1Y", "3Y", "5Y", "10Y"):
        try:
            tab = await page.query_selector(
                f"div.returnCalculator_calculatorContainer__HYJfu :text('{period}')"
            )
            if tab is not None:
                try:
                    await tab.click(timeout=2000)
                    await asyncio.sleep(0.4)
                except Exception:
                    pass
            final_el = await page.query_selector(
                "div.returnCalculator_finalReturns___jz0X"
            )
            if final_el is not None:
                value = (await final_el.inner_text()) or ""
                value = value.strip()
                if value:
                    out[period.lower()] = value
        except Exception:
            continue
    return out


async def _extract_holdings(page: Any) -> list[dict]:
    """Click "See All" then read every row out of the holdings table."""
    holdings: list[dict] = []
    try:
        see_all = await page.query_selector(".holdings_seeAll__4Ge0V")
        if see_all is not None:
            try:
                await see_all.click(timeout=3000)
                await asyncio.sleep(1.5)
            except Exception:
                pass
    except Exception:
        pass

    try:
        rows = await page.query_selector_all(
            "div.holdings_tableContainer__YOQk1 div.holdings_tableRow__VDNCp, "
            "div[class*='holdings_table'] div[class*='holdings_tableRow'], "
            "div[class*='holdings'] div[class*='_tableRow']"
        )
    except Exception:
        rows = []

    if not rows:
        try:
            name_cells = await page.query_selector_all(".holdings_companyName__tGJbM")
            for el in name_cells:
                name = ((await el.inner_text()) or "").strip()
                if name:
                    holdings.append({"name": name, "sector": None, "instrument": None, "weight": None})
            return holdings
        except Exception:
            return holdings

    for row in rows:
        try:
            row_text = (await row.inner_text()) or ""
        except Exception:
            continue
        cells = [c.strip() for c in row_text.split("\n") if c.strip()]
        if not cells:
            continue
        if any(h.lower() in cells[0].lower() for h in ("Company", "Name", "Sector")) and len(cells) <= 5:
            # Likely the header row leaked through.
            continue
        weight = None
        instrument = None
        sector = None
        name = cells[0]
        for cell in cells[1:]:
            if "%" in cell and weight is None:
                weight = _normalize_pct(cell)
                continue
            if instrument is None and any(
                k in cell.lower() for k in ("equity", "debt", "bond", "cash", "treps", "reverse repo")
            ):
                instrument = cell
                continue
            if sector is None:
                sector = cell
        holdings.append(
            {
                "name": name,
                "sector": sector,
                "instrument": instrument,
                "weight": weight,
            }
        )
    return holdings


async def _extract_fund_managers(page: Any) -> list[dict]:
    out: list[dict] = []
    try:
        items = await page.query_selector_all(
            "div.fundManagement_fundsContainer__obk7F div.fundManagement_fundItem__AP5DD"
        )
    except Exception:
        items = []
    for item in items:
        try:
            block_text = (await item.inner_text()) or ""
            link = await item.query_selector(".fundManagement_fundLink__mbkuy")
            name = ((await link.inner_text()) if link else "").strip() or None
        except Exception:
            continue
        if not name:
            # Fall back to first line of the block.
            first = block_text.strip().splitlines()[0:1]
            name = first[0].strip() if first else None
        if not name:
            continue
        tenure = _regex_first(
            block_text,
            r"(?:Since|Tenure|Managing\s+since)[:\s-]*([0-9A-Za-z,\s\.\-]+?)(?:\n|$)",
        )
        education = _regex_first(
            block_text,
            r"Education[:\s-]*([^\n]+)",
        )
        experience = _regex_first(
            block_text,
            r"(?:Experience|Years\s+of\s+experience)[:\s-]*([^\n]+)",
        )
        also_manages_match = re.search(
            r"Also\s+manages[:\s-]*([^\n]+)", block_text, flags=re.IGNORECASE
        )
        also_manages: list[str] = []
        if also_manages_match:
            also_manages = [
                s.strip()
                for s in re.split(r",|;|\u2022", also_manages_match.group(1))
                if s.strip()
            ]
        out.append(
            {
                "name": name,
                "tenure": tenure,
                "education": education,
                "experience": experience,
                "also_manages": also_manages,
            }
        )
    return out


async def _extract_fund_details(page: Any) -> dict:
    """AUM / expense ratio / rating / risk / category / benchmark."""
    out: dict[str, Any] = {
        "aum": None,
        "expense_ratio": None,
        "rating": None,
        "risk_level": None,
        "category": None,
        "sub_category": None,
        "benchmark": None,
    }
    try:
        text = await page.inner_text("div.fundDetails_fundDetailsContainer__Lj8nM")
    except Exception:
        text = ""
    if not text:
        return out
    aum = _regex_first(text, r"AUM[^₹\d]*₹?\s*([\d,]+\.?\d*\s*(?:Cr|Crore|cr|crore|L|Lakh))")
    if aum:
        out["aum"] = aum.replace("Crore", "Cr").strip()
    out["expense_ratio"] = _regex_first(text, r"Expense\s*Ratio[^\d]*([\d.]+\s*%)")
    out["rating"] = _regex_first(text, r"Rating[^\d]*([\d.]+\s*(?:Star|stars?)?)")
    out["risk_level"] = _regex_first(text, r"Risk[^\n]*?([Vv]ery\s+High|High|Moderately\s+High|Moderate|Low\s+to\s+Moderate|Low)")
    out["category"] = _regex_first(text, r"Category[:\s\-]*([A-Za-z &\-]+?)(?:\n|Sub|Risk|$)")
    out["sub_category"] = _regex_first(text, r"Sub\s*Category[:\s\-]*([A-Za-z &\-]+?)(?:\n|$)")
    out["benchmark"] = _regex_first(text, r"Benchmark[:\s\-]*([^\n]+)")
    return out


async def _extract_advanced_ratios(page: Any) -> dict[str, str]:
    """Expand any collapsed accordion sections, then regex out the ratios."""
    try:
        accordions = await page.query_selector_all('div[class*="ac11"]')
    except Exception:
        accordions = []
    for acc in accordions:
        try:
            title_el = await acc.query_selector("div.ac11Title")
            title = ((await title_el.inner_text()) if title_el else "").lower()
            if not title or not any(k in title for k in ("risk", "advanced", "ratio")):
                continue
            icon = await acc.query_selector("div.ac11Icon")
            if icon is not None:
                try:
                    await icon.click(timeout=2000)
                    await asyncio.sleep(0.5)
                except Exception:
                    pass
        except Exception:
            continue

    text_blob = ""
    for acc in accordions:
        try:
            text_blob += "\n" + ((await acc.inner_text()) or "")
        except Exception:
            continue

    ratios: dict[str, str] = {}
    label_patterns: list[tuple[str, str]] = [
        ("alpha", r"Alpha[^\d-]*(-?[\d.]+)"),
        ("beta", r"Beta[^\d-]*(-?[\d.]+)"),
        ("sharpe", r"Sharpe[^\d-]*(-?[\d.]+)"),
        ("sortino", r"Sortino[^\d-]*(-?[\d.]+)"),
        ("standard_deviation", r"Standard\s*Deviation[^\d-]*(-?[\d.]+)"),
    ]
    for key, pat in label_patterns:
        m = re.search(pat, text_blob, flags=re.IGNORECASE)
        if m:
            ratios[key] = m.group(1)
    return ratios


async def _extract_exit_load(page: Any) -> str | None:
    try:
        text = await page.inner_text("div.exitLoadStampDutyTax_container")
    except Exception:
        return None
    if not text:
        return None
    return text.strip() or None


# ---------------------------------------------------------------------------
# Field parsing helpers.
# ---------------------------------------------------------------------------


def _amount_for_label(text: str, labels: tuple[str, ...]) -> str | None:
    """Return the first ₹-amount that follows any of ``labels`` in ``text``."""
    for label in labels:
        pat = re.compile(
            rf"{re.escape(label)}\s*[:\-]?\s*₹?\s*([\d,]+(?:\.\d+)?)",
            re.IGNORECASE,
        )
        m = pat.search(text)
        if m:
            return f"₹{m.group(1)}"
    return None


def _regex_first(text: str, pattern: str) -> str | None:
    if not text:
        return None
    m = re.search(pattern, text, flags=re.IGNORECASE)
    if not m:
        return None
    return m.group(1).strip()


def _normalize_pct(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = raw.replace(",", "").replace("+", "").strip()
    if not cleaned.endswith("%"):
        cleaned = cleaned + "%"
    return cleaned


_PERIOD_KEY_MAP = {
    "1d": "1d",
    "1w": "1w",
    "1m": "1m",
    "3m": "3m",
    "6m": "6m",
    "ytd": "ytd",
    "1y": "1y",
    "2y": "2y",
    "3y": "3y",
    "5y": "5y",
    "10y": "10y",
    "alltime": "all_time",
    "all": "all_time",
}


def _normalize_period_key(label: str) -> str | None:
    return _PERIOD_KEY_MAP.get(label.replace(" ", "").lower())


def _parse_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    s = str(raw).replace(",", "").replace("%", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_amfi_date(raw: str) -> str | None:
    s = (raw or "").strip()
    for fmt in ("%d-%b-%Y", "%d-%b-%y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_aum_to_cr(value: str | None) -> float | None:
    if not value:
        return None
    raw = value.replace("₹", "").replace(",", "").strip()
    m = re.match(r"([\d.]+)\s*(Cr|Crore|L|Lakh)?", raw, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        n = float(m.group(1))
    except ValueError:
        return None
    unit = (m.group(2) or "").lower()
    if unit in ("l", "lakh"):
        return round(n / 100.0, 2)  # 100 L == 1 Cr
    return n


def _parse_pct_to_float(value: str | None) -> float | None:
    if not value:
        return None
    return _parse_float(value.replace("%", ""))


def _parse_money_to_float(value: str | None) -> float | None:
    if not value:
        return None
    return _parse_float(value.replace("₹", ""))


def _parse_exit_load(text: str | None) -> tuple[float | None, int | None]:
    """Return (exit_load_pct, exit_load_window_days) parsed from the raw text."""
    if not text:
        return None, None
    pct = None
    days = None
    m = re.search(r"([\d.]+)\s*%", text)
    if m:
        pct = _parse_float(m.group(1))
    m = re.search(r"within\s+(\d+)\s+(day|days|month|months|year|years)", text, flags=re.IGNORECASE)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith("month"):
            days = n * 30
        elif unit.startswith("year"):
            days = n * 365
        else:
            days = n
    return pct, days


# ---------------------------------------------------------------------------
# Mapping from spec-shaped scrape dict → MFFundMetrics-shaped dict
# (the existing backend reader expects a list of these).
# ---------------------------------------------------------------------------


def _to_metrics_record(
    *,
    scraped: dict,
    amfi: dict | None,
    manifest_entry: dict,
    today: str,
    scraped_at: str,
) -> dict:
    """Build a record matching app.schemas.rag.MFFundMetrics."""
    url: str = manifest_entry["url"]
    doc_id: str = manifest_entry["doc_id"]
    title: str = manifest_entry["title"]
    fund_name = scraped.get("scheme_name") or title

    returns_raw = scraped.get("returns") or {}
    returns_obj = {
        "one_month": _parse_pct_to_float(returns_raw.get("1m")),
        "three_month": _parse_pct_to_float(returns_raw.get("3m")),
        "six_month": _parse_pct_to_float(returns_raw.get("6m")),
        "one_year": _parse_pct_to_float(returns_raw.get("1y")),
        "three_year": _parse_pct_to_float(returns_raw.get("3y")),
        "five_year": _parse_pct_to_float(returns_raw.get("5y")),
        "ten_year": _parse_pct_to_float(returns_raw.get("10y")),
        "all_time": _parse_pct_to_float(returns_raw.get("all_time")),
        "since_inception": None,
    }
    has_returns = any(v is not None for v in returns_obj.values())

    rankings_raw = scraped.get("rankings") or {}
    fund_returns: dict[str, float] = {}
    category_avg: dict[str, float] = {}
    rank: dict[str, int] = {}
    for period, payload in rankings_raw.items():
        if not isinstance(payload, dict):
            continue
        fr = _parse_pct_to_float(payload.get("fund_return"))
        if fr is not None:
            fund_returns[period] = fr
        ca = _parse_pct_to_float(payload.get("category_average"))
        if ca is not None:
            category_avg[period] = ca
        if "/" in (payload.get("rank") or ""):
            try:
                rank[period] = int(payload["rank"].split("/", 1)[0])
            except (ValueError, AttributeError):
                pass

    holdings: list[dict] = []
    for h in scraped.get("holdings") or []:
        name = (h.get("name") or "").strip()
        if not name:
            continue
        holdings.append(
            {
                "name": name,
                "weight_pct": _parse_pct_to_float(h.get("weight")),
                "sector": h.get("sector"),
                "instrument": h.get("instrument"),
            }
        )

    fund_managers: list[dict] = []
    for fm in scraped.get("fund_managers") or []:
        name = (fm.get("name") or "").strip()
        if not name:
            continue
        fund_managers.append(
            {
                "name": name,
                "tenure": fm.get("tenure"),
                "education": fm.get("education"),
                "experience": fm.get("experience"),
                "also_manages": list(fm.get("also_manages") or []),
            }
        )

    advanced_ratios_raw = scraped.get("advanced_ratios") or {}
    advanced_ratios: dict[str, float] = {}
    for k, v in advanced_ratios_raw.items():
        f = _parse_float(v)
        if f is not None:
            advanced_ratios[k] = f

    exit_load_text = scraped.get("exit_load")
    exit_pct, exit_days = _parse_exit_load(exit_load_text)

    record = {
        "doc_id": doc_id,
        "fund_name": fund_name,
        "amc": _infer_amc(fund_name),
        "category": scraped.get("category"),
        "sub_category": scraped.get("sub_category"),
        "plan": "Direct" if "direct" in url.lower() else None,
        "option": "Growth" if "growth" in url.lower() else None,
        "nav": (amfi or {}).get("nav"),
        "nav_date": (amfi or {}).get("nav_date"),
        "nav_source_url": AMFI_NAV_URL if amfi else None,
        "aum_cr": _parse_aum_to_cr(scraped.get("aum")),
        "expense_ratio_pct": _parse_pct_to_float(scraped.get("expense_ratio")),
        "exit_load_pct": exit_pct,
        "exit_load_window_days": exit_days,
        "exit_load_description": exit_load_text,
        "risk_level": scraped.get("risk_level"),
        "rating": scraped.get("rating"),
        "benchmark": scraped.get("benchmark"),
        "min_sip_amount": _parse_money_to_float(scraped.get("min_sip")),
        "min_lumpsum_amount": _parse_money_to_float(scraped.get("min_lumpsum")),
        "returns": returns_obj if has_returns else None,
        "investment_returns": [],
        "returns_and_rankings": (
            {
                "fund_returns": fund_returns,
                "category_average": category_avg,
                "rank": rank,
            }
            if (fund_returns or category_avg or rank)
            else None
        ),
        "top_holdings": holdings,
        "advanced_ratios": advanced_ratios,
        "fund_managers": fund_managers,
        "sector_allocation": [],
        "asset_allocation": {},
        "fund_objective": None,
        "source_url": url,
        "scraped_at": scraped_at,
        "last_checked": today,
        # Convenience extras for downstream consumers (ignored by MFFundMetrics
        # validation since pydantic ignores unknown fields by default in v2
        # only when extra='ignore', which is the default for our schema).
        "scheme_code": (amfi or {}).get("scheme_code"),
        "fund_house": scraped.get("fund_house"),
        "calculator_returns": scraped.get("calculator_returns") or {},
    }
    return record


def _infer_amc(fund_name: str | None) -> str | None:
    if not fund_name:
        return None
    lower = fund_name.lower()
    for hint, amc in (
        ("motilal oswal", "Motilal Oswal AMC"),
        ("hdfc", "HDFC AMC"),
        ("sbi", "SBI Funds Management"),
        ("icici prudential", "ICICI Prudential AMC"),
        ("axis", "Axis AMC"),
        ("kotak", "Kotak Mahindra AMC"),
        ("mirae asset", "Mirae Asset Investment Managers"),
        ("nippon", "Nippon India AMC"),
        ("dsp", "DSP Investment Managers"),
        ("aditya birla", "Aditya Birla Sun Life AMC"),
        ("uti", "UTI AMC"),
        ("franklin", "Franklin Templeton"),
        ("tata", "Tata Asset Management"),
        ("invesco", "Invesco Asset Management"),
        ("quant", "Quant Money Managers"),
        ("parag parikh", "PPFAS Mutual Fund"),
    ):
        if hint in lower:
            return amc
    return None


# ---------------------------------------------------------------------------
# Scrape orchestration (sequential + jittered + try/except per fund).
# ---------------------------------------------------------------------------


async def scrape_all_funds(manifest: list[dict]) -> tuple[list[dict], dict[str, dict]]:
    """Run AMFI fetch + Playwright pass over every URL in FUND_URLS.

    Returns:
        (records_by_url, scraped_raw_by_url)
        ``records_by_url``: list of MFFundMetrics-shaped dicts
        ``scraped_raw_by_url``: spec-shaped raw dicts (used to author chunks)
    """
    today = date.today().isoformat()
    scraped_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"\n[amfi] Fetching AMFI NAV report from {AMFI_NAV_URL}")
    try:
        amfi_text = fetch_amfi_text()
        amfi_rows = parse_amfi_text(amfi_text)
        print(f"  OK    parsed {len(amfi_rows):,} AMFI scheme rows")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        print(f"  ERROR AMFI fetch failed: {exc} — proceeding with empty NAV map")
        amfi_rows = []

    skip_pw = os.getenv("SKIP_PLAYWRIGHT_MF", "").lower() in ("1", "true", "yes")
    if skip_pw:
        print("\n[playwright] SKIP_PLAYWRIGHT_MF=true — skipping Groww browser scrape.")

    records: list[dict] = []
    raw_by_url: dict[str, dict] = {}

    for idx, url in enumerate(FUND_URLS):
        slug = _slug_from_url(url)
        manifest_entry = _manifest_for(url, manifest)
        amfi_match = match_amfi_for_fund(slug, amfi_rows) if amfi_rows else None

        if amfi_match:
            print(
                f"\n[fund {idx+1}/{len(FUND_URLS)}] {manifest_entry['doc_id']} | "
                f"AMFI matched: {amfi_match['scheme_name']} | NAV {amfi_match['nav']} "
                f"({amfi_match['nav_date']})"
            )
        else:
            print(f"\n[fund {idx+1}/{len(FUND_URLS)}] {manifest_entry['doc_id']} | AMFI: no match")

        scraped_dict: dict = {}
        if not skip_pw:
            try:
                scraped_dict = await scrape_fund(url)
                print(
                    f"  PLAY  scheme_name={scraped_dict.get('scheme_name')!r} "
                    f"holdings={len(scraped_dict.get('holdings') or [])}"
                )
            except Exception as exc:
                print(f"  ERROR Playwright scrape failed for {url}: {exc!r}")
                scraped_dict = {}

        scraped_dict.setdefault("source_url", url)
        raw_by_url[url] = scraped_dict

        try:
            record = _to_metrics_record(
                scraped=scraped_dict,
                amfi=amfi_match,
                manifest_entry=manifest_entry,
                today=today,
                scraped_at=scraped_at,
            )
            records.append(record)
        except Exception as exc:
            print(f"  ERROR Failed to build metrics record for {url}: {exc!r}")

        if idx < len(FUND_URLS) - 1 and not skip_pw:
            jitter = random.uniform(1.5, 2.5)
            await asyncio.sleep(jitter)

    return records, raw_by_url


# ---------------------------------------------------------------------------
# Chunk authoring (DocumentChunk-shaped dicts).
# ---------------------------------------------------------------------------


def _chunk_id(doc_id: str, section: str) -> str:
    h = hashlib.sha256(f"{doc_id}:{section}".encode("utf-8")).hexdigest()[:12].upper()
    return f"CHK-{h}"


def _format_returns_prose(returns: dict[str, float] | None) -> str:
    if not returns:
        return ""
    parts = []
    label_map = [
        ("one_year", "1Y"),
        ("three_year", "3Y"),
        ("five_year", "5Y"),
        ("ten_year", "10Y"),
        ("all_time", "All-time"),
    ]
    for key, label in label_map:
        v = returns.get(key)
        if v is not None:
            parts.append(f"{label}: {v}%")
    return ", ".join(parts)


def _build_chunks_for_record(record: dict) -> list[dict]:
    """Author one DocumentChunk-shaped dict per non-empty section of a fund."""
    doc_id = record["doc_id"]
    title = record.get("fund_name") or doc_id
    url = record["source_url"]
    last_checked = record.get("last_checked") or date.today().isoformat()
    common = {
        "doc_id": doc_id,
        "source_url": url,
        "title": title,
        "doc_type": "mutual_fund_page",
        "last_checked": last_checked,
        "embedding": None,
        "rating": None,
        "review_date": None,
        "app_version": None,
        "found_review_helpful": None,
    }
    chunks: list[dict] = []
    chunk_index = 0

    overview_lines: list[str] = [f"{title}."]
    if record.get("nav") is not None:
        nav_date = record.get("nav_date") or "n/a"
        overview_lines.append(f"NAV: ₹{record['nav']} as of {nav_date}.")
    if record.get("aum_cr") is not None:
        overview_lines.append(f"AUM: ₹{record['aum_cr']} Cr.")
    if record.get("expense_ratio_pct") is not None:
        overview_lines.append(f"Expense ratio: {record['expense_ratio_pct']}%.")
    if record.get("min_sip_amount") is not None:
        overview_lines.append(f"Min SIP: ₹{int(record['min_sip_amount'])}.")
    if record.get("min_lumpsum_amount") is not None:
        overview_lines.append(f"Min lumpsum: ₹{int(record['min_lumpsum_amount'])}.")
    if record.get("rating"):
        overview_lines.append(f"Rating: {record['rating']}.")
    if record.get("fund_house"):
        overview_lines.append(f"Fund house: {record['fund_house']}.")
    if record.get("category"):
        overview_lines.append(f"Category: {record['category']}.")
    if record.get("risk_level"):
        overview_lines.append(f"Risk level: {record['risk_level']}.")
    returns_prose = _format_returns_prose(record.get("returns"))
    if returns_prose:
        overview_lines.append(f"Returns — {returns_prose}.")
    if len(overview_lines) > 1:
        chunks.append(
            {
                **common,
                "chunk_id": _chunk_id(doc_id, f"overview-{chunk_index}"),
                "content": " ".join(overview_lines),
                "chunk_index": chunk_index,
            }
        )
        chunk_index += 1

    holdings = record.get("top_holdings") or []
    if holdings:
        lines = [f"{title} — Top holdings as of {last_checked}:"]
        for h in holdings[:50]:
            piece = h.get("name") or ""
            extras = []
            if h.get("sector"):
                extras.append(h["sector"])
            if h.get("instrument"):
                extras.append(h["instrument"])
            if h.get("weight_pct") is not None:
                extras.append(f"{h['weight_pct']}%")
            if extras:
                piece += f" ({', '.join(extras)})"
            lines.append(piece + ".")
        chunks.append(
            {
                **common,
                "chunk_id": _chunk_id(doc_id, f"holdings-{chunk_index}"),
                "content": " ".join(lines),
                "chunk_index": chunk_index,
            }
        )
        chunk_index += 1

    managers = record.get("fund_managers") or []
    if managers:
        lines = [f"{title} — Fund managers:"]
        for m in managers:
            piece = m.get("name") or ""
            tenure = m.get("tenure")
            experience = m.get("experience")
            education = m.get("education")
            details = []
            if tenure:
                details.append(f"tenure {tenure}")
            if experience:
                details.append(f"experience {experience}")
            if education:
                details.append(f"education {education}")
            if m.get("also_manages"):
                details.append(f"also manages {', '.join(m['also_manages'])}")
            if details:
                piece += " — " + "; ".join(details)
            lines.append(piece + ".")
        chunks.append(
            {
                **common,
                "chunk_id": _chunk_id(doc_id, f"managers-{chunk_index}"),
                "content": " ".join(lines),
                "chunk_index": chunk_index,
            }
        )
        chunk_index += 1

    ratios = record.get("advanced_ratios") or {}
    if ratios:
        ratio_pairs = ", ".join(f"{k} {v}" for k, v in ratios.items())
        chunks.append(
            {
                **common,
                "chunk_id": _chunk_id(doc_id, f"ratios-{chunk_index}"),
                "content": f"{title} — Advanced ratios: {ratio_pairs}.",
                "chunk_index": chunk_index,
            }
        )
        chunk_index += 1

    if record.get("exit_load_description"):
        chunks.append(
            {
                **common,
                "chunk_id": _chunk_id(doc_id, f"exit-load-{chunk_index}"),
                "content": f"{title} — Exit load: {record['exit_load_description']}",
                "chunk_index": chunk_index,
            }
        )
        chunk_index += 1

    return chunks


# ---------------------------------------------------------------------------
# Fixture-mode loaders (preserve no-network behavior of the previous script).
# ---------------------------------------------------------------------------


def _load_fixture_metrics_records() -> list[dict]:
    if not _FIXTURE_METRICS_PATH.exists():
        return []
    try:
        return json.loads(_FIXTURE_METRICS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _load_fixture_corpus_chunks() -> list[dict]:
    """Convert mf_corpus.json (list of SourceDocument-shaped) into DocumentChunk
    dicts via simple paragraph splitting. Avoids importing app.* unless
    --embed is requested."""
    if not _FIXTURE_CORPUS_PATH.exists():
        return []
    try:
        raw = json.loads(_FIXTURE_CORPUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    chunks: list[dict] = []
    for doc in raw:
        content = (doc.get("content") or "").strip()
        if not content:
            continue
        paragraphs = [p.strip() for p in re.split(r"\n{2,}", content) if p.strip()]
        if not paragraphs:
            paragraphs = [content]
        for idx, passage in enumerate(paragraphs):
            if len(passage) < 30:
                continue
            chunks.append(
                {
                    "chunk_id": _chunk_id(doc["doc_id"], f"fixture-{idx}"),
                    "doc_id": doc["doc_id"],
                    "source_url": doc.get("url", ""),
                    "title": doc.get("title", ""),
                    "doc_type": doc.get("doc_type", "mutual_fund_page"),
                    "last_checked": doc.get("last_checked", date.today().isoformat()),
                    "content": passage,
                    "chunk_index": idx,
                    "embedding": None,
                    "rating": None,
                    "review_date": None,
                    "app_version": None,
                    "found_review_helpful": None,
                }
            )
    return chunks


# ---------------------------------------------------------------------------
# Orchestrator.
# ---------------------------------------------------------------------------


async def _build_index(
    use_fixture: bool,
    scrape: bool,
    embed: bool,
) -> tuple[list[dict], list[dict]]:
    manifest = _load_manifest()
    print(f"Manifest loaded: {len(manifest)} source(s)")

    metrics_records: list[dict] = []
    chunks: list[dict] = []

    if use_fixture:
        print(f"\n[fixture] Loading metrics from {_FIXTURE_METRICS_PATH}")
        metrics_records = _load_fixture_metrics_records()
        print(f"  Loaded {len(metrics_records)} fixture metric record(s).")

        print(f"[fixture] Loading corpus chunks from {_FIXTURE_CORPUS_PATH}")
        chunks = _load_fixture_corpus_chunks()
        print(f"  Built {len(chunks)} chunk(s) from fixture corpus.")

    if scrape:
        scraped_records, _scraped_raw = await scrape_all_funds(manifest)
        scraped_ids = {r["doc_id"] for r in scraped_records}

        # Replace any fixture rows whose doc_id was scraped (live wins).
        metrics_records = [r for r in metrics_records if r.get("doc_id") not in scraped_ids]
        metrics_records.extend(scraped_records)

        # Drop fixture chunks for scraped funds and rebuild from live data.
        chunks = [c for c in chunks if c.get("doc_id") not in scraped_ids]
        for record in scraped_records:
            chunks.extend(_build_chunks_for_record(record))

        print(
            f"\n[scrape] Built {len(scraped_records)} live metric record(s) "
            f"and {sum(1 for c in chunks if c.get('doc_id') in scraped_ids)} live chunk(s)."
        )

    if not metrics_records and not chunks:
        print("ERROR: No data to index. Use --use-fixture or --scrape.")
        sys.exit(1)

    if embed:
        try:
            chunks = await _embed_chunks(chunks)
        except Exception as exc:
            print(f"[embed] WARN: embedding step failed ({exc}); chunks will be BM25-only.")

    _INDEX_DIR.mkdir(parents=True, exist_ok=True)
    _METRICS_PATH.write_text(
        json.dumps(metrics_records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _CHUNKS_PATH.write_text(
        json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"\n[write] mf_metrics.json -> {_METRICS_PATH} ({len(metrics_records)} record(s))"
    )
    print(f"[write] chunks.json -> {_CHUNKS_PATH} ({len(chunks)} chunk(s))")

    enable_supabase = os.getenv("ENABLE_SUPABASE_WRITE", "").lower() in ("1", "true", "yes")
    if enable_supabase:
        await _maybe_supabase_upsert(metrics_records)
    else:
        print("[supabase] Skipped (set ENABLE_SUPABASE_WRITE=true to persist to Supabase).")

    print("\nDone. Restart the backend server to load the updated indexes.")
    return metrics_records, chunks


async def _embed_chunks(chunks: list[dict]) -> list[dict]:
    """Optional Gemini embedding step. Imports app.* lazily."""
    print("\n[embed] Generating Gemini embeddings...")
    _ensure_imports()
    os.environ.setdefault("APP_ENV", "build")
    os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
    os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
    os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "build-placeholder")

    from app.core.config import clear_settings_cache, get_settings  # type: ignore
    from app.rag.embeddings import EmbeddingIndex  # type: ignore
    from app.schemas.rag import DocumentChunk  # type: ignore

    clear_settings_cache()
    settings = get_settings()
    if not settings.gemini_api_key:
        print("  WARN: GEMINI_API_KEY not set; skipping embeddings.")
        return chunks

    typed = [DocumentChunk.model_validate(c) for c in chunks]
    emb_index = EmbeddingIndex()
    typed = await emb_index.embed_chunks(typed, settings)
    embedded = sum(1 for c in typed if c.embedding is not None)
    print(f"  Embedded {embedded} / {len(typed)} chunk(s).")
    return [c.model_dump() for c in typed]


async def _maybe_supabase_upsert(metrics_records: list[dict]) -> None:
    print("[supabase] ENABLE_SUPABASE_WRITE=true — upserting to Supabase...")
    _ensure_imports()
    os.environ.setdefault("APP_ENV", "build")
    os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
    try:
        from app.core.config import clear_settings_cache, get_settings  # type: ignore
        from app.repositories.mf_repository import get_mf_repository  # type: ignore
        from app.schemas.rag import MFFundMetrics  # type: ignore

        clear_settings_cache()
        repo = get_mf_repository(get_settings())
        for m in metrics_records:
            try:
                obj = MFFundMetrics.model_validate(m)
                await repo.upsert_fund_metrics(obj)
            except Exception as exc:
                print(f"  WARN  {m.get('doc_id', '?')}: metrics upsert failed — {exc}")
        print(f"[supabase] Upserted {len(metrics_records)} metric record(s).")
    except Exception as exc:
        print(f"[supabase] WARN: Supabase write failed ({exc}); local index files are intact.")


# ---------------------------------------------------------------------------
# CLI entry point.
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="Rebuild the Phase 4 RAG chunk + metrics indexes.")
    ap.add_argument("--use-fixture", action="store_true", help="Load fixture MF corpus (no network).")
    ap.add_argument("--scrape", action="store_true", help="Scrape live MF/fee pages from Groww + AMFI.")
    ap.add_argument("--embed", action="store_true", help="Generate Gemini embeddings for each chunk.")
    args = ap.parse_args()

    if not args.use_fixture and not args.scrape:
        print("No source specified. Defaulting to --use-fixture.")
        args.use_fixture = True

    records, chunks = asyncio.run(
        _build_index(use_fixture=args.use_fixture, scrape=args.scrape, embed=args.embed)
    )

    print("\n[smoke-test]")
    if records:
        first = records[0]
        print(
            f"  first record: scheme_name={first.get('fund_name')!r} | "
            f"nav={first.get('nav')!r} ({first.get('nav_date')!r}) | "
            f"aum_cr={first.get('aum_cr')!r} | "
            f"holdings_count={len(first.get('top_holdings') or [])}"
        )
    else:
        print("  first record: <none>")
    print(f"  total chunks written: {len(chunks)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
