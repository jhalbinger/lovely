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
historial_conversacion = defaultdict(lambda: deque(maxlen=4))  # guarda últimas 4 entradas

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

        # === PROMPT ESPECIAL PARA WHATSAPP ===
        system_prompt = (
            "Sos un asistente virtual de *Lovely Taller Deco* 🛋️. "
            "Tu única fuente de verdad es el CONTEXTO que te paso. "
            "\n\n"
            "➡️ **Formato para WhatsApp:**\n"
            "- Usá *un solo asterisco* para resaltar palabras clave como precios, productos o direcciones.\n"
            "- Usá ✅ para listas y poné saltos de línea para que sea fácil de leer en celular.\n"
            "- Si hay una URL en el CONTEXTO, imprimila sola en una línea para que WhatsApp muestre la vista previa.\n"
            "- Máximo 2 emojis por respuesta para no recargar.\n"
            "\n"
            "➡️ **Comportamiento:**\n"
            "- En la PRIMERA respuesta de la conversación, saludá y da la bienvenida: '¡Hola! 👋 *Bienvenido a Lovely Taller Deco* 🛋️✨' seguido de una breve frase explicando qué puede consultar.\n"
            "- En mensajes posteriores NO vuelvas a saludar, respondé directo.\n"
            "- No repitas showroom ni ubicación si ya se dieron en la misma conversación, salvo que lo pidan.\n"
            "- Si la pregunta no está en el CONTEXTO, no inventes, invitá a visitar el showroom 🏠 o llamar al 011 6028‑1211.\n"
            "- Después de responder, sugerí SOLO 1 tema lógico para continuar. Si ya respondimos 3+ dudas, ofrecé cierre como: "
            "'¿Querés coordinar una visita al showroom 🏠 o te paso info para reservar?'\n"
        )

        # === ARMAMOS HISTORIAL DE CONVERSACIÓN ===
        historial = list(historial_conversacion[user_id])
        mensajes_historial = []
        for rol, msg in historial:
            mensajes_historial.append({"role": rol, "content": msg})

        mensajes_historial.append({"role": "user", "content": mensaje_usuario})

        # === CONSTRUIMOS EL INPUT COMPLETO ===
        user_prompt = (
            f"CONTEXTO:\n{CONTEXTO_COMPLETO}\n\n"
            "Conversación previa:\n\n"
        )
        for rol, msg in historial:
            user_prompt += f"{rol.upper()}: {msg}\n"
        user_prompt += f"\nUSUARIO (nuevo): {mensaje_usuario}"

        # === LLAMADA AL MODELO ===
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
        return jsonify({"respuesta": "Estoy tardando en procesar tu consulta, intentá de nuevo en unos segundos 🙏"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
