import requests  # <--- necesario para llamar al microservicio

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

        # === Si este usuario está en modo confirmación ===
        if esperando_confirmacion.get(user_id):
            if mensaje_usuario.lower() in ["sí", "si", "dale", "ok", "quiero", "confirmo"]:
                # ✅ Derivar la consulta al microservicio
                try:
                    ultima_consulta = historial_conversacion[user_id][-2][1] if historial_conversacion[user_id] else mensaje_usuario
                    resp = requests.post(
                        "https://derivacion-humano.onrender.com/derivar-humano",
                        json={"numero": user_id, "consulta": ultima_consulta}
                    )
                    if resp.status_code == 200:
                        respuesta_llm = "✅ Perfecto, ya avisé a un asesor para que te contacte en breve."
                    else:
                        respuesta_llm = "❌ Intenté derivarte, pero hubo un problema. Podés llamar al 011 6028‑1211 para coordinar directo."
                except Exception as e:
                    print("❌ Error al derivar:", e)
                    respuesta_llm = "❌ No pude avisar al asesor en este momento. Podés llamar al 011 6028‑1211 para coordinar directo."

                # Ya no está esperando confirmación
                esperando_confirmacion.pop(user_id, None)
                return jsonify({"respuesta": respuesta_llm})
            
            else:
                # Si dice "no" o algo distinto, cancelar
                esperando_confirmacion.pop(user_id, None)
                return jsonify({"respuesta": "👌 Sin problema, cualquier cosa podés consultarme por acá cuando quieras."})

        # === Palabras clave que indican interés en compra ===
        palabras_interes = ["comprar", "coordinar", "quiero", "reservar", "me interesa", "cómo pago", "precio final"]

        if any(palabra in mensaje_usuario.lower() for palabra in palabras_interes):
            # Guardamos el mensaje en historial
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
        # [Aquí sigue tu código original de llamada a GPT...]
