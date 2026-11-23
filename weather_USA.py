"""MCP Server: תחזית מזג אוויר בארה"ב דרך ה-API של api.weather.gov."""
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("weather_usa", log_level="WARNING")

NWS_API_BASE = "https://api.weather.gov"
USER_AGENT = "weather-mcp-course/1.0"


async def make_nws_request(url: str) -> dict[str, Any] | None:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/geo+json"}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None


def format_alert(feature: dict) -> str:
    props = feature["properties"]
    return (
        f"Event: {props.get('event', 'Unknown')}\n"
        f"Area: {props.get('areaDesc', 'Unknown')}\n"
        f"Severity: {props.get('severity', 'Unknown')}\n"
        f"Description: {props.get('description', 'No description available')}\n"
        f"Instructions: {props.get('instruction', 'No specific instructions provided')}"
    )


@mcp.tool()
async def get_alerts(state: str) -> str:
    """Get active weather alerts for a US state.

    Args:
        state: Two-letter US state code (e.g. CA, NY)
    """
    data = await make_nws_request(f"{NWS_API_BASE}/alerts/active/area/{state.upper()}")
    if not data or "features" not in data:
        return "Unable to fetch alerts or no alerts found."
    if not data["features"]:
        return "No active alerts for this state."
    return "\n---\n".join(format_alert(f) for f in data["features"])


@mcp.tool()
async def get_forecast(latitude: float, longitude: float) -> str:
    """Get weather forecast for a location in the USA.

    Args:
        latitude: Latitude of the location
        longitude: Longitude of the location
    """
    points = await make_nws_request(f"{NWS_API_BASE}/points/{latitude},{longitude}")
    if not points:
        return "Unable to fetch forecast data for this location."
    forecast = await make_nws_request(points["properties"]["forecast"])
    if not forecast:
        return "Unable to fetch detailed forecast."
    periods = forecast["properties"]["periods"][:5]
    return "\n---\n".join(
        f"{p['name']}:\nTemperature: {p['temperature']}°{p['temperatureUnit']}\n"
        f"Wind: {p['windSpeed']} {p['windDirection']}\nForecast: {p['detailedForecast']}"
        for p in periods
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
