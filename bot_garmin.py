import os
import asyncio
import logging
from datetime import date, timedelta
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from garminconnect import Garmin
import anthropic

# ============================================
# CONFIGURACIÓN - PON TUS DATOS AQUÍ
# ============================================
import os
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
GARMIN_EMAIL = os.environ.get("GARMIN_EMAIL")
GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD")
TELEGRAM_USER_ID = int(os.environ.get("TELEGRAM_USER_ID", "5063997331"))
# ============================================

logging.basicConfig(level=logging.INFO)

# Sistema de prompt — personalidad del bot
SYSTEM_PROMPT = """Eres OMS-24, el asistente personal de Óscar. Eres inteligente, directo y útil en cualquier tema.

Tienes acceso a los datos de Garmin de Óscar en tiempo real: actividades, sueño, pasos, frecuencia cardíaca.

Puedes ayudar con:
- Análisis de entrenamiento y salud basado en sus datos reales de Garmin
- Cualquier pregunta general: tecnología, ciencia, cocina, viajes, idiomas, matemáticas, etc.
- Redactar textos, emails, mensajes
- Consejos, recomendaciones, planificación
- Conversación general

Responde siempre en español, de forma clara y directa. Si tienes datos de Garmin relevantes úsalos, si no, responde como asistente general sin mencionar que no tienes datos."""

def get_garmin_data():
    try:
        client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
        try:
            client.login(tokenstore="~/.garth")
        except:
            client.login()
            client.garth.dump("~/.garth")

        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        hace_30_dias = (date.today() - timedelta(days=30)).isoformat()

        data = {}

        # Pasos
        try:
            data['pasos_hoy'] = client.get_steps_data(today)
        except:
            data['pasos_hoy'] = "No disponible"

        # Sueño
        try:
            data['sueno_anoche'] = client.get_sleep_data(yesterday)
        except:
            data['sueno_anoche'] = "No disponible"

        # Frecuencia cardíaca
        try:
            data['frecuencia_cardiaca_hoy'] = client.get_heart_rates(today)
        except:
            data['frecuencia_cardiaca_hoy'] = "No disponible"

        # Últimas 30 actividades
        try:
            data['actividades_recientes'] = client.get_activities(0, 30)
        except:
            data['actividades_recientes'] = []

        # Estadísticas últimos 30 días
        try:
            data['stats_30_dias'] = client.get_stats_and_body(today)
        except:
            data['stats_30_dias'] = "No disponible"

        # Body battery
        try:
            data['body_battery'] = client.get_body_battery(today)
        except:
            data['body_battery'] = "No disponible"

        # Estrés
        try:
            data['estres_hoy'] = client.get_stress_data(today)
        except:
            data['estres_hoy'] = "No disponible"

        # VO2 Max
        try:
            data['vo2max'] = client.get_max_metrics(today)
        except:
            data['vo2max'] = "No disponible"

        # Récords personales
        try:
            data['records_personales'] = client.get_personal_record()
        except:
            data['records_personales'] = "No disponible"

        # Hidratación
        try:
            data['hidratacion'] = client.get_hydration_data(today)
        except:
            data['hidratacion'] = "No disponible"

        return data
    except Exception as e:
        return {"error": str(e)}

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesa cada mensaje recibido"""
    
    # Seguridad — solo tu ID puede usarlo
    if update.effective_user.id != TELEGRAM_USER_ID:
        await update.message.reply_text("No autorizado.")
        return
    
    user_message = update.message.text
    await update.message.reply_text("⏳ Consultando datos...")
    
    # Obtener datos de Garmin
    garmin_data = get_garmin_data()
    
    # Construir contexto para Claude
    context_message = f"""
El usuario pregunta: {user_message}

Datos actuales de Garmin:
{garmin_data}

Fecha de hoy: {date.today().isoformat()}
"""
    
    # Llamar a Claude
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": context_message}]
        )
        answer = response.content[0].text
    except Exception as e:
        answer = f"Error al contactar con Claude: {str(e)}"
    
    await update.message.reply_text(answer)

def main():
    print("🤖 Bot iniciando...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Bot activo — esperando mensajes en Telegram")
    app.run_polling()

if __name__ == "__main__":
    main()