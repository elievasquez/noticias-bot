import html
import logging
from config import HTTP_SESSION, EQUIPO_DESTACADO

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

    except Exception as e:
        logging.error(f"Error al obtener la tabla de fútbol: {e}")
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