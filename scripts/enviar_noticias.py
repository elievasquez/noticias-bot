"""
Boletín automático de noticias, clima, heladas y precios de combustible
para Longaví, Linares y Yerbas Buenas (Región del Maule, Chile).

Se ejecuta desde GitHub Actions cada hora, y solo genera/envía el boletín
cuando la hora local de Chile es 9:00 o 21:00 (para no depender de si Chile
está en horario de verano o invierno).

El boletín se manda como DOS mensajes de Telegram:
  1. Resumen rápido + clima + aviso de heladas (corto, pensado para fijar/pin)
  2. Noticias (locales, nacionales, mundo y tecnología)

La edición de las 9:00 va completa. La de las 21:00 va resumida (menos
noticias por sección), para no repetir todo el contenido de la mañana.
"""

import os
import sys
import html
import math
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import feedparser

# ---------------------------------------------------------------------------
# CONFIGURACIÓN
# ---------------------------------------------------------------------------

ZONA_CL = ZoneInfo("America/Santiago")
HORAS_DE_ENVIO = {9, 21}          # horas del día en que se manda el boletín
UMBRAL_HELADA_C = 3.0             # bajo esta temperatura mínima, se avisa helada
SEPARADOR = "⸻" * 12

CIUDADES = {
    "Longaví":       {"lat": -35.9667, "lon": -71.7000, "comuna_cne": "Longaví"},
    "Linares":       {"lat": -35.8483, "lon": -71.5936, "comuna_cne": "Linares"},
    "Yerbas Buenas": {"lat": -35.7667, "lon": -71.5833, "comuna_cne": "Yerbas Buenas"},
}

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
CNE_EMAIL = os.environ.get("CNE_EMAIL")        # opcional, ver README
CNE_PASSWORD = os.environ.get("CNE_PASSWORD")  # opcional, ver README
FORZAR_ENVIO = os.environ.get("FORZAR_ENVIO", "false").lower() == "true"

RADIO_KM_COMBUSTIBLE = 15  # radio de búsqueda de estaciones alrededor de cada ciudad

# Cantidad de noticias por sección según la edición
NOTICIAS_LOCALES = {"manana": 3, "noche": 1}
NOTICIAS_GLOBALES = {"manana": 2, "noche": 1}   # por cada tema: nacional/mundo/tec

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


def resumen_clima_ciudad(nombre_ciudad, datos):
    """Devuelve (temp_actual, linea_corta_html, alerta_helada_o_None)."""
    actual = datos["current"]
    diario = datos["daily"]
    desc_actual = WMO_CODES.get(actual["weather_code"], "—")

    linea = (
        f"<b>{html.escape(nombre_ciudad)}</b> {actual['temperature_2m']}°C, "
        f"{desc_actual.lower()} · min {diario['temperature_2m_min'][0]}° / "
        f"máx {diario['temperature_2m_max'][0]}°"
    )

    alerta = None
    tmin_manana = diario["temperature_2m_min"][1] if len(diario["temperature_2m_min"]) > 1 else None
    if tmin_manana is not None and tmin_manana <= UMBRAL_HELADA_C:
        alerta = (
            f"❄️ <b>Helada en {html.escape(nombre_ciudad)}</b> — "
            f"mínima de {tmin_manana}°C mañana de madrugada"
        )

    return actual["temperature_2m"], linea, alerta


# ---------------------------------------------------------------------------
# PRECIOS DE COMBUSTIBLE (API oficial api.cne.cl)
# ---------------------------------------------------------------------------
#
# La API real de la CNE (https://api.cne.cl/apidocs) NO usa auth_key: se
# autentica con un correo y contraseña de una cuenta gratuita (creada en
# https://api.cne.cl/register), lo que entrega un token que se manda como
# "Authorization: Bearer <token>". La respuesta no trae comuna, así que el
# filtro por ciudad se hace por cercanía (latitud/longitud) usando el mismo
# radio para las tres localidades. Ver README para cómo crear la cuenta.

_CNE_TOKEN = None
_CNE_ESTACIONES = None  # cache: se piden una sola vez por ejecución

FUEL_KEYS = {
    "93": ("93", "A93"),
    "95": ("95", "A95"),
    "97": ("97", "A97"),
    "diésel": ("DI", "ADI"),
}


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def cne_login():
    global _CNE_TOKEN
    if _CNE_TOKEN:
        return _CNE_TOKEN
    if not CNE_EMAIL or not CNE_PASSWORD:
        print("[CNE] Faltan CNE_EMAIL / CNE_PASSWORD como secrets del repo.", file=sys.stderr)
        return None
    try:
        r = requests.post(
            "https://api.cne.cl/api/login",
            data={"email": CNE_EMAIL, "password": CNE_PASSWORD},
            headers={"Accept": "application/json"},
            timeout=20,
        )
        print(f"[CNE] POST /api/login -> status {r.status_code}", file=sys.stderr)
        if not r.ok:
            print(f"[CNE] Cuerpo de la respuesta: {r.text[:500]}", file=sys.stderr)
            return None
        payload = r.json()
        token = payload.get("token")
        if not token:
            print(f"[CNE] Login OK pero sin 'token' en la respuesta. Claves recibidas: {list(payload.keys())}", file=sys.stderr)
            return None
        _CNE_TOKEN = token
        print("[CNE] Login correcto, token obtenido.", file=sys.stderr)
    except Exception as e:
        print(f"[CNE] Error al autenticar: {e}", file=sys.stderr)
        _CNE_TOKEN = None
    return _CNE_TOKEN


def obtener_estaciones_cne():
    global _CNE_ESTACIONES
    if _CNE_ESTACIONES is not None:
        return _CNE_ESTACIONES
    token = cne_login()
    if not token:
        _CNE_ESTACIONES = []
        return _CNE_ESTACIONES
    try:
        r = requests.get(
            "https://api.cne.cl/api/v4/estaciones",
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            timeout=30,
        )
        print(f"[CNE] GET /api/v4/estaciones -> status {r.status_code}", file=sys.stderr)
        if not r.ok:
            print(f"[CNE] Cuerpo de la respuesta: {r.text[:500]}", file=sys.stderr)
            _CNE_ESTACIONES = []
            return _CNE_ESTACIONES
        datos = r.json()
        _CNE_ESTACIONES = datos if isinstance(datos, list) else []
        print(f"[CNE] Estaciones recibidas: {len(_CNE_ESTACIONES)}", file=sys.stderr)
    except Exception as e:
        print(f"[CNE] Error al consultar estaciones: {e}", file=sys.stderr)
        _CNE_ESTACIONES = []
    return _CNE_ESTACIONES


def mejores_precios_ciudad(lat, lon, radio_km=RADIO_KM_COMBUSTIBLE):
    """Devuelve {'93': (precio, marca, direccion), '95': ..., ...} o None."""
    estaciones = obtener_estaciones_cne()
    if not estaciones:
        return None

    mejores = {}
    dentro_del_radio = 0
    for est in estaciones:
        ubic = est.get("ubicacion") or {}
        try:
            elat = float(ubic.get("latitud"))
            elon = float(ubic.get("longitud"))
        except (TypeError, ValueError):
            continue
        if _haversine_km(lat, lon, elat, elon) > radio_km:
            continue
        dentro_del_radio += 1

        precios = est.get("precios") or {}
        marca = (est.get("distribuidor") or {}).get("marca") or "sin marca"
        direccion = ubic.get("direccion") or ""

        for etiqueta, claves in FUEL_KEYS.items():
            for clave in claves:
                oferta = precios.get(clave)
                if not isinstance(oferta, dict):
                    continue
                try:
                    precio = float(oferta.get("precio"))
                except (TypeError, ValueError):
                    continue
                if precio <= 0:
                    continue
                mejor_actual = mejores.get(etiqueta)
                if mejor_actual is None or precio < mejor_actual[0]:
                    mejores[etiqueta] = (precio, marca, direccion)

    print(f"[CNE] {dentro_del_radio} estaciones dentro de {radio_km} km, {len(mejores)} combustibles con precio.", file=sys.stderr)
    return mejores or None


def texto_combustible(nombre_ciudad, lat, lon):
    mejores = mejores_precios_ciudad(lat, lon)
    if not mejores:
        return f"<b>{html.escape(nombre_ciudad)}</b> · revisa bencinaenlinea.cl"

    partes = [f"<b>{html.escape(nombre_ciudad)}</b> (radio {RADIO_KM_COMBUSTIBLE} km):"]
    for etiqueta in ("93", "95", "97", "diésel"):
        if etiqueta in mejores:
            precio, marca, direccion = mejores[etiqueta]
            precio_fmt = f"{precio:,.0f}".replace(",", ".")
            partes.append(
                f"  • {etiqueta}: ${precio_fmt} — {html.escape(marca)} "
                f"<i>({html.escape(direccion)})</i>"
            )
    return "\n".join(partes)


# ---------------------------------------------------------------------------
# NOTICIAS (Google News RSS, gratis, sin API key)
# ---------------------------------------------------------------------------

def buscar_noticias_por_texto(consulta, n):
    q = urllib.parse.quote(consulta)
    url = f"https://news.google.com/rss/search?q={q}&hl=es-419&gl=CL&ceid=CL:es"
    feed = feedparser.parse(url)
    return feed.entries[:n]


def noticias_por_tema(tema, n):
    # temas válidos: WORLD, NATION, BUSINESS, TECHNOLOGY, SCIENCE, SPORTS, HEALTH
    url = f"https://news.google.com/rss/headlines/section/topic/{tema}?hl=es-419&gl=CL&ceid=CL:es"
    feed = feedparser.parse(url)
    return feed.entries[:n]


def formatear_items(entradas):
    """Lista de líneas '• título — fuente' en HTML, con link en el título."""
    lineas = []
    for e in entradas:
        titulo = html.escape(e.title)
        link = e.link
        fuente = ""
        if hasattr(e, "source") and getattr(e.source, "title", None):
            fuente = f" <i>— {html.escape(e.source.title)}</i>"
        lineas.append(f'• <a href="{link}">{titulo}</a>{fuente}')
    return lineas if lineas else ["Sin novedades por ahora."]


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
# ARMADO DEL BOLETÍN (2 mensajes)
# ---------------------------------------------------------------------------

def armar_mensaje_resumen(ahora, es_manana):
    """Mensaje 1: encabezado + resumen rápido + clima + aviso de heladas."""
    emoji_momento = "☀️" if es_manana else "🌙"
    titulo_momento = "Boletín de la mañana" if es_manana else "Boletín de la noche"

    lineas_clima = []
    alertas_helada = []
    temps = []
    for ciudad, datos_ciudad in CIUDADES.items():
        try:
            clima = obtener_clima(datos_ciudad["lat"], datos_ciudad["lon"])
            temp, linea, alerta = resumen_clima_ciudad(ciudad, clima)
            temps.append(temp)
            lineas_clima.append(linea)
            if alerta:
                alertas_helada.append(alerta)
        except Exception:
            lineas_clima.append(f"<b>{html.escape(ciudad)}</b>: no se pudo obtener el clima.")

    temp_prom = round(sum(temps) / len(temps), 1) if temps else None
    resumen_partes = []
    if temp_prom is not None:
        resumen_partes.append(f"{temp_prom}°C promedio")
    resumen_partes.append(f"{len(alertas_helada)} alerta(s) de helada" if alertas_helada else "sin heladas")
    resumen_partes.append("combustible al final del boletín de noticias")

    partes = [
        f"<b>{emoji_momento} {titulo_momento} — {ahora.strftime('%A %d-%m-%Y %H:%M')}</b>",
        f"<i>{' · '.join(resumen_partes)}</i>",
        "",
        "🌦️ <b>Clima</b>",
        "\n".join(lineas_clima),
    ]

    if alertas_helada:
        partes.append("")
        for alerta in alertas_helada:
            partes.append(f"<blockquote>{alerta}</blockquote>")

    return "\n".join(partes)


def armar_mensaje_noticias(ahora, es_manana):
    """Mensaje 2: noticias locales + nacional/mundo/tecnología + combustible."""
    n_local = NOTICIAS_LOCALES["manana" if es_manana else "noche"]
    n_global = NOTICIAS_GLOBALES["manana" if es_manana else "noche"]

    partes = ["📍 <b>Noticias locales</b>"]
    for ciudad in CIUDADES:
        entradas = buscar_noticias_por_texto(f'"{ciudad}" Chile', n_local)
        partes.append(f"<b>{html.escape(ciudad)}</b>")
        partes.extend(formatear_items(entradas))
        partes.append("")

    partes.append(SEPARADOR)
    partes.append("")
    partes.append("🇨🇱🌍💻 <b>Chile, mundo y tecnología</b>")
    partes.extend(formatear_items(noticias_por_tema("NATION", n_global)))
    partes.extend(formatear_items(noticias_por_tema("WORLD", n_global)))
    partes.extend(formatear_items(noticias_por_tema("TECHNOLOGY", n_global)))

    partes.append("")
    partes.append(SEPARADOR)
    partes.append("")
    partes.append("⛽ <b>Combustible</b>")
    for ciudad, datos_ciudad in CIUDADES.items():
        partes.append(texto_combustible(ciudad, datos_ciudad["lat"], datos_ciudad["lon"]))

    return "\n".join(partes)


def main():
    ahora = datetime.now(ZONA_CL)
    if not FORZAR_ENVIO and ahora.hour not in HORAS_DE_ENVIO:
        print(f"Hora actual en Chile: {ahora.strftime('%H:%M')} — no toca enviar boletín. Saliendo.")
        return

    es_manana = ahora.hour < 15

    mensaje_resumen = armar_mensaje_resumen(ahora, es_manana)
    enviar_telegram(mensaje_resumen)

    mensaje_noticias = armar_mensaje_noticias(ahora, es_manana)
    enviar_telegram(mensaje_noticias)

    print("Boletín enviado correctamente (2 mensajes).")


if __name__ == "__main__":
    main()
