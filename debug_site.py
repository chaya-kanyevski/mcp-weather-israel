"""כלי עזר לפיתוח: מריץ את ה-Tools של weather_Israel ישירות, בלי LLM ובלי MCP.

    uv run debug_site.py ירושלים           # הרצת כל 4 השלבים והדפסת התוצאה
    uv run debug_site.py --inspect חיפה    # עזרה במציאת סלקטורים אם האתר השתנה
"""
import asyncio
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import weather_Israel as w


async def run_flow(city: str) -> None:
    print("1)", await w.open_weather_forecast_israel())
    print("2)", await w.enter_weather_forecast_city_israel(city))
    print("3)", await w.select_weather_forecast_city_israel())
    content = await w.get_weather_forecast_page_content(3000)
    print("4)", content)
    input("\nלחצי Enter לסגירת הדפדפן...")
    await w.state.close()


async def inspect(city: str) -> None:
    page = await w.state.get_page()
    await page.goto(w.FORECAST_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)
    print("\n== שדות input גלויים בדף ==")
    inputs = await page.evaluate("""() => [...document.querySelectorAll('input')]
        .filter(e => e.offsetParent !== null)
        .map(e => ({id: e.id, name: e.name, type: e.type, cls: e.className,
                    placeholder: e.placeholder}))""")
    for i in inputs:
        print("  ", i)

    found = await w.first_visible(page, w.SEARCH_INPUT_SELECTORS)
    if not found:
        print("\nלא נמצא שדה חיפוש. הגדירי SEARCH_INPUT_SELECTOR ב-.env לפי הרשימה למעלה.")
        input("Enter לסגירה...")
        return await w.state.close()
    print(f"\nשדה החיפוש שנבחר: {found[1]}")
    await found[0].press_sequentially(city, delay=150)
    await page.wait_for_timeout(2500)

    print(f"\n== אלמנטים גלויים שמכילים '{city}' (מועמדים לרשימת ההצעות) ==")
    matches = await page.evaluate("""(city) => [...document.querySelectorAll('li,a,div,span')]
        .filter(e => e.offsetParent !== null && e.children.length < 3
                     && (e.innerText || '').includes(city))
        .slice(0, 15)
        .map(e => ({tag: e.tagName.toLowerCase(), cls: e.className, id: e.id,
                    parentCls: e.parentElement && e.parentElement.className,
                    text: e.innerText.trim().slice(0, 50)}))""", city)
    for m in matches:
        print("  ", m)
    sugg = await w.wait_for_suggestions(page, 1000)
    print(f"\nסלקטור ההצעות שזוהה אוטומטית: {sugg[1] if sugg else 'לא זוהה'}")
    print("אם לא זוהה – הגדירי SUGGESTION_SELECTOR ב-.env, למשל: .some-class li")
    input("\nEnter לסגירה...")
    await w.state.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--inspect":
        asyncio.run(inspect(" ".join(args[1:]) or "ירושלים"))
    else:
        asyncio.run(run_flow(" ".join(args) or "ירושלים"))
