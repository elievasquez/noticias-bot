import re
import math
import logging
from config import HTTP_SESSION, CNE_EMAIL, CNE_PASSWORD, CIUDADES, RADIO_KM_COMBUSTIBLE

_CNE_TOKEN = None
_CNE_ESTACIONES = None

def cne_login():
    global _CNE_TOKEN
    if _CNE_TOKEN or not CNE_EMAIL or not CNE_PASSWORD: 
        return _CNE_TOKEN
    try:
        r = HTTP_SESSION.post("https://api.cne.cl/api/login", data={"email": CNE_EMAIL, "password": CNE_PASSWORD}, headers={"Accept": "application/json"}, timeout=20)
        if r.ok: 
            _CNE_TOKEN = r.json().get("token")
    except Exception as e:
        logging.warning(f"No se pudo hacer login en CNE: {e}")
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
        r = HTTP_SESSION.get("https://api.cne.cl/api/v4/estaciones", headers={"Accept": "application/json", "Authorization": f"Bearer {token}"}, timeout=30)
        _CNE_ESTACIONES = r.json() if r.ok and isinstance(r.json(), list) else []
    except Exception as e:
        logging.warning(f"Error al obtener estaciones de CNE: {e}")
        _CNE_ESTACIONES = []
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