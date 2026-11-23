"""MCP Server: תחזית מזג אוויר בישראל – באמצעות שליטה בדפדפן עם Playwright.

במקום API, ה-Server "מתנהג כמו משתמש": פותח דפדפן, מקליד שם עיר, בוחר מהרשימה
ושולף את תוכן הדף. כל שלב הוא Tool נפרד, וה-LLM מפעיל אותם בזה אחר זה.

⚠️ בשרת stdio אסור להדפיס ל-stdout (זה ערוץ התקשורת של הפרוטוקול) – כל הלוגים הולכים ל-stderr.
"""
from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from playwright.async_api import Browser, Locator, Page, Playwright, async_playwright

load_dotenv()
logging.basicConfig(stream=sys.stderr, level=os.getenv("LOG_LEVEL", "WARNING"),
                    format="[weather_israel] %(message)s")
log = logging.getLogger(__name__)

FORECAST_URL = "https://www.weather2day.co.il/forecast"
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
SLOW_MO = int(os.getenv("SLOW_MO", "300"))

# האתר עלול לשנות את המבנה שלו, ולכן יש כמה סלקטורים מועמדים לכל רכיב.
# אפשר לדרוס דרך .env – ראו debug_site.py --inspect
SEARCH_INPUT_SELECTORS = [s for s in [
    os.getenv("SEARCH_INPUT_SELECTOR", ""),
    'input[type="search"]',
    'input[placeholder*="עיר"]',
    'input[placeholder*="ישוב"]',
    'input[placeholder*="יישוב"]',
    'input[placeholder*="חיפוש"]',
    'input[placeholder*="חפש"]',
    'input[name*="search" i]',
    'input[id*="search" i]',
    'input[class*="search" i]',
    'input[id*="city" i]',
    'input[type="text"]',
] if s]

SUGGESTION_SELECTORS = [s for s in [
    os.getenv("SUGGESTION_SELECTOR", ""),
    ".ui-autocomplete li",
    ".ui-menu-item",
    '[role="listbox"] [role="option"]',
    '[role="option"]',
    ".autocomplete-suggestion",
    ".autocomplete-suggestions div",
    ".tt-suggestion",
    'ul[class*="autocomplete" i] li',
    'ul[class*="suggest" i] li',
    'div[class*="suggest" i] li',
    'div[class*="suggest" i] a',
    'div[class*="result" i] li',
    'div[class*="result" i] a',
] if s]

POPUP_CLOSE_SELECTORS = [
    'button:has-text("אישור")', 'button:has-text("הבנתי")', 'button:has-text("מסכים")',
    'button:has-text("סגור")', '[aria-label="Close"]', '[aria-label="סגור"]',
    ".close", ".modal-close",
]


# ---------------- ניהול הדפדפן ----------------

class BrowserState:
    """דפדפן אחד שנשאר פתוח לאורך כל השיחה – כך כל Tool ממשיך מאיפה שהקודם עצר."""

    def __init__(self) -> None:
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.page: Page | None = None

    async def get_page(self) -> Page:
        if self.page is None or self.page.is_closed():
            if self.playwright is None:
                self.playwright = await async_playwright().start()
            if self.browser is None or not self.browser.is_connected():
                self.browser = await self.playwright.chromium.launch(
                    headless=HEADLESS, slow_mo=SLOW_MO)
            context = await self.browser.new_context(locale="he-IL",
                                                     viewport={"width": 1280, "height": 900})
            self.page = await context.new_page()
            self.page.set_default_timeout(15_000)
        return self.page

    async def close(self) -> None:
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        self.page = self.browser = self.playwright = None


state = BrowserState()


@asynccontextmanager
async def lifespan(_server: FastMCP) -> AsyncIterator[None]:
    try:
        yield
    finally:
        await state.close()  # סגירה מסודרת של הדפדפן כשה-Server נכבה


mcp = FastMCP("weather_israel", lifespan=lifespan, log_level="WARNING")


# ---------------- עזרים ----------------

async def first_visible(page: Page, selectors: list[str]) -> tuple[Locator, str] | None:
    """מחזיר את האלמנט הנראה הראשון מבין רשימת סלקטורים מועמדים."""
    for sel in selectors:
        loc = page.locator(sel)
        try:
            count = await loc.count()
        except Exception:
            continue
        for i in range(min(count, 10)):
            item = loc.nth(i)
            try:
                if await item.is_visible():
                    return item, sel
            except Exception:
                continue
    return None


async def dismiss_popups(page: Page) -> None:
    for sel in POPUP_CLOSE_SELECTORS:
        found = await first_visible(page, [sel])
        if found:
            try:
                await found[0].click(timeout=1500)
                log.info("נסגר חלון קופץ: %s", sel)
            except Exception:
                pass


async def wait_for_suggestions(page: Page, timeout_ms: int = 6000) -> tuple[Locator, str] | None:
    step = 300
    for _ in range(timeout_ms // step):
        found = await first_visible(page, SUGGESTION_SELECTORS)
        if found:
            return found
        await page.wait_for_timeout(step)
    return None


def on_site(page: Page) -> bool:
    return "weather2day.co.il" in (page.url or "")


# ---------------- Tools ----------------

@mcp.tool()
async def open_weather_forecast_israel() -> str:
    """STEP 1 of 4 for weather in ISRAEL. Opens a browser and navigates to the Israeli
    weather forecast website (weather2day.co.il). Call this first, before entering a city."""
    page = await state.get_page()
    await page.goto(FORECAST_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(1500)
    await dismiss_popups(page)
    title = await page.title()
    log.info("נפתח: %s", page.url)
    return f"The forecast website is open. URL: {page.url} | Title: {title}"


@mcp.tool()
async def enter_weather_forecast_city_israel(city: str) -> str:
    """STEP 2 of 4 for weather in ISRAEL. Types a city name into the website's search box
    so the list of matching cities opens.

    Args:
        city: City name IN HEBREW, e.g. "ירושלים", "תל אביב", "בני ברק", "חיפה".
              If the user wrote the city in English, translate it to Hebrew first.
    """
    page = await state.get_page()
    note = ""
    if not on_site(page):
        await open_weather_forecast_israel()
        note = "(The website was not open, so it was opened first.) "

    found = await first_visible(page, SEARCH_INPUT_SELECTORS)
    if not found:
        return (note + "ERROR: could not find the city search box on the page. "
                "The site layout may have changed – run `uv run debug_site.py --inspect`.")
    box, sel = found
    await box.click()
    await box.fill("")
    # הקלדה תו-אחר-תו – כדי להפעיל את ה-autocomplete של האתר
    await box.press_sequentially(city, delay=120)
    log.info("הוקלד '%s' בשדה %s", city, sel)

    sugg = await wait_for_suggestions(page)
    if not sugg:
        return (note + f"Typed '{city}' into the search box, but no suggestion list appeared. "
                "You can still call select_weather_forecast_city_israel – it will press Enter.")
    loc = page.locator(sugg[1])
    texts = []
    for i in range(min(await loc.count(), 8)):
        t = (await loc.nth(i).inner_text()).strip()
        if t and await loc.nth(i).is_visible():
            texts.append(t.replace("\n", " "))
    return note + f"Typed '{city}'. Suggestions shown: " + " | ".join(texts or ["(unreadable)"])


@mcp.tool()
async def select_weather_forecast_city_israel() -> str:
    """STEP 3 of 4 for weather in ISRAEL. Selects the FIRST city in the suggestion list,
    which opens the forecast page of that city. Call after enter_weather_forecast_city_israel."""
    page = await state.get_page()
    if not on_site(page):
        return "ERROR: the website is not open. Call open_weather_forecast_israel first."
    url_before = page.url

    sugg = await wait_for_suggestions(page, timeout_ms=3000)
    if sugg:
        chosen = (await sugg[0].inner_text()).strip().replace("\n", " ")
        await sugg[0].click()
        method = f"clicked the first suggestion: '{chosen}'"
    else:
        box = await first_visible(page, SEARCH_INPUT_SELECTORS)
        if not box:
            return "ERROR: no suggestion list and no search box found."
        await box[0].press("ArrowDown")
        await box[0].press("Enter")
        method = "no visible list – pressed ArrowDown + Enter"

    try:
        await page.wait_for_url(lambda u: u != url_before, timeout=10_000)
    except Exception:
        pass
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(1500)
    title = await page.title()
    log.info("נבחרה עיר: %s", page.url)
    changed = "" if page.url != url_before else " (WARNING: URL did not change – selection may have failed)"
    return f"Selected city ({method}). Now on: {page.url} | Title: {title}{changed}"


@mcp.tool()
async def get_weather_forecast_page_content(max_chars: int = 6000) -> str:
    """STEP 4 of 4 for weather in ISRAEL. Extracts and cleans the text of the current
    forecast page, so you can answer the user's question from it (temperatures, rain,
    wind, days ahead). Call after select_weather_forecast_city_israel.

    Args:
        max_chars: Maximum characters of page text to return (default 6000).
    """
    page = await state.get_page()
    if not on_site(page):
        return "ERROR: the forecast website is not open."

    # ניקוי ב-DOM: הסרת סקריפטים, תפריטים, פרסומות וכו' – ושליפת הטקסט הגלוי בלבד
    raw = await page.evaluate("""() => {
        const root = (document.querySelector('main') || document.body).cloneNode(true);
        root.querySelectorAll(
          'script,style,noscript,iframe,svg,nav,header,footer,aside,form,button,' +
          '[class*="ad" i][class*="banner" i],[id*="google_ads"],[class*="cookie" i],' +
          '[class*="menu" i],[class*="share" i],[class*="social" i]'
        ).forEach(el => el.remove());
        return root.innerText || '';
    }""")
    text = clean_text(raw)
    if len(text) < 200:  # אם הניקוי האגרסיבי השאיר מעט מדי – נשתמש בכל הגוף
        text = clean_text(await page.inner_text("body"))

    title = await page.title()
    header = f"PAGE: {title}\nURL: {page.url}\n---\n"
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[truncated]"
    return header + text


@mcp.tool()
async def close_weather_browser_israel() -> str:
    """Closes the browser opened by the Israeli weather tools. Use only if the user asks."""
    await state.close()
    return "Browser closed."


def clean_text(raw: str) -> str:
    """ניקוי טקסט: רווחים, שורות ריקות, כפילויות ושורות 'רעש'."""
    seen, lines = set(), []
    for line in raw.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line or len(line) < 2:
            continue
        if line in seen:  # שורות חוזרות (תפריטים, כותרות כפולות)
            continue
        seen.add(line)
        lines.append(line)
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
