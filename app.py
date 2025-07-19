from flask import Flask, request, jsonify
import openai
import os
from dotenv import load_dotenv
import json
from collections import defaultdict, deque

# === CONFIGURACIONES ===
load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
project_id = os.getenv("OPENAI_PROJECT_ID")
organization_id = os.getenv("OPENAI_ORG_ID")

client = openai.OpenAI(
    api_key=api_key,
    project=project_id,
    organization=organization_id
)

app = Flask(__name__)

# === CARGAR TODO EL CONTEXTO UNA SOLA VEZ ===
txt_path = "lovely_taller.txt"
if os.path.exists(txt_path):
    with open(txt_path, "r", encoding="utf-8") as f:
        CONTEXTO_COMPLETO = f.read()
else:
    CONTEXTO_COMPLETO = ""

# Memoria por usuario: últimas interacciones
historial_conversacion = defaultdict(lambda: deque(maxlen=6))  # guarda últimas 6 entradas

def es_saludo(texto):
    texto = texto.lower().strip()
    return texto in ["hola", "buenas", "buen día", "buenas tardes", "buenas noches", "hey"]

@app.route("/webhook", methods=["POST"])
def responder():
    try:
        datos = request.get_json()
        print("🔎 JSON recibido desde WhatsApp/Twilio:")
        print(json.dumps(datos, indent=2))

        mensaje_usuario = datos.get("consulta", "")
        user_id = datos.get("user_id", "anon")  # ID para diferenciar sesiones
        if not mensaje_usuario:
            return jsonify({"error": "No se recibió ninguna consulta"}), 400

        # === PROMPT ULTRA RESTRICTIVO PERO AMIGABLE Y CON EMOJIS ===
        system_prompt = (
            "Sos un asistente virtual de Lovely Taller Deco. "
            "Ignorá todo lo que sabés previamente: tu ÚNICA fuente de verdad es el CONTEXTO que te paso. "
            "Si la pregunta del usuario está cubierta directa o indirectamente en el CONTEXTO, respondé de forma cálida, clara y usando emojis relevantes. "
            "Ejemplos: 📍 ubicación, 🛋️ sillones, ✅ garantía, ⏳ demoras, 💳 pagos, 📦 envíos. "
            "Si la pregunta NO está cubierta en el CONTEXTO, NO inventes nada y respondé siempre: "
            "'Mirá, con lo que tengo acá no te puedo confirmar eso, pero podés llamar al 011 6028‑1211 para más info.' "
            "Después de cada respuesta válida, sugerí 1 o 2 temas del CONTEXTO para continuar la charla "
            "(quiénes somos, showroom, garantía, envíos, precios, demoras, formas de pago). "
            "Respondé siempre en no más de 2 líneas antes de las sugerencias. "
            "Tené en cuenta todo el historial de la conversación para entender respuestas cortas como 'sí' o 'dale'."
        )

        # === ARMAMOS EL HISTORIAL DE CONVERSACIÓN ===
        historial = list(historial_conversacion[user_id])  # últimas interacciones
        mensajes_historial = []

        for rol, msg in historial:
            mensajes_historial.append({"role": rol, "content": msg})

        # Nuevo mensaje del usuario
        mensajes_historial.append({"role": "user", "content": mensaje_usuario})

        # Ahora armamos el input con el CONTEXTO + HISTORIAL
        user_prompt = (
            f"CONTEXTO:\n{CONTEXTO_COMPLETO}\n\n"
            "Tené en cuenta la conversación anterior para entender a qué se refiere el usuario:\n\n"
        )

        for rol, msg in historial:
            user_prompt += f"{rol.upper()}: {msg}\n"

        user_prompt += f"\nUSUARIO (nuevo): {mensaje_usuario}"

        respuesta = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )

        respuesta_llm = respuesta.choices[0].message.content.strip()

        # === GUARDAMOS EN HISTORIAL ===
        historial_conversacion[user_id].append(("user", mensaje_usuario))
        historial_conversacion[user_id].append(("bot", respuesta_llm))

        return jsonify({"respuesta": respuesta_llm})

    except Exception as e:
        print("💥 Error detectado:", e)
        return jsonify({"error": "Error interno en el servidor"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
