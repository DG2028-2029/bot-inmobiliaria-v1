from flask import Flask, request, render_template, redirect, session, url_for
from supabase import create_client
import os
from datetime import datetime
import config
from config_clientes import CLIENTES

app = Flask(__name__)
app.secret_key = config.SECRET_KEY 

# --- CONEXIÓN A SUPABASE ---
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

# --- LÓGICA DE NEGOCIO ---
def clasificar_lead(p):
    try:
        p = float(p.replace('$', '').replace(',', '')) if isinstance(p, str) else float(p)
        if p >= 300000: return "ALTO VALOR 💎"
        elif p >= 150000: return "VALOR MEDIO 🟡"
        else: return "BAJO VALOR ⚪"
    except: return "NO DEFINIDO"

def calcular_score(d):
    score = 0
    try:
        p = float(d.get("presupuesto", 0))
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

# --- RUTAS ---
@app.route("/")
def index():
    return "Sistema Inmobiliario Cloud Activo. 🚀"

@app.route("/cliente/<cliente_id>", methods=["GET","POST"])
def formulario(cliente_id):
    cliente = CLIENTES.get(cliente_id.lower())
    if not cliente: return "Error: Este vendedor no existe", 404
    
    if request.method == "POST":
        d = {
            "nombre": request.form.get("nombre"), 
            "telefono": request.form.get("telefono"), 
            "zona": request.form.get("zona"), 
            "presupuesto": request.form.get("presupuesto"), 
            "mensaje": request.form.get("mensaje"),
            "cliente_id": cliente_id.lower()
        }
        
        score = calcular_score(d)
        datos_supabase = {
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "nombre": d["nombre"],
            "telefono": d["telefono"],
            "zona": d["zona"],
            "presupuesto": d["presupuesto"],
            "clasificacion": clasificar_lead(d["presupuesto"]),
            "score": score,
            "temperatura": temperatura_lead(score),
            "estado": "Nuevo",
            "mensaje": d["mensaje"],
            "cliente_id": d["cliente_id"]
        }
        
        supabase.table("leads").insert(datos_supabase).execute()
        return render_template("formulario.html", enviado=True, link_whatsapp=f"https://wa.me/{cliente['whatsapp']}", cliente=cliente)
    
    return render_template("formulario.html", enviado=False, cliente=cliente)

@app.route("/login/<cliente_id>", methods=["GET","POST"])
def login(cliente_id):
    cliente = CLIENTES.get(cliente_id.lower())
    if not cliente: return "Vendedor no existe", 404
    
    if request.method == "POST":
        if request.form.get("usuario") == cliente["usuario"] and request.form.get("password") == cliente["password"]:
            session["cliente"] = cliente_id.lower()
            return redirect(url_for('historial', cliente_id=cliente_id.lower()))
        return render_template("login.html", error="Credenciales incorrectas", cliente=cliente)
    
    return render_template("login.html", cliente=cliente)

@app.route("/historial/<cliente_id>")
def historial(cliente_id):
    if session.get("cliente") != cliente_id.lower():
        return redirect(url_for('login', cliente_id=cliente_id))
    
    cliente = CLIENTES.get(cliente_id.lower())
    q = request.args.get('q', '') 
    
    query = supabase.table("leads").select("*").eq("cliente_id", cliente_id.lower())
    
    if q:
        query = query.ilike("nombre", f"%{q}%")
    
    resultado = query.order("id", desc=True).execute()
    leads = resultado.data
            
    return render_template("historial.html", leads=leads, cliente=cliente)

if __name__ == "__main__":
    app.run()
