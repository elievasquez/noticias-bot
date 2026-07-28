"""
Boletín automático en UNA SOLA IMAGEN PNG (Diseño Dinámico: Mañana / Noche)
Noticias, clima, heladas y precios de combustible para Maule.
"""

import os
import sys
import html
import math
import asyncio
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import feedparser
from playwright.async_api import async_playwright

# ---------------------------------------------------------------------------
# CONFIGURACIÓN
# ---------------------------------------------------------------------------

ZONA_CL = ZoneInfo("America/Santiago")
HORAS_DE_ENVIO = {9, 21}
UMBRAL_HELADA_C = 3.0

CIUDADES = {
    "Longaví":       {"lat": -35.9667, "lon": -71.7000},
    "Linares":       {"lat": -35.8483, "lon": -71.5936},
    "Yerbas Buenas": {"lat": -35.7667, "lon": -71.5833},
}

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
CNE_EMAIL = os.environ.get("CNE_EMAIL")
CNE_PASSWORD = os.environ.get("CNE_PASSWORD")
FORZAR_ENVIO = os.environ.get("FORZAR_ENVIO", "false").lower() == "true"

RADIO_KM_COMBUSTIBLE = 15

WMO_CODES = {
    0: "Despejado", 1: "Mayormente despejado", 2: "Parcialmente nublado",
    3: "Nublado", 45: "Niebla", 48: "Niebla helada", 51: "Llovizna débil",
    53: "Llovizna moderada", 55: "Llovizna intensa", 61: "Lluvia débil",
    63: "Lluvia moderada", 65: "Lluvia intensa", 71: "Nieve débil",
    73: "Nieve moderada", 75: "Nieve intensa", 80: "Chubascos débiles",
    81: "Chubascos moderados", 82: "Chubascos violentos", 95: "Tormenta eléctrica",
}

DIAS_ESP = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MESES_ESP = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

# ---------------------------------------------------------------------------
# CONSULTAS DE DATOS
# ---------------------------------------------------------------------------

def obtener_clima(lat, lon):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,weather_code",
        "timezone": "America/Santiago", "forecast_days": 2,
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

_CNE_TOKEN = None
_CNE_ESTACIONES = None

def cne_login():
    global _CNE_TOKEN
    if _CNE_TOKEN or not CNE_EMAIL or not CNE_PASSWORD: return _CNE_TOKEN
    try:
        r = requests.post("https://api.cne.cl/api/login", data={"email": CNE_EMAIL, "password": CNE_PASSWORD}, headers={"Accept": "application/json"}, timeout=20)
        if r.ok: _CNE_TOKEN = r.json().get("token")
    except Exception: pass
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
    except Exception: _CNE_ESTACIONES = []
    return _CNE_ESTACIONES

def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    d_lat, d_lon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))

def mejores_precios_combustible():
    estaciones = obtener_estaciones_cne()
    mejores = {
        "93": {"monto": "—", "ciudad": "—", "direccion": "—"},
        "95": {"monto": "—", "ciudad": "—", "direccion": "—"},
        "97": {"monto": "—", "ciudad": "—", "direccion": "—"},
        "Diésel": {"monto": "—", "ciudad": "—", "direccion": "—"}
    }
    if not estaciones: 
        return mejores
    
    precios_min = {}
    for est in estaciones:
        ubic = est.get("ubicacion") or {}
        
        # Extraer correctamente el nombre de la comuna desde el objeto/dict o string
        comuna_raw = ubic.get("comuna")
        if isinstance(comuna_raw, dict):
            comuna = comuna_raw.get("nombre") or comuna_raw.get("nom_comuna") or "Maule"
        elif isinstance(comuna_raw, str):
            comuna = comuna_raw
        else:
            comuna = "Maule"

        # Extraer calle y número para armar la dirección exacta
        calle = str(ubic.get("calle") or ubic.get("direccion_calle") or est.get("direccion_calle") or "").strip()
        numero = str(ubic.get("numero") or ubic.get("direccion_numero") or est.get("direccion_numero") or "").strip()
        
        if calle and numero and numero.lower() != "none":
            direccion_str = f"{calle} #{numero}"
        elif calle:
            direccion_str = calle
        else:
            direccion_str = "Dirección N/I"

        try:
            elat, elon = float(ubic.get("latitud")), float(ubic.get("longitud"))
        except (TypeError, ValueError): 
            continue
        
        # Verificar si la estación está dentro del radio de 15 km de alguna de tus ciudades
        cerca = any(_haversine_km(datos["lat"], datos["lon"], elat, elon) <= RADIO_KM_COMBUSTIBLE for datos in CIUDADES.values())
        if not cerca: 
            continue

        precios = est.get("precios") or {}
        mapeo = {"93": ["93", "A93"], "95": ["95", "A95"], "97": ["97", "A97"], "Diésel": ["DI", "ADI"]}
        for k_label, k_keys in mapeo.items():
            for k in k_keys:
                if k in precios and isinstance(precios[k], dict):
                    try:
                        p = float(precios[k].get("precio"))
                        if p > 0 and (k_label not in precios_min or p < precios_min[k_label][0]):
                            precios_min[k_label] = (p, comuna, direccion_str)
                    except (TypeError, ValueError): 
                        pass

    for k, v in precios_min.items():
        mejores[k] = {
            "monto": f"${v[0]:,.0f}".replace(",", "."), 
            "ciudad": v[1],
            "direccion": v[2]
        }
    return mejores

def buscar_noticias(query, n=2):
    q = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={q}&hl=es-419&gl=CL&ceid=CL:es"
    feed = feedparser.parse(url)
    res = []
    for e in feed.entries[:n]:
        fuente = e.source.title if hasattr(e, "source") and getattr(e.source, "title", None) else "Prensa"
        res.append({"titulo": e.title, "fuente": fuente})
    return res

def noticias_tema(tema, n=2):
    url = f"https://news.google.com/rss/headlines/section/topic/{tema}?hl=es-419&gl=CL&ceid=CL:es"
    feed = feedparser.parse(url)
    res = []
    for e in feed.entries[:n]:
        fuente = e.source.title if hasattr(e, "source") and getattr(e.source, "title", None) else "Noticias"
        res.append({"titulo": e.title, "fuente": fuente})
    return res

# ---------------------------------------------------------------------------
# ESTILOS CSS (MAÑANA VS NOCHE)
# ---------------------------------------------------------------------------

CSS_MANANA = """
  body { font-family: 'Poppins', system-ui, -apple-system, sans-serif; color: #33404A; background: #FFFFFF; width: 794px; }
  .pagina { padding: 0 0 28px 0; background: #FFFFFF; }
  
  .masthead { padding: 40px 48px 22px 48px; }
  .masthead-top { display: flex; justify-content: space-between; align-items: baseline; }
  .eyebrow { font-size: 11px; letter-spacing: 1.5px; text-transform: uppercase; color: #2F80ED; font-weight: 700; background: #E5E9EC; padding: 4px 10px; border-radius: 4px; }
  .titulo { font-weight: 700; font-size: 42px; color: #5A6E7F; letter-spacing: -0.5px; margin-top: 12px; }
  .titulo .acento { color: #2F80ED; }
  .fecha-box { text-align: right; color: #8A97A1; font-size: 13px; line-height: 1.6; }
  .fecha-box .dia { font-size: 15px; color: #5A6E7F; font-weight: 600; }
  .masthead-rule { margin-top: 22px; height: 2px; background: #E5E9EC; position: relative; }
  .masthead-rule::after { content: ""; position: absolute; left: 0; top: 0; height: 2px; width: 90px; background: #2F80ED; }
  .comunas { margin-top: 14px; color: #8A97A1; font-size: 12.5px; letter-spacing: 0.3px; }
  .comunas b { color: #5A6E7F; }

  .seccion { padding: 24px 48px 0 48px; }
  .seccion-titulo { font-weight: 700; font-size: 19px; color: #5A6E7F; display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
  .seccion-titulo .barra { width: 22px; height: 4px; background: #2F80ED; border-radius: 2px; display: inline-block; }

  .clima-fila { display: flex; gap: 14px; }
  .clima-card { flex: 1; background: #FFFFFF; border: 1px solid #E5E9EC; border-radius: 10px; padding: 16px 18px; }
  .clima-card .ciudad { font-weight: 700; font-size: 16.5px; color: #5A6E7F; }
  .clima-card .desc { font-size: 12px; color: #8A97A1; margin-top: 2px; }
  .clima-fila-datos { display: flex; align-items: flex-end; justify-content: space-between; margin-top: 14px; }
  .clima-card .temp { font-size: 38px; font-weight: 700; color: #2F80ED; line-height: 1; }
  .clima-card .minmax { font-size: 12px; color: #8A97A1; margin-top: 8px; }
  .clima-card .viento { font-size: 12px; color: #5A6E7F; font-weight: 600; margin-top: 4px; }

  .gauge-box { margin-top: 14px; background: #FFFFFF; border: 1px solid #E5E9EC; border-radius: 10px; padding: 35px 26px 35px 26px; }
  .gauge-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 30px; }
  .gauge-titulo { font-weight: 700; font-size: 14.5px; color: #E0523F; }
  .gauge-nota { font-size: 11px; color: #8A97A1; }
  .gauge-track { position: relative; height: 6px; background: #E5E9EC; border-radius: 3px; }
  .gauge-track-riesgo { position: absolute; left: 0; top: 0; height: 6px; background: #F6C9C1; border-radius: 3px 0 0 3px; }
  .gauge-cero { position: absolute; top: -10px; width: 2px; height: 26px; background: #5A6E7F; }
  .gauge-cero-label { position: absolute; top: -28px; transform: translateX(-50%); font-size: 10px; font-weight: 700; color: #5A6E7F; background: #FFFFFF; padding: 1px 5px; border-radius: 4px; border: 1px solid #E5E9EC; }
  
  .gauge-punto { position: absolute; top: -7px; width: 20px; height: 20px; margin-left: -10px; }
  .gauge-punto .bola { width: 20px; height: 20px; border-radius: 50%; background: #2F80ED; border: 3px solid #FFFFFF; box-shadow: 0 0 0 1px #E5E9EC; }
  .gauge-punto.alerta .bola { background: #E0523F; }
  .gauge-punto .etiqueta { 
    position: absolute; 
    left: 50%; 
    font-size: 10px; 
    white-space: nowrap; 
    line-height: 1.1; 
    padding: 3px 6px; 
    border-radius: 4px; 
    display: flex; 
    gap: 4px; 
    align-items: center; 
    box-shadow: 0 2px 5px rgba(0,0,0,0.1); 
    background: #FFFFFF; 
    color: #33404A; 
    border: 1px solid #E5E9EC; 
  }
  .gauge-punto.pos-abajo .etiqueta { top: 24px; }
  .gauge-punto.pos-arriba .etiqueta { bottom: 24px; }
  .gauge-punto .etiqueta b { font-weight: 700; }
  .gauge-punto.alerta .etiqueta b { color: #E0523F; }
  .gauge-escala { display: flex; justify-content: space-between; margin-top: 35px; font-size: 10px; color: #8A97A1; }

  .noticias-cols { display: flex; gap: 30px; margin-top: 2px; }
  .col { flex: 1; }
  .subgrupo { margin-bottom: 14px; }
  .subgrupo-titulo { display: inline-block; font-size: 11px; font-weight: 700; color: #2F80ED; text-transform: uppercase; letter-spacing: 1px; background: #E5E9EC; padding: 3px 8px; border-radius: 4px; margin-bottom: 8px; }
  .noticia { font-size: 12.5px; line-height: 1.45; margin-bottom: 8px; padding-left: 12px; border-left: 2px solid #E5E9EC; }
  .noticia .titulo-n { color: #33404A; font-weight: 500; }
  .noticia .fuente-n { color: #8A97A1; font-size: 10.5px; margin-top: 2px; }

  .combustible-box { margin-top: 10px; background: #5A6E7F; border-radius: 10px; padding: 20px 26px; }
  .combustible-titulo { color: #FFFFFF; font-size: 15px; font-weight: 700; display: flex; justify-content: space-between; align-items: center; }
  .combustible-titulo span.nota { font-size: 10.5px; color: #C9D3DA; font-weight: 400; }
  .precios-fila { display: flex; gap: 14px; margin-top: 14px; }
  .precio-card { flex: 1; background: #4C5F6F; border-radius: 8px; padding: 12px 10px; text-align: center; }
  .precio-card .tipo { font-size: 11px; color: #8FC1FF; font-weight: 700; letter-spacing: 1px; }
  .precio-card .monto { font-size: 21px; color: #FFFFFF; font-weight: 700; margin-top: 4px; }
  .precio-card .ciudad-p { font-size: 10px; color: #FFFFFF; font-weight: 600; margin-top: 4px; }
  .precio-card .direccion-p { font-size: 8.5px; color: #C9D3DA; margin-top: 2px; line-height: 1.2; word-break: break-word; }

  .footer { margin: 24px 48px 0 48px; padding-top: 14px; border-top: 1px solid #E5E9EC; display: flex; justify-content: space-between; font-size: 10.5px; color: #8A97A1; }
"""

CSS_NOCHE = """
  body { font-family: 'Poppins', system-ui, -apple-system, sans-serif; color: #E1E7EC; background: #18222D; width: 794px; }
  .pagina { padding: 0 0 28px 0; background: #18222D; }
  
  .masthead { padding: 40px 48px 22px 48px; }
  .masthead-top { display: flex; justify-content: space-between; align-items: baseline; }
  .eyebrow { font-size: 11px; letter-spacing: 1.5px; text-transform: uppercase; color: #00E0FF; font-weight: 700; background: #233242; padding: 4px 10px; border-radius: 4px; }
  .titulo { font-weight: 700; font-size: 42px; color: #FFFFFF; letter-spacing: -0.5px; margin-top: 12px; }
  .titulo .acento { color: #00E0FF; }
  .fecha-box { text-align: right; color: #8A9DAE; font-size: 13px; line-height: 1.6; }
  .fecha-box .dia { font-size: 15px; color: #E1E7EC; font-weight: 600; }
  .masthead-rule { margin-top: 22px; height: 2px; background: #2A3B4C; position: relative; }
  .masthead-rule::after { content: ""; position: absolute; left: 0; top: 0; height: 2px; width: 90px; background: #00E0FF; }
  .comunas { margin-top: 14px; color: #8A9DAE; font-size: 12.5px; letter-spacing: 0.3px; }
  .comunas b { color: #FFFFFF; }

  .seccion { padding: 24px 48px 0 48px; }
  .seccion-titulo { font-weight: 700; font-size: 19px; color: #FFFFFF; display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
  .seccion-titulo .barra { width: 22px; height: 4px; background: #00E0FF; border-radius: 2px; display: inline-block; }

  .clima-fila { display: flex; gap: 14px; }
  .clima-card { flex: 1; background: #212E3D; border: 1px solid #2A3B4C; border-radius: 10px; padding: 16px 18px; }
  .clima-card .ciudad { font-weight: 700; font-size: 16.5px; color: #FFFFFF; }
  .clima-card .desc { font-size: 12px; color: #8A9DAE; margin-top: 2px; }
  .clima-fila-datos { display: flex; align-items: flex-end; justify-content: space-between; margin-top: 14px; }
  .clima-card .temp { font-size: 38px; font-weight: 700; color: #00E0FF; line-height: 1; }
  .clima-card .minmax { font-size: 12px; color: #8A9DAE; margin-top: 8px; }
  .clima-card .viento { font-size: 12px; color: #E1E7EC; font-weight: 600; margin-top: 4px; }

  .gauge-box { margin-top: 14px; background: #212E3D; border: 1px solid #2A3B4C; border-radius: 10px; padding: 35px 26px 35px 26px; }
  .gauge-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 30px; }
  .gauge-titulo { font-weight: 700; font-size: 14.5px; color: #FF6B6B; }
  .gauge-nota { font-size: 11px; color: #8A9DAE; }
  .gauge-track { position: relative; height: 6px; background: #2A3B4C; border-radius: 3px; }
  .gauge-track-riesgo { position: absolute; left: 0; top: 0; height: 6px; background: #5A2A2A; border-radius: 3px 0 0 3px; }
  .gauge-cero { position: absolute; top: -10px; width: 2px; height: 26px; background: #8A9DAE; }
  .gauge-cero-label { position: absolute; top: -28px; transform: translateX(-50%); font-size: 10px; font-weight: 700; color: #FFFFFF; background: #212E3D; padding: 1px 5px; border-radius: 4px; border: 1px solid #2A3B4C; }
  
  .gauge-punto { position: absolute; top: -7px; width: 20px; height: 20px; margin-left: -10px; }
  .gauge-punto .bola { width: 20px; height: 20px; border-radius: 50%; background: #00E0FF; border: 3px solid #212E3D; box-shadow: 0 0 0 1px #2A3B4C; }
  .gauge-punto.alerta .bola { background: #FF6B6B; }
  .gauge-punto .etiqueta { 
    position: absolute; 
    left: 50%; 
    font-size: 10px; 
    white-space: nowrap; 
    line-height: 1.1; 
    padding: 3px 6px; 
    border-radius: 4px; 
    display: flex; 
    gap: 4px; 
    align-items: center; 
    box-shadow: 0 2px 5px rgba(0,0,0,0.2); 
    background: #18222D; 
    color: #E1E7EC; 
    border: 1px solid #2A3B4C; 
  }
  .gauge-punto.pos-abajo .etiqueta { top: 24px; }
  .gauge-punto.pos-arriba .etiqueta { bottom: 24px; }
  .gauge-punto .etiqueta b { font-weight: 700; }
  .gauge-punto.alerta .etiqueta b { color: #FF6B6B; }
  .gauge-escala { display: flex; justify-content: space-between; margin-top: 35px; font-size: 10px; color: #8A9DAE; }

  .noticias-cols { display: flex; gap: 30px; margin-top: 2px; }
  .col { flex: 1; }
  .subgrupo { margin-bottom: 14px; }
  .subgrupo-titulo { display: inline-block; font-size: 11px; font-weight: 700; color: #00E0FF; text-transform: uppercase; letter-spacing: 1px; background: #233242; padding: 3px 8px; border-radius: 4px; margin-bottom: 8px; }
  .noticia { font-size: 12.5px; line-height: 1.45; margin-bottom: 8px; padding-left: 12px; border-left: 2px solid #2A3B4C; }
  .noticia .titulo-n { color: #E1E7EC; font-weight: 500; }
  .noticia .fuente-n { color: #8A9DAE; font-size: 10.5px; margin-top: 2px; }

  .combustible-box { margin-top: 10px; background: #212E3D; border: 1px solid #2A3B4C; border-radius: 10px; padding: 20px 26px; }
  .combustible-titulo { color: #FFFFFF; font-size: 15px; font-weight: 700; display: flex; justify-content: space-between; align-items: center; }
  .combustible-titulo span.nota { font-size: 10.5px; color: #8A9DAE; font-weight: 400; }
  .precios-fila { display: flex; gap: 14px; margin-top: 14px; }
  .precio-card { flex: 1; background: #18222D; border: 1px solid #2A3B4C; border-radius: 8px; padding: 12px 10px; text-align: center; }
  .precio-card .tipo { font-size: 11px; color: #00E0FF; font-weight: 700; letter-spacing: 1px; }
  .precio-card .monto { font-size: 21px; color: #FFFFFF; font-weight: 700; margin-top: 4px; }
  .precio-card .ciudad-p { font-size: 10px; color: #FFFFFF; font-weight: 600; margin-top: 4px; }
  .precio-card .direccion-p { font-size: 8.5px; color: #8A9DAE; margin-top: 2px; line-height: 1.2; word-break: break-word; }

  .footer { margin: 24px 48px 0 48px; padding-top: 14px; border-top: 1px solid #2A3B4C; display: flex; justify-content: space-between; font-size: 10.5px; color: #8A9DAE; }
"""

# ---------------------------------------------------------------------------
# RENDERIZADO Y PLAYWRIGHT
# ---------------------------------------------------------------------------

async def html_a_imagen(html_content: str) -> bytes:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 794, "height": 1000}, device_scale_factor=2)
        await page.set_content(html_content, wait_until="networkidle")
        await page.evaluate("document.fonts.ready")
        elemento = await page.query_selector(".pagina")
        img_bytes = await elemento.screenshot(type="png")
        await browser.close()
        return img_bytes

def renderizar_plantilla_html(ahora, es_manana, datos_clima, datos_noticias, datos_combustible):
    edicion_txt = "Edición de la mañana" if es_manana else "Edición de la noche"
    css_tema = CSS_MANANA if es_manana else CSS_NOCHE
    
    dia_nombre = DIAS_ESP[ahora.weekday()]
    mes_nombre = MESES_ESP[ahora.month - 1]
    fecha_txt = f"{dia_nombre} {ahora.day} de {mes_nombre}, {ahora.year}"
    hora_txt = f"Actualizado {ahora.strftime('%H:%M')} hrs"

    # Clima Cards
    clima_cards_html = ""
    for ciudad, info in datos_clima.items():
        clima_cards_html += f"""
        <div class="clima-card">
          <div class="ciudad">{ciudad}</div>
          <div class="desc">{info['desc']}</div>
          <div class="clima-fila-datos">
            <div>
              <div class="minmax">mín {info['min']}° / máx {info['max']}°</div>
              <div class="viento">viento {info['viento']} km/h</div>
            </div>
            <div class="temp">{info['temp']}°</div>
          </div>
        </div>"""

    # -----------------------------------------------------------------------
    # GAUGE HELADAS CON PREVENCIÓN DE SOLAPAMIENTO
    # -----------------------------------------------------------------------
    min_temp, max_temp = -2.0, 10.0
    rango = max_temp - min_temp
    pos_cero = ((0.0 - min_temp) / rango) * 100
    
    ciudades_ordenadas = sorted(datos_clima.items(), key=lambda x: x[1]['tmin_madrugada'])
    
    gauge_puntos_html = ""
    ultimas_pos = []  # Para guardar los porcentajes y detectar cercanía

    for idx, (ciudad, info) in enumerate(ciudades_ordenadas):
        t_min = info['tmin_madrugada']
        pct = max(3, min(97, ((t_min - min_temp) / rango) * 100))
        alerta_cls = "alerta" if t_min <= UMBRAL_HELADA_C else ""
        
        # Alternar posición vertical (arriba / abajo)
        offset_v = "pos-arriba" if idx % 2 == 0 else "pos-abajo"
        
        # Ajuste de desplazamiento horizontal en caso de colisión (< 12% de diferencia)
        shift_x = "transform: translateX(-50%);" # Centrado por defecto
        if ultimas_pos:
            pos_anterior = ultimas_pos[-1]
            if abs(pct - pos_anterior) < 12:
                # Si está muy cerca del anterior, desplazamos levemente
                shift_x = "transform: translateX(-15%);" if idx % 2 == 0 else "transform: translateX(-85%);"
        
        ultimas_pos.append(pct)
        
        gauge_puntos_html += f"""
        <div class="gauge-punto {alerta_cls} {offset_v}" style="left:{pct:.1f}%;">
          <div class="bola"></div>
          <div class="etiqueta" style="{shift_x}">
            <b>{ciudad}</b> <span>{t_min}°C</span>
          </div>
        </div>"""

    # Noticias
    def gen_subgrupo(titulo, lista_noticias):
        items = ""
        for n in lista_noticias:
            items += f"""
            <div class="noticia">
              <div class="titulo-n">{html.escape(n['titulo'])}</div>
              <div class="fuente-n">— {html.escape(n['fuente'])}</div>
            </div>"""
        return f"""<div class="subgrupo"><div class="subgrupo-titulo">{titulo}</div>{items}</div>"""

    noticias_col1 = gen_subgrupo("Longaví", datos_noticias["Longaví"]) + gen_subgrupo("Linares", datos_noticias["Linares"]) + gen_subgrupo("Yerbas Buenas", datos_noticias["Yerbas Buenas"])
    noticias_col2 = gen_subgrupo("Chile", datos_noticias["Chile"]) + gen_subgrupo("Mundo", datos_noticias["Mundo"]) + gen_subgrupo("Tecnología", datos_noticias["Tecnología"])

    return f"""<!DOCTYPE html>
<html lang="es-CL">
<head>
<meta charset="UTF-8">
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  {css_tema}
</style>
</head>
<body>
<div class="pagina">
  <div class="masthead">
    <div class="masthead-top">
      <div>
        <span class="eyebrow">{edicion_txt}</span>
        <div class="titulo">Boletín <span class="acento">Maule</span></div>
      </div>
      <div class="fecha-box">
        <div class="dia">{fecha_txt}</div>
        <div>{hora_txt}</div>
      </div>
    </div>
    <div class="masthead-rule"></div>
    <div class="comunas"><b>Longaví</b> · <b>Linares</b> · <b>Yerbas Buenas</b> — Región del Maule</div>
  </div>

  <div class="seccion">
    <div class="seccion-titulo"><span class="barra"></span>Clima</div>
    <div class="clima-fila">
      {clima_cards_html}
    </div>

    <div class="gauge-box">
      <div class="gauge-header">
        <div class="gauge-titulo">Riesgo de helada — mínima de madrugada</div>
        <div class="gauge-nota">línea = 0°C</div>
      </div>
      <div class="gauge-track">
        <div class="gauge-track-riesgo" style="width:{pos_cero:.1f}%;"></div>
        <div class="gauge-cero" style="left:{pos_cero:.1f}%;"></div>
        <div class="gauge-cero-label" style="left:{pos_cero:.1f}%;">0°</div>
        {gauge_puntos_html}
      </div>
      <div class="gauge-escala"><span>-2°C</span><span>10°C</span></div>
    </div>
  </div>

  <div class="seccion">
    <div class="seccion-titulo"><span class="barra"></span>Noticias</div>
    <div class="noticias-cols">
      <div class="col">{noticias_col1}</div>
      <div class="col">{noticias_col2}</div>
    </div>
  </div>

  <div class="seccion">
    <div class="combustible-box">
      <div class="combustible-titulo">Combustible hoy <span class="nota">mejor precio en radio de 15 km</span></div>
      <div class="precios-fila">
        <div class="precio-card">
          <div class="tipo">93</div>
          <div class="monto">{datos_combustible['93']['monto']}</div>
          <div class="ciudad-p">{datos_combustible['93']['ciudad']}</div>
          <div class="direccion-p">{datos_combustible['93']['direccion']}</div>
        </div>
        <div class="precio-card">
          <div class="tipo">95</div>
          <div class="monto">{datos_combustible['95']['monto']}</div>
          <div class="ciudad-p">{datos_combustible['95']['ciudad']}</div>
          <div class="direccion-p">{datos_combustible['95']['direccion']}</div>
        </div>
        <div class="precio-card">
          <div class="tipo">97</div>
          <div class="monto">{datos_combustible['97']['monto']}</div>
          <div class="ciudad-p">{datos_combustible['97']['ciudad']}</div>
          <div class="direccion-p">{datos_combustible['97']['direccion']}</div>
        </div>
        <div class="precio-card">
          <div class="tipo">Diésel</div>
          <div class="monto">{datos_combustible['Diésel']['monto']}</div>
          <div class="ciudad-p">{datos_combustible['Diésel']['ciudad']}</div>
          <div class="direccion-p">{datos_combustible['Diésel']['direccion']}</div>
        </div>
      </div>
    </div>
  </div>

  <div class="footer">
    <span>By Eliecer Vásquez</span>
    <span>Longaví · Linares · Yerbas Buenas, Región del Maule</span>
  </div>
</div>
</body>
</html>"""

# ---------------------------------------------------------------------------
# ENVÍO Y MAIN
# ---------------------------------------------------------------------------

def enviar_foto_telegram(imagen_bytes):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID.", file=sys.stderr)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    payload = {"chat_id": TELEGRAM_CHAT_ID}
    files = {"photo": ("boletin.png", imagen_bytes, "image/png")}

    resp = requests.post(url, data=payload, files=files, timeout=30)
    print(f"DEBUG Telegram Status Code: {resp.status_code}")
    if not resp.ok:
        print(f"Error Telegram: {resp.text}", file=sys.stderr)
        resp.raise_for_status()

async def main_async():
    ahora = datetime.now(ZONA_CL)
    if not FORZAR_ENVIO and ahora.hour not in HORAS_DE_ENVIO:
        print(f"Hora actual en Chile: {ahora.strftime('%H:%M')} — no toca enviar. Saliendo.")
        return

    # Se considera mañana antes de las 15:00 hrs
    es_manana = ahora.hour < 15

    # 1. Clima
    datos_clima = {}
    for ciudad, coords in CIUDADES.items():
        raw = obtener_clima(coords["lat"], coords["lon"])
        curr = raw["current"]
        daily = raw["daily"]
        datos_clima[ciudad] = {
            "temp": round(curr["temperature_2m"]),
            "min": round(daily["temperature_2m_min"][0]),
            "max": round(daily["temperature_2m_max"][0]),
            "viento": round(curr["wind_speed_10m"]),
            "desc": WMO_CODES.get(curr["weather_code"], "—"),
            "tmin_madrugada": round(daily["temperature_2m_min"][1], 1) if len(daily["temperature_2m_min"]) > 1 else round(daily["temperature_2m_min"][0], 1)
        }

    # 2. Noticias
    datos_noticias = {
        "Longaví": buscar_noticias('"Longaví" Chile', 2),
        "Linares": buscar_noticias('"Linares" Chile', 2),
        "Yerbas Buenas": buscar_noticias('"Yerbas Buenas" Chile', 2),
        "Chile": noticias_tema("NATION", 2),
        "Mundo": noticias_tema("WORLD", 1),
        "Tecnología": noticias_tema("TECHNOLOGY", 1)
    }

    # 3. Combustibles
    datos_combustible = mejores_precios_combustible()

    # 4. Renderizado Dinámico
    html_final = renderizar_plantilla_html(ahora, es_manana, datos_clima, datos_noticias, datos_combustible)
    imagen_bytes = await html_a_imagen(html_final)

    # 5. Enviar
    enviar_foto_telegram(imagen_bytes)
    print(f"Boletín enviado con éxito ({'Edición Mañana - Modo Claro' if es_manana else 'Edición Noche - Modo Oscuro'}).")

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
