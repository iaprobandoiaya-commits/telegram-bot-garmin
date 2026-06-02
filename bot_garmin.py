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
request_counter = 0

TOOLS_LIST = [
    "get_activities", "get_activities_by_date", "get_last_activity",
    "get_daily_summary", "get_daily_health_snapshot", "get_heart_rate",
    "get_resting_heart_rate", "get_sleep_data", "get_sleep_data_range",
    "get_stress", "get_stress_range", "get_body_battery", "get_steps",
    "get_daily_steps_range", "get_weekly_steps", "get_hrv", "get_hrv_range",
    "get_vo2max", "get_vo2max_range", "get_spo2", "get_spo2_range",
    "get_respiration", "get_respiration_range", "get_training_readiness",
    "get_training_readiness_range", "get_training_status", "get_progress_summary",
    "get_personal_records", "get_race_predictions", "get_endurance_score",
    "get_hill_score", "get_fitness_age", "get_body_composition", "get_weigh_ins",
    "get_latest_weight", "get_goals", "get_earned_badges", "get_gear",
    "get_user_profile", "get_activity_details", "get_activity_splits",
    "get_activity_hr_zones", "get_weekly_intensity_minutes"
]

SYSTEM_PROMPT = """Eres OMS-24, el asistente personal de Óscar. Eres inteligente, directo y útil en cualquier tema.

Tienes acceso COMPLETO a todos los datos de Garmin de Óscar via servidor MCP. Puedes consultar CUALQUIER métrica y CUALQUIER fecha histórica.

HERRAMIENTAS DISPONIBLES (llama a call_garmin cuando necesites datos):
- get_daily_health_snapshot(date) — resumen completo de un día
- get_sleep_data_range(startDate, endDate) — sueño por rango de fechas
- get_activities_by_date(startDate, endDate) — actividades por rango
- get_heart_rate(date) — frecuencia cardíaca de un día
- get_hrv_range(startDate, endDate) — HRV por rango
- get_stress_range(startDate, endDate) — estrés por rango
- get_vo2max_range(startDate, endDate) — VO2 max por rango
- get_progress_summary(startDate, endDate, metric) — resumen de progreso
- get_body_composition(startDate, endDate) — composición corporal
- get_personal_records() — récords personales
- get_race_predictions() — predicciones de carrera
- get_training_status(date) — estado de entrenamiento
- get_daily_steps_range(startDate, endDate) — pasos por rango
Y muchas más.

IMPORTANTE: Cuando el usuario pregunta por datos históricos, usa las fechas correctas. Hoy es {today}.

También gestionas agenda y notas:
- Para guardar cita: [GUARDAR_CITA: fecha|hora|descripcion]
- Para guardar nota: [GUARDAR_NOTA: texto]

Responde siempre en español, directo y claro."""


def call_garmin(tool_name, arguments={}):
    global request_counter
    request_counter += 1
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": request_counter,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        response = requests.post(
            f"{GARMIN_MCP_URL}/message",
            json=payload,
            timeout=30
        )
        if response.status_code == 200:
            data = response.json()
            if "result" in data:
                return data["result"]
            elif "error" in data:
                return {"error": data["error"]}
        return {"error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"error": str(e)}


def get_contexto_inicial():
    """Obtiene un snapshot básico para contexto"""
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    snapshot = call_garmin("get_daily_health_snapshot", {"date": today})
    last_activity = call_garmin("get_last_activity")
    return {
        "snapshot_hoy": snapshot,
        "ultima_actividad": last_activity,
        "fecha_hoy": today,
        "fecha_ayer": yesterday
    }


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

    today = date.today().isoformat()
    contexto = get_contexto_inicial()
    agenda_texto = json.dumps(AGENDA, ensure_ascii=False) if AGENDA else "Sin citas"
    notas_texto = json.dumps(NOTAS, ensure_ascii=False) if NOTAS else "Sin notas"

    system = SYSTEM_PROMPT.replace("{today}", today)

    context_message = f"""
El usuario dice: {user_message}

Fecha actual: {today}
Hora actual: {datetime.now(timezone.utc).strftime("%H:%M")} UTC

Contexto Garmin actual:
{json.dumps(contexto, ensure_ascii=False, default=str)[:4000]}

Agenda: {agenda_texto}
Notas: {notas_texto}

INSTRUCCIÓN: Si el usuario pregunta por datos históricos específicos (sueño de mayo, actividades de abril, etc.), indícale qué datos concretos necesitas y yo haré la consulta. Si puedes responder con el contexto actual, hazlo directamente."""

    try:
        claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=system,
            messages=[{"role": "user", "content": context_message}]
        )
        answer = response.content[0].text

        # Si Claude necesita datos históricos, hacer la consulta
        if "[CONSULTAR:" in answer:
            try:
                inicio = answer.index("[CONSULTAR:") + 11
                fin = answer.index("]", inicio)
                consulta = json.loads(answer[inicio:fin])
                datos_extra = call_garmin(consulta["tool"], consulta.get("args", {}))
                
                response2 = claude.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=1000,
                    system=system,
                    messages=[
                        {"role": "user", "content": context_message},
                        {"role": "assistant", "content": answer},
                        {"role": "user", "content": f"Datos obtenidos: {json.dumps(datos_extra, ensure_ascii=False, default=str)[:3000]}"}
                    ]
                )
                answer = response2.content[0].text
            except Exception:
                pass

        answer = procesar_comandos(answer)
    except Exception as e:
        answer = f"Error: {str(e)}"

    await update.message.reply_text(answer)


async def informe_matutino(context):
    try:
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        snapshot = call_garmin("get_daily_health_snapshot", {"date": yesterday})
        ultima = call_garmin("get_last_activity")

        claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            system="Eres OMS-24. Genera un informe matutino breve y motivador en español con los datos de Garmin de ayer.",
            messages=[{"role": "user", "content": f"Datos de ayer ({yesterday}): {json.dumps(snapshot, ensure_ascii=False, default=str)[:2000]}\nÚltima actividad: {json.dumps(ultima, ensure_ascii=False, default=str)[:500]}"}]
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

    hora_utc = time(hour=6, minute=0, tzinfo=timezone.utc)
    app.job_queue.run_daily(informe_matutino, time=hora_utc)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Bot activo — esperando mensajes en Telegram")
    app.run_polling()


if __name__ == "__main__":
    main()