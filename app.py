import os
import json
import gspread
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from google.oauth2.service_account import Credentials
from datetime import datetime
from dotenv import load_dotenv
from collections import defaultdict

load_dotenv()

# ── Configuración ────────────────────────────────
SPREADSHEET_NAME = "Control de Gastos"  # nombre exacto de tu Google Sheet

USUARIOS = {
    "+56930604535": {"nombre": "Seba", "hoja": "Personal Seba"},
    "+56975798059": {"nombre": "Rita", "hoja": "Personal Rita"},
}

CATEGORIAS = {
    "supermercado": "Alimentación",
    "almuerzo":     "Alimentación",
    "restaurant":   "Alimentación",
    "uber eats":    "Alimentación",
    "rappi":        "Alimentación",
    "comida":       "Alimentación",
    "cita":         "Entretenimiento",
    "uber":         "Transporte",
    "bencina":      "Transporte",
    "metro":        "Transporte",
    "bus":          "Transporte",
    "Ropa":          "Vestuario",
    "juegos":       "Entretenimiento",
    "netflix":      "Entretenimiento",
    "spotify":      "Entretenimiento",
    "cine":         "Entretenimiento",
    "farmacia":     "Salud",
    "médico":       "Salud",
    "muebles":      "Vivienda",
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
    creds_json = os.getenv("GOOGLE_CREDENTIALS")
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)

cliente     = conectar_sheets()
spreadsheet = cliente.open(SPREADSHEET_NAME)


# ── Resumen mensual ──────────────────────────────
def actualizar_resumen():
    resumen = defaultdict(lambda: defaultdict(lambda: {"Seba": 0, "Rita": 0, "Conjuntos": 0}))

    for usuario in USUARIOS.values():
        if not usuario:
            continue
        nombre      = usuario["nombre"]
        hoja_nombre = usuario["hoja"]
        try:
            filas = spreadsheet.worksheet(hoja_nombre).get_all_records()
            for fila in filas:
                fecha     = str(fila.get("Fecha", ""))
                mes       = fecha[:7]
                categoria = fila.get("Categoría", "Otros") or "Otros"
                monto     = int(fila.get("Monto", 0))
                if mes:
                    resumen[mes][categoria][nombre] += monto
        except Exception:
            pass

    try:
        filas_wawas = spreadsheet.worksheet("Wawas").get_all_records()
        for fila in filas_wawas:
            fecha     = str(fila.get("Fecha", ""))
            mes       = fecha[:7]
            categoria = fila.get("Categoría", "Otros") or "Otros"
            monto     = int(fila.get("Monto", 0))
            if mes:
                resumen[mes][categoria]["Conjuntos"] += monto
    except Exception:
        pass

    hoja_resumen = spreadsheet.worksheet("Resumen_Mensual")
    hoja_resumen.clear()
    hoja_resumen.append_row(["Mes", "Categoría", "Seba", "Rita", "Conjuntos", "Total"])

    filas_resumen = []
    for mes in sorted(resumen.keys(), reverse=True):
        for categoria in sorted(resumen[mes].keys()):
            seba      = resumen[mes][categoria]["Seba"]
            rita      = resumen[mes][categoria]["Rita"]
            conjuntos = resumen[mes][categoria]["Conjuntos"]
            total     = seba + rita + conjuntos
            filas_resumen.append([mes, categoria, seba, rita, conjuntos, total])

    if filas_resumen:
        hoja_resumen.append_rows(filas_resumen)


# ── Lógica del bot ───────────────────────────────
def detectar_categoria(descripcion):
    desc_lower = descripcion.lower()
    for keyword, categoria in CATEGORIAS.items():
        if keyword in desc_lower:
            return categoria
    return "Otros"


def limpiar_monto(texto):
    """Acepta montos con punto o coma: 38.000 → 38000"""
    return texto.replace(".", "").replace(",", "")


def parsear_mensaje(mensaje):
    mensaje = mensaje.strip()
    es_conjunto = mensaje.startswith("*")
    if es_conjunto:
        mensaje = mensaje[1:].strip()

    msg_lower = mensaje.lower()

    # Comandos
    if msg_lower in ["/resumen", "resumen"]:
        return {"comando": "resumen"}
    if msg_lower in ["/resumen categorias", "resumen categorias"]:
        return {"comando": "resumen_categorias"}
    if msg_lower in ["/ultimo", "ultimo", "último"]:
        return {"comando": "ultimo"}
    if msg_lower in ["/borrar", "borrar"]:
        return {"comando": "borrar"}
    if msg_lower in ["/ayuda", "ayuda"]:
        return {"comando": "ayuda"}

    partes = mensaje.split()
    monto, idx_monto = None, None

    for i, p in enumerate(partes):
        limpio = limpiar_monto(p)
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


def obtener_hoja_usuario(usuario_nombre):
    return next(
        (u["hoja"] for u in USUARIOS.values() if u and u.get("nombre") == usuario_nombre), None
    )


def cmd_resumen(usuario_nombre):
    mes_actual     = datetime.now().strftime("%Y-%m")
    total_personal = 0
    total_conjunto = 0

    hoja_nombre = obtener_hoja_usuario(usuario_nombre)
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


def cmd_resumen_categorias(usuario_nombre):
    mes_actual  = datetime.now().strftime("%Y-%m")
    categorias  = defaultdict(int)

    hoja_nombre = obtener_hoja_usuario(usuario_nombre)
    if hoja_nombre:
        filas = spreadsheet.worksheet(hoja_nombre).get_all_records()
        for fila in filas:
            if str(fila.get("Fecha", "")).startswith(mes_actual):
                cat   = fila.get("Categoría", "Otros") or "Otros"
                monto = int(fila.get("Monto", 0))
                categorias[cat] += monto

    filas_wawas = spreadsheet.worksheet("Wawas").get_all_records()
    for fila in filas_wawas:
        if str(fila.get("Fecha", "")).startswith(mes_actual) and fila.get("Quién") == usuario_nombre:
            cat   = fila.get("Categoría", "Otros") or "Otros"
            monto = int(fila.get("Monto", 0))
            categorias[f"{cat} (conjunto)"] += monto

    if not categorias:
        return f"📊 Sin gastos registrados en {mes_actual}"

    lineas = [f"📊 Por categoría {mes_actual}"]
    for cat, monto in sorted(categorias.items(), key=lambda x: -x[1]):
        lineas.append(f"  {cat}: ${monto:,}")
    lineas.append(f"💰 Total: ${sum(categorias.values()):,}")

    return "\n".join(lineas)


def cmd_ultimo(usuario_nombre):
    hoja_nombre = obtener_hoja_usuario(usuario_nombre)
    ultimo = None

    # Buscar en hoja personal
    if hoja_nombre:
        filas = spreadsheet.worksheet(hoja_nombre).get_all_records()
        filas_usuario = [f for f in filas if f.get("Quién") == usuario_nombre]
        if filas_usuario:
            ultimo = filas_usuario[-1]

    # Buscar en hoja conjunta
    filas_wawas = spreadsheet.worksheet("Wawas").get_all_records()
    filas_usuario_wawas = [f for f in filas_wawas if f.get("Quién") == usuario_nombre]

    if filas_usuario_wawas:
        ultimo_wawas = filas_usuario_wawas[-1]
        if not ultimo or ultimo_wawas.get("Fecha", "") > ultimo.get("Fecha", ""):
            ultimo = ultimo_wawas

    if not ultimo:
        return "📭 No tienes gastos registrados aún."

    tipo = "conjunto 👫" if ultimo.get("Tipo") == "Conjunto" else "personal 👤"
    return (
        f"🔍 Último gasto ({tipo})\n"
        f"📅 {ultimo.get('Fecha')}\n"
        f"📝 {ultimo.get('Descripción')}\n"
        f"💰 ${int(ultimo.get('Monto', 0)):,}\n"
        f"🏷️  {ultimo.get('Categoría')}\n\n"
        f"Para borrarlo escribe /borrar"
    )


def cmd_borrar(usuario_nombre):
    hoja_nombre  = obtener_hoja_usuario(usuario_nombre)
    ultima_hoja  = None
    ultima_fila  = None
    ultima_fecha = ""

    # Buscar última fila en hoja personal
    if hoja_nombre:
        hoja  = spreadsheet.worksheet(hoja_nombre)
        filas = hoja.get_all_values()
        for i in range(len(filas) - 1, 0, -1):
            if filas[i] and filas[i][1] == usuario_nombre:
                if filas[i][0] >= ultima_fecha:
                    ultima_fecha = filas[i][0]
                    ultima_hoja  = hoja
                    ultima_fila  = i + 1  # gspread usa índice base 1
                break

    # Buscar última fila en hoja conjunta
    hoja_wawas  = spreadsheet.worksheet("Wawas")
    filas_wawas = hoja_wawas.get_all_values()
    for i in range(len(filas_wawas) - 1, 0, -1):
        if filas_wawas[i] and filas_wawas[i][1] == usuario_nombre:
            if filas_wawas[i][0] >= ultima_fecha:
                ultima_hoja = hoja_wawas
                ultima_fila = i + 1
            break

    if not ultima_hoja or not ultima_fila:
        return "📭 No tienes gastos para borrar."

    fila_datos = ultima_hoja.row_values(ultima_fila)
    ultima_hoja.delete_rows(ultima_fila)

    try:
        actualizar_resumen()
    except Exception:
        pass

    return (
        f"🗑️ Gasto eliminado:\n"
        f"📝 {fila_datos[2]}\n"
        f"💰 ${int(fila_datos[3]):,}\n"
        f"🏷️  {fila_datos[4]}"
    )


def cmd_ayuda():
    return (
        "🤖 Comandos disponibles:\n\n"
        "💸 Registrar gasto:\n"
        "  Descripción Monto\n"
        "  Ej: Almuerzo 4.500\n\n"
        "👫 Gasto conjunto (Wawas):\n"
        "  *Descripción Monto\n"
        "  Ej: *Supermercado 38.000\n\n"
        "📊 Consultas:\n"
        "  /resumen → total del mes\n"
        "  /resumen categorias → por categoría\n"
        "  /ultimo → último gasto\n"
        "  /borrar → elimina último gasto\n"
        "  /ayuda → este menú"
    )


def registrar_gasto(numero_telefono, mensaje):
    numero_limpio = numero_telefono.replace("whatsapp:", "")

    if numero_limpio not in USUARIOS or USUARIOS[numero_limpio] is None:
        return "❌ Tu número no está registrado."

    usuario = USUARIOS[numero_limpio]
    datos   = parsear_mensaje(mensaje)

    if datos is None:
        return (
            "❌ No entendí el mensaje.\n"
            "Escribe /ayuda para ver los comandos 🙂"
        )

    comando = datos.get("comando")
    if comando == "resumen":
        return cmd_resumen(usuario["nombre"])
    if comando == "resumen_categorias":
        return cmd_resumen_categorias(usuario["nombre"])
    if comando == "ultimo":
        return cmd_ultimo(usuario["nombre"])
    if comando == "borrar":
        return cmd_borrar(usuario["nombre"])
    if comando == "ayuda":
        return cmd_ayuda()

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

    try:
        actualizar_resumen()
    except Exception as e:
        print(f"⚠️ Error actualizando resumen: {e}")

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