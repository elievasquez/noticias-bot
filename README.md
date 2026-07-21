# 📰 Boletín automático — Longaví / Linares / Yerbas Buenas

Bot que corre en GitHub Actions y te manda por Telegram, todos los días a las
**9:00** y a las **21:00** (hora de Chile), un boletín con:

- Noticias locales de Longaví, Linares y Yerbas Buenas
- Precios de combustible (mejor precio / comparador)
- Clima de las tres localidades
- Aviso de heladas
- Noticias nacionales, del mundo y de tecnología

No necesita servidor propio: todo corre gratis en GitHub Actions.

**Formato:** cada envío llega como **2 mensajes** de Telegram:
1. Resumen rápido + clima + aviso de heladas (corto, ideal para fijar/pin en el chat).
2. Noticias locales, nacionales/mundo/tecnología y combustible.

La edición de las **9:00** va completa. La de las **21:00** va resumida
(menos noticias por sección), para no repetir todo lo mismo dos veces al día.
Esto se ajusta en `NOTICIAS_LOCALES` y `NOTICIAS_GLOBALES` dentro del script.

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

Y estos otros (opcionales, ver sección de combustibles más abajo):

| Nombre | Valor |
|---|---|
| `CNE_EMAIL` | correo de tu cuenta gratuita en api.cne.cl |
| `CNE_PASSWORD` | contraseña de esa cuenta |

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

La fuente es la **API oficial de la CNE** (https://api.cne.cl/apidocs), la
misma que usa la app "Bencina en Línea". A diferencia de lo que se pensaba
al principio, **no usa `auth_key`**: se autentica con correo y contraseña
de una cuenta gratuita, lo que entrega un token temporal.

1. Entra a https://api.cne.cl/register y crea una cuenta gratuita (correo + contraseña).
2. Agrega esas credenciales como secrets `CNE_EMAIL` y `CNE_PASSWORD` (paso 3 de arriba).

El script hace login automáticamente (`POST /api/login`), guarda el token
durante esa ejecución y consulta `GET /api/v4/estaciones`. Como la API no
entrega la comuna de cada estación, el filtro por ciudad se hace por
**cercanía geográfica**: se buscan estaciones dentro de un radio (por
defecto 15 km, variable `RADIO_KM_COMBUSTIBLE`) alrededor de las
coordenadas de cada localidad, y se muestra el precio más bajo encontrado
para 93, 95, 97 y diésel (considerando tanto atención asistida como
autoservicio).

Mientras no configures `CNE_EMAIL`/`CNE_PASSWORD` — o si no hay ninguna
estación dentro del radio — el boletín igual funciona: deja el link directo
a bencinaenlinea.cl para comparar en un clic.

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
