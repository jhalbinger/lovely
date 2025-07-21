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
historial_conversacion = defaultdict(lambda: deque(maxlen=4))  # últimos 4 mensajes

@app.route("/webhook", methods=["POST"])
def responder():
    try:
        datos = request.get_json()
        print("🔎 JSON recibido desde WhatsApp/Twilio:")
        print(json.dumps(datos, indent=2))

        mensaje_usuario = datos.get("consulta", "")
        user_id = datos.get("user_id", "anon")
        if not mensaje_usuario:
            return jsonify({"error": "No se recibió ninguna consulta"}), 400

        # === PROMPT MEJORADO PARA FORMATO WHATSAPP ===
        system_prompt = (
            "Sos un asistente virtual de Lovely Taller Deco 🛋️. "
            "Respondé SOLO con el CONTEXTO que te paso, nunca inventes datos. "
            "\n\n"
            "➡️ **Formato para WhatsApp:**\n"
            "- Usá DOBLE ASTERISCO para resaltar palabras clave (**texto**).\n"
            "- Usá ✅ y otros emojis para listar elementos importantes.\n"
            "- Agregá saltos de línea entre secciones para que no quede bloque.\n"
            "- Si hay un link en el CONTEXTO, ponelo SOLO en una línea aparte para que WhatsApp lo muestre como preview.\n"
            "- Máximo 2 emojis por respuesta.\n"
            "\n"
            "➡️ **Comportamiento inteligente:**\n"
            "- Saludá SOLO en el primer mensaje de la conversación.\n"
            "- Si ya hubo varias respuestas, no repitas showroom ni ubicación salvo que lo pidan.\n"
            "- Si la consulta no está en el CONTEXTO, invitá a visitar el showroom 🏠 o llamar al 011 6028‑1211.\n"
            "- Después de responder, sugerí UN solo tema lógico para continuar.\n"
            "- Si ya respondimos 3+ dudas, ofrecé cierre como: "
            "'¿Querés coordinar una visita al showroom 🏠 o te paso info para reservar?'\n"
        )

        # === ARMAMOS HISTORIAL ===
        historial = list(historial_conversacion[user_id])
        mensajes_historial = []
        for rol, msg in historial:
            mensajes_historial.append({"role": rol, "content": msg})
        mensajes_historial.append({"role": "user", "content": mensaje_usuario})

        # === CONTEXTO + HISTORIAL ===
        user_prompt = (
            f"CONTEXTO:\n{CONTEXTO_COMPLETO}\n\n"
            "Conversación previa:\n\n"
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
        return jsonify({"respuesta": "Estoy tardando en procesar tu consulta, podés intentar de nuevo en unos segundos 🙏"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
