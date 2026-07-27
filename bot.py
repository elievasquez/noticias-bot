from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from utils.card_generator import generar_tarjeta_clima
from utils.clima import obtener_clima  # Función que consulta la API de clima

async def enviar_boletin_clima(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    # 1. Obtener datos reales actualizados
    ciudades_data = obtener_clima() 
    fecha_hoy = "Lunes 27 de julio"
    hora_edicion = "Edición de las 9:00"

    # 2. Generar el buffer PNG
    imagen_bytes = generar_tarjeta_clima(ciudades_data, fecha_hoy, hora_edicion)

    # 3. Enviar mediante Telegram sendPhoto
    await context.bot.send_photo(
        chat_id=chat_id,
        photo=imagen_bytes,
        caption="🌦️ *Boletín de Clima y Heladas del Maule*",
        parse_mode="Markdown"
    )

# Configuración del handler
app = ApplicationBuilder().token("TU_TELEGRAM_BOT_TOKEN").build()
app.add_handler(CommandHandler("clima", enviar_boletin_clima))
app.run_polling()
