"""
Boletín automático de noticias, clima, heladas y precios de combustible
para Longaví, Linares y Yerbas Buenas (Región del Maule, Chile).

Se ejecuta desde GitHub Actions cada hora, y solo genera/envía el boletín
cuando la hora local de Chile es 9:00 o 21:00 (para no depender de si Chile
está en horario de verano o invierno).

El boletín se manda como:
  1. Imagen PNG (Tarjeta de Clima y Heladas)
  2. Resumen rápido + clima + aviso de heladas (Texto)
  3. Noticias + Combustible (Texto)
"""

import os
import sys
import html
import math
import io
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import feedparser
from PIL import Image, ImageDraw, ImageFont

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
CNE_EMAIL = os.environ.get("CNE_EMAIL")        # opcional
CNE_PASSWORD = os.environ.get("CNE_PASSWORD")  # opcional
FORZAR_ENVIO = os.environ.get("FORZAR_ENVIO", "false").lower() == "true"

RADIO_KM_COMBUSTIBLE = 15

NOTICIAS_LOCALES = {"manana": 3, "noche": 1}
NOTICIAS_GLOBALES = {"manana": 2, "noche": 1}
NOTICIAS_FEEDS_ADICIONALES = {"manana": 3, "noche": 1}

FEEDS_ADICIONALES = [
    {"nombre": "Longaví.cl", "url": "https://longavi.cl/feed/"},
    {"nombre": "PuraNoticia", "url": "https://puranoticia.pnt.cl/cms/site/list/port/feed.rss"},
]

WMO_CODES = {
    0: "Despejado", 1: "Mayormente despejado", 2: "Parcialmente nublado",
    3: "Nublado", 45: "Niebla", 48: "Niebla helada", 51: "Llovizna débil",
    53: "Llovizna moderada", 55: "Llovizna intensa", 61: "Lluvia débil",
    63: "Lluvia moderada", 65: "Lluvia intensa", 71: "Nieve débil",
    73: "Nieve moderada", 75: "Nieve intensa", 80: "Chubascos débiles",
    81: "Chubascos moderados", 82: "Chubascos violentos", 95: "Tormenta eléctrica",
}

# Configuración de Paleta y Fuentes para la Tarjeta PNG
TITULAR = (90, 110, 127)
FONDO = (255, 255, 255)
CTA = (47, 128, 237)
SEPARADOR_CARD = (229, 233, 236)
TEXTO_CUERPO = (51, 64, 74)
GRIS_TEXTO = (138, 151, 161)
ALERTA = (224, 82, 63)
ALERTA_FONDO = (253, 235, 232)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS_DIR = os.path.join(BASE_DIR, "assets", "fonts")


# ---------------------------------------------------------------------------
# GENERADOR DE TARJETA PNG
# ---------------------------------------------------------------------------

def _font(nombre, size):
    ruta = os.path.join(FONTS_DIR, nombre)
    try:
        return ImageFont.truetype(ruta, size)
    except OSError:
        return ImageFont.load_default()

def _icono_sol(draw, cx, cy, r, color):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    for i in range(8):
        ang = i * (2 * math.pi / 8)
        x1, y1 = cx + math.cos(ang) * (r + 7), cy + math.sin(ang) * (r + 7)
        x2, y2 = cx + math.cos(ang) * (r + 17), cy + math.sin(ang) * (r + 17)
        draw.line([x1, y1, x2, y2], fill=color, width=4)

def _icono_nube(draw, cx, cy, r, color, color_borde):
    draw.ellipse([cx - r, cy - r * 0.5, cx + r * 0.4, cy + r * 0.6], fill=color, outline=color_borde, width=2)
    draw.ellipse([cx - r * 0.5, cy - r * 0.9, cx + r * 0.9, cy + r * 0.5], fill=color, outline=color_borde, width=2)
    draw.ellipse([cx - r * 1.1, cy - r * 0.3, cx + r * 0.3, cy + r * 0.7], fill=color, outline=color_borde, width=2)

def _icono_viento(draw, x, y, size, color):
    for i, dy in enumerate([0, 9, 18]):
        largo = size - i * 7
        draw.line([x, y + dy, x + largo, y + dy], fill=color, width=3)
        draw.arc([x + largo - 7, y + dy - 5, x + largo + 7, y + dy + 5], -90, 90, fill=color, width=3)

def _icono_copo(draw, cx, cy, r, color):
    for i in range(3):
        ang = i * (math.pi / 3)
        x1, y1 = cx - math.cos(ang) * r, cy - math.sin(ang) * r
        x2, y2 = cx + math.cos(ang) * r, cy + math.sin(ang) * r
        draw.line([x1, y1, x2, y2], fill=color, width=4)

def generar_tarjeta_clima(lista_ciudades, fecha_texto, hora_edicion) -> io.BytesIO:
    f_titulo = _font("Poppins-Bold.ttf", 50)
    f_subtitulo = _font("Poppins-Medium.ttf", 24)
    f_ciudad = _font("Poppins-Bold.ttf", 32)
    f_temp = _font("Poppins-Bold.ttf", 60)
    f_desc = _font("Poppins-Regular.ttf", 22)
    f_dato = _font("Poppins-Medium.ttf", 20)
    f_helada_titulo = _font("Poppins-Bold.ttf", 24)
    f_helada_texto = _font("Poppins-Regular.ttf", 21)
    f_footer = _font("Poppins-Regular.ttf", 18)
    f_etiqueta = _font("Poppins-Bold.ttf", 14)

    W, H = 1200, 1360
    img = Image.new("RGB", (W, H), FONDO)
    draw = ImageDraw.Draw(img)
    margen = 60

    draw.rounded_rectangle([margen, 56, margen + 300, 56 + 34], radius=6, fill=SEPARADOR_CARD)
    draw.text((margen + 16, 63), "EDICIÓN DE LA MAÑANA", font=f_etiqueta, fill=CTA)

    draw.text((margen, 108), "Boletín Maule", font=f_titulo, fill=TITULAR)
    draw.text((margen, 178), f"{hora_edicion} · {fecha_texto}", font=f_subtitulo, fill=GRIS_TEXTO)

    draw.line([margen, 232, margen + 90, 232], fill=CTA, width=3)
    draw.line([margen + 90, 232, W - margen, 232], fill=SEPARADOR_CARD, width=3)

    y_cursor = 268
    card_h = 196
    card_gap = 22

    for c in lista_ciudades:
        box = [margen, y_cursor, W - margen, y_cursor + card_h]
        draw.rounded_rectangle(box, radius=20, fill=FONDO, outline=SEPARADOR_CARD, width=2)

        icon_cx, icon_cy = margen + 84, y_cursor + card_h // 2
        if "Despejado" in c.get("desc", ""):
            _icono_sol(draw, icon_cx, icon_cy, 30, CTA)
        else:
            _icono_nube(draw, icon_cx, icon_cy, 30, SEPARADOR_CARD, TITULAR)

        draw.text((margen + 160, y_cursor + 26), c["nombre"], font=f_ciudad, fill=TITULAR)
        draw.text((margen + 160, y_cursor + 70), c["desc"], font=f_desc, fill=GRIS_TEXTO)
        draw.text((margen + 160, y_cursor + 110), f"mín {c['min']}°  ·  máx {c['max']}°", font=f_dato, fill=GRIS_TEXTO)

        _icono_viento(draw, margen + 160, y_cursor + 150, 40, TITULAR)
        draw.text((margen + 222, y_cursor + 140), f"{c['viento']} km/h", font=f_dato, fill=TITULAR)

        temp_txt = f"{c['temp']}°"
        bbox = draw.textbbox((0, 0), temp_txt, font=f_temp)
        tw = bbox[2] - bbox[0]
        draw.text((W - margen - 40 - tw, y_cursor + card_h // 2 - 42), temp_txt, font=f_temp, fill=CTA)

        y_cursor += card_h + card_gap

    alertas = [c for c in lista_ciudades if c.get("helada")]
    if alertas:
        box_h = 84 + len(alertas) * 42
        box = [margen, y_cursor, W - margen, y_cursor + box_h]
        draw.rounded_rectangle(box, radius=20, fill=ALERTA_FONDO)
        draw.rounded_rectangle([margen, y_cursor, margen + 8, y_cursor + box_h], radius=4, fill=ALERTA)

        _icono_copo(draw, margen + 56, y_cursor + 42, 18, ALERTA)
        draw.text((margen + 92, y_cursor + 24), f"Alerta de helada · {len(alertas)} localidad(es)", font=f_helada_titulo, fill=ALERTA)

        yy = y_cursor + 70
        for c in alertas:
            draw.text((margen + 92, yy), f"{c['nombre']}  —  mínima de {c['tmin_helada']}°C de madrugada", font=f_helada_texto, fill=TEXTO_CUERPO)
            yy += 42

        y_cursor += box_h + card_gap

    draw.line([margen, H - 76, W - margen, H - 76], fill=SEPARADOR_CARD, width=2)
    draw.text((margen, H - 54), "Boletín automático · Longaví · Linares · Yerbas Buenas", font=f_footer, fill=GRIS_TEXTO)

    bio = io.BytesIO()
    bio.name = 'tarjeta_clima.png'
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio


# ---------------------------------------------------------------------------
# CLIMA Y HELADAS
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
    actual = datos["current"]
    diario = datos["daily"]
    desc_actual = WMO_CODES.get(actual["weather_code"], "—")

    linea = (
        f"<b>{html.escape(nombre_ciudad)}</b> {actual['temperature_2m']}°C, "
        f"{desc_actual.lower()} · min {diario['temperature_2m_min'][0]}° / "
        f"máx {diario['temperature_2m_max'][0]}° · 💨 {actual['wind_speed_10m']} km/h"
    )

    alerta = None
    tmin_manana = diario["temperature_2m_min"][1] if len(diario["temperature_2m_min"]) > 1 else None
    helada = False
    if tmin_manana is not None and tmin_manana <= UMBRAL_HELADA_C:
        helada = True
        alerta = (
            f"❄️ <b>Helada en {html.escape(nombre_ciudad)}</b> — "
            f"mínima de {tmin_manana}°C mañana de madrugada"
        )

    dict_tarjeta = {
        "nombre": nombre_ciudad,
        "temp": round(actual["temperature_2m"]),
        "min": round(diario["temperature_2m_min"][0]),
        "max": round(diario["temperature_2m_max"][0]),
        "viento": round(actual["wind_speed_10m"]),
        "desc": desc_actual,
        "helada": helada,
        "tmin_helada": tmin_manana
    }

    return actual["temperature_2m"], linea, alerta, dict_tarjeta


# ---------------------------------------------------------------------------
# PRECIOS DE COMBUSTIBLE & NOTICIAS
# ---------------------------------------------------------------------------

_CNE_TOKEN = None
_CNE_ESTACIONES = None

FUEL_KEYS = {
    "93": ("93", "A93"),
    "95": ("95", "A95"),
    "97": ("97", "A97"),
    "diésel": ("DI", "ADI"),
}

def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    d_lat, d_lon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))

def cne_login():
    global _CNE_TOKEN
    if _CNE_TOKEN: return _CNE_TOKEN
    if not CNE_EMAIL or not CNE_PASSWORD: return None
    try:
        r = requests.post("https://api.cne.cl/api/login", data={"email": CNE_EMAIL, "password": CNE_PASSWORD}, headers={"Accept": "application/json"}, timeout=20)
        if not r.ok: return None
        _CNE_TOKEN = r.json().get("token")
    except Exception:
        _CNE_TOKEN = None
    return _CNE_TOKEN

def obtener_estaciones_cne():
    global _CNE_ESTACIONES
    if _CNE_ESTACIONES is not None: return _CNE_ESTACIONES
    token = cne_login()
    if not token:
        _CNE_ESTACIONES = []
        return _CNE_ESTACIONES
    try:
        r = requests.get("https://api.cne.cl/api/v4/estaciones", headers={"Accept": "application/json", "Authorization": f"Bearer {token}"}, timeout=30)
        _CNE_ESTACIONES = r.json() if r.ok and isinstance(r.json(), list) else []
    except Exception:
        _CNE_ESTACIONES = []
    return _CNE_ESTACIONES

def mejores_precios_ciudad(lat, lon, radio_km=RADIO_KM_COMBUSTIBLE):
    estaciones = obtener_estaciones_cne()
    if not estaciones: return None
    mejores = {}
    for est in estaciones:
        ubic = est.get("ubicacion") or {}
        try:
            elat, elon = float(ubic.get("latitud")), float(ubic.get("longitud"))
        except (TypeError, ValueError): continue
        if _haversine_km(lat, lon, elat, elon) > radio_km: continue
        precios = est.get("precios") or {}
        marca = (est.get("distribuidor") or {}).get("marca") or "sin marca"
        direccion = ubic.get("direccion") or ""
        for etiqueta, claves in FUEL_KEYS.items():
            for clave in claves:
                oferta = precios.get(clave)
                if isinstance(oferta, dict):
                    try:
                        precio = float(oferta.get("precio"))
                        if precio > 0 and (etiqueta not in mejores or precio < mejores[etiqueta][0]):
                            mejores[etiqueta] = (precio, marca, direccion)
                    except (TypeError, ValueError): pass
    return mejores or None

def texto_combustible(nombre_ciudad, lat, lon):
    mejores = mejores_precios_ciudad(lat, lon)
    if not mejores: return f"<b>{html.escape(nombre_ciudad)}</b> · revisa bencinaenlinea.cl"
    partes = [f"<b>{html.escape(nombre_ciudad)}</b> (radio {RADIO_KM_COMBUSTIBLE} km):"]
    for etiqueta in ("93", "95", "97", "diésel"):
        if etiqueta in mejores:
            precio, marca, direccion = mejores[etiqueta]
            partes.append(f"  • {etiqueta}: ${precio:,.0f}".replace(",", ".") + f" — {html.escape(marca)} <i>({html.escape(direccion)})</i>")
    return "\n".join(partes)

def buscar_noticias_por_texto(consulta, n):
    q = urllib.parse.quote(consulta)
    url = f"https://news.google.com/rss/search?q={q}&hl=es-419&gl=CL&ceid=CL:es"
    return feedparser.parse(url).entries[:n]

def noticias_por_tema(tema, n):
    url = f"https://news.google.com/rss/headlines/section/topic/{tema}?hl=es-419&gl=CL&ceid=CL:es"
    return feedparser.parse(url).entries[:n]

def formatear_items(entradas, fuente=None):
    lineas = []
    for e in entradas:
        titulo = html.escape(e.title)
        link = e.link
        fuente_texto = f" <i>— {html.escape(fuente)}</i>" if fuente else (f" <i>— {html.escape(e.source.title)}</i>" if hasattr(e, "source") and getattr(e.source, "title", None) else "")
        lineas.append(f'• <a href="{link}">{titulo}</a>{fuente_texto}')
    return lineas if lineas else ["Sin novedades por ahora."]

def noticias_de_feed(url, n):
    try: return feedparser.parse(url).entries[:n]
    except Exception: return []


# ---------------------------------------------------------------------------
# TELEGRAM
# ---------------------------------------------------------------------------

def enviar_foto_telegram(imagen_bytes, caption=""):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID.", file=sys.stderr)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"}
    files = {"photo": ("tarjeta_clima.png", imagen_bytes, "image/png")}

    resp = requests.post(url, data=payload, files=files, timeout=30)
    print(f"DEBUG Telegram Status Code (Foto): {resp.status_code}")
    print(f"DEBUG Telegram Response (Foto): {resp.text}")
    if not resp.ok:
        resp.raise_for_status()

def enviar_telegram(texto):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID.", file=sys.stderr)
        sys.exit(1)

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    LIMITE = 3900

    bloques, actual = [], ""
    for linea in texto.split("\n"):
        if len(actual) + len(linea) + 1 > LIMITE:
            if actual: bloques.append(actual)
            actual = ""
            while len(linea) > LIMITE:
                bloques.append(linea[:LIMITE])
                linea = linea[LIMITE:]
        actual += linea + "\n"
    if actual: bloques.append(actual)

    bloques_balanceados, blockquote_abierto = [], False
    for bloque in bloques:
        contenido = ("<blockquote>" + bloque) if blockquote_abierto else bloque
        if contenido.count("<blockquote>") > contenido.count("</blockquote>"):
            contenido += "</blockquote>"
            blockquote_abierto = True
        else:
            blockquote_abierto = False
        bloques_balanceados.append(contenido)

    for bloque in bloques_balanceados:
        resp = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": bloque, "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=20)
        print(f"DEBUG Telegram Status Code (Texto): {resp.status_code}")
        if not resp.ok:
            print("Error enviando a Telegram:", resp.text, file=sys.stderr)
            resp.raise_for_status()


# ---------------------------------------------------------------------------
# ARMADO Y EJECUCIÓN
# ---------------------------------------------------------------------------

def armar_mensaje_resumen(ahora, es_manana):
    emoji_momento = "☀️" if es_manana else "🌙"
    titulo_momento = "Boletín de la mañana" if es_manana else "Boletín de la noche"

    lineas_clima, alertas_helada, temps, ciudades_tarjeta = [], [], [], []
    for ciudad, datos_ciudad in CIUDADES.items():
        try:
            clima = obtener_clima(datos_ciudad["lat"], datos_ciudad["lon"])
            temp, linea, alerta, dict_tarjeta = resumen_clima_ciudad(ciudad, clima)
            temps.append(temp)
            lineas_clima.append(linea)
            ciudades_tarjeta.append(dict_tarjeta)
            if alerta: alertas_helada.append(alerta)
        except Exception as e:
            print(f"Error procesando {ciudad}: {e}", file=sys.stderr)
            lineas_clima.append(f"<b>{html.escape(ciudad)}</b>: no se pudo obtener el clima.")

    # Generar la imagen PNG
    fecha_fmt = ahora.strftime('%A %d de %B').capitalize()
    hora_fmt = f"Edición de las {ahora.strftime('%H:%M')}"
    imagen_tarjeta = generar_tarjeta_clima(ciudades_tarjeta, fecha_fmt, hora_fmt)

    temp_prom = round(sum(temps) / len(temps), 1) if temps else None
    resumen_partes = []
    if temp_prom is not None: resumen_partes.append(f"{temp_prom}°C promedio")
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

    return imagen_tarjeta, "\n".join(partes)

def armar_mensaje_noticias(ahora, es_manana):
    n_local = NOTICIAS_LOCALES["manana" if es_manana else "noche"]
    n_global = NOTICIAS_GLOBALES["manana" if es_manana else "noche"]
    n_feed = NOTICIAS_FEEDS_ADICIONALES["manana" if es_manana else "noche"]

    partes = ["📍 <b>Noticias locales</b>"]
    for ciudad in CIUDADES:
        entradas = buscar_noticias_por_texto(f'"{ciudad}" Chile', n_local)
        partes.append(f"<b>{html.escape(ciudad)}</b>")
        partes.extend(formatear_items(entradas))
        partes.append("")

    if FEEDS_ADICIONALES:
        partes.append("📰 <b>Más fuentes locales</b>")
        for feed_info in FEEDS_ADICIONALES:
            entradas = noticias_de_feed(feed_info["url"], n_feed)
            partes.append(f"<b>{html.escape(feed_info['nombre'])}</b>")
            partes.extend(formatear_items(entradas))
            partes.append("")

    partes.extend([SEPARADOR, "", "🇨🇱🌍💻 <b>Chile, mundo y tecnología</b>"])
    partes.extend(formatear_items(noticias_por_tema("NATION", n_global)))
    partes.extend(formatear_items(noticias_por_tema("WORLD", n_global)))
    partes.extend(formatear_items(noticias_por_tema("TECHNOLOGY", n_global)))

    partes.extend(["", SEPARADOR, "", "⛽ <b>Combustible</b>"])
    for ciudad, datos_ciudad in CIUDADES.items():
        partes.append(texto_combustible(ciudad, datos_ciudad["lat"], datos_ciudad["lon"]))

    return "\n".join(partes)

def main():
    ahora = datetime.now(ZONA_CL)
    print(f"DEBUG: Token detectado: {bool(TELEGRAM_TOKEN)}")
    print(f"DEBUG: Chat ID detectado: {TELEGRAM_CHAT_ID}")

    if not FORZAR_ENVIO and ahora.hour not in HORAS_DE_ENVIO:
        print(f"Hora actual en Chile: {ahora.strftime('%H:%M')} — no toca enviar boletín. Saliendo.")
        return

    es_manana = ahora.hour < 15

    try:
        # 1. Armar tarjeta y texto 1
        imagen_tarjeta, mensaje_resumen = armar_mensaje_resumen(ahora, es_manana)

        # 2. Enviar tarjeta PNG por Telegram
        enviar_foto_telegram(imagen_tarjeta, caption="🌦️ <b>Resumen gráfico del Clima</b>")

        # 3. Enviar mensaje de resumen por Telegram
        enviar_telegram(mensaje_resumen)

        # 4. Armar y enviar noticias
        mensaje_noticias = armar_mensaje_noticias(ahora, es_manana)
        enviar_telegram(mensaje_noticias)

        print("Boletín enviado correctamente (Imagen + 2 mensajes).")
    except Exception as e:
        print(f"Error generando/enviando el boletín: {e}", file=sys.stderr)
        try:
            enviar_telegram(
                "⚠️ <b>Error en el boletín</b>\n"
                "No se pudo generar o enviar el boletín completo hoy.\n"
                f"<code>{html.escape(str(e))}</code>"
            )
        except Exception as e2:
            print(f"Además falló el aviso de error por Telegram: {e2}", file=sys.stderr)
        raise

if __name__ == "__main__":
    main()