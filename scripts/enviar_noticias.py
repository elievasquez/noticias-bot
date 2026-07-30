import sys
import json
import html
import asyncio
import datetime
import logging
from pathlib import Path

from config import (
    ZONA_CL, ARCHIVO_ESTADO_ENVIO, UMBRAL_HELADA_C, CIUDADES,
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, FORZAR_ENVIO, TOLERANCIA_MINUTOS,
    DIAS_ESP, MESES_ESP, METRICA_ICONOS, ESTILOS_COMBUSTIBLE, CATEGORIA_ESTILO,
    HTTP_SESSION
)
from services.weather import obtener_clima, estilo_clima
from services.news import buscar_noticias, noticias_tema
from services.sports import obtener_tabla_futbol, renderizar_tabla_futbol
from services.fuel import mejores_precios_combustible
from services.pdf import html_a_pdf

WMO_CODES = {
    0: "Despejado ☀️",
    1: "Principalmente despejado 🌤️",
    2: "Parcialmente nublado ⛅",
    3: "Nublado ☁️",
    45: "Niebla 🌫️",
    48: "Niebla con escarcha 🌫️❄️",
    51: "Llovizna ligera 🌧️",
    53: "Llovizna moderada 🌧️",
    55: "Llovizna densa 🌧️",
    56: "Llovizna helada ligera ❄️",
    57: "Llovizna helada densa ❄️",
    61: "Lluvia ligera 🌧️",
    63: "Lluvia moderada 🌧️",
    65: "Lluvia fuerte 🌧️",
    66: "Lluvia helada ligera ❄️",
    67: "Lluvia helada fuerte ❄️",
    71: "Nieve ligera 🌨️",
    73: "Nieve moderada 🌨️",
    75: "Nieve fuerte 🌨️",
    77: "Granizo fino 🌨️",
    80: "Chubascos ligeros 🌦️",
    81: "Chubascos moderados 🌦️",
    82: "Chubascos violentos ⛈️",
    85: "Chubascos de nieve ligeros 🌨️",
    86: "Chubascos de nieve fuertes 🌨️",
    95: "Tormenta eléctrica 🌩️",
    96: "Tormenta con granizo ligero ⛈️",
    99: "Tormenta con granizo fuerte ⛈️",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def edicion_objetivo(ahora):
    minutos_ahora = ahora.hour * 60 + ahora.minute
    objetivos = (
        (9 * 60 + 0, "manana"),   # 09:00
        (21 * 60 + 0, "noche"),   # 21:00
    )
    for objetivo_minutos, nombre in objetivos:
        if abs(minutos_ahora - objetivo_minutos) <= TOLERANCIA_MINUTOS:
            return nombre
    return None

def cargar_estado_envio():
    try:
        with open(ARCHIVO_ESTADO_ENVIO, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def guardar_estado_envio(fecha_str, edicion):
    with open(ARCHIVO_ESTADO_ENVIO, "w", encoding="utf-8") as f:
        json.dump({"fecha": fecha_str, "edicion": edicion}, f)

def obtener_indicadores_economicos():
    try:
        r = HTTP_SESSION.get("https://mindicador.cl/api", timeout=8).json()
        uf = f"${r['uf']['valor']:,.0f}".replace(",", ".")
        dolar = f"${r['dolar']['valor']:,.2f}".replace(".", "X").replace(",", ".").replace("X", ",")
        return {"uf": uf, "dolar": dolar}
    except Exception as e:
        logging.warning(f"Error al obtener indicadores económicos: {e}")
        return {"uf": "$37.500", "dolar": "$940,00"}

MESES_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
}

def obtener_proximo_feriado(ahora):
    try:
        url = "https://api.boostr.cl/feriados/en.json"
        
        # Cabeceras completas para emular un navegador real
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'es-ES,es;q=0.9',
        }
        
        res_resp = HTTP_SESSION.get(url, headers=headers, timeout=5)
        res_resp.raise_for_status()
        res = res_resp.json()
        
        feriados = res.get("data", [])
        
        # Asegurar que 'ahora' se trate como date
        hoy_date = ahora.date() if isinstance(ahora, datetime.datetime) else ahora
        hoy_str = hoy_date.strftime("%Y-%m-%d")
        
        for f in feriados:
            fecha_str = f.get("date")
            if fecha_str and fecha_str >= hoy_str:
                fecha_f = datetime.datetime.strptime(fecha_str, "%Y-%m-%d").date()
                dias_faltantes = (fecha_f - hoy_date).days
                
                # Formato de fecha en español
                fecha_formateada = f"{fecha_f.day} de {MESES_ES.get(fecha_f.month, '')}"
                
                if dias_faltantes == 0:
                    texto_dias = "¡HOY!"
                elif dias_faltantes == 1:
                    texto_dias = "¡Mañana!"
                else:
                    texto_dias = f"Faltan {dias_faltantes} días"
                
                return {
                    "nombre": f.get("title"),
                    "fecha": fecha_formateada,
                    "dias": texto_dias
                }
                
    except Exception as e:
        logging.warning(f"Error al obtener próximo feriado: {e}")
        
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

def obtener_articulo_utilidad(ahora):
    articulos = [
        {"categoria": "Hogar", "titulo": "Cómo prevenir la humedad en invierno",
         "texto": "Ventila tu vivienda unos 10 minutos al día, incluso con frío, para renovar el aire y evitar condensación en las ventanas. Revisa techos y canaletas antes de las lluvias fuertes para prevenir filtraciones."},
        {"categoria": "Salud", "titulo": "Hidratación en días de calor",
         "texto": "Bebe agua de forma regular durante el día sin esperar a sentir sed, sobre todo si trabajas al aire libre. Evita las horas de mayor exposición solar (12:00 a 16:00) para labores físicas intensas."},
        {"categoria": "Finanzas", "titulo": "Cómo armar un presupuesto mensual simple",
         "texto": "Anota tus ingresos y gastos fijos del mes, separa un porcentaje para ahorro apenas recibas tu sueldo y revisa semanalmente en qué se te va el dinero para ajustar a tiempo."},
        {"categoria": "Tecnología", "titulo": "Protege tu WhatsApp de intentos de robo",
         "texto": "Activa la verificación en dos pasos en Ajustes > Cuenta > Verificación en dos pasos, y nunca compartas el código de 6 dígitos que llega por SMS, aunque te digan que es de un familiar."},
        {"categoria": "Agro y Jardín", "titulo": "Cuidado de cultivos ante heladas",
         "texto": "Riega el suelo antes de una helada, ya que la tierra húmeda retiene mejor el calor. Cubre las plantas sensibles con mallas o telas antes del anochecer y retíralas después del amanecer."},
        {"categoria": "Seguridad Vial", "titulo": "Manejo seguro con niebla o lluvia",
         "texto": "Reduce la velocidad y aumenta la distancia con el vehículo de adelante, usa las luces bajas (nunca las altas con niebla) y evita frenar de golpe sobre pavimento mojado."},
        {"categoria": "Prevención", "titulo": "Cómo evitar incendios domésticos en invierno",
         "texto": "No dejes estufas a leña o parafina encendidas sin supervisión, revisa que los ductos de calefacción estén despejados de material inflamable y ten un extintor accesible en la cocina."},
        {"categoria": "Ahorro", "titulo": "Reduce tu cuenta de electricidad",
         "texto": "Desconecta cargadores y aparatos en modo 'stand by', ya que igual consumen energía. Aprovecha la luz natural durante el día y cambia ampolletas antiguas por LED."},
        {"categoria": "Primeros Auxilios", "titulo": "Qué hacer ante una quemadura leve",
         "texto": "Enfría la zona con agua tibia o fría (nunca helada) durante al menos 10 minutos, no apliques pasta dental ni mantequilla, y cubre con un paño limpio antes de buscar atención médica."},
        {"categoria": "Educación", "titulo": "Técnica Pomodoro para estudiar mejor",
         "texto": "Estudia en bloques de 25 minutos con descansos de 5 minutos entre cada uno. Cada 4 bloques, toma un descanso más largo de 15 a 20 minutos para mantener la concentración."},
    ]
    dia_num = ahora.day
    return articulos[dia_num % len(articulos)]

def renderizar_plantilla_html(ahora, fecha_reporte, es_manana, eco, feriado, luna, extra, datos_clima, datos_noticias, datos_combustible, html_futbol="", articulo=None):
    articulo = articulo or {"categoria": "Utilidad", "titulo": "", "texto": ""}
    edicion_txt = "Edición de la mañana" if es_manana else "Edición de la noche"
    
    nombre_css = "manana.css" if es_manana else "noche.css"
    path_css = Path(__file__).parent / "templates" / "styles" / nombre_css
    with open(path_css, "r", encoding="utf-8") as f:
        css_tema = f.read()

    path_layout = Path(__file__).parent / "templates" / "layout.html"
    with open(path_layout, "r", encoding="utf-8") as f:
        template_html = f.read()

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

    html_destacada = ""
    noticia_destacada = datos_noticias.get("Destacada", [])
    if noticia_destacada:
        nd = noticia_destacada[0]
        img_src = nd.get("imagen") or "https://images.unsplash.com/photo-1504711434969-e33886168f5c?w=600&auto=format&fit=crop"
        
        html_destacada = f"""
        <div class="destacada-box">
          <img class="destacada-img" src="{img_src}" alt="Noticia Destacada">
          <div class="destacada-body">
            <div class="destacada-badge">⭐ Noticia Destacada del Día</div>
            <div class="destacada-titulo">{html.escape(nd['titulo'])}</div>
            <div class="destacada-bajada">{html.escape(nd['bajada'])}</div>
            <div class="destacada-fuente">— {html.escape(nd['fuente'])}</div>
          </div>
        </div>
        """

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

    return template_html.format(
        css_tema=css_tema,
        edicion_txt=edicion_txt,
        fecha_txt=fecha_txt,
        santoral=extra['santoral'],
        hora_txt=hora_txt,
        dolar_icon=METRICA_ICONOS['dolar']['icono'],
        dolar_icon_color=METRICA_ICONOS['dolar']['color'],
        dolar_val=eco['dolar'],
        uf_icon=METRICA_ICONOS['uf']['icono'],
        uf_icon_color=METRICA_ICONOS['uf']['color'],
        uf_val=eco['uf'],
        uv_icon=METRICA_ICONOS['uv']['icono'],
        uv_icon_color=METRICA_ICONOS['uv']['color'],
        uv_prom_val=uv_prom_val,
        aire_icon=METRICA_ICONOS['aire']['icono'],
        aire_icon_color=METRICA_ICONOS['aire']['color'],
        feriado_nombre=feriado['nombre'],
        feriado_fecha=feriado['fecha'],
        feriado_dias=feriado['dias'],
        titulo_clima=titulo_clima,
        clima_cards_html=clima_cards_html,
        subtitulo_heladas=subtitulo_heladas,
        pos_cero=pos_cero,
        gauge_puntos_html=gauge_puntos_html,
        lunar_days_html=lunar_days_html,
        combustibles_cards_html=combustibles_cards_html,
        html_destacada=html_destacada,
        noticias_col1=noticias_col1,
        noticias_col2=noticias_col2,
        html_futbol=html_futbol,
        frase=extra['frase'],
        autor=extra['autor'],
        dato_maule=extra['dato'],
        articulo_categoria=articulo['categoria'],
        articulo_titulo=articulo['titulo'],
        articulo_texto=articulo['texto']
    )

def enviar_pdf_telegram(pdf_bytes, caption_text="", nombre_archivo="boletin.pdf"):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.error("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption_text}
    files = {"document": (nombre_archivo, pdf_bytes, "application/pdf")}

    try:
        resp = HTTP_SESSION.post(url, data=payload, files=files, timeout=60)
        resp.raise_for_status()
        logging.info(f"Boletín PDF '{nombre_archivo}' enviado con éxito a Telegram.")
    except Exception as e:
        logging.error(f"Error al enviar a Telegram: {e}")

async def main_async():
    ahora = datetime.datetime.now(ZONA_CL)
    edicion = edicion_objetivo(ahora)

    if not FORZAR_ENVIO and edicion is None:
        logging.info(f"Hora actual en Chile: {ahora.strftime('%H:%M')} — no toca enviar. Saliendo.")
        return

    fecha_str = ahora.strftime("%Y-%m-%d")
    if not FORZAR_ENVIO:
        estado = cargar_estado_envio()
        if estado.get("fecha") == fecha_str and estado.get("edicion") == edicion:
            logging.info(f"La edición '{edicion}' del {fecha_str} ya fue enviada antes. Saliendo.")
            return

    logging.info("🔄 Recopilando información para el Boletín Maule...")
    es_manana = edicion == "manana" if edicion is not None else ahora.hour < 15
    idx_dia = 0 if es_manana else 1
    fecha_reporte = ahora if es_manana else ahora + datetime.timedelta(days=1)

    # 1. Datos varios
    eco = obtener_indicadores_economicos()
    feriado = obtener_proximo_feriado(ahora)
    luna = obtener_fase_lunar_semanal(ahora)
    extra = obtener_santoral_y_frase(ahora)
    articulo = obtener_articulo_utilidad(ahora)

    # 2. Clima
    datos_clima = {}
    for ciudad, coords in CIUDADES.items():
        raw = obtener_clima(coords["lat"], coords["lon"])
        curr = raw.get("current", {})
        daily = raw.get("daily", {})
        
        temp_destacada = round(curr.get("temperature_2m", 0)) if es_manana else round(daily.get("temperature_2m_max", [0, 0])[idx_dia])
        uv_max = daily.get("uv_index_max", [0.0, 0.0])[idx_dia]
        
        datos_clima[ciudad] = {
            "temp": temp_destacada,
            "min": round(daily.get("temperature_2m_min", [0, 0])[idx_dia]),
            "max": round(daily.get("temperature_2m_max", [0, 0])[idx_dia]),
            "viento": round(curr.get("wind_speed_10m", 0)),
            "desc": WMO_CODES.get(curr.get("weather_code", 3), "—"),
            "codigo": curr.get("weather_code", 3),
            "tmin_madrugada": round(daily.get("temperature_2m_min", [0, 0])[idx_dia], 1),
            "uv": uv_max
        }

    # 3. Noticias
    titulos_vistos = set()
    datos_noticias = {}
    
    destacada = buscar_noticias("noticias Maule Chile", titulos_vistos, 1)
    if not destacada:
        destacada = noticias_tema("NATION", titulos_vistos, 1)
    datos_noticias["Destacada"] = destacada

    datos_noticias["Longaví"] = buscar_noticias('"Longaví" Chile', titulos_vistos, 2)
    datos_noticias["Linares"] = buscar_noticias('"Linares" Chile', titulos_vistos, 2)
    datos_noticias["Yerbas Buenas"] = buscar_noticias('"Yerbas Buenas" Chile', titulos_vistos, 2)
    datos_noticias["Chile"] = noticias_tema("NATION", titulos_vistos, 2)
    datos_noticias["Mundo"] = noticias_tema("WORLD", titulos_vistos, 2)
    datos_noticias["Salud"] = buscar_noticias("salud bienestar Chile", titulos_vistos, 2)
    datos_noticias["Tecnología"] = noticias_tema("TECHNOLOGY", titulos_vistos, 2)
    datos_noticias["Deportes"] = noticias_tema("SPORTS", titulos_vistos, 2)
    datos_noticias["Entretención"] = buscar_noticias("espectaculos entretenimiento Chile", titulos_vistos, 2)
    datos_noticias["Tendencias"] = buscar_noticias("tendencias viral Chile", titulos_vistos, 2)

    # 4. Combustibles y Fútbol
    datos_combustible = mejores_precios_combustible()
    tabla_futbol = obtener_tabla_futbol(top_n=10)
    html_futbol = renderizar_tabla_futbol(tabla_futbol)

    # 5. Renderizado PDF
    logging.info("🎨 Generando HTML y renderizando PDF vectorial con Playwright...")
    html_final = renderizar_plantilla_html(
        ahora, fecha_reporte, es_manana, eco, feriado, luna, extra, 
        datos_clima, datos_noticias, datos_combustible, html_futbol,
        articulo=articulo
    )
    pdf_bytes = await html_a_pdf(html_final)

    # 6. Envío
    icono_edicion = "☀️" if es_manana else "🌙"
    nombre_edicion = "Edición Mañana" if es_manana else "Edición Noche"
    dia_nombre = DIAS_ESP[ahora.weekday()]
    mes_nombre = MESES_ESP[ahora.month - 1]
    
    caption = (
        f"🗞️ Boletín Maule — {nombre_edicion} {icono_edicion}\n"
        f"📅 {dia_nombre} {ahora.day} de {mes_nombre} de {ahora.year} — {ahora.strftime('%H:%M')} hrs\n"
        f"📍 Longaví · Linares · Yerbas Buenas"
    )

    tipo_edicion = "Manana" if es_manana else "Noche"
    nombre_dinamico = f"Boletin_Maule_{fecha_reporte.strftime('%Y-%m-%d')}_{tipo_edicion}.pdf"

    logging.info(f"📤 Enviando PDF ({nombre_dinamico}) a Telegram...")
    enviar_pdf_telegram(pdf_bytes, caption_text=caption, nombre_archivo=nombre_dinamico)

    if not FORZAR_ENVIO and edicion is not None:
        guardar_estado_envio(fecha_str, edicion)
        logging.info(f"📝 Estado guardado: edición '{edicion}' del {fecha_str} enviada.")

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
