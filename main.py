from flask import Flask, request, render_template, redirect, session, url_for, send_file, jsonify
from supabase import create_client
import os
import re
import math
import json
from datetime import datetime, timedelta
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.units import inch
import config
from config_clientes import CLIENTES
from traducciones import DICCIONARIO
from email_service import enviar_email_cliente, notificar_vendedor_lead_nuevo, notificar_vendedor_cliente_marcado
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
    """Genera un PDF profesional con los leads del período seleccionado."""
    try:
        leads = obtener_leads_por_periodo(cliente_id, periodo)
        
        pdf_buffer = BytesIO()
        doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
        
        elements = []
        styles = getSampleStyleSheet()
        
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            textColor=colors.HexColor('#667eea'),
            spaceAfter=6,
            alignment=1
        )
        
        subtitle_style = ParagraphStyle(
            'CustomSubtitle',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#666666'),
            spaceAfter=20,
            alignment=1
        )
        
        elements.append(Paragraph(f"REPORTE DE LEADS - {cliente_nombre}", title_style))
        elements.append(Paragraph(f"Periodo: {periodo.upper()} | Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}", subtitle_style))
        elements.append(Spacer(1, 0.15*inch))
        
        data = [["Fecha", "Nombre", "Telefono", "Zona", "Presupuesto", "Clasificacion", "Score", "Temperatura"]]
        
        for lead in leads:
            data.append([
                str(lead.get("fecha", ""))[:10],
                str(lead.get("nombre", ""))[:18],
                str(lead.get("telefono", ""))[:12],
                str(lead.get("zona_interes", ""))[:10],
                str(lead.get("presupuesto", 0))[:12],
                str(lead.get("clasificacion", ""))[:12],
                str(lead.get("score", 0)),
                str(lead.get("temperatura", ""))[:10]
            ])
        
        table = Table(data, colWidths=[0.85*inch, 1.1*inch, 0.95*inch, 0.85*inch, 1.1*inch, 1.15*inch, 0.55*inch, 0.9*inch])
        
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (1, 1), (1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#cccccc')),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ]))
        
        elements.append(table)
        doc.build(elements)
        
        pdf_buffer.seek(0)
        return pdf_buffer
    
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
                enviar_email_cliente(id_clean, d.get("nombre"), email_cliente)
            
            # ✨ NOTIFICAR AL VENDEDOR DEL NUEVO LEAD
            notificar_vendedor_lead_nuevo(
                cliente_id=id_clean,
                nombre=d.get("nombre"),
                telefono=d.get("telefono"),
                zona=d.get("zona_interes"),
                presupuesto=d.get("presupuesto"),
                mensaje=d.get("mensaje"),
                score=score_final
            )
            
            return render_template("formulario.html", enviado=True, textos=textos, cliente_id=id_clean, whatsapp=vendedor['whatsapp'], cliente_nombre=vendedor['nombre'])
        except Exception as e:
            return f"System Synch Error: {e}", 500

    return render_template("formulario.html", enviado=False, cliente_id=id_clean, textos=textos, cliente_nombre=vendedor['nombre'])

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

@app.route("/inventario/<cliente_id>", methods=["GET"])
def inventario(cliente_id):
    """Muestra el inventario de propiedades del vendedor."""
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean:
        return redirect(url_for('login', cliente_id=id_clean))
    
    vendedor = CLIENTES.get(id_clean)
    if not vendedor:
        return "Error 404: Vendedor no encontrado.", 404
    
    try:
        resultado = supabase.table("propiedades").select("*").eq("vendedor", id_clean).order("created_at", desc=True).execute()
        propiedades = resultado.data or []
        
        # Convertir a JSON para pasar a JavaScript
        propiedades_json = json.dumps(propiedades)
        
        return render_template("inventario.html", 
                             cliente_id=id_clean, 
                             cliente_nombre=vendedor['nombre'],
                             propiedades_json=propiedades_json)
    
    except Exception as e:
        print(f"Error cargando inventario: {e}")
        return render_template("inventario.html", 
                             cliente_id=id_clean, 
                             cliente_nombre=vendedor['nombre'],
                             propiedades_json='[]')

@app.route("/agregar_propiedad/<cliente_id>", methods=["POST"])
def agregar_propiedad(cliente_id):
    """Agrega una nueva propiedad al inventario."""
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean:
        return "Error 403: No autorizado.", 403
    
    vendedor = CLIENTES.get(id_clean)
    if not vendedor:
        return "Error 404: Vendedor no encontrado.", 404
    
    try:
        propiedad_data = {
            "titulo": request.form.get("titulo").strip(),
            "descripcion": request.form.get("descripcion", "").strip(),
            "precio": float(request.form.get("precio", 0)),
            "ubicacion": request.form.get("ubicacion").strip(),
            "imagen_url": request.form.get("imagen_url", "").strip(),
            "vendedor": id_clean,
            "estado": "disponible"
        }
        
        supabase.table("propiedades").insert(propiedad_data).execute()
        print(f"✅ Propiedad agregada: {propiedad_data['titulo']}")
        
        return redirect(url_for('inventario', cliente_id=id_clean))
    
    except Exception as e:
        print(f"Error agregando propiedad: {e}")
        return f"Error: {e}", 500

@app.route("/eliminar_propiedad/<cliente_id>/<int:prop_id>", methods=["POST"])
def eliminar_propiedad(cliente_id, prop_id):
    """Elimina una propiedad del inventario."""
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean:
        return "Error 403: No autorizado.", 403
    
    vendedor = CLIENTES.get(id_clean)
    if not vendedor:
        return "Error 404: Vendedor no encontrado.", 404
    
    try:
        supabase.table("propiedades").delete().eq("id", prop_id).eq("vendedor", id_clean).execute()
        print(f"✅ Propiedad {prop_id} eliminada")
        
        return redirect(url_for('inventario', cliente_id=id_clean))
    
    except Exception as e:
        print(f"Error eliminando propiedad: {e}")
        return f"Error: {e}", 500

@app.route("/herramientas/<cliente_id>")
def herramientas(cliente_id):
    """Muestra las calculadoras inmobiliarias."""
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean:
        return redirect(url_for('login', cliente_id=id_clean))
    
    vendedor = CLIENTES.get(id_clean)
    if not vendedor:
        return "Error 404: Vendedor no encontrado.", 404
    
    textos = DICCIONARIO.get(session.get('idioma', 'es'), DICCIONARIO['es'])
    
    return render_template("herramientas.html", cliente=vendedor, textos=textos)

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
        
        # Obtener datos del lead para la notificación
        resultado = supabase.table("leads").select("*").eq("id", lead_id).execute()
        if resultado.data:
            lead = resultado.data[0]
            
            supabase.table("leads").update({
                "temperatura": "MUY_CALIENTE",
                "clasificacion": "💎 CLIENTE"
            }).eq("id", lead_id).execute()
            
            # ✨ NOTIFICAR AL VENDEDOR QUE SE MARCÓ UN CLIENTE
            notificar_vendedor_cliente_marcado(
                cliente_id=id_clean,
                nombre=lead.get("nombre"),
                telefono=lead.get("telefono"),
                zona=lead.get("zona_interes"),
                presupuesto=lead.get("presupuesto")
            )
            
            print(f"Lead {lead_id} marcado como cliente exitosamente")
        
        return redirect(url_for('historial', cliente_id=id_clean))
    
    except Exception as e:
        print(f"Error al marcar cliente: {str(e)}")
        return f"Error: {str(e)}", 500

@app.route("/desmarcar_cliente/<cliente_id>/<int:lead_id>", methods=["POST"])
def desmarcar_cliente(cliente_id, lead_id):
    """Desmarca un lead como CLIENTE (revierte a clasificación original)."""
    id_clean = cliente_id.lower()
    
    if session.get("cliente") != id_clean:
        return "Error 403: No autorizado.", 403
    
    vendedor = CLIENTES.get(id_clean)
    if not vendedor:
        return "Error 404: Vendedor no encontrado.", 404
    
    try:
        print(f"Desmarcando lead {lead_id}...")
        
        resultado = supabase.table("leads").select("*").eq("id", lead_id).execute()
        if not resultado.data:
            return "Lead no encontrado.", 404
        
        lead = resultado.data[0]
        
        lead_data = {
            "nombre": lead.get("nombre", ""),
            "telefono": lead.get("telefono", ""),
            "zona_interes": lead.get("zona_interes", ""),
            "presupuesto": lead.get("presupuesto", ""),
            "mensaje": lead.get("mensaje", "")
        }
        
        score_nuevo = motor_scoring_global(lead_data)
        clasificacion_nueva, temperatura_nueva = calificar_lead_profesional(score_nuevo)
        
        supabase.table("leads").update({
            "score": score_nuevo,
            "clasificacion": clasificacion_nueva,
            "temperatura": temperatura_nueva
        }).eq("id", lead_id).execute()
        
        print(f"Lead {lead_id} desmarcado exitosamente")
        return redirect(url_for('historial', cliente_id=id_clean))
    
    except Exception as e:
        print(f"Error al desmarcar cliente: {str(e)}")
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
            return redirect(url_for('seleccion_idioma', cliente_id=id_clean))
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
