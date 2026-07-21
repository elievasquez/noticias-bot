# 📰 Boletín automático — Longaví / Linares / Yerbas Buenas

Bot que corre en GitHub Actions y te manda por Telegram, todos los días a las
**9:00** y a las **21:00** (hora de Chile), un boletín con:

- Noticias locales de Longaví, Linares y Yerbas Buenas
- Precios de combustible (mejor precio / comparador)
- Clima de las tres localidades
- Aviso de heladas
- Noticias nacionales, del mundo y de tecnología

No necesita servidor propio: todo corre gratis en GitHub Actions.

---

## 1. Crear tu bot de Telegram

1. En Telegram, habla con **@BotFather**.
2. Envía `/newbot`, ponle un nombre (ej: `Boletín Maule`) y un usuario que
   termine en `bot` (ej: `boletin_maule_bot`).
3. BotFather te entrega un **token**, algo como
   `123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`. Guárdalo.
4. Ahora necesitas tu **chat_id**:
   - Búscate a ti mismo (o crea un grupo/canal) y mándale un mensaje cualquiera a tu bot recién creado.
   - Abre en el navegador:
     `https://api.telegram.org/bot<TU_TOKEN>/getUpdates`
   - Busca el campo `"chat":{"id":...}` — ese número es tu `chat_id`.

> Si prefieres un canal en vez de un chat privado, agrega el bot como
> administrador del canal y usa el id del canal (normalmente empieza con `-100`).

---

## 2. Subir este proyecto a GitHub

1. Crea un repositorio nuevo en GitHub (puede ser privado).
2. Sube todos estos archivos manteniendo la misma estructura de carpetas
   (`.github/workflows/noticias.yml` debe quedar en esa ruta exacta).

Desde tu computador, dentro de esta carpeta:

```bash
git init
git add .
git commit -m "Boletín automático inicial"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/TU_REPO.git
git push -u origin main
```

---

## 3. Configurar los "Secrets" en GitHub

En tu repositorio: **Settings → Secrets and variables → Actions → New repository secret**

Crea estos dos (obligatorios):

| Nombre | Valor |
|---|---|
| `TELEGRAM_BOT_TOKEN` | el token que te dio BotFather |
| `TELEGRAM_CHAT_ID` | tu chat_id |

Y este otro (opcional, ver sección de combustibles más abajo):

| Nombre | Valor |
|---|---|
| `CNE_AUTH_KEY` | tu auth_key de energiaabierta.cl |

---

## 4. Probarlo

Ve a la pestaña **Actions** de tu repositorio → selecciona el workflow
**"Boletín de Noticias"** → botón **"Run workflow"**. Esto lo fuerza a enviar
de inmediato, sin esperar a las 9:00 o 21:00, para que revises que todo llegue
bien a Telegram.

Una vez probado, el workflow queda corriendo solo, todos los días.

> El workflow se ejecuta cada hora y revisa internamente si en Chile son las
> 9:00 o las 21:00 antes de enviar algo. Esto es a propósito: así el horario
> se ajusta solo cuando Chile cambia entre horario de invierno y de verano,
> sin que tengas que tocar el cron.

---

## 5. Sobre los precios de combustible ⛽

La fuente oficial es **Bencina en Línea**, de la Comisión Nacional de
Energía (CNE). Su API de datos abiertos requiere una `auth_key` gratuita:

1. Entra a https://energiaabierta.cl y crea una cuenta gratuita.
2. Busca el dataset **"Bencina en Línea"** y genera tu `auth_key`.
3. Agrégala como secret `CNE_AUTH_KEY` (paso 3 de arriba).

Mientras no configures esa clave, el boletín igual funciona: en vez de los
precios exactos, te deja el link directo a bencinaenlinea.cl para comparar
en un clic. Si quieres, puedo ayudarte después a afinar el filtrado por
comuna una vez que tengas la `auth_key` y veamos el formato real que
devuelve la API (varía según el dataset exacto que te asignen).

---

## 6. Personalizar

Todo el contenido se arma en `scripts/enviar_noticias.py`:

- **Ciudades**: diccionario `CIUDADES` (agrega/quita localidades y sus coordenadas).
- **Horarios de envío**: `HORAS_DE_ENVIO = {9, 21}`.
- **Umbral de helada**: `UMBRAL_HELADA_C = 3.0` (°C).
- **Cantidad de noticias por sección**: `NOTICIAS_POR_SECCION`.
- **Búsquedas de noticias locales**: función `armar_boletin()`, línea donde
  se arma la consulta `f'"{ciudad}" Chile'` — puedes afinarla, por ejemplo
  agregando `"Región del Maule"` para filtrar mejor.

---

## 💡 Ideas para sumar más contenido

- **Alertas SENAPRED** (antes ONEMI): RSS de alertas y emergencias por región.
- **Calidad del aire**: SINCA (sinca.mma.gob.cl) tiene estaciones cercanas (Linares, Talca).
- **Nivel de ríos / riesgo de crecidas** (útil en invierno, zona de riego agrícola).
- **Cartelera de eventos locales** (ferias, fiestas costumbristas, actividades municipales).
- **Valor UF, dólar y UTM del día** (útil para trámites y sueldos).
- **Frase o efeméride del día**.
- **Resumen de fútbol chileno** (resultados/próximos partidos, ej. Ñublense, Rangers, Curicó Unido).
- **Feriados / días especiales próximos**.
- **Estado de la Ruta 5 / rutas Longaví–Linares** (Vialidad / cámaras de tránsito), útil si hay cortes por obras o accidentes.
- **Resumen agrícola**: precios de referencia de commodities (leche, trigo, remolacha) si te sirve para el trabajo.

## 🎨 Ideas de formato

- Mandar **un mensaje separado por sección** en vez de uno gigante (más fácil de leer en el celular, y puedes fijar el del clima).
- Usar **botones inline de Telegram** (ej. "Ver más noticias", "Ver mapa de combustibles") que abren links.
- Generar además una **imagen tipo "tarjeta resumen"** (con Pillow) con el clima y la helada, para compartir directo en un grupo de WhatsApp/Facebook del sector.
- Guardar cada boletín como archivo `.md` en una carpeta `historial/` del mismo repo (commit automático), para tener un archivo histórico consultable.
- Mandar un **resumen semanal los domingos** (variación de precios de combustible, heladas de la semana, etc.).

Si quieres, puedo implementar cualquiera de estas extensiones directamente en el script.
