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

# --- MOTOR DE INTELIGENCIA DE NEGOCIOS (OMNI-ALGORITHM) ---

def motor_scoring_profesional(d):
    """
    Algoritmo de calificación de 4 niveles.
    Mide: Capacidad (30%), Urgencia (30%), Calidad de Datos (20%), Relevancia (20%).
    """
    score = 0
    msg = d.get("mensaje", "").strip().lower()
    nombre = d.get("nombre", "").strip()
    
    # 1. ANÁLISIS DE CAPACIDAD FINANCIERA (Filtro de Inversión)
    try:
        # Limpieza profunda de caracteres monetarios globales
        p_clean = re.sub(r'[^\d.]', '', str(d.get("presupuesto", 0)))
        p_val = float(p_clean)
        
        if p_val >= 1000000: score += 30      # Inversionista institucional
        elif p_val >= 500000: score += 25     # High Net Worth
        elif p_val >= 200000: score += 15     # Cliente Prime
        elif p_val >= 100000: score += 5      # Entrada de mercado
    except:
        pass

    # 2. DETECTOR DE INTENCIÓN PSICOLÓGICA MULTILINGÜE
    # Analiza verbos de acción en los idiomas configurados (ES, EN, FR, DE, PT, ZH)
    keywords_cierre = [
        "comprar", "invertir", "ahora", "urgente", "visita", "contado", "pago", "ya", # ES
        "buy", "invest", "now", "urgent", "visit", "cash", "closing", "ready",       # EN
        "acheter", "maintenant", "urgent", "viste", "rdv",                            # FR
        "kaufen", "jetzt", "sofort", "dringend", "termin",                            # DE
        "comprar", "agora", "urgente", "visita", "imediato",                          # PT
        "购买", "现在", "紧急", "预约", "现金"                                          # ZH
    ]
    
    # Si detecta intención de cierre, asigna puntaje máximo de urgencia
    if any(k in msg for k in keywords_cierre):
        score += 30
    elif len(msg.split()) > 10:
        score += 15 # El cliente se tomó el tiempo de explicar su necesidad

    # 3. VALIDACIÓN DE CALIDAD DE PERFIL (Anti-Spam/Bot)
    # Un cliente profesional escribe nombre y apellido, y deja un mensaje coherente.
    if len(nombre.split()) >= 2: score += 10  # Verificación de identidad
    
    # Medidor de "Sustancia" (Longitud del mensaje)
    if len(msg) > 150: score += 10            # Lead de alta descripción
    elif len(msg) > 50: score += 5

    # 4. RELEVANCIA GEOGRÁFICA Y DE PRODUCTO
    # Zonas de alto valor y términos de propiedad específicos
    premium_patterns = ["10", "14", "15", "16", "cayala", "muxbal", "antigua", "penthouse", "lujo", "luxury"]
    zona = d.get("zona_interes", "").lower()
    
    if any(p in zona or p in msg for p in premium_patterns):
        score += 20
    elif len(zona) > 2:
        score += 10

    return min(int(score), 100)

def obtener_metadatos_lead(score):
    """Genera las etiquetas profesionales para el CRM basadas en el scoring."""
    # Clasificación de Negocio
    if score >= 85: clas = "ALTO VALOR"
    elif score >= 55: clas = "PROSPECTO"
    else: clas = "SEGUIMIENTO"
    
    # Estado de la Venta (Temperatura)
    if score >= 85: temp = "MUY_CALIENTE"
    elif score >= 65: temp = "CALIENTE"
    elif score >= 40: temp = "MEDIO"
    else: temp = "FRIO"
    
    return clas, temp

# --- CONTROLADORES (ROUTES) ---

@app.route("/form/<cliente_id>", methods=["GET","POST"])
def formulario(cliente_id):
    vendedor = CLIENTES.get(cliente_id.lower())
    if not vendedor: return "Vendedor no registrado", 404
    
    lang = session.get('idioma', 'es')
    textos = DICCIONARIO.get(lang, DICCIONARIO['es'])
    
    if request.method == "POST":
        payload = {
            "nombre": request.form.get("nombre"), 
            "telefono": request.form.get("telefono"), 
            "zona_interes": request.form.get("zona"), 
            "presupuesto": request.form.get("presupuesto"), 
            "mensaje": request.form.get("mensaje"),
            "vendedor": cliente_id.lower() 
        }
        
        # Ejecución del motor de inteligencia
        final_score = motor_scoring_profesional(payload)
        clasificacion, temperatura = obtener_metadatos_lead(final_score)
        
        lead_data = {
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "nombre": payload["nombre"],
            "telefono": payload["telefono"],
            "zona_interes": payload["zona_interes"], 
            "presupuesto": payload["presupuesto"],
            "clasificacion": clasificacion,
            "score": final_score,
            "temperatura": temperatura,
            "estado": "Nuevo",
            "mensaje": payload["mensaje"],
            "vendedor": payload["vendedor"]
        }
        
        try:
            supabase.table("leads").insert(lead_data).execute()
            return render_template("formulario.html", enviado=True, link_whatsapp=f"https://wa.me/{vendedor['whatsapp']}", cliente=vendedor, textos=textos)
        except Exception as e:
            return f"Error en la base de datos: {e}", 500

    return render_template("formulario.html", enviado=False, cliente=vendedor, textos=textos)

@app.route("/historial/<cliente_id>")
def historial(cliente_id):
    if session.get("cliente") != cliente_id.lower():
        return redirect(url_for('login', cliente_id=cliente_id))
    
    vendedor = CLIENTES.get(cliente_id.lower())
    lang = session.get('idioma', 'es')
    textos = DICCIONARIO.get(lang, DICCIONARIO['es'])
    
    # Los mejores negocios siempre aparecen en la parte superior (Ranking por Score)
    query = supabase.table("leads").select("*").eq("vendedor", cliente_id.lower())
    
    # Soporte para búsqueda por nombre
    q = request.args.get('q', '')
    if q: query = query.ilike("nombre", f"%{q}%")
    
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
        return render_template("login.html", error="Error de autenticación", cliente=vendedor, textos=textos)
    return render_template("login.html", cliente=vendedor, textos=textos)

@app.route("/idioma/<lang>/<proximo>/<cliente_id>")
def cambiar_idioma(lang, proximo, cliente_id):
    session['idioma'] = lang
    return redirect(url_for(proximo, cliente_id=cliente_id))

@app.route("/")
def index():
    return "API Real Estate Engine Online. 🌐"

if __name__ == "__main__":
    app.run(debug=True)
