import os
import logging
import json
from datetime import date, timedelta, datetime, time, timezone
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from garminconnect import Garmin
import anthropic

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
GARMIN_EMAIL = os.environ.get("GARMIN_EMAIL")
GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD")
TELEGRAM_USER_ID = int(os.environ.get("TELEGRAM_USER_ID", "5063997331"))

logging.basicConfig(level=logging.INFO)

# Almacenamiento en memoria (se mantiene mientras Railway no reinicie)
AGENDA = []
NOTAS = []

SYSTEM_PROMPT = """Eres OMS-24, el asistente personal de Óscar. Eres inteligente, directo y útil en cualquier tema.

Tienes acceso a los datos de Garmin de Óscar en tiempo real: actividades, sueño, pasos, frecuencia cardíaca, body battery, estrés, VO2 max, récords personales.

También gestionas su agenda personal y sus notas.

COMANDOS QUE PUEDES USAR EN TU RESPUESTA:
- Si el usuario quiere guardar una cita escribe al final: [GUARDAR_CITA: fecha|hora|descripcion]
- Si el usuario quiere guardar una nota escribe al final: [GUARDAR_NOTA: texto]

Puedes ayudar con cualquier cosa: entrenamiento, salud, tecnología, cocina, viajes, redactar textos, cálculos, preguntas generales.

Responde siempre en español, de forma clara y directa."""


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
        data = {}

        try:
            data['pasos_hoy'] = client.get_steps_data(today)
        except:
            data['pasos_hoy'] = "No disponible"
        try:
            data['sueno_anoche'] = client.get_sleep_data(yesterday)
        except:
            data['sueno_anoche'] = "No disponible"
        try:
            data['frecuencia_cardiaca'] = client.get_heart_rates(today)
        except:
            data['frecuencia_cardiaca'] = "No disponible"
        try:
            data['actividades_recientes'] = client.get_activities(0, 30)
        except:
            data['actividades_recientes'] = []
        try:
            data['body_battery'] = client.get_body_battery(today)
        except:
            data['body_battery'] = "No disponible"
        try:
            data['estres'] = client.get_stress_data(today)
        except:
            data['estres'] = "No disponible"
        try:
            data['vo2max'] = client.get_max_metrics(today)
        except:
            data['vo2max'] = "No disponible"
        try:
            data['records'] = client.get_personal_record()
        except:
            data['records'] = "No disponible"

        return data
    except Exception as e:
        return {"error": str(e)}


def procesar_comandos(texto):
    try:
        if "[GUARDAR_CITA:" in texto:
            inicio = texto.index("[GUARDAR_CITA:") + 14
            fin = texto.index("]", inicio)
            partes = texto[inicio:fin].split("|")
            if len(partes) == 3:
                AGENDA.append({
                    "fecha": partes[0].strip(),
                    "hora": partes[1].strip(),
                    "descripcion": partes[2].strip()
                })
            texto = texto[:texto.index("[GUARDAR_CITA:")].strip()
    except Exception:
        pass

    try:
        if "[GUARDAR_NOTA:" in texto:
            inicio = texto.index("[GUARDAR_NOTA:") + 14
            fin = texto.index("]", inicio)
            NOTAS.append({
                "fecha": date.today().isoformat(),
                "texto": texto[inicio:fin].strip()
            })
            texto = texto[:texto.index("[GUARDAR_NOTA:")].strip()
    except Exception:
        pass

    return texto


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != TELEGRAM_USER_ID:
        await update.message.reply_text("No autorizado.")
        return

    user_message = update.message.text
    await update.message.reply_text("⏳ Procesando...")

    garmin_data = get_garmin_data()
    agenda_texto = json.dumps(AGENDA, ensure_ascii=False) if AGENDA else "Sin citas guardadas"
    notas_texto = json.dumps(NOTAS, ensure_ascii=False) if NOTAS else "Sin notas guardadas"

    context_message = f"""
El usuario dice: {user_message}

Fecha y hora actual (España): {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")} UTC

Datos de Garmin:
{json.dumps(garmin_data, ensure_ascii=False, default=str)[:3000]}

Agenda:
{agenda_texto}

Notas:
{notas_texto}
"""

    try:
        claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": context_message}]
        )
        answer = response.content[0].text
        answer = procesar_comandos(answer)
    except Exception as e:
        answer = f"Error: {str(e)}"

    await update.message.reply_text(answer)


async def informe_matutino(context):
    try:
        garmin_data = get_garmin_data()
        claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            system="Eres OMS-24. Genera un informe matutino breve y motivador en español con los datos de Garmin.",
            messages=[{"role": "user", "content": f"Datos Garmin de Óscar: {json.dumps(garmin_data, ensure_ascii=False, default=str)[:2000]}"}]
        )
        texto = f"🌅 Buenos días Óscar!\n\n{response.content[0].text}"
        await context.bot.send_message(chat_id=TELEGRAM_USER_ID, text=texto)
    except Exception as e:
        logging.error(f"Error informe matutino: {e}")


def main():
    print("🤖 Bot iniciando...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Informe matutino a las 8:00 hora España (UTC+2 verano = 6:00 UTC)
    hora_utc = time(hour=6, minute=0, tzinfo=timezone.utc)
    app.job_queue.run_daily(informe_matutino, time=hora_utc)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Bot activo — esperando mensajes en Telegram")
    app.run_polling()


if __name__ == "__main__":
    main()