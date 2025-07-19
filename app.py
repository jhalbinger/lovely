from flask import Flask, request, jsonify
import openai
import os
from dotenv import load_dotenv
import json
import fitz  # PyMuPDF
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
pdf_path = "lovely_taller.pdf"  # El PDF estará en el mismo repo
document_chunks = []      # Lista de textos divididos
document_embeddings = []  # Lista de embeddings correspondientes

# === FUNCIONES AUXILIARES ===

def extraer_texto_pdf(pdf_path):
    """Extrae texto plano del PDF"""
    texto = ""
    doc = fitz.open(pdf_path)
    for pagina in doc:
        texto += pagina.get_text()
    return texto

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
    """Carga y vectoriza el PDF al iniciar"""
    global document_chunks, document_embeddings

    print("📄 Extrayendo texto del PDF...")
    texto = extraer_texto_pdf(pdf_path)

    print("✂️ Dividiendo en chunks...")
    document_chunks = dividir_en_chunks(texto, max_tokens=500)

    print(f"🔢 Total de chunks: {len(document_chunks)}")

    print("🧠 Generando embeddings del documento...")
    for chunk in document_chunks:
        emb = obtener_embedding(chunk)
        document_embeddings.append(emb)

    print("✅ Documento cargado y vectorizado.")

def buscar_contexto_relevante(pregunta, top_k=3):
    """Busca los chunks más relevantes para la pregunta"""
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
                        "Sos un asistente virtual argentino, hablás en tono rioplatense, cercano y natural. "
                        "Respondé únicamente en base al CONTEXTO que te paso. "
                        "Si la información no está en el contexto, decí: "
                        "'Mirá, con lo que tengo acá no te puedo confirmar eso, pero podés llamar al 011 6028‑1211 para más info.' "
                        "No inventes nada. Sé amable, breve (máximo 2 líneas) y claro para responder por WhatsApp."
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
    preparar_documento()  # Cargar y vectorizar PDF al inicio
    app.run(host="0.0.0.0", port=5000)
