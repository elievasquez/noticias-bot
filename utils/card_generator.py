import io
import math
import os
from PIL import Image, ImageDraw, ImageFont

# Definir la ruta base a la carpeta de fuentes local
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS_DIR = os.path.join(BASE_DIR, "assets", "fonts")

# Paleta corporativa
TITULAR = (90, 110, 127)       # #5A6E7F
FONDO = (255, 255, 255)        # #FFFFFF
CTA = (47, 128, 237)           # #2F80ED
SEPARADOR = (229, 233, 236)    # #E5E9EC
TEXTO_CUERPO = (51, 64, 74)    # #33404A
GRIS_TEXTO = (138, 151, 161)   # #8A97A1
ALERTA = (224, 82, 63)         # #E0523F
ALERTA_FONDO = (253, 235, 232) # #FDEBE8

def _font(nombre, size):
    ruta = os.path.join(FONTS_DIR, nombre)
    try:
        return ImageFont.truetype(ruta, size)
    except OSError:
        # Fallback a fuente predeterminada si no encuentra la fuente específica
        return ImageFont.load_default()

def _icono_sol(draw, cx, cy, r, color):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    for i in range(8):
        ang = i * (2 * math.pi / 8)
        x1 = cx + math.cos(ang) * (r + 7)
        y1 = cy + math.sin(ang) * (r + 7)
        x2 = cx + math.cos(ang) * (r + 17)
        y2 = cy + math.sin(ang) * (r + 17)
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
        x1 = cx - math.cos(ang) * r
        y1 = cy - math.sin(ang) * r
        x2 = cx + math.cos(ang) * r
        y2 = cy + math.sin(ang) * r
        draw.line([x1, y1, x2, y2], fill=color, width=4)

def generar_tarjeta_clima(ciudades, fecha_texto, hora_edicion) -> io.BytesIO:
    """
    Recibe los datos del clima y retorna un buffer de bytes en memoria (BytesIO) con la imagen PNG.
    """
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

    # Header
    draw.rounded_rectangle([margen, 56, margen + 300, 56 + 34], radius=6, fill=SEPARADOR)
    draw.text((margen + 16, 63), "EDICIÓN DE LA MAÑANA", font=f_etiqueta, fill=CTA)
    draw.text((margen, 108), "Boletín Maule", font=f_titulo, fill=TITULAR)
    draw.text((margen, 178), f"{hora_edicion} · {fecha_texto}", font=f_subtitulo, fill=GRIS_TEXTO)

    # Líneas separadoras
    draw.line([margen, 232, margen + 90, 232], fill=CTA, width=3)
    draw.line([margen + 90, 232, W - margen, 232], fill=SEPARADOR, width=3)

    y_cursor = 268
    card_h = 196
    card_gap = 22

    # Cards por ciudad
    for c in ciudades:
        box = [margen, y_cursor, W - margen, y_cursor + card_h]
        draw.rounded_rectangle(box, radius=20, fill=FONDO, outline=SEPARADOR, width=2)

        icon_cx, icon_cy = margen + 84, y_cursor + card_h // 2
        if "Despejado" in c.get("desc", ""):
            _icono_sol(draw, icon_cx, icon_cy, 30, CTA)
        else:
            _icono_nube(draw, icon_cx, icon_cy, 30, SEPARADOR, TITULAR)

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

    # Bloque de heladas
    alertas = [c for c in ciudades if c.get("helada")]
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

    # Footer
    draw.line([margen, H - 76, W - margen, H - 76], fill=SEPARADOR, width=2)
    nombres_ciudades = " · ".join([c["nombre"] for c in ciudades])
    draw.text((margen, H - 54), f"Boletín automático · {nombres_ciudades}", font=f_footer, fill=GRIS_TEXTO)

    # Convertir la imagen a BytesIO para enviar por Telegram sin guardar en disco
    bio = io.BytesIO()
    bio.name = 'tarjeta_clima.png'
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio
