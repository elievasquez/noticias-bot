import os
import re
from zoneinfo import ZoneInfo
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import requests

# ==========================================
# CONFIGURACIÓN GENERAL Y VARIABLES ENTORNO
# ==========================================

ZONA_CL = ZoneInfo("America/Santiago")

ARCHIVO_ESTADO_ENVIO = "estado_envio.json"
UMBRAL_HELADA_C = 3.0
RADIO_KM_COMBUSTIBLE = 15
EQUIPO_DESTACADO = "None"
TOLERANCIA_MINUTOS = 30

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

DIAS_ESP = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MESES_ESP = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

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

METRICA_ICONOS = {
    "dolar": {"icono": "💵", "color": "#00A896"},
    "uf":    {"icono": "📊", "color": "#6366F1"},
    "uv":    {"icono": "☀️", "color": "#F97316"},
    "aire":  {"icono": "🌾", "color": "#22C55E"},
}

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