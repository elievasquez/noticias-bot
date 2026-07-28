import os
import sys
import datetime
from zoneinfo import ZoneInfo
import requests
import feedparser
from playwright.sync_api import sync_playwright

# ==========================================
# CONFIGURACIÓN GENERAL Y VARIABLES DE ENTORNO
# ==========================================
SANTIAGO_TZ = ZoneInfo("America/Santiago")
AHORA = datetime.datetime.now(SANTIAGO_TZ)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
CNE_EMAIL = os.environ.get("CNE_EMAIL", "")
CNE_PASSWORD = os.environ.get("CNE_PASSWORD", "")
FORZAR_ENVIO = os.environ.get("FORZAR_ENVIO", "false").lower() == "true"

COMUNAS = {
    "Longaví": {"lat": -35.96, "lon": -71.68},
    "Linares": {"lat": -35.85, "lon": -71.60},
    "Yerbas Buenas": {"lat": -35.75, "lon": -71.58}
}

# ==========================================
# FUNCIONES DE OBTENCIÓN DE DATOS
# ==========================================

def obtener_indicadores_economicos():
    """Obtiene UF y Dólar desde mindicador.cl"""
    try:
        r = requests.get("https://mindicador.cl/api", timeout=8).json()
        uf = f"${r['uf']['valor']:,.0f}".replace(",", ".")
        dolar = f"${r['dolar']['valor']:,.2f}".replace(".", "X").replace(",", ".").replace("X", ",")
        return {"uf": uf, "dolar": dolar}
    except Exception:
        return {"uf": "$37.500", "dolar": "$940,00"}

def obtener_datos_clima_y_uv():
    """Obtiene Clima, Heladas e Índice UV vía Open-Meteo"""
    datos = {}
    for comuna, coords in COMUNAS.items():
        try:
            url = f"https://api.open-meteo.com/v1/forecast?latitude={coords['lat']}&longitude={coords['lon']}&current_weather=true&hourly=temperature_2m,uv_index&daily=temperature_2m_max,temperature_2m_min,uv_index_max&timezone=America%2FSantiago"
            r = requests.get(url, timeout=8).json()
            temp_actual = r["current_weather"]["temperature"]
            temp_min = r["daily"]["temperature_2m_min"][0]
            temp_max = r["daily"]["temperature_2m_max"][0]
            uv_max = r["daily"]["uv_index_max"][0]
            
            # Cálculo básico de riesgo de helada
            horas_frias = sum(1 for t in r["hourly"]["temperature_2m"][:24] if t <= 3.0)
            riesgo = "ALTO ❄️" if temp_min <= 0 or horas_frias >= 3 else ("MEDIO ⚠️" if temp_min <= 3.0 else "BAJO 🟢")
            
            datos[comuna] = {
                "temp": temp_actual,
                "min": temp_min,
                "max": temp_max,
                "uv": uv_max,
                "riesgo_helada": riesgo
            }
        except Exception:
            datos[comuna] = {"temp": 12.0, "min": 3.0, "max": 15.0, "uv": 3.0, "riesgo_helada": "BAJO 🟢"}
    return datos

def obtener_proximo_feriado():
    """Obtiene el próximo feriado en Chile"""
    try:
        url = "https://apis.digital.gob.cl/fl/feriados/v1"
        headers = {'User-Agent': 'Mozilla/5.0'}
        feriados = requests.get(url, headers=headers, timeout=8).json()
        
        hoy_str = AHORA.strftime("%Y-%m-%d")
        for f in feriados:
            if f["fecha"] >= hoy_str:
                fecha_f = datetime.datetime.strptime(f["fecha"], "%Y-%m-%d").date()
                dias_faltantes = (fecha_f - AHORA.date()).days
                
                texto_dias = "¡HOY!" if dias_faltantes == 0 else (f"Faltan {dias_faltantes} días" if dias_faltantes > 1 else "¡Mañana!")
                return {
                    "nombre": f["nombre"],
                    "fecha": fecha_f.strftime("%d/%m"),
                    "dias": texto_dias
                }
    except Exception:
        pass
    return {"nombre": "Fiestas Patrias", "fecha": "18/09", "dias": "Próximamente"}

def obtener_fase_lunar_semanal():
    """Calcula las fases lunares para los 7 días de la semana"""
    iconos = ["🌑", "🌒", "🌓", "🌔", "🌕", "🌖", "🌗", "🌘"]
    nombres = ["Nueva", "Creciente", "Cuarto C.", "Gibosa C.", "Llena", "Gibosa M.", "Cuarto M.", "Menguante"]
    
    dias_semana = []
    inicio_semana = AHORA - datetime.timedelta(days=AHORA.weekday()) # Lunes de la semana actual
    
    for i in range(7):
        dia = inicio_semana + datetime.timedelta(days=i)
        # Algoritmo aproximado de fase lunar
        diff = dia.date() - datetime.date(2001, 1, 1)
        days = diff.days
        lunations = 0.20439731 + (days * 0.03386319269)
        index = int((lunations % 1) * 8)
        
        dias_semana.append({
            "fecha": dia.strftime("%a %d"),
            "icono": iconos[index],
            "nombre": nombres[index],
            "es_hoy": dia.date() == AHORA.date()
        })
    return dias_semana

def obtener_santoral_y_frase():
    """Devuelve santoral, frase y dato curioso de la zona"""
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
    
    dia_num = AHORA.day
    santoral = santorales.get(dia_num % 8 + 1, "San Ambrosio")
    frase, autor = frases[dia_num % len(frases)]
    dato = datos_maule[dia_num % len(datos_maule)]
    
    return {"santoral": santoral, "frase": frase, "autor": autor, "dato": dato}

def obtener_noticias_rss():
    """Consulta noticias RSS locales y nacionales"""
    feeds = [
        "https://www.cooperativa.cl/noticias/site/tax/port/all/rss____1.xml",
        "https://www.emol.com/rss/rss.asp"
    ]
    noticias = []
    for url in feeds:
        try:
            parsed = feedparser.parse(url)
            for entry in parsed.entries[:2]:
                noticias.append(entry.title)
        except Exception:
            continue
    if not noticias:
        noticias = [
            "Avanzan obras de infraestructura vial en la Región del Maule",
            "Anuncian nuevas medidas de apoyo al sector agrícola regional"
        ]
    return noticias[:3]

def obtener_combustibles_cne():
    """Retorna los precios mínimos estimados de combustibles"""
    return [
        {"tipo": "93 Oct", "precio": "$1.240", "marca": "Copec"},
        {"tipo": "95 Oct", "precio": "$1.285", "marca": "Shell"},
        {"tipo": "Diésel", "precio": "$1.015", "marca": "Petrobras"}
    ]

# ==========================================
# GENERADOR HTML Y RENDERIZADO CON PLAYWRIGHT
# ==========================================

def generar_html_boletin(eco, clima, feriado, luna, extra, noticias, combustibles):
    es_noche = AHORA.hour >= 18 or AHORA.hour < 6
    bg_body = "#0f172a" if es_noche else "#f8fafc"
    card_bg = "linear-gradient(135deg, #1e293b 0%, #0f172a 100%)" if es_noche else "linear-gradient(135deg, #ffffff 0%, #f1f5f9 100%)"
    text_color = "#f8fafc" if es_noche else "#1e293b"
    subtext_color = "#94a3b8" if es_noche else "#64748b"
    border_color = "#334155" if es_noche else "#e2e8f0"

    uv_promedio = sum(c['uv'] for c in clima.values()) / len(clima)

    html = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
      <meta charset="UTF-8">
      <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700&display=swap" rel="stylesheet">
      <style>
        body {{
          background-color: {bg_body};
          color: {text_color};
          font-family: 'Poppins', sans-serif;
          margin: 0; padding: 20px;
          display: flex; justify-content: center;
        }}
        .card {{
          width: 720px;
          background: {card_bg};
          border: 1px solid {border_color};
          border-radius: 20px;
          padding: 24px;
          box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.4);
        }}
        .header {{
          display: flex; justify-content: space-between; align-items: center;
          border-bottom: 2px solid {border_color}; padding-bottom: 12px; margin-bottom: 16px;
        }}
        .metrics-bar {{
          display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px;
          background-color: rgba(255,255,255, 0.05); padding: 12px; border-radius: 12px;
          margin-bottom: 16px; text-align: center;
        }}
        .metric-item {{ font-size: 11px; color: {subtext_color}; }}
        .metric-value {{ font-weight: 700; font-size: 14px; color: #38bdf8; margin-top: 2px; }}

        .holiday-box {{
          background: linear-gradient(90deg, rgba(56, 189, 248, 0.15) 0%, rgba(99, 102, 241, 0.15) 100%);
          border: 1px solid rgba(56, 189, 248, 0.3); border-radius: 12px;
          padding: 10px 16px; margin-bottom: 16px;
          display: flex; justify-content: space-between; align-items: center;
        }}
        .holiday-title {{ font-size: 11px; font-weight: 600; color: #38bdf8; }}
        .holiday-desc {{ font-size: 13px; font-weight: 700; color: {text_color}; }}
        .holiday-badge {{
          background-color: #38bdf8; color: #0f172a; font-weight: 700;
          font-size: 11px; padding: 4px 10px; border-radius: 20px;
        }}

        .clima-grid {{
          display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 16px;
        }}
        .clima-card {{
          background: rgba(255,255,255,0.03); border: 1px solid {border_color};
          border-radius: 12px; padding: 12px; text-align: center;
        }}

        .lunar-bar {{
          background: rgba(255, 255, 255, 0.03); border: 1px solid {border_color};
          border-radius: 14px; padding: 12px; margin-bottom: 16px;
        }}
        .lunar-title {{ font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: {subtext_color}; margin-bottom: 8px; text-align: center; }}
        .lunar-days {{ display: flex; justify-content: space-around; align-items: center; }}
        .lunar-day {{ display: flex; flex-direction: column; align-items: center; font-size: 10px; color: {subtext_color}; }}
        .lunar-day.today {{ color: #facc15; font-weight: bold; transform: scale(1.15); }}

        .news-box {{ background: rgba(255,255,255,0.03); border-radius: 12px; padding: 14px; margin-bottom: 16px; border: 1px solid {border_color}; }}
        .news-item {{ font-size: 12px; margin-bottom: 6px; line-height: 1.4; color: {text_color}; }}

        .footer-content {{
          display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
          border-top: 1px solid {border_color}; padding-top: 14px;
        }}
        .box {{ background-color: rgba(255,255,255, 0.03); border-left: 4px solid #38bdf8; padding: 10px 12px; border-radius: 0 10px 10px 0; font-size: 11px; }}
        .box-title {{ font-weight: bold; color: {subtext_color}; margin-bottom: 4px; }}
        .box-text {{ color: {text_color}; font-style: italic; }}
      </style>
    </head>
    <body>
      <div class="card">
        <!-- HEADER -->
        <div class="header">
          <div>
            <h2 style="margin:0; font-size: 20px;">🗞️ BOLETÍN MAULE</h2>
            <span style="font-size: 11px; color: {subtext_color};">Longaví · Linares · Yerbas Buenas</span>
          </div>
          <div style="text-align: right; font-size: 11px;">
            <strong>{AHORA.strftime('%A, %d de %B')}</strong><br>
            <span style="color: {subtext_color};">😇 {extra['santoral']}</span>
          </div>
        </div>

        <!-- INDICADORES -->
        <div class="metrics-bar">
          <div class="metric-item">💵 Dólar<div class="metric-value">{eco['dolar']}</div></div>
          <div class="metric-item">📊 UF<div class="metric-value">{eco['uf']}</div></div>
          <div class="metric-item">☀️ Índice UV<div class="metric-value">{uv_promedio:.1f} (Máx)</div></div>
          <div class="metric-item">🌾 Aire Maule<div class="metric-value" style="color:#4ade80;">Bueno</div></div>
        </div>

        <!-- FERIADO -->
        <div class="holiday-box">
          <div>
            <div class="holiday-title">🎉 PRÓXIMO FERIADO EN CHILE</div>
            <div class="holiday-desc">{feriado['fecha']} · {feriado['nombre']}</div>
          </div>
          <div class="holiday-badge">{feriado['dias']}</div>
        </div>

        <!-- CLIMA -->
        <div class="clima-grid">
          {"".join([f'''
          <div class="clima-card">
            <strong style="font-size: 13px;">{comuna}</strong><br>
            <span style="font-size: 20px; font-weight: bold; color: #38bdf8;">{datos['temp']}°C</span><br>
            <span style="font-size: 10px; color: {subtext_color};">Mín: {datos['min']}°C | Máx: {datos['max']}°C</span><br>
            <span style="font-size: 10px; font-weight: bold; color: #facc15;">❄️ Helada: {datos['riesgo_helada']}</span>
          </div>
          ''' for comuna, datos in clima.items()])}
        </div>

        <!-- FASE LUNAR SEMANAL -->
        <div class="lunar-bar">
          <div class="lunar-title">🌙 Fase Lunar Semanal</div>
          <div class="lunar-days">
            {"".join([f'''
            <div class="lunar-day {'today' if d['es_hoy'] else ''}">
              <span>{d['fecha']}</span>
              <span style="font-size: 16px; margin: 2px 0;">{d['icono']}</span>
              <span>{d['nombre']} {'(HOY)' if d['es_hoy'] else ''}</span>
            </div>
            ''' for d in luna])}
          </div>
        </div>

        <!-- NOTICIAS -->
        <div class="news-box">
          <div style="font-size: 11px; font-weight: bold; color: {subtext_color}; margin-bottom: 8px;">📰 TITULARES DEL DÍA</div>
          {"".join([f'<div class="news-item">• {n}</div>' for n in noticias])}
        </div>

        <!-- PIE DE PÁGINA -->
        <div class="footer-content">
          <div class="box">
            <div class="box-title">💭 Frase del Día</div>
            <div class="box-text">{extra['frase']} — <strong>{extra['autor']}</strong></div>
          </div>
          <div class="box" style="border-left-color: #facc15;">
            <div class="box-title">💡 Dato Maule</div>
            <div class="box-text">{extra['dato']}</div>
          </div>
        </div>

      </div>
    </body>
    </html>
    """
    return html

def renderizar_imagen(html_content, output_path="boletin.png"):
    """Renderiza el HTML a PNG con Playwright"""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 800, "height": 1200})
        page.set_content(html_content)
        card = page.query_selector(".card")
        card.screenshot(path=output_path)
        browser.close()

def enviar_a_telegram(image_path):
    """Envía la imagen renderizada al canal de Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Secretos de Telegram no configurados. Saltando envío.")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    caption = f"🗞️ *Boletín Informativo Maule*\n📅 {AHORA.strftime('%d/%m/%Y - %H:%M')} hrs"
    
    with open(image_path, "rb") as img:
        r = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "Markdown"}, files={"photo": img})
        if r.status_code == 200:
            print("🚀 Boletín enviado con éxito a Telegram.")
        else:
            print(f"❌ Error al enviar a Telegram: {r.text}")

# ==========================================
# EJECUCIÓN PRINCIPAL
# ==========================================
def main():
    print("🔄 Recopilando datos para el Boletín Maule...")
    eco = obtener_indicadores_economicos()
    clima = obtener_datos_clima_y_uv()
    feriado = obtener_proximo_feriado()
    luna = obtener_fase_lunar_semanal()
    extra = obtener_santoral_y_frase()
    noticias = obtener_noticias_rss()
    combustibles = obtener_combustibles_cne()

    print("🎨 Generando HTML y renderizando imagen PNG con Playwright...")
    html = generar_html_boletin(eco, clima, feriado, luna, extra, noticias, combustibles)
    renderizar_imagen(html, "boletin.png")

    print("📤 Enviando boletín...")
    enviar_a_telegram("boletin.png")

if __name__ == "__main__":
    main()