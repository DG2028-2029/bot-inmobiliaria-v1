from flask import Flask, request, render_template, redirect, session, url_for
import csv, os
from datetime import datetime
import config
from config_clientes import CLIENTES

app = Flask(__name__)
app.secret_key = config.SECRET_KEY 

def get_ruta_csv(nombre_archivo):
    # Esto limpia el nombre para que funcione bien en el servidor Render
    nombre_limpio = os.path.basename(nombre_archivo)
    return os.path.join("/tmp", nombre_limpio)

def get_cliente(cliente_id):
    return CLIENTES.get(cliente_id.lower())

def asegurar_csv(path):
    ruta = get_ruta_csv(path)
    if not os.path.exists(ruta):
        with open(ruta, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["Fecha","Nombre","Telefono","Zona","Presupuesto","Clasificacion","Score","Temperatura","Estado","Mensaje"])
    return ruta

# --- LÓGICA DE CLASIFICACIÓN ---
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
    if d.get("zona"): score += 15
    msg = d.get("mensaje", "").lower()
    palabras = msg.split()
    if len(palabras) >= 20: score += 20
    elif len(palabras) >= 10: score += 10
    if any(x in msg for x in ["comprar","invertir","cerrar","urgente","este mes"]): score += 20
    return min(int(score), 100)

def temperatura_lead(score):
    if score >= 80: return "🔥 MUY CALIENTE"
    elif score >= 60: return "🔥 CALIENTE"
    elif score >= 40: return "🟡 MEDIO"
    else: return "❄️ FRÍO"

# --- RUTAS DINÁMICAS ---
@app.route("/")
def index():
    return "Sistema Inmobiliario Activo. 🚀"

@app.route("/cliente/<cliente_id>", methods=["GET","POST"])
def formulario(cliente_id):
    cliente = get_cliente(cliente_id)
    if not cliente: return "Error: Este vendedor no existe", 404
    
    if request.method == "POST":
        d = {
            "nombre": request.form.get("nombre"), 
            "telefono": request.form.get("telefono"), 
            "zona": request.form.get("zona"), 
            "presupuesto": request.form.get("presupuesto"), 
            "mensaje": request.form.get("mensaje")
        }
        
        clasif = clasificar_lead(d["presupuesto"])
        score = calcular_score(d)
        temp = temperatura_lead(score)
        
        ruta_csv = asegurar_csv(cliente["archivo_csv"])
        with open(ruta_csv, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([datetime.now().strftime("%Y-%m-%d %H:%M"), d["nombre"], d["telefono"], d["zona"], d["presupuesto"], clasif, score, temp, "Nuevo", d["mensaje"]])
        
        return render_template("formulario.html", enviado=True, link_whatsapp=f"https://wa.me/{cliente['whatsapp']}", cliente=cliente)
    
    return render_template("formulario.html", enviado=False, cliente=cliente)

@app.route("/login/<cliente_id>", methods=["GET","POST"])
def login(cliente_id):
    cliente = get_cliente(cliente_id)
    if not cliente: return "Vendedor no existe", 404
    
    if request.method == "POST":
        if request.form.get("usuario") == cliente["usuario"] and request.form.get("password") == cliente["password"]:
            session["cliente"] = cliente_id
            return redirect(url_for('historial', cliente_id=cliente_id))
        return render_template("login.html", error="Credenciales incorrectas")
    
    return render_template("login.html", cliente=cliente)

@app.route("/historial/<cliente_id>")
def historial(cliente_id):
    if session.get("cliente") != cliente_id:
        return redirect(url_for('login', cliente_id=cliente_id))
    
    cliente = get_cliente(cliente_id)
    ruta_csv = get_ruta_csv(cliente["archivo_csv"])
    
    leads = []
    if os.path.exists(ruta_csv):
        with open(ruta_csv, newline="", encoding="utf-8") as f:
            leads = list(csv.reader(f))[1:]
            leads.reverse() # Para que vean primero lo más nuevo
            
    return render_template("historial.html", leads=leads, cliente=cliente)

if __name__ == "__main__":
    app.run()
