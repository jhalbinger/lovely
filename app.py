from flask import Flask, request, jsonify
import openai
import os
from dotenv import load_dotenv
import json
from collections import defaultdict, deque
import requests  # Necesario para llamar al microservicio de derivación

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

# Memoria por usuario: últimas 4 interacciones
historial_conversacion = defaultdict(lambda: deque(maxlen=4))

# Diccionario para marcar usuarios que esperan confirmación de contacto humano
esperando_confirmacion = {}

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

        # === Si este usuario está en modo confirmación de derivación ===
        if esperando_confirmacion.get(user_id):
            if mensaje_usuario.lower() in ["sí", "si", "dale", "ok", "quiero", "confirmo"]:
                # ✅ Derivar la consulta al microservicio
                try:
                    # Tomamos la última consulta relevante del historial (antes de la confirmación)
                    ultima_consulta = historial_conversacion[user_id][-2][1] if len(historial_conversacion[user_id]) >= 2 else mensaje_usuario

                    resp = requests.post(
                        "https://derivacion-humano.onrender.com/derivar-humano",
                        json={"numero": user_id, "consulta": ultima_consulta}
                    )

                    if resp.status_code == 200:
                        respuesta_llm = "✅ Perfecto, ya avisé a un asesor para que te contacte en breve."
                    else:
                        print("❌ Error Twilio:", resp.text)
                        respuesta_llm = "❌ Intenté derivarte, pero hubo un problema. Podés llamar al 011 6028‑1211 para coordinar directo."
                except Exception as e:
                    print("❌ Error al derivar:", e)
                    respuesta_llm = "❌ No pude avisar al asesor en este momento. Podés llamar al 011 6028‑1211 para coordinar directo."

                # Ya no está esperando confirmación
                esperando_confirmacion.pop(user_id, None)
                return jsonify({"respuesta": respuesta_llm})
            else:
                # Si dice "no" o algo distinto, cancelar derivación
                esperando_confirmacion.pop(user_id, None)
                return jsonify({"respuesta": "👌 Sin problema, cualquier cosa podés consultarme por acá cuando quieras."})

        # === Detectar intención de compra en el mensaje ===
        palabras_interes = ["comprar", "coordinar", "quiero", "reservar", "me interesa", "cómo pago", "precio final"]
        if any(palabra in mensaje_usuario.lower() for palabra in palabras_interes):
            # Guardamos la intención en historial
            historial_conversacion[user_id].append(("user", mensaje_usuario))

            # Respondemos normal pero agregamos la oferta de contacto humano
            respuesta_llm = (
                "Podés comprar este producto con *hasta 12 cuotas sin interés* y demora de entrega de 35-45 días hábiles.\n\n"
                "✅ *¿Querés que un asesor te contacte para coordinar la compra?* Respondé *Sí* para derivarte."
            )

            # Marcamos que este usuario está esperando confirmación
            esperando_confirmacion[user_id] = True

            return jsonify({"respuesta": respuesta_llm})

        # === Si no es intención de compra, flujo normal con OpenAI ===
        # === PROMPT ESPECIAL PARA WHATSAPP ===
        system_prompt = (
            "Sos un asistente virtual de *Lovely Taller Deco* 🛋️. "
            "Respondé solo con la información del CONTEXTO, no inventes nada. "
            "\n\n"
            "➡️ **Formato WhatsApp:**\n"
            "- Usá *un solo asterisco* para resaltar palabras clave (productos, precios, direcciones).\n"
            "- Usá ✅ para listas y agregá SALTOS DE LÍNEA entre frases para que el mensaje no quede en un solo bloque.\n"
            "- Cada 1 o 2 frases, cortá y poné un salto de línea.\n"
            "- Si hay un link, ponelo solo en una línea para que WhatsApp muestre la vista previa.\n"
            "- Máximo 2 emojis por respuesta.\n"
            "\n"
            "➡️ **Extensión del mensaje:**\n"
            "- Respuesta breve pero completa, ideal para leer en celular (máximo 4-5 líneas de texto).\n"
            "- Si es una lista, máximo 4-5 ítems por respuesta.\n"
            "- Después de responder, sugerí UN solo tema lógico para seguir.\n"
            "\n"
            "➡️ **Comportamiento:**\n"
            "- En la PRIMERA respuesta saludá: '¡Hola! 👋 *Bienvenido a Lovely Taller Deco* 🛋️✨' y explicá brevemente qué puede consultar.\n"
            "- En mensajes posteriores NO vuelvas a saludar, respondé directo.\n"
            "- Si ya diste showroom o ubicación en la misma conversación, no los repitas salvo que lo pidan.\n"
            "- Si la consulta no está en el CONTEXTO, no inventes; invitá a visitar el showroom 🏠 o llamar al 011 6028‑1211.\n"
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
