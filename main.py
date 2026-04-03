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

# --- LÓGICA DE NEGOCIO AVANZADA (EL CEREBRO) ---

def clasificar_lead(p):
    """Clasificación simplificada basada en presupuesto para la etiqueta visual."""
    try:
        p_val = float(str(p).replace('$', '').replace(',', ''))
        if p_val >= 500000: return "ALTO VALOR"
        elif p_val >= 150000: return "PROSPECTO"
        else: return "SEGUIMIENTO"
    except: return "ND"

def calcular_score_pro(d):
    """
    Calcula la relevancia real del lead (0-100).
    Ponderación: Presupuesto (40%), Intención (35%), Zona (15%), Calidad Datos (10%).
    """
    score = 0
    
    # 1. Análisis de Presupuesto (Máx 40 pts)
    try:
        p_val = float(str(d.get("presupuesto", 0)).replace('$', '').replace(',', ''))
        if p_val >= 1000000: score += 40
        elif p_val >= 500000: score += 35
        elif p_val >= 250000: score += 25
        elif p_val >= 100000: score += 15
        else: score += 5
    except:
        pass

    # 2. Análisis de Intención IA-Mimic (Máx 35 pts)
    msg = d.get("mensaje", "").lower()
    # Palabras que indican cierre o dinero en mano
    urgentes = ["comprar", "invertir", "contado", "urgente", "ahora", "visita", "cita", "mañana", "pago"]
    # Palabras que indican curiosidad básica
    interes = ["informacion", "precio", "disponible", "detalles", "fotos"]
    
    if any(x in msg for x in urgentes):
        score += 35
    elif any(x in msg for x in interes):
        score += 20
    elif len(msg.split()) > 15:
        score += 10

    # 3. Filtro de Zona Estratégica (Máx 15 pts)
    # Zonas de alta demanda en Guatemala
    zonas_premium = ["10", "14", "15", "16", "cayala", "carretera", "muxbal"]
    zona_user = d.get("zona_interes", "").lower()
    if any(z in zona_user for z in zonas_premium):
        score += 15
    else:
        score += 5

    # 4. Calidad y Seriedad del Perfil (Máx 10 pts)
    nombre = d.get("nombre", "")
    if len(nombre.split()) >= 2: score += 5  # Dio nombre y apellido
    if len(msg) > 60: score += 5             # Mensaje detallado

    return min(int(score), 100)

def temperatura_lead(score):
    """Asigna la temperatura basada en el nuevo score optimizado."""
    if score >= 85: return "MUY_CALIENTE" # 🔥🔥🔥
    elif score >= 65: return "CALIENTE"     # 🔥
    elif score >= 40: return "MEDIO"        # 🟡
    else: return "FRIO"                     # ❄️

# --- RUTAS (Se mantienen igual para no romper el flujo) ---

@app.route("/idioma/<lang>/<proximo>/<cliente_id>")
def cambiar_idioma(lang, proximo, cliente_id):
    session['idioma'] = lang
    return redirect(url_for(proximo, cliente_id=cliente_id))

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
        d = {
            "nombre": request.form.get("nombre"), 
            "telefono": request.form.get("telefono"), 
            "zona_interes": request.form.get("zona"), 
            "presupuesto": request.form.get("presupuesto"), 
            "mensaje": request.form.get("mensaje"),
            "vendedor": cliente_id.lower() 
        }
        
        # Usamos el nuevo cálculo Pro
        score = calcular_score_pro(d)
        
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
        
        supabase.table("leads").insert(datos_supabase).execute()
        return render_template("formulario.html", enviado=True, link_whatsapp=f"https://wa.me/{cliente['whatsapp']}", cliente=cliente, textos=textos)

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
    # Ordenamos por score descendente para que los mejores salgan arriba automáticamente
    query = supabase.table("leads").select("*").eq("vendedor", cliente_id.lower())
    if q: query = query.ilike("nombre", f"%{q}%")
    
    resultado = query.order("score", desc=True).execute()
    leads = resultado.data
    return render_template("historial.html", leads=leads, cliente=cliente, textos=textos)

if __name__ == "__main__":
    app.run(debug=True)
