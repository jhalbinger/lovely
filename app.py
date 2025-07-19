from flask import Flask, request, jsonify
import openai
import os
from dotenv import load_dotenv
import json
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

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

# === VARIABLES PARA EMBEDDINGS ===
txt_path = "lovely_taller.txt"
document_chunks = []
document_embeddings = []

# === FUNCIONES AUXILIARES ===

def extraer_texto_txt(txt_path):
    """Lee texto directo de un archivo .txt"""
    if not os.path.exists(txt_path):
        print(f"❌ ERROR: No se encontró el archivo {txt_path}")
        return ""
    with open(txt_path, "r", encoding="utf-8") as f:
        return f.read()

def dividir_en_chunks(texto, max_tokens=500):
    """Divide el texto en bloques manejables"""
    palabras = texto.split()
    chunks = []
    actual = []
    tokens = 0

    for palabra in palabras:
        actual.append(palabra)
        tokens += 1
        if tokens >= max_tokens:
            chunks.append(" ".join(actual))
            actual = []
            tokens = 0
    if actual:
        chunks.append(" ".join(actual))
    return chunks

def obtener_embedding(texto):
    """Genera el embedding de un texto"""
    response = client.embeddings.create(
        model="text-embedding-ada-002",
        input=texto
    )
    return np.array(response.data[0].embedding)

def preparar_documento():
    """Carga y vectoriza el TXT al iniciar"""
    global document_chunks, document_embeddings

    print("📄 Leyendo texto del archivo...")
    texto = extraer_texto_txt(txt_path)

    if not texto.strip():
        print("❌ ERROR: El archivo está vacío o no se pudo leer.")
        return

    print("✂️ Dividiendo en chunks...")
    document_chunks = dividir_en_chunks(texto, max_tokens=500)

    print(f"🔢 Total de chunks generados: {len(document_chunks)}")
    if len(document_chunks) == 0:
        print("❌ ERROR: No se pudieron generar chunks del documento.")
        return

    print("🧠 Generando embeddings del documento...")
    for chunk in document_chunks:
        emb = obtener_embedding(chunk)
        document_embeddings.append(emb)

    print(f"✅ Documento cargado y vectorizado. Total embeddings: {len(document_embeddings)}")

def buscar_contexto_relevante(pregunta, top_k=3):
    """Busca los chunks más relevantes para la pregunta"""
    if len(document_embeddings) == 0:
        print("⚠️ No hay embeddings cargados, devolviendo contexto vacío.")
        return ""

    pregunta_emb = obtener_embedding(pregunta)
    similitudes = cosine_similarity([pregunta_emb], document_embeddings)[0]

    # Top k más similares
    idx_ordenados = np.argsort(similitudes)[::-1][:top_k]
    fragmentos = [document_chunks[i] for i in idx_ordenados]

    return "\n\n".join(fragmentos)

# === FLASK WEBHOOK ===

@app.route("/webhook", methods=["POST"])
def responder():
    try:
        datos = request.get_json()
        print("🔎 JSON recibido desde WhatsApp/Twilio:")
        print(json.dumps(datos, indent=2))

        mensaje_usuario = datos.get("consulta", "")
        if not mensaje_usuario:
            return jsonify({"error": "No se recibió ninguna consulta"}), 400

        # 1. Buscar contexto relevante
        contexto = buscar_contexto_relevante(mensaje_usuario)

        # 2. Pasar contexto + pregunta al modelo
        respuesta = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Sos un asistente virtual argentino para Lovely Taller Deco. "
                        "Tenés un CONTEXTO con información exacta del negocio. "
                        "Solo podés responder usando la información del CONTEXTO, pero sé proactivo y amable. "
                        "Si la pregunta está relacionada, aunque sea de forma general, y el CONTEXTO tiene algo útil, respondé de forma clara y servicial. "
                        "Si el usuario pregunta algo como '¿Venden sillones?' y en el CONTEXTO hay detalles de sillones, confirmá que sí y mencioná algunos modelos. "
                        "⚠️ Si el CONTEXTO no tiene nada relacionado, NO inventes información. "
                        "En ese caso respondé siempre: "
                        "'Mirá, con lo que tengo acá no te puedo confirmar eso, pero podés llamar al 011 6028‑1211 para más info. ¡Estoy para ayudarte en lo que necesites!' "
                        "Nunca agregues datos que no estén en el CONTEXTO. "
                        "Respondé siempre en no más de 2 líneas, en tono cálido, predispuesto y claro para WhatsApp."
                    )
                },
                {
                    "role": "user",
                    "content": f"CONTEXTO:\n{contexto}\n\nPREGUNTA: {mensaje_usuario}"
                }
            ]
        )

        respuesta_llm = respuesta.choices[0].message.content.strip()
        return jsonify({"respuesta": respuesta_llm})

    except Exception as e:
        print("💥 Error detectado:", e)
        return jsonify({"error": "Error interno en el servidor"}), 500

if __name__ == "__main__":
    preparar_documento()  # Cargar y vectorizar TXT al inicio
    app.run(host="0.0.0.0", port=5000)
