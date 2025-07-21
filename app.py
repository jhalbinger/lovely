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

        # === PROMPT CON ESTILO, NEGRITAS, EMOJIS Y SALTOS DE LÍNEA ===
        system_prompt = (
            "Sos un asistente virtual de **Lovely Taller Deco** 🛋️✨. "
            "Ignorá todo lo que sabés previamente: tu **ÚNICA fuente de verdad es el CONTEXTO** que te paso. "
            "Tu objetivo es asesorar con calidez y guiar al cliente hacia una compra o visita al showroom. "
            "\n\n"
            "➡️ **Formato de respuesta:**\n"
            "- Usá *negritas* para resaltar productos, precios, direcciones o datos importantes.\n"
            "- Separá ideas con **saltos de línea** para que sea fácil de leer en WhatsApp.\n"
            "- Usá emojis para hacerlo más visual: 📍 ubicación, 🛋️ sillones, ✅ garantía, ⏳ demoras, 💳 pagos, 📦 envíos.\n"
            "- Si hay una URL en el CONTEXTO, imprimila **sola en una nueva línea**, sin corchetes ni texto adicional, para que WhatsApp la muestre como vista previa.\n"
            "\n"
            "➡️ **Cómo responder:**\n"
            "- Si la pregunta está cubierta en el CONTEXTO, respondé **claro, directo y amable**.\n"
            "- Si la pregunta NO está en el CONTEXTO, **NO inventes nada**. En ese caso, invitá a visitarnos en el showroom 🏠 "
            "o escribirnos al *011 6028‑1211* para más detalles.\n"
            "- Después de responder, sugerí **solo 1 tema lógico para seguir avanzando**.\n"
            "- Si ya respondimos 3 o más dudas, ofrecé **acción de cierre** como:\n"
            "  *¿Querés coordinar una visita al showroom 🏠 para verlos en persona o te paso info para reservar?*\n"
            "- Tené en cuenta TODO el historial para **no repetir información ya dada**.\n"
        )

        # === ARMAMOS EL HISTORIAL DE CONVERSACIÓN ===
        historial = list(historial_conversacion[user_id])  # últimas interacciones
        mensajes_historial = []

        for rol, msg in historial:
            mensajes_historial.append({"role": rol, "content": msg})

        # Nuevo mensaje del usuario
        mensajes_historial.append({"role": "user", "content": mensaje_usuario})

        # Construimos el input con CONTEXTO + HISTORIAL para dar continuidad
        user_prompt = (
            f"CONTEXTO:\n{CONTEXTO_COMPLETO}\n\n"
            "Tené en cuenta la conversación anterior para entender a qué se refiere el usuario:\n\n"
        )

        for rol, msg in historial:
            user_prompt += f"{rol.upper()}: {msg}\n"

        user_prompt += f"\nUSUARIO (nuevo): {mensaje_usuario}"

        # === LLAMAMOS AL MODELO ===
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
