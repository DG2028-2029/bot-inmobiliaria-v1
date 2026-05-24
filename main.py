from flask import Flask, request, render_template, redirect, session, url_for
from supabase import create_client
import os
import re
import math
from datetime import datetime
import config
from config_clientes import CLIENTES
from traducciones import DICCIONARIO
from email_service import enviar_email_lead

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

# --- INFRAESTRUCTURA DE DATOS ESCALABLE ---
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

# --- MOTOR DE INTELIGENCIA DE NEGOCIOS (OMNI-ENGINE V4) ---

def calcular_entropia_mensaje(texto):
    """Mide la riqueza léxica. Separa leads automáticos de interesados reales."""
    if not texto or len(texto) < 10: return 0
    palabras = texto.lower().split()
    unicas = set(palabras)
    # Si usa muchas palabras diferentes, es un mensaje con mucha sustancia.
    return (len(unicas) / len(palabras)) if palabras else 0

def motor_scoring_global(d):
    """
    Algoritmo de Calificación Universal.
    Independiente de moneda o país.
    Mide: Capacidad (30%), Intención (40%), Esfuerzo (20%), Contexto (10%).
    """
    score = 0
    msg = d.get("mensaje", "").strip()
    msg_l = msg.lower()
    zona = d.get("zona_interes", "").lower()
    
    # 1. ANÁLISIS DE CAPACIDAD FINANCIERA (Normalización de Moneda)
    try:
        # Extrae solo los números, ignorando $, €, Q, o comas.
        p_val = float(re.sub(r'[^\d.]', '', str(d.get("presupuesto", 0))))
        
        # Escala de inversión profesional (Agnóstica al mercado)
        if p_val >= 1000000: score += 30      # Inversionista Global
        elif p_val >= 500000: score += 25     # Cliente Premium
        elif p_val >= 150000: score += 15     # Mercado Estándar
        elif p_val > 0: score += 5
    except: pass

    # 2. INTENCIÓN PSICOLÓGICA Y SEMÁNTICA (40 pts)
    # Buscamos 'Triggers' de cierre en múltiples idiomas
    triggers = [
        "comprar", "invertir", "contado", "urgente", "pago", "visita", "ahora", # ES
        "buy", "invest", "cash", "closing", "ready", "now", "tour",             # EN
        "acheter", "maintenant", "urgent", "viste", "rdv", "paiement",         # FR
        "kaufen", "jetzt", "sofort", "dringend", "termin",                     # DE
        "购买", "现在", "紧急", "预约", "现金", "投资"                             # ZH
    ]
    
    # Detección inteligente de intención
    hits = sum(1 for t in triggers if t in msg_l)
    if hits >= 2: score += 40
    elif hits == 1: score += 25
    elif len(msg.split()) > 15: score += 15 # No hay triggers pero hay explicación larga

    # 3. MÉTRICA DE ESFUERZO (20 pts)
    # Cuanto más escribe el cliente, más probable es el cierre.
    entropia = calcular_entropia_mensaje(msg)
    if entropia > 0.8 and len(msg) > 100: score += 20
    elif len(msg) > 50: score += 10
    
    if len(d.get("nombre", "").split()) >= 2: score += 5 # Formalidad en el nombre

    # 4. RELEVANCIA DE CONTEXTO (10 pts)
    # Detecta si el cliente conoce el mercado o busca lujo
    keywords_premium = ["lujo", "luxury", "penthouse", "roi", "rentabilidad", "yield", "exclusive"]
    if any(k in msg_l or k in zona for k in keywords_premium):
        score += 10

    return min(int(score), 100)

def calificar_lead_profesional(score):
    """Asignación de estatus de grado CRM."""
    if score >= 85: return "💎 VIP / INVERSIONISTA", "MUY_CALIENTE"
    elif score >= 65: return "🔥 PROSPECTO A", "CALIENTE"
    elif score >= 40: return "🟡 SEGUIMIENTO B", "MEDIO"
    return "❄️ LEAD FRÍO", "FRIO"

# --- CONTROLADORES DE RUTA (BUSINESS LOGIC) ---

@app.route("/cliente/<cliente_id>")
def seleccion_idioma(cliente_id):
    """Puerta de enlace global con detección automática de idioma."""
    id_clean = cliente_id.lower()
    vendedor = CLIENTES.get(id_clean)
    if not vendedor: return "Error 403: Acceso denegado a la plataforma.", 403
    
    lang = session.get('idioma', request.accept_languages.best_match(['es', 'en', 'fr', 'de']) or 'es')
    textos = DICCIONARIO.get(lang, DICCIONARIO['es'])
    
    return render_template("bienvenida.html", cliente=vendedor, textos=textos)

@app.route("/form/<cliente_id>", methods=["GET","POST"])
def formulario(cliente_id):
    id_clean = cliente_id.lower()
    vendedor = CLIENTES.get(id_clean)
    if not vendedor: return "Error 404: Vendedor no configurado.", 404
    
    lang = session.get('idioma', 'es')
    textos = DICCIONARIO.get(lang, DICCIONARIO['es'])
    
    if request.method == "POST":
        d = {
            "nombre": request.form.get("nombre").strip(), 
            "telefono": request.form.get("telefono").strip(), 
            "zona_interes": request.form.get("zona").strip(), 
            "presupuesto": request.form.get("presupuesto").strip(), 
            "mensaje": request.form.get("mensaje").strip(),
            "vendedor": id_clean 
        }
        
        # Procesamiento con el motor V4
        score_final = motor_scoring_global(d)
        clasificacion, temperatura = calificar_lead_profesional(score_final)
        
        lead_data = {
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
            **d,
            "clasificacion": clasificacion,
            "score": score_final,
            "temperatura": temperatura,
            "estado": "Nuevo"
        }
        
        try:
            supabase.table("leads").insert(lead_data).execute()
            
            # 🚀 ENVÍO DE EMAIL AUTOMÁTICO (OPCIONAL)
            # Solo se envía si:
            # 1. El cliente tiene "premium_email": True en config_clientes.py
            # 2. El cliente proporcionó su email en el formulario
            email_cliente = request.form.get("email", "").strip()
            if email_cliente:
                enviar_email_lead(id_clean, d.get("nombre"), email_cliente)
            
            # Link dinámico de WhatsApp para respuesta inmediata
            ws_link = f"https://wa.me/{vendedor['whatsapp']}"
            return render_template("formulario.html", enviado=True, link_whatsapp=ws_link, cliente=vendedor, textos=textos)
        except Exception as e:
            return f"System Synch Error: {e}", 500

    return render_template("formulario.html", enviado=False, cliente=vendedor, textos=textos)

@app.route("/historial/<cliente_id>")
def historial(cliente_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean:
        return redirect(url_for('login', cliente_id=id_clean))
    
    vendedor = CLIENTES.get(id_clean)
    textos = DICCIONARIO.get(session.get('idioma', 'es'), DICCIONARIO['es'])
    
    query = supabase.table("leads").select("*").eq("vendedor", id_clean)
    
    # Filtro de búsqueda profesional
    q = request.args.get('q', '')
    if q: query = query.ilike("nombre", f"%{q}%")
    
    # El ranking PRIORIZA el dinero y la intención (Score)
    resultado = query.order("score", desc=True).execute()
    return render_template("historial.html", leads=resultado.data, cliente=vendedor, textos=textos)

# --- NUEVA RUTA PARA TU ACCESO ADMINISTRATIVO ---

@app.route("/access/<cliente_id>")
def seleccion_idioma_login(cliente_id):
    """Muestra la pantalla personalizada de bienvenida_login.html."""
    id_clean = cliente_id.lower()
    vendedor = CLIENTES.get(id_clean)
    if not vendedor: return "Error 403", 403
    return render_template("bienvenida_login.html", cliente=vendedor)

@app.route("/login/<cliente_id>", methods=["GET","POST"])
def login(cliente_id):
    id_clean = cliente_id.lower()
    vendedor = CLIENTES.get(id_clean)
    
    # Usamos el idioma que se haya guardado en la sesión
    lang = session.get('idioma', 'es')
    textos = DICCIONARIO.get(lang, DICCIONARIO['es'])
    
    if request.method == "POST":
        if request.form.get("usuario") == vendedor["usuario"] and request.form.get("password") == vendedor["password"]:
            session["cliente"] = id_clean
            return redirect(url_for('historial', cliente_id=id_clean))
        return render_template("login.html", error="Credenciales Invalidas", cliente=vendedor, textos=textos)
    return render_template("login.html", cliente=vendedor, textos=textos)

@app.route("/idioma/<lang>/<proximo>/<cliente_id>")
def cambiar_idioma(lang, proximo, cliente_id):
    session['idioma'] = lang
    return redirect(url_for(proximo, cliente_id=cliente_id.lower()))

@app.route("/")
def index():
    return "PropTech Global Engine V4.0 [Active Mode] 🌐🚀"

if __name__ == "__main__":
    app.run(debug=True)
