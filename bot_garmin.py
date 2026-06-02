import os
import logging
import json
import requests
from datetime import date, timedelta, datetime, time, timezone
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import anthropic

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
TELEGRAM_USER_ID = int(os.environ.get("TELEGRAM_USER_ID", "5063997331"))
GARMIN_MCP_URL = "https://garmin-mcp-server-production.up.railway.app"

logging.basicConfig(level=logging.INFO)

AGENDA = []
NOTAS = []

SYSTEM_PROMPT = """Eres OMS-24, el asistente personal de Óscar. Eres inteligente, directo y útil en cualquier tema.

Tienes acceso COMPLETO a todos los datos de Garmin de Óscar: cualquier métrica, cualquier fecha histórica, actividades, sueño, pulso, body battery, estrés, VO2 max, récords personales, hidratación, pasos.

También gestionas su agenda y notas personales.

COMANDOS:
- Para guardar cita escribe al final: [GUARDAR_CITA: fecha|hora|descripcion]
- Para guardar nota escribe al final: [GUARDAR_NOTA: texto]

Responde siempre en español, de forma clara y directa."""


def get_garmin_data(query=None):
    """Obtiene datos del garmin-mcp-server"""
    try:
        # Llamada al servidor MCP con la consulta del usuario
        payload = {
            "query": query or "dame un resumen completo de hoy",
            "date": date.today().isoformat()
        }
        response = requests.post(
            f"{GARMIN_MCP_URL}/query",
            json=payload,
            timeout=30
        )
        if response.status_code == 200:
            return response.json()
        else:
            # Fallback: pedir datos básicos
            response = requests.get(f"{GARMIN_MCP_URL}/health", timeout=10)
            return {"status": "conectado", "detalle": response.text[:500]}
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
    await update.message.reply_text("⏳ Consultando datos...")

    garmin_data = get_garmin_data(user_message)
    agenda_texto = json.dumps(AGENDA, ensure_ascii=False) if AGENDA else "Sin citas"
    notas_texto = json.dumps(NOTAS, ensure_ascii=False) if NOTAS else "Sin notas"

    context_message = f"""
El usuario dice: {user_message}

Fecha y hora actual: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")} UTC

Datos de Garmin (via servidor MCP):
{json.dumps(garmin_data, ensure_ascii=False, default=str)[:4000]}

Agenda: {agenda_texto}
Notas: {notas_texto}
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
        garmin_data = get_garmin_data("resumen matutino completo")
        claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            system="Eres OMS-24. Genera un informe matutino breve y motivador en español.",
            messages=[{"role": "user", "content": f"Datos Garmin: {json.dumps(garmin_data, ensure_ascii=False, default=str)[:2000]}"}]
        )
        await context.bot.send_message(
            chat_id=TELEGRAM_USER_ID,
            text=f"🌅 Buenos días Óscar!\n\n{response.content[0].text}"
        )
    except Exception as e:
        logging.error(f"Error informe matutino: {e}")


def main():
    print("🤖 Bot iniciando...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Informe matutino 8:00 España (6:00 UTC verano)
    hora_utc = time(hour=6, minute=0, tzinfo=timezone.utc)
    app.job_queue.run_daily(informe_matutino, time=hora_utc)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Bot activo — esperando mensajes en Telegram")
    app.run_polling()


if __name__ == "__main__":
    main()