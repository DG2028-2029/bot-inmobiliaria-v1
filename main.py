from flask import Flask, request, render_template, redirect, session, url_for, send_file
from supabase import create_client
import os
import re
import math
from datetime import datetime, timedelta
from io import BytesIO
from fpdf import FPDF
import config
from config_clientes import CLIENTES
from traducciones import DICCIONARIO
from email_service import enviar_email_lead
from stats import obtener_stats

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
    
    try:
        p_val = float(re.sub(r'[^\d.]', '', str(d.get("presupuesto", 0))))
        if p_val >= 1000000: score += 30
        elif p_val >= 500000: score += 25
        elif p_val >= 150000: score += 15
        elif p_val > 0: score += 5
    except: pass

    triggers = [
        "comprar", "invertir", "contado", "urgente", "pago", "visita", "ahora",
        "buy", "invest", "cash", "closing", "ready", "now", "tour",
        "acheter", "maintenant", "urgent", "viste", "rdv", "paiement",
        "kaufen", "jetzt", "sofort", "dringend", "termin",
        "購買", "現在", "緊急", "預約", "現金", "投資"
    ]
    
    hits = sum(1 for t in triggers if t in msg_l)
    if hits >= 2: score += 40
    elif hits == 1: score += 25
    elif len(msg.split()) > 15: score += 15

    entropia = calcular_entropia_mensaje(msg)
    if entropia > 0.8 and len(msg) > 100: score += 20
    elif len(msg) > 50: score += 10
    
    if len(d.get("nombre", "").split()) >= 2: score += 5

    keywords_premium = ["lujo", "luxury", "penthouse", "roi", "rentabilidad", "yield", "exclusive"]
    if any(k in msg_l or k in zona for k in keywords_premium):
        score += 10

    return min(int(score), 100)

def calificar_lead_profesional(score):
    """Asignación de estatus de grado CRM."""
    if score >= 85: return "💎 VIP / INVERSIONISTA", "MUY_CALIENTE"
    elif score >= 65: return "🔥 PROSPECTO A", "CALIENTE"
    elif score >= 40: return "🟡 SEGUIMIENTO B", "MEDIO"
    return "❄️ LEAD FRIO", "FRIO"

def obtener_leads_por_periodo(cliente_id, periodo="todo"):
    """Obtiene los leads del cliente filtrados por período."""
    try:
        resultado = supabase.table("leads").select("*").eq("vendedor", cliente_id).execute()
        leads = resultado.data
        
        if not leads:
            return []
        
        hoy = datetime.now()
        fecha_limite = hoy
        
        if periodo == "semana":
            fecha_limite = hoy - timedelta(days=7)
        elif periodo == "mes":
            fecha_limite = hoy - timedelta(days=30)
        elif periodo == "año":
            fecha_limite = hoy - timedelta(days=365)
        elif periodo == "todo":
            fecha_limite = datetime(2000, 1, 1)
        
        leads_filtrados = []
        for lead in leads:
            fecha_str = lead.get("fecha", "")
            if fecha_str:
                try:
                    fecha = datetime.strptime(fecha_str.split(" ")[0], "%Y-%m-%d")
                    if fecha >= fecha_limite:
                        leads_filtrados.append(lead)
                except:
                    leads_filtrados.append(lead)
        
        if not leads_filtrados:
            leads_filtrados = leads
        
        return leads_filtrados
    except Exception as e:
        print(f"Error obteniendo leads: {e}")
        return []

def generar_pdf_leads(cliente_id, periodo="todo", cliente_nombre=""):
    """Genera un PDF con los leads del período seleccionado."""
    try:
        leads = obtener_leads_por_periodo(cliente_id, periodo)
        
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", "B", 14)
        pdf.cell(0, 10, f"Reporte de Leads - {cliente_nombre}", 0, 1, "C")
        
        pdf.set_font("Arial", "I", 9)
        pdf.cell(0, 8, f"Periodo: {periodo} | Fecha: {datetime.now().strftime('%d/%m/%Y')}", 0, 1, "C")
        pdf.ln(5)
        
        pdf.set_font("Arial", "B", 8)
        col_widths = [20, 20, 18, 18, 25, 25, 12, 15]
        headers = ["Fecha", "Nombre", "Tel", "Zona", "Presupuesto", "Clasificacion", "Score", "Temp"]
        
        for i, header in enumerate(headers):
            pdf.cell(col_widths[i], 7, header, 1, 0, "C")
        pdf.ln()
        
        pdf.set_font("Arial", "", 7)
        for lead in leads:
            pdf.cell(col_widths[0], 6, str(lead.get("fecha", ""))[:10], 1, 0, "C")
            pdf.cell(col_widths[1], 6, str(lead.get("nombre", ""))[:12], 1, 0, "L")
            pdf.cell(col_widths[2], 6, str(lead.get("telefono", ""))[:10], 1, 0, "C")
            pdf.cell(col_widths[3], 6, str(lead.get("zona_interes", ""))[:8], 1, 0, "C")
            pdf.cell(col_widths[4], 6, str(lead.get("presupuesto", 0))[:15], 1, 0, "R")
            pdf.cell(col_widths[5], 6, str(lead.get("clasificacion", ""))[:12], 1, 0, "C")
            pdf.cell(col_widths[6], 6, str(lead.get("score", 0)), 1, 0, "C")
            pdf.cell(col_widths[7], 6, str(lead.get("temperatura", ""))[:8], 1, 0, "C")
            pdf.ln()
        
        pdf_bytes = BytesIO(pdf.output())
        return pdf_bytes
    
    except Exception as e:
        print(f"Error generando PDF: {str(e)}")
        return None

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
            
            email_cliente = request.form.get("email", "").strip()
            if email_cliente:
                enviar_email_lead(id_clean, d.get("nombre"), email_cliente)
            
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
    
    q = request.args.get('q', '')
    if q: query = query.ilike("nombre", f"%{q}%")
    
    resultado = query.order("score", desc=True).execute()
    return render_template("historial.html", leads=resultado.data, cliente=vendedor, textos=textos)

@app.route("/stats/<cliente_id>")
def stats(cliente_id):
    """Muestra gráficos y estadísticas del cliente."""
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean:
        return redirect(url_for('login', cliente_id=id_clean))
    
    vendedor = CLIENTES.get(id_clean)
    if not vendedor:
        return "Error 404: Vendedor no encontrado.", 404
    
    periodo = request.args.get('periodo', 'todo')
    stats_data = obtener_stats(id_clean, periodo)
    
    if stats_data is None:
        return "Error al obtener estadísticas.", 500
    
    return render_template("stats.html", cliente=vendedor, stats=stats_data)

@app.route("/descargar_pdf/<cliente_id>", methods=["GET"])
def descargar_pdf(cliente_id):
    """Descarga PDF con leads filtrados por período."""
    id_clean = cliente_id.lower()
    
    if session.get("cliente") != id_clean:
        return "Error 403: No autorizado.", 403
    
    vendedor = CLIENTES.get(id_clean)
    if not vendedor:
        return "Error 404: Vendedor no encontrado.", 404
    
    periodo = request.args.get('periodo', 'todo')
    
    try:
        pdf_bytes = generar_pdf_leads(id_clean, periodo, vendedor['nombre'])
        
        if pdf_bytes is None:
            return "Error al generar PDF.", 500
        
        pdf_bytes.seek(0)
        nombre_archivo = f"Leads_{vendedor['nombre']}_{periodo}_{datetime.now().strftime('%Y%m%d')}.pdf"
        
        return send_file(
            pdf_bytes,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=nombre_archivo
        )
    
    except Exception as e:
        print(f"Error descargando PDF: {e}")
        return f"Error: {e}", 500

@app.route("/marcar_cliente/<cliente_id>/<int:lead_id>", methods=["POST"])
def marcar_cliente(cliente_id, lead_id):
    """Marca un lead como CLIENTE manualmente."""
    id_clean = cliente_id.lower()
    
    if session.get("cliente") != id_clean:
        return "Error 403: No autorizado.", 403
    
    vendedor = CLIENTES.get(id_clean)
    if not vendedor:
        return "Error 404: Vendedor no encontrado.", 404
    
    try:
        print(f"Marcando lead {lead_id} como cliente...")
        
        supabase.table("leads").update({
            "temperatura": "MUY_CALIENTE",
            "clasificacion": "💎 CLIENTE"
        }).eq("id", lead_id).execute()
        
        print(f"Lead {lead_id} marcado como cliente exitosamente")
        return redirect(url_for('historial', cliente_id=id_clean))
    
    except Exception as e:
        print(f"Error al marcar cliente: {str(e)}")
        return f"Error: {str(e)}", 500

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
