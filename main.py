from flask import Flask, request, render_template, redirect, session, url_for
import csv, os, urllib.parse
from datetime import datetime
import smtplib
from email.message import EmailMessage

import config
from config_clientes import CLIENTES

app = Flask(__name__)
app.secret_key = config.SECRET_KEY 

# =========================
# RUTAS DE ACCESO
# =========================
@app.route("/")
def index():
    return "Sistema Inmobiliario Activo. Accede a /login/roberto para entrar."

# =========================
# LÓGICA DE NEGOCIO (Tus funciones originales)
# =========================
def get_cliente(cliente_id):
    return CLIENTES.get(cliente_id)

def asegurar_csv(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["Fecha","Nombre","Telefono","Zona","Presupuesto","Clasificacion","Score","Temperatura","Estado","Mensaje"])

def clasificar_lead(p):
    try:
        p = float(p)
        if p >= 300000: return "ALTO VALOR 💎"
        elif p >= 150000: return "VALOR MEDIO 🟡"
        else: return "BAJO VALOR ⚪"
    except: return "NO DEFINIDO"

def calcular_score(d):
    score = 0
    try:
        p = float(d["presupuesto"])
        score += min(35, p / 30000)
    except: pass
    if d["zona"]: score += 15
    palabras = d["mensaje"].split()
    if len(palabras) >= 20: score += 20
    elif len(palabras) >= 10: score += 10
    if any(x in d["mensaje"].lower() for x in ["comprar","invertir","cerrar","urgente","este mes"]): score += 20
    return min(int(score), 100)

def temperatura_lead(score):
    if score >= 80: return "🔥 MUY CALIENTE"
    elif score >= 60: return "🔥 CALIENTE"
    elif score >= 40: return "🟡 MEDIO"
    else: return "❄️ FRÍO"

def enviar_correo(cliente, d, clasif, score, temp):
    msg = EmailMessage()
    msg["Subject"] = f"📩 Nuevo Lead {temp} | Score {score}"
    msg["From"] = cliente["email_origen"]
    msg["To"] = cliente["email_destino"]
    msg.set_content(f"🏢 Inmobiliaria: {cliente['nombre']}\n👤 Nombre: {d['nombre']}\n💰 Presupuesto: {d['presupuesto']}\n🔥 Temp: {temp}")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(cliente["email_origen"], cliente["email_password"])
        smtp.send_message(msg)

# =========================
# FORMULARIO
# =========================
@app.route("/cliente/<cliente_id>", methods=["GET","POST"])
def formulario(cliente_id):
    cliente = get_cliente(cliente_id)
    if not cliente: return "Cliente no existe", 404
    asegurar_csv(cliente["archivo_csv"])
    if request.method == "POST":
        d = {"nombre": request.form["nombre"], "telefono": request.form["telefono"], "zona": request.form["zona"], "presupuesto": request.form["presupuesto"], "mensaje": request.form["mensaje"]}
        clasif = clasificar_lead(d["presupuesto"])
        score = calcular_score(d)
        temp = temperatura_lead(score)
        with open(cliente["archivo_csv"], "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([datetime.now().strftime("%Y-%m-%d %H:%M"), d["nombre"], d["telefono"], d["zona"], d["presupuesto"], clasif, score, temp, "Nuevo", d["mensaje"]])
        enviar_correo(cliente, d, clasif, score, temp)
        return render_template("formulario.html", enviado=True, link_whatsapp=f"https://wa.me/{cliente['whatsapp']}")
    return render_template("formulario.html", enviado=False)

# =========================
# LOGIN Y HISTORIAL
# =========================
@app.route("/login/<cliente_id>", methods=["GET","POST"])
def login(cliente_id):
    cliente = get_cliente(cliente_id)
    if not cliente: return "Cliente no existe", 404
    if request.method == "POST":
        if request.form["usuario"] == cliente["usuario"] and request.form["password"] == cliente["password"]:
            session["cliente"] = cliente_id
            return redirect(url_for('historial', cliente_id=cliente_id))
        return render_template("login.html", error="Credenciales incorrectas")
    return render_template("login.html")

@app.route("/historial/<cliente_id>")
def historial(cliente_id):
    if session.get("cliente") != cliente_id: return redirect(url_for('login', cliente_id=cliente_id))
    cliente = get_cliente(cliente_id)
    if not os.path.exists(cliente["archivo_csv"]): return "No hay leads aún."
    with open(cliente["archivo_csv"], newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))[1:]
    return render_template("historial.html", leads=rows)

if __name__ == "__main__":
    app.run()
