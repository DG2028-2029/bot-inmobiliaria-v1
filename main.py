from flask import Flask, request, render_template, redirect, session, url_for
from supabase import create_client
import os
import re
from datetime import datetime
import config
from config_clientes import CLIENTES
from traducciones import DICCIONARIO

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

# --- INFRAESTRUCTURA DE DATOS ---
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

# --- MOTOR DE INTELIGENCIA DE NEGOCIOS GLOBAL (OMNI-ALGORITHM V2) ---

def motor_scoring_global(d):
    """
    Algoritmo avanzado de calificación.
    Mide: Capacidad (30%), Intención Semántica (30%), Esfuerzo/Calidad (25%), Coherencia (15%).
    """
    score = 0
    msg = d.get("mensaje", "").strip()
    msg_lower = msg.lower()
    nombre = d.get("nombre", "").strip()
    
    # 1. CAPACIDAD FINANCIERA UNIVERSAL (30 pts)
    # Extraemos el valor numérico sin importar el formato de moneda ($/€/Q/¥)
    try:
        p_clean = re.sub(r'[^\d.]', '', str(d.get("presupuesto", 0)))
        p_val = float(p_clean)
        
        # Escala de inversión global (Normalizada a USD para el cálculo)
        if p_val >= 1000000: score += 30
        elif p_val >= 500000: score += 25
        elif p_val >= 150000: score += 15
        else: score += 5
    except: pass

    # 2. INTENCIÓN PSICOLÓGICA MULTILINGÜE (30 pts)
    # Patrones de alta conversión en los principales idiomas globales
    keywords_urgencia = [
        "comprar", "invertir", "contado", "urgente", "pago", "ya", "cita",  # ES
        "buy", "invest", "now", "urgent", "cash", "closing", "ready",       # EN
        "acheter", "maintenant", "urgent", "viste", "rdv",                  # FR
        "kaufen", "jetzt", "sofort", "dringend", "termin",                  # DE
        "comprar", "agora", "urgente", "imediato",                          # PT
        "购买", "现在", "紧急", "预约", "现金"                                # ZH
    ]
    
    # Si detecta intención directa de cierre
    if any(k in msg_lower for k in keywords_urgencia):
        score += 30
    elif len(msg.split()) > 10:
        score += 10 # Al menos explica su situación

    # 3. EL "ENGAGEMENT SCORE" (ESFUERZO DEL LEAD) (25 pts)
    # El mayor indicador de interés real es cuánto tiempo/esfuerzo dedica el cliente.
    # Un bot o alguien poco interesado escribe poco.
    
    if len(nombre.split()) >= 2: score += 5   # Dio nombre y apellido (Formalidad)
    
    char_count = len(msg)
    if char_count > 250: score += 20          # Explicación detallada (Interés máximo)
    elif char_count > 100: score += 15
    elif char_count > 40: score += 5

    # 4. RELEVANCIA Y COHERENCIA DE DATOS (15 pts)
    # Términos de lujo/propiedad que indican un perfil serio a nivel mundial
    luxury_patterns = ["luxury", "lujo", "penthouse", "exclusive", "exclusivo", "investment", "roi", "yield"]
    zona = d.get("zona_interes", "").lower()
    
    if any(p in msg_lower or p in zona for p in luxury_patterns):
        score += 15
    elif len(zona) > 2:
        score += 5

    return min(int(score), 100)

def obtener_etiquetas_crm(score):
    """Categorización para el Dashboard del vendedor."""
    if score >= 85: return "ALTO VALOR", "MUY_CALIENTE"
    elif score >= 60: return "PROSPECTO", "CALIENTE"
    elif score >= 35: return "SEGUIMIENTO", "MEDIO"
    return "FRIO", "FRIO"

# --- RUTAS DE LA APLICACIÓN ---

@app.route("/form/<cliente_id>", methods=["GET","POST"])
def formulario(cliente_id):
    vendedor = CLIENTES.get(cliente_id.lower())
    if not vendedor: return "Vendedor no registrado", 404
    
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
        
        # Aplicamos el motor de scoring global
        score = motor_scoring_global(d)
        clasificacion, temperatura = obtener_etiquetas_crm(score)
        
        lead_data = {
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "nombre": d["nombre"],
            "telefono": d["telefono"],
            "zona_interes": d["zona_interes"], 
            "presupuesto": d["presupuesto"],
            "clasificacion": clasificacion,
            "score": score,
            "temperatura": temperatura,
            "estado": "Nuevo",
            "mensaje": d["mensaje"],
            "vendedor": d["vendedor"]
        }
        
        try:
            supabase.table("leads").insert(lead_data).execute()
            return render_template("formulario.html", enviado=True, link_whatsapp=f"https://wa.me/{vendedor['whatsapp']}", cliente=vendedor, textos=textos)
        except Exception as e:
            return f"Database Error: {e}", 500

    return render_template("formulario.html", enviado=False, cliente=vendedor, textos=textos)

@app.route("/historial/<cliente_id>")
def historial(cliente_id):
    if session.get("cliente") != cliente_id.lower():
        return redirect(url_for('login', cliente_id=cliente_id))
    
    vendedor = CLIENTES.get(cliente_id.lower())
    lang = session.get('idioma', 'es')
    textos = DICCIONARIO.get(lang, DICCIONARIO['es'])
    
    query = supabase.table("leads").select("*").eq("vendedor", cliente_id.lower())
    
    # Buscador opcional
    q = request.args.get('q', '')
    if q: query = query.ilike("nombre", f"%{q}%")
    
    # Ranking inteligente: El sistema pone los cierres más probables arriba
    resultado = query.order("score", desc=True).execute()
    return render_template("historial.html", leads=resultado.data, cliente=vendedor, textos=textos)

# --- RUTAS DE SOPORTE ---

@app.route("/login/<cliente_id>", methods=["GET","POST"])
def login(cliente_id):
    vendedor = CLIENTES.get(cliente_id.lower())
    lang = session.get('idioma', 'es')
    textos = DICCIONARIO.get(lang, DICCIONARIO['es'])
    
    if request.method == "POST":
        if request.form.get("usuario") == vendedor["usuario"] and request.form.get("password") == vendedor["password"]:
            session["cliente"] = cliente_id.lower()
            return redirect(url_for('historial', cliente_id=cliente_id.lower()))
        return render_template("login.html", error="Auth Error", cliente=vendedor, textos=textos)
    return render_template("login.html", cliente=vendedor, textos=textos)

@app.route("/idioma/<lang>/<proximo>/<cliente_id>")
def cambiar_idioma(lang, proximo, cliente_id):
    session['idioma'] = lang
    return redirect(url_for(proximo, cliente_id=cliente_id))

@app.route("/")
def index():
    return "PropTech Global Engine Active. 🌍"

if __name__ == "__main__":
    app.run(debug=True)
