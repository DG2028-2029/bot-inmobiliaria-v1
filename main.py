from flask import Flask, request, render_template, redirect, session, url_for
from supabase import create_client
import os
from datetime import datetime
import config
from config_clientes import CLIENTES
from traducciones import DICCIONARIO 

app = Flask(__name__)
app.secret_key = config.SECRET_KEY 

# --- CONEXIÓN A SUPABASE ---
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

# --- LÓGICA DE NEGOCIO ---
def clasificar_lead(p):
    """Clasifica el lead según el presupuesto."""
    try:
        p_str = str(p).replace('$', '').replace(',', '')
        p_val = float(p_str)
        if p_val >= 300000: return "ALTO VALOR 💎"
        elif p_val >= 150000: return "VALOR MEDIO 🟡"
        else: return "BAJO VALOR ⚪"
    except: return "NO DEFINIDO"

def calcular_score(d):
    """Calcula la relevancia del lead de 0 a 100."""
    score = 0
    try:
        p_str = str(d.get("presupuesto", 0)).replace('$', '').replace(',', '')
        p = float(p_str)
        score += min(35, p / 30000)
    except: pass
    
    if d.get("zona_interes"): score += 15 
    
    msg = d.get("mensaje", "").lower()
    palabras = msg.split()
    if len(palabras) >= 20: score += 20
    elif len(palabras) >= 10: score += 10
    
    if any(x in msg for x in ["comprar","invertir","cerrar","urgente","este mes"]): 
        score += 20
        
    return min(int(score), 100)

def temperatura_lead(score):
    """Asigna un estado visual según el score."""
    if score >= 80: return "🔥 MUY CALIENTE"
    elif score >= 60: return "🔥 CALIENTE"
    elif score >= 40: return "🟡 MEDIO"
    else: return "❄️ FRÍO"

# --- RUTAS ---
@app.route("/idioma/<lang>/<proximo>/<cliente_id>")
def cambiar_idioma(lang, proximo, cliente_id):
    session['idioma'] = lang
    try:
        return redirect(url_for(proximo, cliente_id=cliente_id))
    except:
        return redirect(url_for('bienvenida', cliente_id=cliente_id))

@app.route("/")
def index():
    return "Sistema Inmobiliario Cloud Activo. 🚀"

@app.route("/cliente/<cliente_id>")
def bienvenida(cliente_id):
    cliente = CLIENTES.get(cliente_id.lower())
    if not cliente: return "Error: Vendedor no existe", 404
    lang = session.get('idioma', 'es')
    textos = DICCIONARIO.get(lang, DICCIONARIO['es'])
    return render_template("bienvenida.html", cliente=cliente, textos=textos)

@app.route("/form/<cliente_id>", methods=["GET","POST"])
def formulario(cliente_id):
    cliente = CLIENTES.get(cliente_id.lower())
    if not cliente: return "Error: Vendedor no existe", 404
    lang = session.get('idioma', 'es')
    textos = DICCIONARIO.get(lang, DICCIONARIO['es'])
    
    if request.method == "POST":
        if not request.form.get("terminos"):
            return "Error: Debe aceptar los términos.", 400

        d = {
            "nombre": request.form.get("nombre"), 
            "telefono": request.form.get("telefono"), 
            "zona_interes": request.form.get("zona"), 
            "presupuesto": request.form.get("presupuesto"), 
            "mensaje": request.form.get("mensaje"),
            "vendedor": cliente_id.lower() 
        }
        
        score = calcular_score(d)
        datos_supabase = {
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "nombre": d["nombre"],
            "telefono": d["telefono"],
            "zona_interes": d["zona_interes"], 
            "presupuesto": d["presupuesto"],
            "clasificacion": clasificar_lead(d["presupuesto"]),
            "score": score,
            "temperatura": temperatura_lead(score),
            "estado": "Nuevo",
            "mensaje": d["mensaje"],
            "vendedor": d["vendedor"]
        }
        
        try:
            # Registro en Supabase
            supabase.table("leads").insert(datos_supabase).execute()
            
            # Nota: Lógica de email eliminada por solicitud del usuario para mayor estabilidad.
            
            return render_template("formulario.html", enviado=True, link_whatsapp=f"https://wa.me/{cliente['whatsapp']}", cliente=cliente, textos=textos)

        except Exception as e:
            print(f"Error crítico: {e}")
            return f"Error en el sistema: {e}", 500
    
    return render_template("formulario.html", enviado=False, cliente=cliente, textos=textos)

@app.route("/login/<cliente_id>", methods=["GET","POST"])
def login(cliente_id):
    cliente = CLIENTES.get(cliente_id.lower())
    if not cliente: return "Vendedor no existe", 404
    lang = session.get('idioma', 'es')
    textos = DICCIONARIO.get(lang, DICCIONARIO['es'])
    
    if request.method == "POST":
        if request.form.get("usuario") == cliente["usuario"] and request.form.get("password") == cliente["password"]:
            session["cliente"] = cliente_id.lower()
            return redirect(url_for('historial', cliente_id=cliente_id.lower()))
        return render_template("login.html", error="Credenciales incorrectas", cliente=cliente, textos=textos)
    
    return render_template("login.html", cliente=cliente, textos=textos)

@app.route("/historial/<cliente_id>")
def historial(cliente_id):
    if session.get("cliente") != cliente_id.lower():
        return redirect(url_for('login', cliente_id=cliente_id))
    
    cliente = CLIENTES.get(cliente_id.lower())
    lang = session.get('idioma', 'es')
    textos = DICCIONARIO.get(lang, DICCIONARIO['es'])
    
    q = request.args.get('q', '') 
    query = supabase.table("leads").select("*").eq("vendedor", cliente_id.lower())
    if q: query = query.ilike("nombre", f"%{q}%")
    
    resultado = query.order("id", desc=True).execute()
    leads = resultado.data
    return render_template("historial.html", leads=leads, cliente=cliente, textos=textos)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
