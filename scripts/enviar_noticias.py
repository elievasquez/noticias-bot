"""
Boletín automático de noticias, clima, heladas y precios de combustible
para Longaví, Linares y Yerbas Buenas (Región del Maule, Chile).

Se ejecuta desde GitHub Actions cada hora, y solo genera/envía el boletín
cuando la hora local de Chile es 9:00 o 21:00 (para no depender de si Chile
está en horario de verano o invierno).
"""

import os
import sys
import html
import urllib.parse
from datetime import datetime, date
from zoneinfo import ZoneInfo

import requests
import feedparser

# ---------------------------------------------------------------------------
# CONFIGURACIÓN
# ---------------------------------------------------------------------------

ZONA_CL = ZoneInfo("America/Santiago")
HORAS_DE_ENVIO = {9, 21}          # horas del día en que se manda el boletín
UMBRAL_HELADA_C = 3.0             # bajo esta temperatura mínima, se avisa helada

CIUDADES = {
    "Longaví":       {"lat": -35.9667, "lon": -71.7000, "comuna_cne": "Longaví"},
    "Linares":       {"lat": -35.8483, "lon": -71.5936, "comuna_cne": "Linares"},
    "Yerbas Buenas": {"lat": -35.7667, "lon": -71.5833, "comuna_cne": "Yerbas Buenas"},
}

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
CNE_AUTH_KEY = os.environ.get("CNE_AUTH_KEY")  # opcional, ver README
FORZAR_ENVIO = os.environ.get("FORZAR_ENVIO", "false").lower() == "true"

NOTICIAS_POR_SECCION = 5

WMO_CODES = {
    0: "Despejado", 1: "Mayormente despejado", 2: "Parcialmente nublado",
    3: "Nublado", 45: "Niebla", 48: "Niebla helada", 51: "Llovizna débil",
    53: "Llovizna moderada", 55: "Llovizna intensa", 61: "Lluvia débil",
    63: "Lluvia moderada", 65: "Lluvia intensa", 71: "Nieve débil",
    73: "Nieve moderada", 75: "Nieve intensa", 80: "Chubascos débiles",
    81: "Chubascos moderados", 82: "Chubascos violentos", 95: "Tormenta eléctrica",
}


# ---------------------------------------------------------------------------
# CLIMA Y HELADAS (Open-Meteo, gratis, sin API key)
# ---------------------------------------------------------------------------

def obtener_clima(lat, lon):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,weather_code",
        "timezone": "America/Santiago",
        "forecast_days": 2,
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def texto_clima_y_helada(nombre_ciudad, datos):
    actual = datos["current"]
    diario = datos["daily"]

    desc_actual = WMO_CODES.get(actual["weather_code"], "—")
    linea_clima = (
        f"🌡️ <b>{html.escape(nombre_ciudad)}</b>: {actual['temperature_2m']}°C, "
        f"{desc_actual}, humedad {actual['relative_humidity_2m']}%, "
        f"viento {actual['wind_speed_10m']} km/h. "
        f"Hoy min {diario['temperature_2m_min'][0]}°C / máx {diario['temperature_2m_max'][0]}°C."
    )

    alerta_helada = None
    tmin_manana = diario["temperature_2m_min"][1] if len(diario["temperature_2m_min"]) > 1 else None
    if tmin_manana is not None and tmin_manana <= UMBRAL_HELADA_C:
        alerta_helada = (
            f"❄️ <b>Aviso de helada en {html.escape(nombre_ciudad)}</b>: "
            f"se espera una mínima de {tmin_manana}°C para la madrugada de mañana."
        )

    return linea_clima, alerta_helada


# ---------------------------------------------------------------------------
# PRECIOS DE COMBUSTIBLE (CNE - Bencina en Línea / datos abiertos)
# ---------------------------------------------------------------------------
#
# La CNE expone datos de "Bencina en Línea" a través de su API de datos
# abiertos (energiaabierta.cl), la cual requiere una auth_key gratuita.
# Cómo obtenerla y cómo encontrar el datastream de tu región están explicados
# en el README. Mientras no configures CNE_AUTH_KEY, el boletín simplemente
# entrega el link directo para comparar precios manualmente.

def obtener_precios_combustible(comuna):
    if not CNE_AUTH_KEY:
        return None
    try:
        url = "http://cne.cloudapi.junar.com/api/v2/datastreams/BENCI-EN-LINEA-V2-80280/data.json/"
        params = {"auth_key": CNE_AUTH_KEY, "limit": 200}
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        filas = r.json().get("answer", [])
        filas_comuna = [f for f in filas if comuna.lower() in str(f).lower()]
        return filas_comuna[:3] if filas_comuna else None
    except Exception:
        return None


def texto_combustible(nombre_ciudad):
    filas = obtener_precios_combustible(nombre_ciudad)
    if not filas:
        return (
            f"⛽ <b>{html.escape(nombre_ciudad)}</b>: revisa los precios actualizados en "
            f'<a href="https://www.bencinaenlinea.cl">bencinaenlinea.cl</a> '
            f"(la integración automática aún no está configurada, ver README)."
        )
    partes = [f"⛽ <b>{html.escape(nombre_ciudad)}</b>:"]
    for f in filas:
        partes.append(f"  • {f}")
    return "\n".join(partes)


# ---------------------------------------------------------------------------
# NOTICIAS (Google News RSS, gratis, sin API key)
# ---------------------------------------------------------------------------

def buscar_noticias_por_texto(consulta, n=NOTICIAS_POR_SECCION):
    q = urllib.parse.quote(consulta)
    url = f"https://news.google.com/rss/search?q={q}&hl=es-419&gl=CL&ceid=CL:es"
    feed = feedparser.parse(url)
    return feed.entries[:n]


def noticias_por_tema(tema, n=NOTICIAS_POR_SECCION):
    # temas válidos: WORLD, NATION, BUSINESS, TECHNOLOGY, SCIENCE, SPORTS, HEALTH
    url = f"https://news.google.com/rss/headlines/section/topic/{tema}?hl=es-419&gl=CL&ceid=CL:es"
    feed = feedparser.parse(url)
    return feed.entries[:n]


def formatear_noticias(titulo_seccion, entradas, emoji="📰"):
    if not entradas:
        return f"{emoji} <b>{html.escape(titulo_seccion)}</b>\nSin novedades por ahora.\n"
    lineas = [f"{emoji} <b>{html.escape(titulo_seccion)}</b>"]
    for e in entradas:
        titulo = html.escape(e.title)
        link = e.link
        fuente = ""
        if hasattr(e, "source") and getattr(e.source, "title", None):
            fuente = f" — {html.escape(e.source.title)}"
        lineas.append(f'• <a href="{link}">{titulo}</a>{fuente}')
    return "\n".join(lineas) + "\n"


# ---------------------------------------------------------------------------
# TELEGRAM
# ---------------------------------------------------------------------------

def enviar_telegram(texto):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID.", file=sys.stderr)
        sys.exit(1)

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    # Telegram limita los mensajes a 4096 caracteres: se parte en bloques.
    bloques = []
    actual = ""
    for linea in texto.split("\n"):
        if len(actual) + len(linea) + 1 > 3900:
            bloques.append(actual)
            actual = ""
        actual += linea + "\n"
    if actual:
        bloques.append(actual)

    for bloque in bloques:
        resp = requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": bloque,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=20)
        if not resp.ok:
            print("Error enviando a Telegram:", resp.text, file=sys.stderr)
            resp.raise_for_status()


# ---------------------------------------------------------------------------
# ARMADO DEL BOLETÍN
# ---------------------------------------------------------------------------

def armar_boletin():
    ahora = datetime.now(ZONA_CL)
    momento = "☀️ Boletín de la mañana" if ahora.hour < 15 else "🌙 Boletín de la noche"
    encabezado = f"<b>{momento} — {ahora.strftime('%A %d-%m-%Y %H:%M')}</b>\n"

    secciones = [encabezado]

    # Noticias locales por ciudad
    for ciudad in CIUDADES:
        entradas = buscar_noticias_por_texto(f'"{ciudad}" Chile')
        secciones.append(formatear_noticias(f"Noticias locales — {ciudad}", entradas, "📍"))

    # Precios de combustible
    secciones.append("⛽ <b>Precios de combustible</b>")
    for ciudad in CIUDADES:
        secciones.append(texto_combustible(ciudad))
    secciones.append("")

    # Clima y heladas
    secciones.append("🌦️ <b>Clima</b>")
    alertas_helada = []
    for ciudad, datos_ciudad in CIUDADES.items():
        try:
            clima = obtener_clima(datos_ciudad["lat"], datos_ciudad["lon"])
            linea, alerta = texto_clima_y_helada(ciudad, clima)
            secciones.append(linea)
            if alerta:
                alertas_helada.append(alerta)
        except Exception as e:
            secciones.append(f"🌡️ <b>{ciudad}</b>: no se pudo obtener el clima ({e}).")
    secciones.append("")

    if alertas_helada:
        secciones.append("<b>❄️ Aviso de heladas</b>")
        secciones.extend(alertas_helada)
        secciones.append("")

    # Noticias nacionales, mundo y tecnología
    secciones.append(formatear_noticias("Noticias nacionales", noticias_por_tema("NATION"), "🇨🇱"))
    secciones.append(formatear_noticias("Noticias del mundo", noticias_por_tema("WORLD"), "🌍"))
    secciones.append(formatear_noticias("Tecnología", noticias_por_tema("TECHNOLOGY"), "💻"))

    return "\n".join(secciones)


def main():
    ahora = datetime.now(ZONA_CL)
    if not FORZAR_ENVIO and ahora.hour not in HORAS_DE_ENVIO:
        print(f"Hora actual en Chile: {ahora.strftime('%H:%M')} — no toca enviar boletín. Saliendo.")
        return

    boletin = armar_boletin()
    enviar_telegram(boletin)
    print("Boletín enviado correctamente.")


if __name__ == "__main__":
    main()
