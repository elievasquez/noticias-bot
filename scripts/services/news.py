import re
import html
import logging
import urllib.parse
import feedparser

def normalizar_titulo(titulo):
    return re.sub(r'\W+', '', titulo.lower())

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

def extraer_imagen_rss(entry):
    if hasattr(entry, 'media_content') and len(entry.media_content) > 0:
        return entry.media_content[0].get('url', '')
    if hasattr(entry, 'media_thumbnail') and len(entry.media_thumbnail) > 0:
        return entry.media_thumbnail[0].get('url', '')
    
    raw_html = getattr(entry, "summary", "") or getattr(entry, "description", "")
    match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw_html)
    if match:
        return match.group(1)
        
    return ""

def _fetch_rss_noticias(url, titulos_vistos, n=1, tipo_fuente="Prensa"):
    try:
        feed = feedparser.parse(url)
        res = []
        for e in feed.entries:
            titulo_limpio = limpiar_titulo_noticia(e.title)
            norm_t = normalizar_titulo(titulo_limpio)
            
            if norm_t in titulos_vistos:
                continue
                
            fuente = e.source.title if hasattr(e, "source") and getattr(e.source, "title", None) else tipo_fuente
            summary_raw = getattr(e, "summary", "") or getattr(e, "description", "")
            bajada = limpiar_bajada_rss(summary_raw, titulo_limpio)
            imagen_url = extraer_imagen_rss(e)
            
            titulos_vistos.add(norm_t)
            res.append({
                "titulo": titulo_limpio, 
                "bajada": bajada, 
                "fuente": fuente, 
                "imagen": imagen_url
            })
            if len(res) == n:
                break
        return res
    except Exception as e:
        logging.error(f"Error al obtener RSS noticias de {url}: {e}")
        return []

def buscar_noticias(query, titulos_vistos, n=1):
    q = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={q}&hl=es-419&gl=CL&ceid=CL:es"
    return _fetch_rss_noticias(url, titulos_vistos, n=n, tipo_fuente="Prensa")

def noticias_tema(tema, titulos_vistos, n=1):
    url = f"https://news.google.com/rss/headlines/section/topic/{tema}?hl=es-419&gl=CL&ceid=CL:es"
    return _fetch_rss_noticias(url, titulos_vistos, n=n, tipo_fuente="Noticias")