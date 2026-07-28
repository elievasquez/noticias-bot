"""
Boletín automático en formato PDF Vectorial de Alta Calidad (Diseño Dinámico: Mañana / Noche)
Combina indicadores económicos, clima, heladas, feriados, fase lunar, 
combustibles con badges de colores integrados, 10 categorías de noticias con bajadas en 2 columnas, tabla de fútbol y frases/datos del Maule.
"""

import os
import sys
import re
import html
import math
import time
import asyncio
import datetime
import urllib.parse
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import feedparser
from playwright.async_api import async_playwright

# ==========================================
# CONFIGURACIÓN GENERAL Y VARIABLES ENTORNO
# ==========================================

ZONA_CL = ZoneInfo("America/Santiago")
HORAS_DE_ENVIO = {9, 21}
TOLERANCIA_MINUTOS = 180  # ventana de tolerancia por si GitHub Actions atrasa el cron
ARCHIVO_ESTADO_ENVIO = "estado_envio.json"
UMBRAL_HELADA_C = 3.0

CIUDADES = {
    "Longaví":       {"lat": -35.9667, "lon": -71.7000},
    "Linares":       {"lat": -35.8483, "lon": -71.5936},
    "Yerbas Buenas": {"lat": -35.7667, "lon": -71.5833},
}

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
CNE_EMAIL = os.environ.get("CNE_EMAIL", "")
CNE_PASSWORD = os.environ.get("CNE_PASSWORD", "")
FORZAR_ENVIO = os.environ.get("FORZAR_ENVIO", "false").lower() == "true"

def edicion_objetivo(ahora):
    """
    Determina si 'ahora' cae dentro de la ventana de envío de alguna edición.
    Devuelve 'manana', 'noche' o None si no corresponde enviar todavía.
    """
    minutos_ahora = ahora.hour * 60 + ahora.minute
    for hora_objetivo, nombre in ((9, "manana"), (21, "noche")):
        objetivo = hora_objetivo * 60
        if 0 <= (minutos_ahora - objetivo) <= TOLERANCIA_MINUTOS:
            return nombre
    return None


def cargar_estado_envio():
    try:
        with open(ARCHIVO_ESTADO_ENVIO, "r", encoding="utf-8") as f:
            import json
            return json.load(f)
    except Exception:
        return {}


def guardar_estado_envio(fecha_str, edicion):
    import json
    with open(ARCHIVO_ESTADO_ENVIO, "w", encoding="utf-8") as f:
        json.dump({"fecha": fecha_str, "edicion": edicion}, f)


RADIO_KM_COMBUSTIBLE = 15
EQUIPO_DESTACADO = "None"

WMO_CODES = {
    0: "Despejado", 1: "Mayormente despejado", 2: "Parcialmente nublado",
    3: "Nublado", 45: "Niebla", 48: "Niebla helada", 51: "Llovizna débil",
    53: "Llovizna moderada", 55: "Llovizna intensa", 61: "Lluvia débil",
    63: "Lluvia moderada", 65: "Lluvia intensa", 71: "Nieve débil",
    73: "Nieve moderada", 75: "Nieve intensa", 80: "Chubascos débiles",
    81: "Chubascos moderados", 82: "Chubascos violentos", 95: "Tormenta eléctrica",
}

WMO_ESTILOS = {
    "soleado":   {"codigos": (0, 1),               "icono": "☀️", "oscuro": False,
                  "gradiente": "linear-gradient(135deg, #FDBA13 0%, #F97316 100%)"},
    "parcial":   {"codigos": (2,),                  "icono": "⛅", "oscuro": False,
                  "gradiente": "linear-gradient(135deg, #60A5FA 0%, #3B82F6 100%)"},
    "nublado":   {"codigos": (3,),                  "icono": "☁️", "oscuro": False,
                  "gradiente": "linear-gradient(135deg, #94A3B8 0%, #64748B 100%)"},
    "niebla":    {"codigos": (45, 48),               "icono": "🌫️", "oscuro": True,
                  "gradiente": "linear-gradient(135deg, #E2E8F0 0%, #CBD5E1 100%)"},
    "lluvia":    {"codigos": (51, 53, 55, 61, 63, 65, 80, 81, 82), "icono": "🌧️", "oscuro": False,
                  "gradiente": "linear-gradient(135deg, #3B82F6 0%, #1E3A8A 100%)"},
    "nieve":     {"codigos": (71, 73, 75),           "icono": "❄️", "oscuro": True,
                  "gradiente": "linear-gradient(135deg, #E0F2FE 0%, #BAE6FD 100%)"},
    "tormenta":  {"codigos": (95,),                  "icono": "⛈️", "oscuro": False,
                  "gradiente": "linear-gradient(135deg, #6D28D9 0%, #1E1B4B 100%)"},
}

def estilo_clima(codigo):
    for estilo in WMO_ESTILOS.values():
        if codigo in estilo["codigos"]:
            return estilo
    return WMO_ESTILOS["nublado"]

METRICA_ICONOS = {
    "dolar": {"icono": "💵", "color": "#00A896"},
    "uf":    {"icono": "📊", "color": "#6366F1"},
    "uv":    {"icono": "☀️", "color": "#F97316"},
    "aire":  {"icono": "🌾", "color": "#22C55E"},
}

DIAS_ESP = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MESES_ESP = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

# ==========================================
# SESIÓN HTTP ROBUSTA CON REINTENTOS
# ==========================================

def crear_sesion_robusta():
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS"]
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

HTTP_SESSION = crear_sesion_robusta()

# ==========================================
# OBTENCIÓN DE DATOS ADICIONALES Y EXTRA
# ==========================================

def obtener_indicadores_economicos():
    try:
        r = HTTP_SESSION.get("https://mindicador.cl/api", timeout=8).json()
        uf = f"${r['uf']['valor']:,.0f}".replace(",", ".")
        dolar = f"${r['dolar']['valor']:,.2f}".replace(".", "X").replace(",", ".").replace("X", ",")
        return {"uf": uf, "dolar": dolar}
    except Exception:
        return {"uf": "$37.500", "dolar": "$940,00"}

def obtener_proximo_feriado(ahora):
    try:
        url = "https://apis.digital.gob.cl/fl/feriados/v1"
        headers = {'User-Agent': 'Mozilla/5.0'}
        feriados = HTTP_SESSION.get(url, headers=headers, timeout=8).json()
        
        hoy_str = ahora.strftime("%Y-%m-%d")
        for f in feriados:
            if f["fecha"] >= hoy_str:
                fecha_f = datetime.datetime.strptime(f["fecha"], "%Y-%m-%d").date()
                dias_faltantes = (fecha_f - ahora.date()).days
                
                texto_dias = "¡HOY!" if dias_faltantes == 0 else (f"Faltan {dias_faltantes} días" if dias_faltantes > 1 else "¡Mañana!")
                return {
                    "nombre": f["nombre"],
                    "fecha": fecha_f.strftime("%d de %B"),
                    "dias": texto_dias
                }
    except Exception:
        pass
    return {"nombre": "Fiestas Patrias", "fecha": "18 de Septiembre", "dias": "Próximamente"}

def obtener_fase_lunar_semanal(ahora):
    iconos = ["🌑", "🌒", "🌓", "🌔", "🌕", "🌖", "🌗", "🌘"]
    nombres = ["Nueva", "Creciente", "Cuarto C.", "Gibosa C.", "Llena", "Gibosa M.", "Cuarto M.", "Menguante"]
    
    dias_semana = []
    inicio_semana = ahora - datetime.timedelta(days=ahora.weekday())
    
    for i in range(7):
        dia = inicio_semana + datetime.timedelta(days=i)
        diff = dia.date() - datetime.date(2001, 1, 1)
        days = diff.days
        lunations = 0.20439731 + (days * 0.03386319269)
        index = int((lunations % 1) * 8)
        
        dias_semana.append({
            "fecha": f"{DIAS_ESP[dia.weekday()][:3]} {dia.day:02d}",
            "icono": iconos[index],
            "nombre": nombres[index],
            "es_hoy": dia.date() == ahora.date()
        })
    return dias_semana

def obtener_santoral_y_frase(ahora):
    santorales = {
        1: "San Pedro", 2: "San Pablo", 3: "Santa María", 4: "San Francisco",
        5: "San Juan", 6: "Santa Ana", 7: "San Goran", 8: "San Alberto"
    }
    frases = [
        ('"La simplicidad es la máxima sofisticación."', 'Leonardo da Vinci'),
        ('"El secreto para salir adelante es comenzar."', 'Mark Twain'),
        ('"El único modo de hacer un gran trabajo es amar lo que haces."', 'Steve Jobs')
    ]
    datos_maule = [
        'Linares fue fundada en 1794 como "Villa de San Ambrosio de Linares".',
        'Longaví proviene del mapudungun y significa "Cabeza de Serpiente".',
        'Yerbas Buenas destaca por su histórica arquitectura colonial e iglesia patrimonial.'
    ]
    
    dia_num = ahora.day
    santoral = santorales.get(dia_num % 8 + 1, "San Ambrosio")
    frase, autor = frases[dia_num % len(frases)]
    dato = datos_maule[dia_num % len(datos_maule)]
    
    return {"santoral": santoral, "frase": frase, "autor": autor, "dato": dato}

# ==========================================
# FÚTBOL (ESPN API)
# ==========================================

def obtener_tabla_futbol(top_n=10):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    try:
        url_teams = "https://site.api.espn.com/apis/site/v2/sports/soccer/chi.1/teams"
        r_teams = HTTP_SESSION.get(url_teams, headers=headers, timeout=10)
        logos = {}
        if r_teams.ok:
            data_teams = r_teams.json()
            for t in data_teams.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", []):
                equipo = t.get("team", {})
                if equipo.get("logos"):
                    logos[equipo["id"]] = equipo["logos"][0]["href"]

        url_standings = "https://site.api.espn.com/apis/v2/sports/soccer/chi.1/standings?sort=rank%3Aasc"
        r = HTTP_SESSION.get(url_standings, headers=headers, timeout=10)
        if not r.ok:
            return []

        data = r.json()
        children = data.get("children", [])
        if not children:
            return []
            
        entradas = children[0].get("standings", {}).get("entries", [])

        tabla = []
        for e in entradas:
            stats = {s["name"]: s.get("value", 0) for s in e.get("stats", [])}
            team_info = e.get("team", {})
            team_id = team_info.get("id", "")
            
            nombre_equipo = (
                team_info.get("shortDisplayName") 
                or team_info.get("displayName") 
                or "Equipo"
            )

            tabla.append({
                "posicion": int(stats.get("rank", stats.get("position", 0))),
                "equipo": nombre_equipo,
                "logo": logos.get(team_id, team_info.get("logos", [{}])[0].get("href", "")),
                "pj": int(stats.get("gamesPlayed", 0)),
                "g": int(stats.get("wins", 0)),
                "e": int(stats.get("ties", 0)),
                "p": int(stats.get("losses", 0)),
                "dg": int(stats.get("pointDifferential", 0)),
                "pts": int(stats.get("points", 0)),
            })

        tabla.sort(key=lambda x: (x["posicion"] if x["posicion"] > 0 else 99, -x["pts"], -x["dg"]))
        
        for idx, item in enumerate(tabla, start=1):
            item["posicion"] = idx

        return tabla[:top_n]

    except Exception:
        return []

def renderizar_tabla_futbol(tabla):
    if not tabla:
        return """
        <div class="futbol-box">
          <div style="display:flex;justify-content:space-between;align-items:baseline;">
            <span class="futbol-titulo">Campeonato Nacional</span>
            <span class="futbol-subtitulo">Fútbol chileno</span>
          </div>
          <div style="font-size:11px;color:#94A3B8;margin-top:8px;text-align:center;padding:10px;">
            Tabla de posiciones no disponible en este momento.
          </div>
        </div>"""

    filas_html = ""
    for fila in tabla:
        dg = fila["dg"]
        dg_clase = "futbol-dg-pos" if dg > 0 else ("futbol-dg-neg" if dg < 0 else "")
        dg_texto = f"+{dg}" if dg > 0 else str(dg)
        fila_clase = "futbol-destacado" if fila["equipo"] == EQUIPO_DESTACADO else ""

        filas_html += f"""
        <tr class="{fila_clase}">
          <td class="futbol-pos">{fila['posicion']}</td>
          <td><img class="futbol-escudo" src="{fila['logo']}"></td>
          <td class="futbol-equipo">{html.escape(fila['equipo'])}</td>
          <td>{fila['pj']}</td>
          <td>{fila['g']}</td>
          <td>{fila['p']}</td>
          <td class="{dg_clase}">{dg_texto}</td>
          <td class="futbol-pts">{fila['pts']}</td>
        </tr>"""

    return f"""
    <div class="futbol-box">
      <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px;">
        <span class="futbol-titulo">Campeonato Nacional</span>
        <span class="futbol-subtitulo">Fútbol chileno</span>
      </div>
      <table class="futbol-tabla">
        <thead>
          <tr>
            <th class="izq">#</th><th></th><th class="izq">Equipo</th>
            <th>PJ</th><th>G</th><th>P</th><th>DG</th><th>Pts</th>
          </tr>
        </thead>
        <tbody>{filas_html}</tbody>
      </table>
    </div>"""

# ==========================================
# CONSULTAS DE CLIMA, CNE Y NOTICIAS
# ==========================================

def limpiar_titulo_noticia(titulo_raw):
    partes = titulo_raw.rsplit(" - ", 1)
    if len(partes) > 1:
        return partes[0].strip()
    return titulo_raw.strip()

def limpiar_bajada_rss(summary_raw, titulo):
    if not summary_raw:
        return ""
    
    texto = html.unescape(summary_raw)
    texto = re.sub(r'<[^>]+>', '', texto)
    texto = " ".join(texto.split()).strip()
    
    if texto.lower() == titulo.lower():
        return ""
        
    return texto

def obtener_clima(lat, lon):
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

_CNE_TOKEN = None
_CNE_ESTACIONES = None

def cne_login():
    global _CNE_TOKEN
    if _CNE_TOKEN or not CNE_EMAIL or not CNE_PASSWORD: return _CNE_TOKEN
    try:
        r = HTTP_SESSION.post("https://api.cne.cl/api/login", data={"email": CNE_EMAIL, "password": CNE_PASSWORD}, headers={"Accept": "application/json"}, timeout=20)
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
        r = HTTP_SESSION.get("https://api.cne.cl/api/v4/estaciones", headers={"Accept": "application/json", "Authorization": f"Bearer {token}"}, timeout=30)
        _CNE_ESTACIONES = r.json() if r.ok and isinstance(r.json(), list) else []
    except Exception: _CNE_ESTACIONES = []
    return _CNE_ESTACIONES

def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    d_lat, d_lon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))

def adaptar_direccion(estacion, ubicacion):
    dir_raw = (
        ubicacion.get("direccion") or 
        ubicacion.get("direccion_calle") or 
        estacion.get("direccion") or 
        estacion.get("direccion_calle") or 
        ""
    ).strip()

    num_raw = str(
        ubicacion.get("numero") or 
        ubicacion.get("direccion_numero") or 
        estacion.get("direccion_numero") or 
        ""
    ).strip()

    if dir_raw and num_raw and num_raw.lower() not in ["none", "null", "0", "s/n", "sn"]:
        if num_raw not in dir_raw:
            dir_raw = f"{dir_raw} #{num_raw}"

    if not dir_raw or dir_raw.lower() in ["none", "null"]:
        dir_raw = estacion.get("nombre_fantasia") or estacion.get("razon_social") or "Sin dirección"

    dir_raw = re.sub(r'(?i)\bAvenida\b', 'Av.', dir_raw)
    dir_raw = re.sub(r'(?i)\bPanamericana\b', 'Panam.', dir_raw)

    if len(dir_raw) > 22:
        dir_raw = dir_raw[:21].rstrip(". ") + "…"

    return dir_raw

ESTILOS_COMBUSTIBLE = {
    "93": {"etiqueta": "93", "bg": "#00a896", "text": "#ffffff", "border": "#028090"},
    "95": {"etiqueta": "95", "bg": "#e63946", "text": "#ffffff", "border": "#d62828"},
    "97": {"etiqueta": "97", "bg": "#0077b6", "text": "#ffffff", "border": "#023e8a"},
    "Diésel": {"etiqueta": "Diésel", "bg": "#2b2d42", "text": "#ffffff", "border": "#14213d"}
}

CATEGORIA_ESTILO = {
    "Longaví":              {"icono": "📍", "color": "#1D63ED"},
    "Linares":               {"icono": "📍", "color": "#1D63ED"},
    "Yerbas Buenas":         {"icono": "📍", "color": "#1D63ED"},
    "Chile":                 {"icono": "🇨🇱", "color": "#DC2626"},
    "Mundo":                 {"icono": "🌎", "color": "#0EA5E9"},
    "Salud y Bienestar":     {"icono": "🩺", "color": "#16A34A"},
    "Tecnología":            {"icono": "💻", "color": "#7C3AED"},
    "Deportes":              {"icono": "⚽", "color": "#F97316"},
    "Entretención":          {"icono": "🎬", "color": "#DB2777"},
    "Tendencias en Chile":   {"icono": "🔥", "color": "#CA8A04"},
}

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
        
        comuna_raw = ubic.get("comuna")
        if isinstance(comuna_raw, dict):
            comuna = comuna_raw.get("nombre") or comuna_raw.get("nom_comuna") or "Maule"
        elif isinstance(comuna_raw, str):
            comuna = comuna_raw
        else:
            comuna = "Maule"

        direccion_str = adaptar_direccion(est, ubic)

        try:
            elat, elon = float(ubic.get("latitud")), float(ubic.get("longitud"))
        except (TypeError, ValueError): 
            continue
        
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

def buscar_noticias(query, n=1):
    q = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={q}&hl=es-419&gl=CL&ceid=CL:es"
    feed = feedparser.parse(url)
    res = []
    for e in feed.entries[:n]:
        fuente = e.source.title if hasattr(e, "source") and getattr(e.source, "title", None) else "Prensa"
        titulo_limpio = limpiar_titulo_noticia(e.title)
        summary_raw = getattr(e, "summary", "") or getattr(e, "description", "")
        bajada = limpiar_bajada_rss(summary_raw, titulo_limpio)
        res.append({"titulo": titulo_limpio, "bajada": bajada, "fuente": fuente})
    return res

def noticias_tema(tema, n=1):
    url = f"https://news.google.com/rss/headlines/section/topic/{tema}?hl=es-419&gl=CL&ceid=CL:es"
    feed = feedparser.parse(url)
    res = []
    for e in feed.entries[:n]:
        fuente = e.source.title if hasattr(e, "source") and getattr(e.source, "title", None) else "Noticias"
        titulo_limpio = limpiar_titulo_noticia(e.title)
        summary_raw = getattr(e, "summary", "") or getattr(e, "description", "")
        bajada = limpiar_bajada_rss(summary_raw, titulo_limpio)
        res.append({"titulo": titulo_limpio, "bajada": bajada, "fuente": fuente})
    return res

# ==========================================
# ESTILOS CSS CON TIPOGRAFÍA INTER OPTIMIZADA
# ==========================================

CSS_MANANA = """
  @import url('https://rsms.me/inter/inter.css');
  
  @page {
    size: A4;
    margin: 0;
  }

  :root {
    --bg-page: #FFFFFF;
    --bg-card: #F8FAFC;
    --border-color: #E2E8F0;
    --text-primary: #0F172A;
    --text-secondary: #475569;
    --text-muted: #64748B;
    --accent: #1D63ED;
    --accent-bg: #EBF3FE;
  }

  body { 
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; 
    color: var(--text-primary); 
    background: var(--bg-page); 
    width: 100%; 
    margin: 0;
    padding: 0;
    -webkit-font-smoothing: antialiased; 
    -webkit-print-color-adjust: exact;
    line-height: 1.48;
  }
  
  .pagina { padding: 0 0 32px 0; background: var(--bg-page); }
  
  .masthead { padding: 36px 44px 20px 44px; }
  .masthead-top { display: flex; justify-content: space-between; align-items: baseline; }
  .eyebrow { font-size: 11.5px; letter-spacing: 0.8px; text-transform: uppercase; color: var(--accent); font-weight: 700; background: var(--accent-bg); padding: 6px 12px; border-radius: 6px; }
  .titulo { font-weight: 800; font-size: 38px; color: var(--text-primary); letter-spacing: -0.02em; margin-top: 8px; line-height: 1.1; }
  .titulo .acento { color: var(--accent); }
  
  .fecha-box { text-align: right; color: var(--text-secondary); font-size: 13.5px; line-height: 1.4; }
  .fecha-box .dia { font-size: 15px; color: var(--text-primary); font-weight: 600; }
  .fecha-box .santoral { font-size: 12.5px; color: var(--accent); font-weight: 500; margin-top: 2px; }
  
  .masthead-rule { margin-top: 18px; height: 2px; background: var(--border-color); position: relative; }
  .masthead-rule::after { content: ""; position: absolute; left: 0; top: 0; height: 2px; width: 90px; background: var(--accent); }
  .comunas { margin-top: 12px; color: var(--text-secondary); font-size: 13.5px; letter-spacing: 0.1px; }
  .comunas b { color: var(--text-primary); font-weight: 600; }

  /* METRICAS */
  .metrics-bar { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; background: var(--bg-card); border: 1px solid var(--border-color); padding: 14px 16px; border-radius: 12px; margin: 16px 44px 0 44px; }
  .metric-item { display: flex; align-items: center; gap: 10px; font-size: 11.5px; color: var(--text-secondary); font-weight: 500; }
  .metric-icono { width: 34px; height: 34px; min-width: 34px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 16px; }
  .metric-value { font-weight: 700; font-size: 14.5px; color: var(--text-primary); margin-top: 2px; }

  /* FERIADO */
  .holiday-box { margin: 16px 44px 0 44px; background: var(--accent-bg); border: 1px solid #BFDBFE; border-radius: 12px; padding: 12px 18px; display: flex; justify-content: space-between; align-items: center; position: relative; overflow: hidden; }
  .holiday-box::before { content: "🎉"; position: absolute; right: -6px; top: -14px; font-size: 64px; opacity: 0.12; transform: rotate(-10deg); }
  .holiday-title { font-size: 11.5px; font-weight: 700; color: var(--accent); text-transform: uppercase; letter-spacing: 0.5px; }
  .holiday-desc { font-size: 13.5px; font-weight: 700; color: var(--text-primary); margin-top: 2px; }
  .holiday-badge { background: var(--accent); color: #FFFFFF; font-weight: 700; font-size: 11.5px; padding: 5px 12px; border-radius: 20px; }

  /* SECCIONES */
  .seccion { padding: 22px 44px 0 44px; page-break-inside: avoid; }
  .seccion-titulo { font-weight: 700; font-size: 19px; color: var(--text-primary); display: flex; align-items: center; gap: 10px; margin-bottom: 14px; letter-spacing: -0.01em; }
  .seccion-titulo .barra { width: 16px; height: 4px; background: var(--accent); border-radius: 2px; display: inline-block; }

  /* CLIMA CARDS */
  .clima-fila { display: flex; gap: 14px; }
  .clima-card { flex: 1; border-radius: 12px; padding: 16px; position: relative; overflow: hidden; box-shadow: 0 4px 12px rgba(15,23,42,0.10); color: rgba(255,255,255,0.95); }
  .clima-card.texto-oscuro { color: rgba(15,23,42,0.85); }
  .clima-icono-fondo { position: absolute; right: -10px; bottom: -16px; font-size: 74px; opacity: 0.20; line-height: 1; }
  .clima-card .ciudad { font-weight: 700; font-size: 16px; position: relative; }
  .clima-card .desc { font-size: 12.5px; opacity: 0.85; margin-top: 2px; font-weight: 500; position: relative; }
  .clima-fila-datos { display: flex; align-items: flex-end; justify-content: space-between; margin-top: 14px; position: relative; }
  .clima-card .temp { font-size: 38px; font-weight: 800; line-height: 0.9; letter-spacing: -0.03em; text-shadow: 0 2px 6px rgba(0,0,0,0.12); }
  .clima-card .minmax { font-size: 12px; opacity: 0.85; font-weight: 500; }
  .clima-card .viento { font-size: 12px; font-weight: 600; margin-top: 3px; opacity: 0.95; }

  /* HELADAS GAUGE */
  .gauge-box { margin-top: 16px; background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 12px; padding: 32px 24px 24px 24px; }
  .gauge-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 28px; }
  .gauge-titulo { font-weight: 700; font-size: 15px; color: #DC2626; }
  .gauge-nota { font-size: 12px; color: var(--text-secondary); font-weight: 500; }
  .gauge-track { position: relative; height: 6px; background: #CBD5E1; border-radius: 3px; }
  .gauge-track-riesgo { position: absolute; left: 0; top: 0; height: 6px; background: #FCA5A5; border-radius: 3px 0 0 3px; }
  .gauge-cero { position: absolute; top: -10px; width: 2px; height: 26px; background: #475569; }
  .gauge-cero-label { position: absolute; top: -28px; transform: translateX(-50%); font-size: 11px; font-weight: 700; color: var(--text-primary); background: #FFFFFF; padding: 2px 6px; border-radius: 4px; border: 1px solid var(--border-color); }
  
  .gauge-punto { position: absolute; top: -7px; width: 20px; height: 20px; margin-left: -10px; }
  .gauge-punto .bola { width: 20px; height: 20px; border-radius: 50%; background: var(--accent); border: 3px solid #FFFFFF; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
  .gauge-punto.alerta .bola { background: #DC2626; }
  .gauge-punto .etiqueta { position: absolute; left: 50%; font-size: 11px; white-space: nowrap; padding: 4px 8px; border-radius: 6px; display: flex; gap: 4px; align-items: center; box-shadow: 0 2px 6px rgba(0,0,0,0.06); background: #FFFFFF; color: var(--text-primary); border: 1px solid var(--border-color); }
  .gauge-punto.pos-abajo .etiqueta { top: 25px; }
  .gauge-punto.pos-arriba .etiqueta { bottom: 25px; }
  .gauge-punto .etiqueta b { font-weight: 700; }
  .gauge-punto.alerta .etiqueta b { color: #DC2626; }
  .gauge-escala { display: flex; justify-content: space-between; margin-top: 32px; font-size: 11px; color: var(--text-secondary); font-weight: 500; }

  /* FASE LUNAR */
  .lunar-bar { background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 12px; padding: 12px 14px; margin-top: 14px; }
  .lunar-title { font-size: 11.5px; text-transform: uppercase; letter-spacing: 0.8px; color: var(--text-secondary); font-weight: 700; margin-bottom: 8px; text-align: center; }
  .lunar-days { display: flex; justify-content: space-around; align-items: center; }
  .lunar-day { display: flex; flex-direction: column; align-items: center; font-size: 11px; color: var(--text-secondary); font-weight: 500; }
  .lunar-day.today { color: var(--accent); font-weight: 700; transform: scale(1.05); }
  .lunar-icon { font-size: 18px; margin: 2px 0; }

  /* NOTICIAS OPTIMIZADAS */
  .noticias-cols { display: flex; gap: 18px; margin-top: 4px; }
  .col { flex: 1; display: flex; flex-direction: column; gap: 12px; }
  .subgrupo { margin-bottom: 0; page-break-inside: avoid; }
  .subgrupo-titulo { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.6px; padding: 4px 10px; border-radius: 20px; margin-bottom: 8px; }
  
  .noticia { 
    font-size: 13.5px; 
    line-height: 1.45; 
    padding: 10px 14px; 
    background: var(--bg-card); 
    border-left: 3px solid var(--accent); 
    border-radius: 0 8px 8px 0; 
    border-top: 1px solid var(--border-color); 
    border-right: 1px solid var(--border-color); 
    border-bottom: 1px solid var(--border-color); 
    page-break-inside: avoid;
  }
  .noticia .titulo-n { color: var(--text-primary); font-weight: 700; font-size: 13.5px; line-height: 1.35; letter-spacing: -0.01em; margin-bottom: 4px; }
  
  .noticia .bajada-n { 
    color: var(--text-secondary); 
    font-size: 12px; 
    font-weight: 400; 
    line-height: 1.45; 
    display: -webkit-box;
    -webkit-line-clamp: 5;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .noticia .fuente-n { color: var(--text-muted); font-size: 11px; margin-top: 6px; font-weight: 500; }

  /* TABLA FÚTBOL */
  .futbol-box { margin-top: 14px; background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 12px; padding: 14px 16px; page-break-inside: avoid; }
  .futbol-titulo { font-size: 14px; font-weight: 700; color: var(--text-primary); }
  .futbol-subtitulo { font-size: 12px; color: var(--text-secondary); font-weight: 500; }
  .futbol-tabla { width: 100%; border-collapse: collapse; table-layout: fixed; }
  .futbol-tabla th { font-size: 10px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; font-weight: 700; padding: 0 0 6px 0; text-align: center; }
  .futbol-tabla th.izq { text-align: left; }
  .futbol-tabla td { padding: 6px 0; font-size: 12px; color: var(--text-secondary); border-top: 1px solid var(--border-color); text-align: center; }
  .futbol-pos { font-weight: 700; color: var(--text-muted); text-align: left !important; }
  .futbol-escudo { width: 18px; height: 18px; object-fit: contain; }
  .futbol-equipo { font-size: 12.5px; font-weight: 600; color: var(--text-primary); text-align: left !important; }
  .futbol-pts { font-size: 12.5px; font-weight: 800; color: var(--accent); }
  .futbol-dg-pos { color: #16A34A; font-weight: 600; }
  .futbol-dg-neg { color: #DC2626; font-weight: 600; }
  .futbol-destacado { background: rgba(29, 99, 237, 0.06); }
  .futbol-destacado .futbol-pos { border-left: 3px solid var(--accent); padding-left: 6px; color: var(--accent); }

  /* COMBUSTIBLES */
  .combustible-box { margin-top: 14px; background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 12px; padding: 18px 20px; page-break-inside: avoid; }
  .combustible-titulo { color: var(--text-primary); font-size: 15px; font-weight: 700; display: flex; justify-content: space-between; align-items: center; }
  .combustible-titulo span.nota { font-size: 12px; color: var(--text-secondary); font-weight: 500; }
  .precios-fila { display: flex; gap: 12px; margin-top: 12px; }
  .precio-card { flex: 1; border: 1px solid var(--border-color); border-radius: 10px; padding: 12px 8px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
  .precio-badge { display: inline-block; font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 6px; margin-bottom: 4px; }
  .precio-card .monto { font-size: 20px; color: var(--text-primary); font-weight: 800; margin-top: 2px; letter-spacing: -0.02em; }
  .precio-card .ciudad-p { font-size: 11.5px; color: var(--text-primary); font-weight: 600; margin-top: 3px; }
  .precio-card .direccion-p { font-size: 10px; color: var(--text-secondary); margin-top: 2px; line-height: 1.3; min-height: 24px; display: flex; align-items: center; justify-content: center; }

  /* FOOTER & EXTRAS */
  .footer-boxes { display: flex; gap: 14px; margin-top: 14px; page-break-inside: avoid; }
  .footer-box { flex: 1; background: var(--bg-card); border: 1px solid var(--border-color); border-left: 4px solid var(--accent); padding: 12px 14px; border-radius: 0 10px 10px 0; position: relative; overflow: hidden; }
  .footer-box-icono { position: absolute; right: 2px; top: -6px; font-size: 42px; opacity: 0.08; }
  .footer-box-title { font-size: 11px; font-weight: 700; color: var(--text-muted); margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px; position: relative; }
  .footer-box-text { font-size: 12.5px; color: var(--text-primary); font-style: italic; line-height: 1.45; position: relative; }

  .footer { margin: 24px 44px 0 44px; padding-top: 14px; border-top: 1px solid var(--border-color); display: flex; justify-content: space-between; font-size: 11.5px; color: var(--text-secondary); font-weight: 500; }
"""

CSS_NOCHE = """
  @import url('https://rsms.me/inter/inter.css');

  @page {
    size: A4;
    margin: 0;
  }

  :root {
    --bg-page: #0F172A;
    --bg-card: #1E293B;
    --border-color: #334155;
    --text-primary: #F8FAFC;
    --text-secondary: #CBD5E1;
    --text-muted: #94A3B8;
    --accent: #38BDF8;
    --accent-bg: rgba(56, 189, 248, 0.12);
  }

  body { 
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; 
    color: var(--text-primary); 
    background: var(--bg-page); 
    width: 100%; 
    margin: 0;
    padding: 0;
    -webkit-font-smoothing: antialiased; 
    -webkit-print-color-adjust: exact;
    line-height: 1.48;
  }
  
  .pagina { padding: 0 0 32px 0; background: var(--bg-page); }
  
  .masthead { padding: 36px 44px 20px 44px; }
  .masthead-top { display: flex; justify-content: space-between; align-items: baseline; }
  .eyebrow { font-size: 11.5px; letter-spacing: 0.8px; text-transform: uppercase; color: var(--accent); font-weight: 700; background: var(--bg-card); padding: 6px 12px; border-radius: 6px; border: 1px solid var(--border-color); }
  .titulo { font-weight: 800; font-size: 38px; color: var(--text-primary); letter-spacing: -0.02em; margin-top: 8px; line-height: 1.1; }
  .titulo .acento { color: var(--accent); }
  
  .fecha-box { text-align: right; color: var(--text-secondary); font-size: 13.5px; line-height: 1.4; }
  .fecha-box .dia { font-size: 15px; color: var(--text-primary); font-weight: 600; }
  .fecha-box .santoral { font-size: 12.5px; color: var(--accent); font-weight: 500; margin-top: 2px; }
  
  .masthead-rule { margin-top: 18px; height: 2px; background: var(--border-color); position: relative; }
  .masthead-rule::after { content: ""; position: absolute; left: 0; top: 0; height: 2px; width: 90px; background: var(--accent); }
  .comunas { margin-top: 12px; color: var(--text-secondary); font-size: 13.5px; letter-spacing: 0.1px; }
  .comunas b { color: var(--text-primary); font-weight: 600; }

  /* METRICAS */
  .metrics-bar { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; background: var(--bg-card); border: 1px solid var(--border-color); padding: 14px 16px; border-radius: 12px; margin: 16px 44px 0 44px; }
  .metric-item { display: flex; align-items: center; gap: 10px; font-size: 11.5px; color: var(--text-secondary); font-weight: 500; }
  .metric-icono { width: 34px; height: 34px; min-width: 34px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 16px; }
  .metric-value { font-weight: 700; font-size: 14.5px; color: var(--text-primary); margin-top: 2px; }

  /* FERIADO */
  .holiday-box { margin: 16px 44px 0 44px; background: var(--accent-bg); border: 1px solid rgba(56, 189, 248, 0.3); border-radius: 12px; padding: 12px 18px; display: flex; justify-content: space-between; align-items: center; position: relative; overflow: hidden; }
  .holiday-box::before { content: "🎉"; position: absolute; right: -6px; top: -14px; font-size: 64px; opacity: 0.10; transform: rotate(-10deg); }
  .holiday-title { font-size: 11.5px; font-weight: 700; color: var(--accent); text-transform: uppercase; letter-spacing: 0.5px; }
  .holiday-desc { font-size: 13.5px; font-weight: 700; color: var(--text-primary); margin-top: 2px; }
  .holiday-badge { background: var(--accent); color: #0F172A; font-weight: 700; font-size: 11.5px; padding: 5px 12px; border-radius: 20px; }

  /* SECCIONES */
  .seccion { padding: 22px 44px 0 44px; page-break-inside: avoid; }
  .seccion-titulo { font-weight: 700; font-size: 19px; color: var(--text-primary); display: flex; align-items: center; gap: 10px; margin-bottom: 14px; letter-spacing: -0.01em; }
  .seccion-titulo .barra { width: 16px; height: 4px; background: var(--accent); border-radius: 2px; display: inline-block; }

  /* CLIMA CARDS */
  .clima-fila { display: flex; gap: 14px; }
  .clima-card { flex: 1; border-radius: 12px; padding: 16px; position: relative; overflow: hidden; box-shadow: 0 4px 14px rgba(0,0,0,0.35); color: rgba(255,255,255,0.95); }
  .clima-card.texto-oscuro { color: rgba(15,23,42,0.85); }
  .clima-icono-fondo { position: absolute; right: -10px; bottom: -16px; font-size: 74px; opacity: 0.22; line-height: 1; }
  .clima-card .ciudad { font-weight: 700; font-size: 16px; position: relative; }
  .clima-card .desc { font-size: 12.5px; opacity: 0.85; margin-top: 2px; font-weight: 500; position: relative; }
  .clima-fila-datos { display: flex; align-items: flex-end; justify-content: space-between; margin-top: 14px; position: relative; }
  .clima-card .temp { font-size: 38px; font-weight: 800; line-height: 0.9; letter-spacing: -0.03em; text-shadow: 0 2px 6px rgba(0,0,0,0.25); }
  .clima-card .minmax { font-size: 12px; opacity: 0.85; font-weight: 500; }
  .clima-card .viento { font-size: 12px; font-weight: 600; margin-top: 3px; opacity: 0.95; }

  /* HELADAS GAUGE */
  .gauge-box { margin-top: 16px; background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 12px; padding: 32px 24px 24px 24px; }
  .gauge-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 28px; }
  .gauge-titulo { font-weight: 700; font-size: 15px; color: #F87171; }
  .gauge-nota { font-size: 12px; color: var(--text-secondary); font-weight: 500; }
  .gauge-track { position: relative; height: 6px; background: #334155; border-radius: 3px; }
  .gauge-track-riesgo { position: absolute; left: 0; top: 0; height: 6px; background: #991B1B; border-radius: 3px 0 0 3px; }
  .gauge-cero { position: absolute; top: -10px; width: 2px; height: 26px; background: #94A3B8; }
  .gauge-cero-label { position: absolute; top: -28px; transform: translateX(-50%); font-size: 11px; font-weight: 700; color: var(--text-primary); background: #0F172A; padding: 2px 6px; border-radius: 4px; border: 1px solid var(--border-color); }
  
  .gauge-punto { position: absolute; top: -7px; width: 20px; height: 20px; margin-left: -10px; }
  .gauge-punto .bola { width: 20px; height: 20px; border-radius: 50%; background: var(--accent); border: 3px solid #1E293B; box-shadow: 0 1px 3px rgba(0,0,0,0.3); }
  .gauge-punto.alerta .bola { background: #F87171; }
  .gauge-punto .etiqueta { position: absolute; left: 50%; font-size: 11px; white-space: nowrap; padding: 4px 8px; border-radius: 6px; display: flex; gap: 4px; align-items: center; box-shadow: 0 2px 6px rgba(0,0,0,0.3); background: #0F172A; color: var(--text-primary); border: 1px solid var(--border-color); }
  .gauge-punto.pos-abajo .etiqueta { top: 25px; }
  .gauge-punto.pos-arriba .etiqueta { bottom: 25px; }
  .gauge-punto .etiqueta b { font-weight: 700; }
  .gauge-punto.alerta .etiqueta b { color: #F87171; }
  .gauge-escala { display: flex; justify-content: space-between; margin-top: 32px; font-size: 11px; color: var(--text-secondary); font-weight: 500; }

  /* FASE LUNAR */
  .lunar-bar { background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 12px; padding: 12px 14px; margin-top: 14px; }
  .lunar-title { font-size: 11.5px; text-transform: uppercase; letter-spacing: 0.8px; color: var(--text-secondary); font-weight: 700; margin-bottom: 8px; text-align: center; }
  .lunar-days { display: flex; justify-content: space-around; align-items: center; }
  .lunar-day { display: flex; flex-direction: column; align-items: center; font-size: 11px; color: var(--text-secondary); font-weight: 500; }
  .lunar-day.today { color: #FACC15; font-weight: 700; transform: scale(1.05); }
  .lunar-icon { font-size: 18px; margin: 2px 0; }

  /* NOTICIAS OPTIMIZADAS */
  .noticias-cols { display: flex; gap: 18px; margin-top: 4px; }
  .col { flex: 1; display: flex; flex-direction: column; gap: 12px; }
  .subgrupo { margin-bottom: 0; page-break-inside: avoid; }
  .subgrupo-titulo { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.6px; padding: 4px 10px; border-radius: 20px; margin-bottom: 8px; }
  
  .noticia { 
    font-size: 13.5px; 
    line-height: 1.45; 
    padding: 10px 14px; 
    background: var(--bg-card); 
    border-left: 3px solid var(--accent); 
    border-radius: 0 8px 8px 0; 
    border-top: 1px solid #2B394A; 
    border-right: 1px solid #2B394A; 
    border-bottom: 1px solid #2B394A; 
    page-break-inside: avoid;
  }
  .noticia .titulo-n { color: var(--text-primary); font-weight: 700; font-size: 13.5px; line-height: 1.35; letter-spacing: -0.01em; margin-bottom: 4px; }
  
  .noticia .bajada-n { 
    color: var(--text-secondary); 
    font-size: 12px; 
    font-weight: 400; 
    line-height: 1.45; 
    display: -webkit-box;
    -webkit-line-clamp: 5;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .noticia .fuente-n { color: var(--text-muted); font-size: 11px; margin-top: 6px; font-weight: 500; }

  /* TABLA FÚTBOL */
  .futbol-box { margin-top: 14px; background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 12px; padding: 14px 16px; page-break-inside: avoid; }
  .futbol-titulo { font-size: 14px; font-weight: 700; color: var(--text-primary); }
  .futbol-subtitulo { font-size: 12px; color: var(--text-secondary); font-weight: 500; }
  .futbol-tabla { width: 100%; border-collapse: collapse; table-layout: fixed; }
  .futbol-tabla th { font-size: 10px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; font-weight: 700; padding: 0 0 6px 0; text-align: center; }
  .futbol-tabla th.izq { text-align: left; }
  .futbol-tabla td { padding: 6px 0; font-size: 12px; color: var(--text-secondary); border-top: 1px solid var(--border-color); text-align: center; }
  .futbol-pos { font-weight: 700; color: var(--text-muted); text-align: left !important; }
  .futbol-escudo { width: 18px; height: 18px; object-fit: contain; }
  .futbol-equipo { font-size: 12.5px; font-weight: 600; color: var(--text-primary); text-align: left !important; }
  .futbol-pts { font-size: 12.5px; font-weight: 800; color: var(--accent); }
  .futbol-dg-pos { color: #4ADE80; font-weight: 600; }
  .futbol-dg-neg { color: #F87171; font-weight: 600; }
  .futbol-destacado { background: rgba(56, 189, 248, 0.08); }
  .futbol-destacado .futbol-pos { border-left: 3px solid var(--accent); padding-left: 6px; color: var(--accent); }

  /* COMBUSTIBLES */
  .combustible-box { margin-top: 14px; background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 12px; padding: 18px 20px; page-break-inside: avoid; }
  .combustible-titulo { color: var(--text-primary); font-size: 15px; font-weight: 700; display: flex; justify-content: space-between; align-items: center; }
  .combustible-titulo span.nota { font-size: 12px; color: var(--text-secondary); font-weight: 500; }
  .precios-fila { display: flex; gap: 12px; margin-top: 12px; }
  .precio-card { flex: 1; border: 1px solid var(--border-color); border-radius: 10px; padding: 12px 8px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.2); }
  .precio-badge { display: inline-block; font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 6px; margin-bottom: 4px; }
  .precio-card .monto { font-size: 20px; color: var(--text-primary); font-weight: 800; margin-top: 2px; letter-spacing: -0.02em; }
  .precio-card .ciudad-p { font-size: 11.5px; color: var(--text-primary); font-weight: 600; margin-top: 3px; }
  .precio-card .direccion-p { font-size: 10px; color: var(--text-secondary); margin-top: 2px; line-height: 1.3; min-height: 24px; display: flex; align-items: center; justify-content: center; }

  /* FOOTER & EXTRAS */
  .footer-boxes { display: flex; gap: 14px; margin-top: 14px; page-break-inside: avoid; }
  .footer-box { flex: 1; background: var(--bg-card); border: 1px solid var(--border-color); border-left: 4px solid var(--accent); padding: 12px 14px; border-radius: 0 10px 10px 0; position: relative; overflow: hidden; }
  .footer-box-icono { position: absolute; right: 2px; top: -6px; font-size: 42px; opacity: 0.12; }
  .footer-box-title { font-size: 11px; font-weight: 700; color: var(--text-muted); margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px; position: relative; }
  .footer-box-text { font-size: 12.5px; color: var(--text-primary); font-style: italic; line-height: 1.45; position: relative; }

  .footer { margin: 24px 44px 0 44px; padding-top: 14px; border-top: 1px solid var(--border-color); display: flex; justify-content: space-between; font-size: 11.5px; color: var(--text-secondary); font-weight: 500; }
"""

# ==========================================
# RENDERIZADO HTML Y PLAYWRIGHT (PDF VECTORIAL)
# ==========================================

async def html_a_pdf(html_content: str) -> bytes:
    """Genera un archivo PDF vectorial utilizando la API nativa de Playwright."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 794, "height": 1123})
        await page.set_content(html_content, wait_until="networkidle")
        await page.evaluate("document.fonts.ready")
        
        pdf_bytes = await page.pdf(
            format="A4",
            print_background=True,
            margin={"top": "0mm", "bottom": "0mm", "left": "0mm", "right": "0mm"}
        )
        
        await browser.close()
        print(f"📄 Tamaño final del PDF: {len(pdf_bytes)/1024:.0f} KB")
        return pdf_bytes

def renderizar_plantilla_html(ahora, fecha_reporte, es_manana, eco, feriado, luna, extra, datos_clima, datos_noticias, datos_combustible, html_futbol=""):
    edicion_txt = "Edición de la mañana" if es_manana else "Edición de la noche"
    css_tema = CSS_MANANA if es_manana else CSS_NOCHE
    
    titulo_clima = "Clima para hoy" if es_manana else "Pronóstico clima para mañana"
    subtitulo_heladas = "mínima para hoy en la madrugada" if es_manana else "mínima para la próxima madrugada"

    dia_nombre = DIAS_ESP[fecha_reporte.weekday()]
    mes_nombre = MESES_ESP[fecha_reporte.month - 1]
    fecha_txt = f"{dia_nombre} {fecha_reporte.day} de {mes_nombre}, {fecha_reporte.year}"
    hora_txt = f"Actualizado {ahora.strftime('%H:%M')} hrs"

    clima_cards_html = ""
    uv_max_prom = 0
    for ciudad, info in datos_clima.items():
        uv_max_prom += info.get("uv", 0)
        estilo = estilo_clima(info.get("codigo", 3))
        clase_extra = " texto-oscuro" if estilo["oscuro"] else ""
        clima_cards_html += f"""
        <div class="clima-card{clase_extra}" style="background:{estilo['gradiente']};">
          <div class="clima-icono-fondo">{estilo['icono']}</div>
          <div class="ciudad">{ciudad}</div>
          <div class="desc">{estilo['icono']} {info['desc']}</div>
          <div class="clima-fila-datos">
            <div>
              <div class="minmax">mín {info['min']}° / máx {info['max']}°</div>
              <div class="viento">viento {info['viento']} km/h</div>
            </div>
            <div class="temp">{info['temp']}°</div>
          </div>
        </div>"""
    uv_prom_val = round(uv_max_prom / len(datos_clima), 1) if datos_clima else 0

    min_temp, max_temp = -2.0, 10.0
    rango = max_temp - min_temp
    pos_cero = ((0.0 - min_temp) / rango) * 100

    temp_grupos = {}
    for ciudad, info in datos_clima.items():
        t = info['tmin_madrugada']
        if t not in temp_grupos:
            temp_grupos[t] = []
        nombre_format = "Y. Buenas" if ciudad == "Yerbas Buenas" else ciudad
        temp_grupos[t].append(nombre_format)

    grupos_ordenados = sorted(temp_grupos.items(), key=lambda x: x[0])

    gauge_puntos_html = ""
    ultimas_pos = []

    for idx, (t_min, lista_ciudades) in enumerate(grupos_ordenados):
        pct = max(3, min(97, ((t_min - min_temp) / rango) * 100))
        alerta_cls = "alerta" if t_min <= UMBRAL_HELADA_C else ""
        
        texto_ciudades = ", ".join(lista_ciudades)
        offset_v = "pos-arriba" if idx % 2 == 0 else "pos-abajo"
        
        shift_x = "transform: translateX(-50%);"
        if ultimas_pos:
            pos_anterior = ultimas_pos[-1]
            if abs(pct - pos_anterior) < 14:
                shift_x = "transform: translateX(-10%);" if idx % 2 == 0 else "transform: translateX(-90%);"
        
        ultimas_pos.append(pct)
        
        gauge_puntos_html += f"""
        <div class="gauge-punto {alerta_cls} {offset_v}" style="left:{pct:.1f}%;">
          <div class="bola"></div>
          <div class="etiqueta" style="{shift_x}">
            <b>{texto_ciudades}</b> <span>{t_min}°C</span>
          </div>
        </div>"""

    lunar_days_html = ""
    for d in luna:
        today_cls = "today" if d["es_hoy"] else ""
        today_label = " (HOY)" if d["es_hoy"] else ""
        lunar_days_html += f"""
        <div class="lunar-day {today_cls}">
          <span>{d['fecha']}</span>
          <span class="lunar-icon">{d['icono']}</span>
          <span>{d['nombre']}{today_label}</span>
        </div>"""

    def gen_subgrupo(titulo, lista_noticias):
        estilo_cat = CATEGORIA_ESTILO.get(titulo, {"icono": "📰", "color": "#1D63ED"})
        color = estilo_cat["color"]
        items = ""
        for n in lista_noticias:
            bajada_html = f"<div class=\"bajada-n\">{html.escape(n['bajada'])}</div>" if n.get('bajada') else ""
            items += f"""
            <div class="noticia" style="border-left-color:{color};">
              <div class="titulo-n">{html.escape(n['titulo'])}</div>
              {bajada_html}
              <div class="fuente-n">— {html.escape(n['fuente'])}</div>
            </div>"""
        titulo_chip = f"""<div class="subgrupo-titulo" style="background:{color}1F; color:{color};">{estilo_cat['icono']} {titulo}</div>"""
        return f"""<div class="subgrupo">{titulo_chip}{items}</div>"""

    noticias_col1 = (
        gen_subgrupo("Longaví", datos_noticias["Longaví"]) + 
        gen_subgrupo("Linares", datos_noticias["Linares"]) + 
        gen_subgrupo("Yerbas Buenas", datos_noticias["Yerbas Buenas"]) +
        gen_subgrupo("Chile", datos_noticias["Chile"]) + 
        gen_subgrupo("Mundo", datos_noticias["Mundo"])
    )
    noticias_col2 = (
        gen_subgrupo("Salud y Bienestar", datos_noticias["Salud"]) + 
        gen_subgrupo("Tecnología", datos_noticias["Tecnología"]) + 
        gen_subgrupo("Deportes", datos_noticias["Deportes"]) + 
        gen_subgrupo("Entretención", datos_noticias["Entretención"]) + 
        gen_subgrupo("Tendencias en Chile", datos_noticias["Tendencias"])
    )

    combustibles_cards_html = ""
    for clave, config in ESTILOS_COMBUSTIBLE.items():
        info = datos_combustible.get(clave, {"monto": "—", "ciudad": "—", "direccion": "—"})
        combustibles_cards_html += f"""
        <div class="precio-card" style="background: linear-gradient(180deg, {config['bg']}26 0%, {config['bg']}08 100%); border-top: 3px solid {config['bg']};">
          <div class="precio-badge" style="background-color:{config['bg']}; color:{config['text']}; border:1px solid {config['border']};">
            {config['etiqueta']}
          </div>
          <div class="monto">{info['monto']}</div>
          <div class="ciudad-p">{info['ciudad']}</div>
          <div class="direccion-p">{html.escape(info['direccion'])}</div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="es-CL">
<head>
<meta charset="UTF-8">
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
        <div class="santoral">😇 Santoral: {extra['santoral']}</div>
        <div>{hora_txt}</div>
      </div>
    </div>
    <div class="masthead-rule"></div>
    <div class="comunas"><b>Longaví</b> · <b>Linares</b> · <b>Yerbas Buenas</b> — Región del Maule</div>
  </div>

  <!-- INDICADORES ECONÓMICOS -->
  <div class="metrics-bar">
    <div class="metric-item">
      <div class="metric-icono" style="background:{METRICA_ICONOS['dolar']['color']}22; color:{METRICA_ICONOS['dolar']['color']};">{METRICA_ICONOS['dolar']['icono']}</div>
      <div>Dólar<div class="metric-value">{eco['dolar']}</div></div>
    </div>
    <div class="metric-item">
      <div class="metric-icono" style="background:{METRICA_ICONOS['uf']['color']}22; color:{METRICA_ICONOS['uf']['color']};">{METRICA_ICONOS['uf']['icono']}</div>
      <div>UF<div class="metric-value">{eco['uf']}</div></div>
    </div>
    <div class="metric-item">
      <div class="metric-icono" style="background:{METRICA_ICONOS['uv']['color']}22; color:{METRICA_ICONOS['uv']['color']};">{METRICA_ICONOS['uv']['icono']}</div>
      <div>Máx UV<div class="metric-value">{uv_prom_val}</div></div>
    </div>
    <div class="metric-item">
      <div class="metric-icono" style="background:{METRICA_ICONOS['aire']['color']}22; color:{METRICA_ICONOS['aire']['color']};">{METRICA_ICONOS['aire']['icono']}</div>
      <div>Aire Maule<div class="metric-value" style="color:#22c55e;">Bueno</div></div>
    </div>
  </div>

  <!-- PRÓXIMO FERIADO -->
  <div class="holiday-box">
    <div>
      <div class="holiday-title">🎉 Próximo Feriado en Chile</div>
      <div class="holiday-desc">{feriado['fecha']} · {feriado['nombre']}</div>
    </div>
    <div class="holiday-badge">{feriado['dias']}</div>
  </div>

  <!-- CLIMA Y HELADAS -->
  <div class="seccion">
    <div class="seccion-titulo"><span class="barra"></span>{titulo_clima}</div>
    <div class="clima-fila">
      {clima_cards_html}
    </div>

    <div class="gauge-box">
      <div class="gauge-header">
        <div class="gauge-titulo">Riesgo de helada — {subtitulo_heladas}</div>
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

    <!-- FASE LUNAR SEMANAL -->
    <div class="lunar-bar">
      <div class="lunar-title">🌙 Fase Lunar Semanal</div>
      <div class="lunar-days">
        {lunar_days_html}
      </div>
    </div>
  </div>

  <!-- NOTICIAS -->
  <div class="seccion">
    <div class="seccion-titulo"><span class="barra"></span>Noticias</div>
    <div class="noticias-cols">
      <div class="col">{noticias_col1}</div>
      <div class="col">{noticias_col2}</div>
    </div>
    {html_futbol}
  </div>

  <!-- COMBUSTIBLES -->
  <div class="seccion">
    <div class="combustible-box">
      <div class="combustible-titulo">Combustible hoy <span class="nota">mejor precio en radio de 15 km</span></div>
      <div class="precios-fila">
        {combustibles_cards_html}
      </div>
    </div>

    <!-- FRASE Y DATO CURIOSO -->
    <div class="footer-boxes">
      <div class="footer-box">
        <div class="footer-box-icono">💭</div>
        <div class="footer-box-title">💭 Frase del Día</div>
        <div class="footer-box-text">{extra['frase']} — <strong>{extra['autor']}</strong></div>
      </div>
      <div class="footer-box" style="border-left-color: #facc15;">
        <div class="footer-box-icono">💡</div>
        <div class="footer-box-title">💡 Dato Curioso Maule</div>
        <div class="footer-box-text">{extra['dato']}</div>
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

# ==========================================
# ENVÍO A TELEGRAM (DOCUMENTO PDF)
# ==========================================

def enviar_pdf_telegram(pdf_bytes, caption_text="", nombre_archivo="boletin.pdf"):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID.", file=sys.stderr)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "caption": caption_text
    }
    
    files = {"document": (nombre_archivo, pdf_bytes, "application/pdf")}

    try:
        resp = HTTP_SESSION.post(url, data=payload, files=files, timeout=60)
        resp.raise_for_status()
        print(f"Boletín PDF '{nombre_archivo}' enviado con éxito a Telegram.")
    except requests.exceptions.ReadTimeout:
        print("ERROR: Timeout leyendo la respuesta de Telegram tras varios reintentos.", file=sys.stderr)
    except requests.exceptions.RequestException as e:
        print(f"ERROR al enviar a Telegram: {e}", file=sys.stderr)

# ==========================================
# EJECUCIÓN PRINCIPAL
# ==========================================

async def main_async():
    ahora = datetime.datetime.now(ZONA_CL)
    edicion = edicion_objetivo(ahora)

    if not FORZAR_ENVIO and edicion is None:
        print(f"Hora actual en Chile: {ahora.strftime('%H:%M')} — no toca enviar. Saliendo.")
        return

    fecha_str = ahora.strftime("%Y-%m-%d")
    if not FORZAR_ENVIO:
        estado = cargar_estado_envio()
        if estado.get("fecha") == fecha_str and estado.get("edicion") == edicion:
            print(f"La edición '{edicion}' del {fecha_str} ya fue enviada antes. Saliendo.")
            return

    print("🔄 Recopilando información para el Boletín Maule...")
    if edicion is not None:
        es_manana = edicion == "manana"
    else:
        es_manana = ahora.hour < 15
    idx_dia = 0 if es_manana else 1
    fecha_reporte = ahora if es_manana else ahora + datetime.timedelta(days=1)

    # 1. Datos económicos, feriados y cultura
    eco = obtener_indicadores_economicos()
    feriado = obtener_proximo_feriado(ahora)
    luna = obtener_fase_lunar_semanal(ahora)
    extra = obtener_santoral_y_frase(ahora)

    # 2. Clima
    datos_clima = {}
    for ciudad, coords in CIUDADES.items():
        raw = obtener_clima(coords["lat"], coords["lon"])
        curr = raw["current"]
        daily = raw["daily"]
        
        temp_destacada = round(curr["temperature_2m"]) if es_manana else round(daily["temperature_2m_max"][idx_dia])
        uv_max = daily["uv_index_max"][idx_dia] if "uv_index_max" in daily else 0.0
        
        datos_clima[ciudad] = {
            "temp": temp_destacada,
            "min": round(daily["temperature_2m_min"][idx_dia]),
            "max": round(daily["temperature_2m_max"][idx_dia]),
            "viento": round(curr["wind_speed_10m"]),
            "desc": WMO_CODES.get(curr["weather_code"], "—"),
            "codigo": curr["weather_code"],
            "tmin_madrugada": round(daily["temperature_2m_min"][idx_dia], 1),
            "uv": uv_max
        }

    # 3. Noticias
    datos_noticias = {
        "Longaví": buscar_noticias('"Longaví" Chile', 2),
        "Linares": buscar_noticias('"Linares" Chile', 2),
        "Yerbas Buenas": buscar_noticias('"Yerbas Buenas" Chile', 2),
        "Chile": noticias_tema("NATION", 2),
        "Mundo": noticias_tema("WORLD", 2),
        "Salud": buscar_noticias("salud bienestar Chile", 2),
        "Tecnología": noticias_tema("TECHNOLOGY", 2),
        "Deportes": noticias_tema("SPORTS", 2),
        "Entretención": buscar_noticias("espectaculos entretenimiento Chile", 2),
        "Tendencias": buscar_noticias("tendencias viral Chile", 2)
    }

    # 4. Combustibles
    datos_combustible = mejores_precios_combustible()

    # 5. Tabla de Fútbol
    tabla_futbol = obtener_tabla_futbol(top_n=10)
    html_futbol = renderizar_tabla_futbol(tabla_futbol)

    # 6. Renderizado PDF Vectorial
    print("🎨 Generando HTML y renderizando PDF vectorial con Playwright...")
    html_final = renderizar_plantilla_html(
        ahora, fecha_reporte, es_manana, eco, feriado, luna, extra, 
        datos_clima, datos_noticias, datos_combustible, html_futbol
    )
    pdf_bytes = await html_a_pdf(html_final)

    # 7. Crear texto del mensaje (Caption de Telegram)
    icono_edicion = "☀️" if es_manana else "🌙"
    nombre_edicion = "Edición Mañana" if es_manana else "Edición Noche"
    dia_nombre = DIAS_ESP[ahora.weekday()]
    mes_nombre = MESES_ESP[ahora.month - 1]
    
    caption = (
        f"🗞️ Boletín Maule — {nombre_edicion} {icono_edicion}\n"
        f"📅 {dia_nombre} {ahora.day} de {mes_nombre} de {ahora.year} — {ahora.strftime('%H:%M')} hrs\n"
        f"📍 Longaví · Linares · Yerbas Buenas"
    )

    # 8. Enviar a Telegram
    tipo_edicion = "Manana" if es_manana else "Noche"
    nombre_dinamico = f"Boletin_Maule_{fecha_reporte.strftime('%Y-%m-%d')}_{tipo_edicion}.pdf"

    print(f"📤 Enviando PDF ({nombre_dinamico}) a Telegram...")
    enviar_pdf_telegram(pdf_bytes, caption_text=caption, nombre_archivo=nombre_dinamico)

    if not FORZAR_ENVIO and edicion is not None:
        guardar_estado_envio(fecha_str, edicion)
        print(f"📝 Estado guardado: edición '{edicion}' del {fecha_str} enviada.")

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()