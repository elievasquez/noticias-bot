import logging
from config import HTTP_SESSION, WMO_ESTILOS

def estilo_clima(codigo):
    for estilo in WMO_ESTILOS.values():
        if codigo in estilo["codigos"]:
            return estilo
    return WMO_ESTILOS["nublado"]

def obtener_clima(lat, lon):
    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat, "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,weather_code,uv_index_max",
            "timezone": "America/Santiago", "forecast_days": 2,
        }
        r = HTTP_SESSION.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logging.error(f"Error al obtener clima ({lat}, {lon}): {e}")
        return {}
