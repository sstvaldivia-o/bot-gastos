import os
import gspread
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from google.oauth2.service_account import Credentials
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── Configuración ────────────────────────────────
SPREADSHEET_NAME = "Wawas"

USUARIOS = {
    os.getenv("NUMERO_SEBA"): {"nombre": "Seba", "hoja": "Personal Seba"},
    os.getenv("NUMERO_RITA"): {"nombre": "Rita", "hoja": "Personal Rita"},
}

CATEGORIAS = {
    "supermercado": "Alimentación",
    "almuerzo":     "Alimentación",
    "restaurant":   "Alimentación",
    "uber":         "Transporte",
    "bencina":      "Transporte",
    "metro":        "Transporte",
    "netflix":      "Entretenimiento",
    "spotify":      "Entretenimiento",
    "cine":         "Entretenimiento",
    "farmacia":     "Salud",
    "médico":       "Salud",
    "arriendo":     "Vivienda",
    "luz":          "Vivienda",
    "agua":         "Vivienda",
}

HEADERS = ["Fecha", "Quién", "Descripción", "Monto", "Categoría", "Tipo"]

# ── Google Sheets ────────────────────────────────
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def conectar_sheets():
    creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    return gspread.authorize(creds)

cliente      = conectar_sheets()
spreadsheet  = cliente.open(SPREADSHEET_NAME)

# ── Lógica del bot ───────────────────────────────
def detectar_categoria(descripcion):
    desc_lower = descripcion.lower()
    for keyword, categoria in CATEGORIAS.items():
        if keyword in desc_lower:
            return categoria
    return "Otros"


def parsear_mensaje(mensaje):
    mensaje = mensaje.strip()
    es_conjunto = mensaje.startswith("*")
    if es_conjunto:
        mensaje = mensaje[1:].strip()

    if mensaje.lower() in ["/resumen", "resumen"]:
        return {"comando": "resumen"}

    partes = mensaje.split()
    monto, idx_monto = None, None

    for i, p in enumerate(partes):
        limpio = p.replace(".", "").replace(",", "")
        if limpio.isdigit():
            monto = int(limpio)
            idx_monto = i
            break

    if monto is None:
        return None

    descripcion      = " ".join(partes[:idx_monto]).capitalize()
    categoria_manual = " ".join(partes[idx_monto + 1:]).capitalize() if idx_monto + 1 < len(partes) else None
    categoria        = categoria_manual or detectar_categoria(descripcion)

    return {
        "descripcion": descripcion,
        "monto":       monto,
        "categoria":   categoria,
        "es_conjunto": es_conjunto,
    }


def obtener_resumen(usuario_nombre):
    mes_actual     = datetime.now().strftime("%Y-%m")
    total_personal = 0
    total_conjunto = 0

    hoja_nombre = next(
        (u["hoja"] for u in USUARIOS.values() if u and u.get("nombre") == usuario_nombre), None
    )
    if hoja_nombre:
        filas = spreadsheet.worksheet(hoja_nombre).get_all_records()
        for fila in filas:
            if str(fila.get("Fecha", "")).startswith(mes_actual):
                total_personal += int(fila.get("Monto", 0))

    filas_wawas = spreadsheet.worksheet("Wawas").get_all_records()
    for fila in filas_wawas:
        if str(fila.get("Fecha", "")).startswith(mes_actual) and fila.get("Quién") == usuario_nombre:
            total_conjunto += int(fila.get("Monto", 0))

    return (
        f"📊 Resumen {mes_actual}\n"
        f"👤 Personal: ${total_personal:,}\n"
        f"👫 Conjunto (tus registros): ${total_conjunto:,}\n"
        f"💰 Total: ${total_personal + total_conjunto:,}"
    )


def registrar_gasto(numero_telefono, mensaje):
    numero_limpio = numero_telefono.replace("whatsapp:", "")

    if numero_limpio not in USUARIOS or USUARIOS[numero_limpio] is None:
        return "❌ Tu número no está registrado."

    usuario = USUARIOS[numero_limpio]
    datos   = parsear_mensaje(mensaje)

    if datos is None:
        return (
            "❌ No entendí el mensaje. Usa:\n"
            "  Descripción Monto        → personal\n"
            "  *Descripción Monto       → conjunto (Wawas)\n"
            "  /resumen                 → ver gastos del mes\n\n"
            "Ejemplo: Almuerzo 4500\n"
            "Ejemplo conjunto: *Supermercado 35000"
        )

    if datos.get("comando") == "resumen":
        return obtener_resumen(usuario["nombre"])

    hoja_nombre = "Wawas" if datos["es_conjunto"] else usuario["hoja"]
    hoja        = spreadsheet.worksheet(hoja_nombre)

    fila = [
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        usuario["nombre"],
        datos["descripcion"],
        datos["monto"],
        datos["categoria"],
        "Conjunto" if datos["es_conjunto"] else "Personal",
    ]
    hoja.append_row(fila)

    tipo = "conjunto 👫" if datos["es_conjunto"] else "personal 👤"
    return (
        f"✅ Gasto registrado ({tipo})\n"
        f"📝 {datos['descripcion']}\n"
        f"💰 ${datos['monto']:,}\n"
        f"🏷️  {datos['categoria']}"
    )


# ── Flask ────────────────────────────────────────
app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    numero  = request.form.get("From", "")
    mensaje = request.form.get("Body", "").strip()

    print(f"📱 Mensaje de {numero}: {mensaje}")

    respuesta_texto = registrar_gasto(numero, mensaje)

    resp = MessagingResponse()
    resp.message(respuesta_texto)
    return str(resp)

@app.route("/", methods=["GET"])
def index():
    return "🤖 Bot de gastos activo", 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
