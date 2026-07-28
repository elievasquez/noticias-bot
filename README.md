# 🗞️ Boletín Automático Maule

Bot en Python y GitHub Actions que genera y envía automáticamente un **boletín informativo en formato imagen PNG** a Telegram. Diseñado con una tipografía limpia y estilo dinámico adaptable (edición Mañana y Noche).

Cubre información clave para las comunas de **Longaví, Linares y Yerbas Buenas** (Región del Maule, Chile).

---

## 🚀 Características

* 🎨 **Diseño Dinámico**: Estilo visual adaptable a la hora del día (modo claro para la mañana, modo oscuro para la noche) mediante HTML/CSS renderizado con **Playwright**.
* 🌤️ **Pronóstico del Clima**: Datos de temperatura actual, mín/máx, viento y estado del tiempo vía Open-Meteo.
* ❄️ **Gauge de Heladas**: Indicador visual inteligente de riesgo de helada (temperaturas ≤ 3.0 °C), agrupando automáticamente comunas con temperaturas similares para evitar superposición.
* 📰 **Titulares de Noticias**: Búsqueda en tiempo real mediante RSS (noticias locales de Longaví, Linares, Yerbas Buenas, además de Chile, Mundo y Tecnología).
* ⛽ **Combustibles CNE**: Consulta directa a la API de la Comisión Nacional de Energía (CNE) para obtener el mejor precio de gasolina (93, 95, 97 y Diésel) en un radio de 15 km.
* 🤖 **100% Automatizado**: Se ejecuta sin servidor mediante **GitHub Actions** en horarios clave (09:00 y 21:00 hrs Chile).

---

## 🛠️ Tecnologías Utilizadas

* **Python 3.11**
* **Playwright** (Renderizado Chromium a alta resolución)
* **Requests & Feedparser** (Consultas API y RSS)
* **GitHub Actions** (Automatización CI/CD)
* **Telegram Bot API** (Envío directo de la imagen)

---

## ⚙️ Configuración del Repositorio

Para que el script se ejecute correctamente en GitHub Actions, debes configurar los siguientes **Secrets** en tu repositorio (*Settings > Secrets and variables > Actions*):

| Secret | Descripción | Requerido |
| :--- | :--- | :---: |
| `TELEGRAM_BOT_TOKEN` | Token de tu bot otorgado por BotFather | **Sí** |
| `TELEGRAM_CHAT_ID` | ID del canal o grupo de Telegram donde se enviará | **Sí** |
| `CNE_EMAIL` | Correo registrado en la API de CNE Chile | Opcional |
| `CNE_PASSWORD` | Contraseña registrada en la API de CNE Chile | Opcional |

---

## 💻 Ejecución Local

1. **Clona el repositorio:**
   ```bash
   git clone [https://github.com/elievasquez/noticias-bot.git](https://github.com/elievasquez/noticias-bot.git)
   cd noticias-bot
