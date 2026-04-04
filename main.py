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

# --- CONEXIÓN A SUPABASE ---
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

# --- EL MOTOR DE DECISIÓN "OMNI-SCORING" ---

def motor_calificacion_elite(d):
    """
    Analiza la intención real del cliente (0-100 pts).
    Supera a una IA básica mediante validación de patrones de comportamiento.
    """
    score = 0
    msg = d.get("mensaje", "").lower()
    nombre = d.get("nombre", "").strip()
    
    # 1. CAPA DE INTENCIÓN PSICOLÓGICA (Máx 35 pts)
    # Buscamos verbos de acción y urgencia en los 6 idiomas del sistema
    patrones_alta_intencion = [
        "comprar", "invertir", "ahora", "urgente", "visita", "contado", "cita", "pago", # ES
        "buy", "invest", "now", "urgent", "visit", "cash", "appointment", "ready",    # EN
        "acheter", "maintenant", "viste", "urgent", "rdv",                            # FR
        "kaufen", "jetzt", "sofort", "dringend", "termin",                            # DE
        "comprar", "agora", "urgente", "visita",                                      # PT
        "购买", "现在", "紧急", "预约"                                                  # ZH
    ]
    
    if any(p in msg for p in patrones_alta_intencion):
        score += 35
    elif len(msg.split()) > 8:
        score += 15 # Interés narrativo (el cliente explica su situación)

    # 2. CAPA DE ESFUERZO Y CALIDAD DE DATOS (Máx 25 pts)
    # Un cliente "real" se esfuerza más al llenar el formulario.
    if " " in nombre: score += 5              # Dio nombre y apellido
    
    # Análisis de longitud de mensaje: Más texto = Mayor compromiso
    if len(msg) > 200: score += 20            
    elif len(msg) > 100: score += 15
    elif len(msg) > 40: score += 10
    
    # 3. CAPA DE CAPACIDAD FINANCIERA (Máx 25 pts)
    try:
        # Extraer solo números para soporte de cualquier moneda ($ o €)
        p_limpio = re.sub(r'[^\d.]', '', str(d.get("presupuesto", 0)))
        p_val = float(p_limpio)
        
        if p_val >= 1000000: score += 25      # Perfil Inversionista
        elif p_val >= 500000: score += 20     # Perfil Premium
        elif p_val >= 150000: score += 10     # Perfil Estándar
        else: score += 5
    except:
        pass

    # 4. CAPA DE RELEVANCIA GEOGRÁFICA (Máx 15 pts)
    # Zonas de alta plusvalía o interés estratégico (Guatemala y Global)
    zonas_top = ["10", "14", "15", "16", "cayala", "muxbal", "fraijanes", "antigua", "zona 14", "zona 10"]
    zona_lead = d.get("zona_interes", "").lower()
    
    if any(z in zona_lead for z in zonas_top):
        score += 15
    elif len(zona_lead) > 3:
        score += 5 # Especificó una ubicación real

    return min(int(score), 100)

def determinar_etiquetas_pro(score):
    """Sincroniza el score con las traducciones del Dashboard."""
    # Clasificación (Visual)
    if score >= 85: clas = "ALTO VALOR"
    elif score >= 50: clas = "PROSPECTO"
    else: clas = "SEGUIMIENTO"
    
    # Temperatura (Iconografía)
    if score >= 85: temp = "MUY_CALIENTE"
    elif score >= 65: temp = "CALIENTE"
    elif score >= 40: temp = "MEDIO"
    else: temp = "FRIO"
    
    return clas, temp

# --- RUTAS MEJORADAS ---

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
        
        # PROCESAMIENTO CON EL NUEVO MOTOR ELITE
        score_final = motor_calificacion_elite(d)
        clasificacion, temperatura = determinar_etiquetas_pro(score_final)
        
        datos_supabase = {
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "nombre": d["nombre"],
            "telefono": d["telefono"],
            "zona_interes": d["zona_interes"], 
            "presupuesto": d["presupuesto"],
            "clasificacion": clasificacion,
            "score": score_final,
            "temperatura": temperatura,
            "estado": "Nuevo",
            "mensaje": d["mensaje"],
            "vendedor": d["vendedor"]
        }
        
        try:
            supabase.table("leads").insert(datos_supabase).execute()
            return render_template("formulario.html", enviado=True, link_whatsapp=f"https://wa.me/{cliente['whatsapp']}", cliente=cliente, textos=textos)
        except Exception as e:
            return f"Error de conexión: {e}", 500
            
    return render_template("formulario.html", enviado=False, cliente=cliente, textos=textos)

@app.route("/historial/<cliente_id>")
def historial(cliente_id):
    if session.get("cliente") != cliente_id.lower():
        return redirect(url_for('login', cliente_id=cliente_id))
    
    cliente = CLIENTES.get(cliente_id.lower())
    lang = session.get('idioma', 'es')
    textos = DICCIONARIO.get(lang, DICCIONARIO['es'])
    
    # ORDENAMIENTO POR SCORE: Los clientes "cerrables" aparecen primero.
    resultado = supabase.table("leads").select("*").eq("vendedor", cliente_id.lower()).order("score", desc=True).execute()
    
    return render_template("historial.html", leads=resultado.data, cliente=cliente, textos=textos)

# ... (Rutas de login, idioma e index igual) ...
