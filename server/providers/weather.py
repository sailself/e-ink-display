"""Weather via Open-Meteo (no API key)."""
from datetime import datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from http_util import get_json

API = "https://api.open-meteo.com/v1/forecast"

WMO_TEXT = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Light showers", 81: "Showers", 82: "Heavy showers", 85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm, hail", 99: "Thunderstorm, hail",
}


def icon_for(code, is_day=True):
    if code in (0, 1):
        return "sun" if is_day else "moon"
    if code == 2:
        return "partly"
    if code == 3:
        return "cloud"
    if code in (45, 48):
        return "fog"
    if 51 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    if code >= 95:
        return "storm"
    return "cloud"


def fetch(cfg):
    loc = cfg["location"]
    units = cfg.get("units", "metric")
    params = {
        "latitude": loc["latitude"],
        "longitude": loc["longitude"],
        "timezone": loc["timezone"],
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day",
        "hourly": "temperature_2m,precipitation_probability,weather_code",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
        "forecast_days": 2,
    }
    if units == "imperial":
        params["temperature_unit"] = "fahrenheit"
        params["wind_speed_unit"] = "mph"
    data = get_json(f"{API}?{urlencode(params)}")

    tz = ZoneInfo(loc["timezone"])
    now = datetime.now(tz).replace(minute=0, second=0, microsecond=0)
    cur = data["current"]
    hourly = []
    h = data["hourly"]
    for t, temp, pop, code in zip(h["time"], h["temperature_2m"], h["precipitation_probability"], h["weather_code"]):
        ts = datetime.fromisoformat(t).replace(tzinfo=tz)
        if ts < now:
            continue
        hourly.append({"time": ts.isoformat(), "temp": temp, "pop": pop, "code": code,
                       "icon": icon_for(code, 6 <= ts.hour < 20)})
        if len(hourly) >= 14:
            break
    d = data["daily"]
    days = []
    for i in range(len(d["time"])):
        code = d["weather_code"][i]
        days.append({
            "date": d["time"][i], "code": code, "text": WMO_TEXT.get(code, "-"), "icon": icon_for(code),
            "hi": d["temperature_2m_max"][i], "lo": d["temperature_2m_min"][i],
            "pop": d["precipitation_probability_max"][i], "sunrise": d["sunrise"][i], "sunset": d["sunset"][i],
        })
    is_day = bool(cur.get("is_day", 1))
    return {
        "location": loc.get("name") or "{},{}".format(loc["latitude"], loc["longitude"]),
        "units": {"temp": "°F" if units == "imperial" else "°C", "wind": "mph" if units == "imperial" else "km/h"},
        "current": {
            "temp": cur["temperature_2m"], "feels": cur["apparent_temperature"], "humidity": cur["relative_humidity_2m"],
            "wind": cur["wind_speed_10m"], "code": cur["weather_code"], "is_day": is_day,
            "text": WMO_TEXT.get(cur["weather_code"], "-"), "icon": icon_for(cur["weather_code"], is_day),
        },
        "hourly": hourly,
        "daily": days,
    }
