# 🌦️ Weather Israel MCP – MCP ששם ל-LLM יד על העכבר

MCP Server שעונה על שאלות מזג אוויר בישראל, **בלי API**. הוא פותח דפדפן אמיתי עם Playwright, מקליד את שם העיר באתר [weather2day.co.il](https://www.weather2day.co.il/forecast), בוחר אותה מהרשימה ושולף את תוכן דף התחזית.
את התוכן הוא מעביר ל-LLM, שעונה על השאלה ישירות בצ'אט (RAG).

לצידו מחובר גם `weather_USA.py`, Server שמשתמש ב-API הרשמי של ארה"ב. כך ה-Host צריך לבחור בכל שאלה את ה-Server המתאים.

## 🧩 ארכיטקטורה

```
 משתמשת ──► host.py (צ'אט בטרמינל) ──► LLM
                │   ▲                     │ "תפעיל את tool X"
                ▼   │ תוצאה               ▼
        ┌── MCPClient ──┐      ┌── MCPClient ──┐
        │  (stdio)      │      │  (stdio)      │
        ▼               │      ▼               │
  weather_Israel.py ────┘   weather_USA.py ────┘
   Playwright → 🌐 weather2day     httpx → api.weather.gov
```

| קובץ | תפקיד |
|---|---|
| `host.py` | **Host**: צ'אט טרמינל. מצרף לכל קריאה ל-LLM את רשימת ה-Tools, ומריץ את ה-Tools שהמודל מבקש בלולאה עד לתשובה סופית |
| `client.py` | **MCP Client** גנרי: מריץ Server כתהליך, פותח session על stdio, מגלה Tools ומפעיל אותם |
| `weather_Israel.py` | **MCP Server** ישראלי מבוסס Playwright |
| `weather_USA.py` | **MCP Server** אמריקאי מבוסס API |
| `debug_site.py` | כלי פיתוח: מריץ את ה-Tools ישירות, בלי LLM, ועוזר לאתר סלקטורים |

## 🔨 ה-Tools של weather_Israel

| # | Tool | מה הוא עושה |
|---|---|---|
| 1 | `open_weather_forecast_israel` | פותח דפדפן ומנווט לאתר התחזית (וסוגר חלונות קופצים) |
| 2 | `enter_weather_forecast_city_israel(city)` | מקליד את שם העיר בשדה החיפוש, תו אחר תו כדי להפעיל את ההשלמה האוטומטית, ומחזיר את ההצעות שהופיעו |
| 3 | `select_weather_forecast_city_israel` | בוחר את הפריט הראשון ברשימה ומגיע לדף התחזית של העיר |
| 4 | `get_weather_forecast_page_content` | **שלב ב' (RAG):** מחלץ את טקסט הדף, מנקה סקריפטים, תפריטים, פרסומות וכפילויות, ומחזיר ל-LLM |
| ➕ | `close_weather_browser_israel` | סוגר את הדפדפן |

כמה החלטות תכנון שכדאי להכיר:
- **דפדפן אחד לכל השיחה.** הדפדפן נשאר פתוח בין קריאות, וכך כל Tool ממשיך מהמקום שבו הקודם עצר.
- **סלקטורים עמידים.** לכל רכיב יש רשימה של סלקטורים מועמדים, כי אתרים משנים מבנה. אפשר לדרוס אותם ב-`.env`.
- **הודעות שגיאה ברורות ל-LLM**, במקום חריגות. כך המודל יכול לדווח מה נכשל ולא ממציא תחזית.
- **בשרת stdio כל הלוגים נשלחים ל-stderr.** ה-stdout הוא ערוץ הפרוטוקול, והדפסה אליו שוברת את החיבור.

## 🚀 התקנה והרצה

```bash
uv sync                                  # התקנת התלויות
uv run playwright install chromium       # התקנת דפדפן עבור Playwright
cp .env.example .env                     # להזין LLM_API_KEY
uv run host.py                           # הפעלת הצ'אט
```

ברירת המחדל היא Gemini דרך ה-endpoint התואם ל-OpenAI. אפשר להחליף לכל ספק תואם OpenAI ב-`.env`.
הדפדפן נפתח מול העיניים (`HEADLESS=false`) עם השהיה קלה בין פעולות (`SLOW_MO`), כדי שיהיה אפשר לראות את האוטומציה.

## 💬 דוגמאות לשאלות

| שאלה | מה קורה |
|---|---|
| מה התחזית היום בירושלים? | 4 ה-Tools הישראליים רצים ברצף, ומתקבלת תשובה מסוכמת |
| האם צפוי גשם בבני ברק מחר? | אותו רצף, והתשובה מתמקדת בגשם |
| מה ללבוש היום בחיפה? 🧥👒 | המלצת לבוש לפי הטמפרטורות בדף |
| What's the weather in Tel Aviv? | המודל מתרגם את שם העיר לעברית לפני ההקלדה |
| What's the forecast in Chicago? | `get_forecast` של ה-Server האמריקאי |
| Any weather alerts in Texas? | `get_alerts("TX")` |

דוגמת פלט בטרמינל:
```
את: מה התחזית היום בירושלים?
   🔧 open_weather_forecast_israel({})
   🔧 enter_weather_forecast_city_israel({"city": "ירושלים"})
   🔧 select_weather_forecast_city_israel({})
   🔧 get_weather_forecast_page_content({})
🤖 ...
```

## 🛠️ אם האתר שינה מבנה

```bash
uv run debug_site.py ירושלים              # מריץ את 4 השלבים בלי LLM ומדפיס את התוצאה
uv run debug_site.py --inspect ירושלים    # מציג את שדות החיפוש והאלמנטים של רשימת ההצעות
```
את הסלקטור הנכון מזינים ב-`.env` (`SEARCH_INPUT_SELECTOR` / `SUGGESTION_SELECTOR`), בלי לשנות קוד.

## 🖥️ חיבור לאפליקציית ChatBox

בהגדרות MCP של ChatBox מוסיפים Server מקומי עם הפקודה:
```
uv --directory C:\path\to\mcp-weather-israel run weather_Israel.py
```

## 📚 מה למדתי

- איך לממש MCP Server עצמאי עם `@mcp.tool()`, ולמה ה-docstring של כל Tool הוא בעצם פרומפט: ממנו ה-LLM מבין מתי ובאיזה סדר להפעיל אותו.
- איך ה-Host בוחר בין כמה Servers לפי תיאורי ה-Tools.
- איך Playwright הופך את ה-LLM מ"מוח" גם ל"ידיים".
- RAG בסיסי: שליפה, ניקוי וצמצום של תוכן כדי להעשיר את הקונטקסט של המודל.
