from flask import Flask, request, jsonify
import openai
import os
from dotenv import load_dotenv
import json
from collections import defaultdict, deque
import requests

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

# Memoria por usuario: últimas 4 interacciones para GPT
historial_conversacion = defaultdict(lambda: deque(maxlen=4))

# Estado de cada usuario: "esperando_confirmacion" o "derivado"
estado_usuario = {}
# Último producto consultado por usuario
producto_usuario = {}

# Palabras clave que fuerzan derivación inmediata
TRIGGER_DERIVACION = [
    "hablar con alguien", "pasar con", "asesor", "humano",
    "persona", "me pasas con alguien", "quiero hablar con alguien"
]

@app.route("/webhook", methods=["POST"])
def responder():
    try:
        datos = request.get_json()
        print("🔎 JSON recibido desde WhatsApp/Twilio:")
        print(json.dumps(datos, indent=2))

        mensaje_usuario = datos.get("consulta", "").lower().strip()
        user_id = datos.get("user_id", "anon").strip()

        if not mensaje_usuario:
            return jsonify({"error": "No se recibió ninguna consulta"}), 400

        # === Si ya fue derivado en esta sesión, no derivar de nuevo ===
        if estado_usuario.get(user_id) == "derivado":
            return responder_normal(mensaje_usuario, user_id)

        # === Si usuario pide explícitamente hablar con alguien, forzamos derivación ===
        if any(trigger in mensaje_usuario for trigger in TRIGGER_DERIVACION):
            return forzar_derivacion(user_id)

        # === Si está esperando confirmación de derivación ===
        if estado_usuario.get(user_id) == "esperando_confirmacion":
            if mensaje_usuario in ["sí", "si", "dale", "ok", "quiero", "confirmo"]:
                return derivar_asesor(user_id)
            else:
                # Si dice "no" o algo distinto, cancela derivación
                estado_usuario.pop(user_id, None)
                return jsonify({"respuesta": "👌 Sin problema, cualquier cosa podés consultarme por acá cuando quieras."})

        # === Intentamos detectar si menciona un producto en esta consulta ===
        prod_detectado = detectar_producto_mencionado(mensaje_usuario)
        if prod_detectado:
            producto_usuario[user_id] = prod_detectado

        # === Agregamos esta consulta al historial ANTES de decidir ===
        historial_conversacion[user_id].append(("user", mensaje_usuario))

        # Contamos cuántas consultas ha hecho el usuario hasta ahora
        consultas_usuario = [msg for rol, msg in historial_conversacion[user_id] if rol == "user"]
        cantidad_consultas = len(consultas_usuario)

        # Flujo normal con GPT
        respuesta_normal = responder_normal(mensaje_usuario, user_id)

        # Si ya hizo 3 consultas, le ofrecemos derivación (solo una vez)
        if cantidad_consultas >= 3 and estado_usuario.get(user_id) != "derivado":
            estado_usuario[user_id] = "esperando_confirmacion"
            extra = "\n\n✅ *Si querés, puedo pedir que un asesor te contacte para coordinar la compra. ¿Querés que te llame?*"
            respuesta_data = json.loads(respuesta_normal.get_data())
            respuesta_data["respuesta"] += extra
            return jsonify(respuesta_data)

        return respuesta_normal

    except Exception as e:
        print("💥 Error detectado:", e)
        return jsonify({"respuesta": "Estoy tardando en procesar tu consulta, intentá de nuevo en unos segundos 🙏"}), 200


def responder_normal(mensaje_usuario, user_id):
    """Flujo original de GPT para respuestas normales"""
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

    historial = list(historial_conversacion[user_id])
    mensajes_historial = [{"role": rol, "content": msg} for rol, msg in historial]
    mensajes_historial.append({"role": "user", "content": mensaje_usuario})

    # CONTEXTO + HISTORIAL
    user_prompt = f"CONTEXTO:\n{CONTEXTO_COMPLETO}\n\nConversación previa:\n\n"
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

    # Guardamos historial con la respuesta
    historial_conversacion[user_id].append(("bot", respuesta_llm))

    return jsonify({"respuesta": respuesta_llm})


def forzar_derivacion(user_id):
    """Cuando el cliente pide explícitamente hablar con alguien"""
    producto = producto_usuario.get(user_id, "No especificado")
    mensaje_para_dueño = (
        f"📩 Usuario {user_id} pidió hablar con un asesor.\n"
        f"🛋️ Producto consultado: {producto}"
    )
    try:
        resp = requests.post(
            "https://derivacion-humano.onrender.com/derivar-humano",
            json={"numero": user_id, "consulta": mensaje_para_dueño}
        )
        if resp.status_code == 200:
            estado_usuario[user_id] = "derivado"
            return jsonify({"respuesta": "✅ Te paso con un asesor, ya le avisé. Mientras tanto, seguí escribiéndome si necesitás más info 😉"})
        else:
            print("❌ Error Twilio:", resp.text)
            return jsonify({"respuesta": "❌ Intenté derivarte, pero hubo un problema. Podés llamar al 011 6028‑1211 para coordinar directo."})
    except Exception as e:
        print("❌ Error al derivar:", e)
        return jsonify({"respuesta": "❌ No pude avisar al asesor en este momento. Podés llamar al 011 6028‑1211 para coordinar directo."})


def derivar_asesor(user_id):
    """Cuando acepta ser derivado tras la oferta"""
    estado_usuario[user_id] = "derivado"
    producto = producto_usuario.get(user_id, "No especificado")
    mensaje_para_dueño = (
        f"📩 Usuario {user_id} pidió hablar con un asesor.\n"
        f"🛋️ Producto consultado: {producto}"
    )
    try:
        resp = requests.post(
            "https://derivacion-humano.onrender.com/derivar-humano",
            json={"numero": user_id, "consulta": mensaje_para_dueño}
        )
        if resp.status_code == 200:
            return jsonify({"respuesta": "✅ Listo, ya avisé a un asesor para que te contacte. Mientras tanto, cualquier consulta seguí escribiéndome por acá que sigo a disposición 😉"})
        else:
            print("❌ Error Twilio:", resp.text)
            return jsonify({"respuesta": "❌ Intenté derivarte, pero hubo un problema. Podés llamar al 011 6028‑1211 para coordinar directo."})
    except Exception as e:
        print("❌ Error al derivar:", e)
        return jsonify({"respuesta": "❌ No pude avisar al asesor en este momento. Podés llamar al 011 6028‑1211 para coordinar directo."})


def detectar_producto_mencionado(texto):
    """Busca si el mensaje menciona un producto específico del contexto"""
    productos = [
        "sillón nube", "sillón roma", "sillón bella", "sillón lady",
        "puff", "esquinero", "mecedora", "respaldo", "silla pétalo",
        "queen", "estrella", "victoria", "brooklyn", "astor", "diva"
    ]
    texto_lower = texto.lower()
    for p in productos:
        if p in texto_lower:
            return p.title()
    return None


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
