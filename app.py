from flask import Flask, request, jsonify
import openai
import os
from dotenv import load_dotenv
import json
from collections import defaultdict, deque
import requests

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

# === CONTEXTO FIJO ===
txt_path = "lovely_taller.txt"
if os.path.exists(txt_path):
    with open(txt_path, "r", encoding="utf-8") as f:
        CONTEXTO_COMPLETO = f.read()
else:
    CONTEXTO_COMPLETO = ""

# === Memoria ===
historial_conversacion = defaultdict(lambda: deque(maxlen=4))
estado_usuario = {}
producto_usuario = {}

TRIGGER_DERIVACION = [
    "hablar con alguien", "pasar con", "asesor", "humano",
    "persona", "quiero hablar", "me pasas con alguien"
]

@app.route("/webhook", methods=["POST"])
def responder():
    try:
        datos = request.get_json()
        print("🔎 JSON recibido desde Watson:")
        print(json.dumps(datos, indent=2))

        # ✅ Watson SIEMPRE manda estos campos
        mensaje_usuario = datos.get("consulta", "").lower().strip()
        user_id = datos.get("user_id", "anon")  # <- número real debe venir de Watson

        if not mensaje_usuario:
            return jsonify({"error": "No se recibió ninguna consulta"}), 400

        # Si ya fue derivado, sigue respondiendo pero no vuelve a ofrecer
        if estado_usuario.get(user_id) == "derivado":
            return responder_normal(mensaje_usuario, user_id)

        # Si usuario pide humano directo (palabras clave)
        if any(trigger in mensaje_usuario for trigger in TRIGGER_DERIVACION):
            return derivar_asesor(user_id)

        # Si estaba esperando confirmación para derivar
        if estado_usuario.get(user_id) == "esperando_confirmacion":
            if mensaje_usuario in ["sí", "si", "dale", "ok", "quiero", "confirmo"]:
                return derivar_asesor(user_id)
            else:
                # cancela la oferta de derivación
                estado_usuario.pop(user_id, None)
                return jsonify({"respuesta": "👌 Sin problema, cualquier cosa podés consultarme por acá cuando quieras."})

        # Detectar producto mencionado
        prod_detectado = detectar_producto_mencionado(mensaje_usuario)
        if prod_detectado:
            producto_usuario[user_id] = prod_detectado

        # Contar consultas previas en esta sesión
        consultas_previas = [msg for rol, msg in historial_conversacion[user_id] if rol == "user"]
        cantidad_consultas_ahora = len(consultas_previas) + 1

        # Guardar mensaje en historial
        historial_conversacion[user_id].append(("user", mensaje_usuario))

        # Responder normalmente
        respuesta_normal = responder_normal(mensaje_usuario, user_id)

        # Después de 3 consultas, ofrecer derivación
        if cantidad_consultas_ahora == 3 and estado_usuario.get(user_id) != "derivado":
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
    """Hace la llamada normal a GPT con contexto y retorna respuesta JSON"""
    system_prompt = (
        "Sos un asistente virtual de *Lovely Taller Deco* 🛋️. "
        "Respondé solo con la información del CONTEXTO, no inventes nada.\n\n"
        "➡️ **Formato WhatsApp:**\n"
        "- Usá *un solo asterisco* para resaltar palabras clave (productos, precios, direcciones).\n"
        "- Usá ✅ para listas y agregá SALTOS DE LÍNEA.\n"
        "- Máximo 2 emojis por respuesta.\n"
        "➡️ **Extensión:** Breve (máx 4-5 líneas).\n"
        "➡️ **Comportamiento:**\n"
        "- Saludá solo la primera vez.\n"
        "- No repitas showroom/ubicación salvo que lo pidan.\n"
        "- Si no está en el CONTEXTO invitá a visitar el showroom o llamar al 011 6028‑1211."
    )

    historial = list(historial_conversacion[user_id])
    mensajes_historial = [{"role": rol, "content": msg} for rol, msg in historial]
    mensajes_historial.append({"role": "user", "content": mensaje_usuario})

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
    historial_conversacion[user_id].append(("bot", respuesta_llm))

    return jsonify({"respuesta": respuesta_llm})

def derivar_asesor(user_id):
    """Envia derivación al endpoint externo"""
    estado_usuario[user_id] = "derivado"
    producto = producto_usuario.get(user_id, "No especificado")

    # ✅ Enviar número + producto consultado
    mensaje_dueño = f"Producto consultado: {producto}"

    return enviar_derivacion(user_id, mensaje_dueño)

def enviar_derivacion(numero_cliente, mensaje_dueño):
    """Llama al microservicio derivador"""
    try:
        resp = requests.post(
            "https://derivacion-humano.onrender.com/derivar-humano",
            json={
                "numero": numero_cliente,      # ← se manda el número real
                "consulta": mensaje_dueño      # ← solo el motivo
            }
        )
        if resp.status_code == 200:
            return jsonify({
                "respuesta": "✅ Ya avisé a un asesor para que te contacte. Mientras tanto sigo disponible 😉"
            })
        else:
            print("❌ Error derivando:", resp.text)
            return jsonify({
                "respuesta": "❌ Hubo un problema. Podés llamar al 011 6028‑1211 para coordinar."
            })
    except Exception as e:
        print("❌ Excepción derivando:", e)
        return jsonify({
            "respuesta": "❌ No pude avisar al asesor. Llamá al 011 6028‑1211."
        })

def detectar_producto_mencionado(texto):
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

@app.route("/")
def index():
    return "✅ Webhook activo."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
