from flask import Flask, request, render_template, redirect, session, url_for, send_file, jsonify
from supabase import create_client
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import check_password_hash
import os
import re
import json
import cloudinary
import cloudinary.uploader
from datetime import datetime, timedelta
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.units import inch
import config
from traducciones import DICCIONARIO
from email_service import (enviar_email_cliente, notificar_vendedor_lead_nuevo,
                           notificar_vendedor_cliente_marcado, enviar_seguimiento_automatico)
from stats import obtener_stats

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

limiter = Limiter(get_remote_address, app=app, default_limits=[], storage_uri="memory://")

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET")
)

IDIOMA_NOMBRE_A_CODIGO = {
    'español': 'es', 'inglés': 'en', 'ingles': 'en',
    'francés': 'fr', 'frances': 'fr', 'alemán': 'de', 'aleman': 'de',
    'portugués': 'pt', 'portugues': 'pt', 'chino': 'zh',
    'es': 'es', 'en': 'en', 'fr': 'fr', 'de': 'de', 'pt': 'pt', 'zh': 'zh'
}

# --- CARGA DE CLIENTES DESDE SUPABASE ---
def cargar_clientes():
    try:
        resultado = supabase.table("clientes").select("*").eq("activo", True).execute()
        clientes = {}
        for c in resultado.data:
            clientes[c['id']] = c
        return clientes
    except Exception as e:
        print(f"❌ Error cargando clientes: {e}")
        return {}

def get_cliente(cliente_id):
    try:
        resultado = supabase.table("clientes").select("*").eq("id", cliente_id).eq("activo", True).execute()
        if resultado.data:
            return resultado.data[0]
        return None
    except:
        return None

def get_idioma_default(vendedor):
    nombre = vendedor.get('idioma_default', 'español').lower()
    return IDIOMA_NOMBRE_A_CODIGO.get(nombre, 'es')

def verificar_password(password_ingresada, password_guardada):
    if password_guardada.startswith('scrypt:') or password_guardada.startswith('pbkdf2:'):
        return check_password_hash(password_guardada, password_ingresada)
    return password_ingresada == password_guardada

# --- SEGUIMIENTO AUTOMÁTICO ---
def job_seguimiento_automatico():
    print(f"🔄 [{datetime.now().strftime('%Y-%m-%d %H:%M')}] Ejecutando seguimiento automático...")
    try:
        hace_3_dias = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        resultado = supabase.table("leads").select("*") \
            .eq("seguimiento_enviado", False) \
            .not_.is_("email", "null") \
            .not_.ilike("clasificacion", "%CLIENTE%") \
            .lte("fecha", hace_3_dias + " 23:59") \
            .execute()
        leads = resultado.data or []
        print(f"📋 Leads para seguimiento: {len(leads)}")
        for lead in leads:
            email = lead.get("email", "").strip()
            if not email:
                continue
            enviado = enviar_seguimiento_automatico(
                cliente_id=lead.get("vendedor"),
                nombre=lead.get("nombre", ""),
                telefono=lead.get("telefono", ""),
                email_prospecto=email,
                zona=lead.get("zona_interes", ""),
                presupuesto=lead.get("presupuesto", "")
            )
            if enviado:
                supabase.table("leads").update({"seguimiento_enviado": True}) \
                    .eq("id", lead["id"]).execute()
                print(f"✅ Seguimiento enviado a {lead.get('nombre')} ({email})")
    except Exception as e:
        print(f"❌ Error en seguimiento automático: {e}")

# --- VERIFICACIÓN DE SESIÓN ---
@app.before_request
def verificar_sesion():
    rutas_publicas = ['formulario', 'index', 'seleccion_idioma_login', 'static',
                      'login', 'cambiar_idioma', 'cron_seguimiento', 'admin_login']
    if request.endpoint in rutas_publicas:
        return
    if request.endpoint and request.endpoint.startswith('admin'):
        if not session.get('admin'):
            return redirect(url_for('admin_login'))
        return
    if 'cliente' in session:
        login_time = session.get('login_time')
        if login_time:
            if datetime.now() - datetime.fromisoformat(login_time) > timedelta(hours=8):
                cliente_id = session.get('cliente')
                session.clear()
                return redirect(url_for('login', cliente_id=cliente_id or 'roberto'))
        else:
            cliente_id = session.get('cliente')
            session.clear()
            return redirect(url_for('login', cliente_id=cliente_id or 'roberto'))

@app.after_request
def agregar_headers_seguridad(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response

# --- MOTOR DE SCORING ---
def calcular_entropia_mensaje(texto):
    if not texto or len(texto) < 10: return 0
    palabras = texto.lower().split()
    unicas = set(palabras)
    return (len(unicas) / len(palabras)) if palabras else 0

def motor_scoring_global(d):
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
    if score >= 85: return "💎 VIP / INVERSIONISTA", "MUY_CALIENTE"
    elif score >= 65: return "🔥 PROSPECTO A", "CALIENTE"
    elif score >= 40: return "🟡 SEGUIMIENTO B", "MEDIO"
    return "❄️ LEAD FRIO", "FRIO"

def obtener_leads_por_periodo(cliente_id, periodo="todo"):
    try:
        resultado = supabase.table("leads").select("*").eq("vendedor", cliente_id).execute()
        leads = resultado.data
        if not leads: return []
        hoy = datetime.now()
        if periodo == "semana": fecha_limite = hoy - timedelta(days=7)
        elif periodo == "mes": fecha_limite = hoy - timedelta(days=30)
        elif periodo == "año": fecha_limite = hoy - timedelta(days=365)
        else: fecha_limite = datetime(2000, 1, 1)
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
        return leads_filtrados if leads_filtrados else leads
    except Exception as e:
        print(f"Error obteniendo leads: {e}")
        return []

def generar_pdf_leads(cliente_id, periodo="todo", cliente_nombre="", textos=None):
    if textos is None: textos = {}
    try:
        leads = obtener_leads_por_periodo(cliente_id, periodo)
        pdf_buffer = BytesIO()
        doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
        elements = []
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontSize=16,
            textColor=colors.HexColor('#667eea'), spaceAfter=6, alignment=1)
        subtitle_style = ParagraphStyle('CustomSubtitle', parent=styles['Normal'], fontSize=9,
            textColor=colors.HexColor('#666666'), spaceAfter=20, alignment=1)
        titulo_pdf = textos.get('pdf_reporte', 'REPORTE DE LEADS')
        periodo_label = textos.get('pdf_periodo', 'Período')
        fecha_label = textos.get('pdf_fecha', 'Fecha')
        elements.append(Paragraph(f"{titulo_pdf} - {cliente_nombre}", title_style))
        elements.append(Paragraph(f"{periodo_label}: {periodo.upper()} | {fecha_label}: {datetime.now().strftime('%d/%m/%Y %H:%M')}", subtitle_style))
        elements.append(Spacer(1, 0.15*inch))
        col_fecha = textos.get('pdf_col_fecha', 'Fecha')
        col_nombre = textos.get('pdf_col_nombre', 'Nombre')
        col_telefono = textos.get('pdf_col_telefono', 'Telefono')
        col_zona = textos.get('pdf_col_zona', 'Zona')
        col_presupuesto = textos.get('pdf_col_presupuesto', 'Presupuesto')
        col_clasificacion = textos.get('pdf_col_clasificacion', 'Clasificacion')
        col_score = textos.get('pdf_col_score', 'Score')
        col_temperatura = textos.get('pdf_col_temperatura', 'Temperatura')
        data = [[col_fecha, col_nombre, col_telefono, col_zona, col_presupuesto, col_clasificacion, col_score, col_temperatura]]
        for lead in leads:
            data.append([
                str(lead.get("fecha", ""))[:10], str(lead.get("nombre", ""))[:18],
                str(lead.get("telefono", ""))[:12], str(lead.get("zona_interes", ""))[:10],
                str(lead.get("presupuesto", 0))[:12], str(lead.get("clasificacion", ""))[:12],
                str(lead.get("score", 0)), str(lead.get("temperatura", ""))[:10]
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

# ============================================================
# PANEL DE ADMIN
# ============================================================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        admin_pass = os.environ.get("ADMIN_PASSWORD", "admin_diego_2024")
        if password == admin_pass:
            session["admin"] = True
            session["admin_time"] = datetime.now().isoformat()
            return redirect(url_for('admin_panel'))
        error = "Contraseña incorrecta"
    return render_template("admin_login.html", error=error)

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    session.pop("admin_time", None)
    return redirect(url_for('admin_login'))

@app.route("/admin")
def admin_panel():
    if not session.get("admin"):
        return redirect(url_for('admin_login'))
    try:
        resultado = supabase.table("clientes").select("*").order("created_at", desc=True).execute()
        clientes = resultado.data or []
        # Contar leads por cliente
        for c in clientes:
            try:
                leads_r = supabase.table("leads").select("id", count="exact").eq("vendedor", c['id']).execute()
                c['total_leads'] = leads_r.count or 0
            except:
                c['total_leads'] = 0
    except Exception as e:
        clientes = []
        print(f"Error cargando panel admin: {e}")
    return render_template("admin.html", clientes=clientes)

@app.route("/admin/cliente/nuevo", methods=["POST"])
def admin_nuevo_cliente():
    if not session.get("admin"):
        return redirect(url_for('admin_login'))
    try:
        cliente_id = request.form.get("id", "").strip().lower().replace(" ", "_")
        if not cliente_id:
            return redirect(url_for('admin_panel'))
        data = {
            "id": cliente_id,
            "nombre": request.form.get("nombre", "").strip(),
            "email_vendedor": request.form.get("email_vendedor", "").strip(),
            "whatsapp": request.form.get("whatsapp", "").strip(),
            "usuario": request.form.get("usuario", "").strip(),
            "password": request.form.get("password", "").strip(),
            "idioma_default": request.form.get("idioma_default", "español"),
            "color_primario": request.form.get("color_primario", "#667eea"),
            "premium_email": True,
            "email_api_key": request.form.get("email_api_key", "").strip(),
            "activo": True
        }
        supabase.table("clientes").insert(data).execute()
        print(f"✅ Cliente nuevo creado: {cliente_id}")
    except Exception as e:
        print(f"❌ Error creando cliente: {e}")
    return redirect(url_for('admin_panel'))

@app.route("/admin/cliente/editar/<cliente_id>", methods=["POST"])
def admin_editar_cliente(cliente_id):
    if not session.get("admin"):
        return redirect(url_for('admin_login'))
    try:
        data = {
            "nombre": request.form.get("nombre", "").strip(),
            "email_vendedor": request.form.get("email_vendedor", "").strip(),
            "whatsapp": request.form.get("whatsapp", "").strip(),
            "usuario": request.form.get("usuario", "").strip(),
            "idioma_default": request.form.get("idioma_default", "español"),
            "color_primario": request.form.get("color_primario", "#667eea"),
            "email_api_key": request.form.get("email_api_key", "").strip(),
            "activo": request.form.get("activo") == "on"
        }
        nueva_password = request.form.get("password", "").strip()
        if nueva_password:
            data["password"] = nueva_password
        supabase.table("clientes").update(data).eq("id", cliente_id).execute()
        print(f"✅ Cliente editado: {cliente_id}")
    except Exception as e:
        print(f"❌ Error editando cliente: {e}")
    return redirect(url_for('admin_panel'))

@app.route("/admin/cliente/eliminar/<cliente_id>", methods=["POST"])
def admin_eliminar_cliente(cliente_id):
    if not session.get("admin"):
        return redirect(url_for('admin_login'))
    try:
        supabase.table("clientes").update({"activo": False}).eq("id", cliente_id).execute()
        print(f"✅ Cliente desactivado: {cliente_id}")
    except Exception as e:
        print(f"❌ Error desactivando cliente: {e}")
    return redirect(url_for('admin_panel'))

# ============================================================
# RUTAS PRINCIPALES
# ============================================================

@app.route("/cron/seguimiento/<secret_key>", methods=["GET"])
def cron_seguimiento(secret_key):
    clave_esperada = os.environ.get("CRON_SECRET", "seguimiento_secreto_roberto_2024")
    if secret_key != clave_esperada:
        return "No autorizado", 403
    try:
        job_seguimiento_automatico()
        return f"✅ Seguimiento ejecutado: {datetime.now().strftime('%Y-%m-%d %H:%M')}", 200
    except Exception as e:
        return f"❌ Error: {e}", 500

@app.route("/cliente/<cliente_id>")
def seleccion_idioma(cliente_id):
    id_clean = cliente_id.lower()
    vendedor = get_cliente(id_clean)
    if not vendedor: return "Error 403: Acceso denegado.", 403
    lang = session.get('idioma', request.accept_languages.best_match(['es', 'en', 'fr', 'de']) or 'es')
    textos = DICCIONARIO.get(lang, DICCIONARIO['es'])
    return render_template("bienvenida.html", cliente=vendedor, textos=textos)

@app.route("/form/<cliente_id>", methods=["GET","POST"])
def formulario(cliente_id):
    id_clean = cliente_id.lower()
    vendedor = get_cliente(id_clean)
    if not vendedor: return "Error 404: Vendedor no configurado.", 404
    idioma_default = get_idioma_default(vendedor)
    lang = session.get('idioma', idioma_default)
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
        email_prospecto = request.form.get("email", "").strip()
        lead_data = {
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
            **d,
            "clasificacion": clasificacion,
            "score": score_final,
            "temperatura": temperatura,
            "estado": "Nuevo",
            "email": email_prospecto,
            "seguimiento_enviado": False
        }
        try:
            supabase.table("leads").insert(lead_data).execute()
            if email_prospecto:
                enviar_email_cliente(id_clean, d.get("nombre"), email_prospecto)
            notificar_vendedor_lead_nuevo(
                cliente_id=id_clean, nombre=d.get("nombre"), telefono=d.get("telefono"),
                zona=d.get("zona_interes"), presupuesto=d.get("presupuesto"),
                mensaje=d.get("mensaje"), score=score_final, email_prospecto=email_prospecto
            )
            return render_template("formulario.html", enviado=True, textos=textos,
                                   cliente_id=id_clean, whatsapp=vendedor['whatsapp'],
                                   cliente_nombre=vendedor['nombre'], idioma_actual=lang)
        except Exception as e:
            return f"System Synch Error: {e}", 500
    return render_template("formulario.html", enviado=False, cliente_id=id_clean,
                           textos=textos, cliente_nombre=vendedor['nombre'], idioma_actual=lang)

@app.route("/historial/<cliente_id>")
def historial(cliente_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean:
        return redirect(url_for('login', cliente_id=id_clean))
    vendedor = get_cliente(id_clean)
    idioma_default = get_idioma_default(vendedor)
    idioma = session.get('idioma', idioma_default)
    textos = DICCIONARIO.get(idioma, DICCIONARIO['es'])
    query = supabase.table("leads").select("*").eq("vendedor", id_clean)
    q = request.args.get('q', '')
    if q: query = query.ilike("nombre", f"%{q}%")
    resultado = query.order("score", desc=True).execute()
    return render_template("historial.html", leads=resultado.data, cliente=vendedor, textos=textos, idioma_actual=idioma)

@app.route("/inventario/<cliente_id>", methods=["GET"])
def inventario(cliente_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean:
        return redirect(url_for('login', cliente_id=id_clean))
    vendedor = get_cliente(id_clean)
    if not vendedor: return "Error 404: Vendedor no encontrado.", 404
    idioma = session.get('idioma', get_idioma_default(vendedor))
    textos = DICCIONARIO.get(idioma, DICCIONARIO['es'])
    try:
        resultado = supabase.table("propiedades").select("*").eq("vendedor", id_clean).order("created_at", desc=True).execute()
        propiedades = resultado.data or []
        return render_template("inventario.html", cliente_id=id_clean,
                               cliente_nombre=vendedor['nombre'],
                               propiedades_json=json.dumps(propiedades),
                               textos=textos, idioma_actual=idioma)
    except Exception as e:
        return render_template("inventario.html", cliente_id=id_clean,
                               cliente_nombre=vendedor['nombre'], propiedades_json='[]',
                               textos=textos, idioma_actual=idioma)

@app.route("/propiedades/<cliente_id>", methods=["GET"])
def inventario_publico(cliente_id):
    id_clean = cliente_id.lower()
    vendedor = get_cliente(id_clean)
    if not vendedor: return "Error 404: No encontrado.", 404
    try:
        resultado = supabase.table("propiedades").select("*").eq("vendedor", id_clean).eq("estado", "disponible").order("created_at", desc=True).execute()
        propiedades = resultado.data or []
        return render_template("inventario_publico.html", cliente_id=id_clean,
                               cliente_nombre=vendedor['nombre'], whatsapp=vendedor['whatsapp'],
                               propiedades_json=json.dumps(propiedades))
    except Exception as e:
        return f"Error: {e}", 500

@app.route("/agregar_propiedad/<cliente_id>", methods=["POST"])
def agregar_propiedad(cliente_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean: return "Error 403: No autorizado.", 403
    vendedor = get_cliente(id_clean)
    if not vendedor: return "Error 404: Vendedor no encontrado.", 404
    try:
        imagenes_urls = []
        archivos = request.files.getlist("imagenes")[:5]
        for archivo in archivos:
            if archivo and archivo.filename:
                resultado = cloudinary.uploader.upload(archivo,
                    folder=f"bot_inmobiliaria/{id_clean}",
                    transformation=[{"width": 1200, "height": 900, "crop": "limit", "quality": "auto"}])
                imagenes_urls.append(resultado["secure_url"])
        habitaciones = request.form.get("habitaciones", "").strip()
        banos = request.form.get("banos", "").strip()
        metros2 = request.form.get("metros2", "").strip()
        propiedad_data = {
            "titulo": request.form.get("titulo").strip(),
            "descripcion": request.form.get("descripcion", "").strip(),
            "precio": float(request.form.get("precio", 0)),
            "ubicacion": request.form.get("ubicacion").strip(),
            "habitaciones": int(habitaciones) if habitaciones else None,
            "banos": float(banos) if banos else None,
            "metros2": float(metros2) if metros2 else None,
            "imagen_url": json.dumps(imagenes_urls),
            "vendedor": id_clean, "estado": "disponible"
        }
        supabase.table("propiedades").insert(propiedad_data).execute()
        return redirect(url_for('inventario', cliente_id=id_clean))
    except Exception as e:
        return f"Error: {e}", 500

@app.route("/editar_propiedad/<cliente_id>/<int:prop_id>", methods=["POST"])
def editar_propiedad(cliente_id, prop_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean: return "Error 403: No autorizado.", 403
    vendedor = get_cliente(id_clean)
    if not vendedor: return "Error 404: Vendedor no encontrado.", 404
    try:
        prop_actual = supabase.table("propiedades").select("imagen_url").eq("id", prop_id).execute()
        imagenes_existentes = []
        if prop_actual.data:
            try:
                imagenes_existentes = json.loads(prop_actual.data[0].get("imagen_url", "[]"))
                if not isinstance(imagenes_existentes, list): imagenes_existentes = []
            except: pass
        espacio_disponible = max(0, 5 - len(imagenes_existentes))
        archivos = request.files.getlist("imagenes")[:espacio_disponible]
        for archivo in archivos:
            if archivo and archivo.filename:
                resultado = cloudinary.uploader.upload(archivo,
                    folder=f"bot_inmobiliaria/{id_clean}",
                    transformation=[{"width": 1200, "height": 900, "crop": "limit", "quality": "auto"}])
                imagenes_existentes.append(resultado["secure_url"])
        habitaciones = request.form.get("habitaciones", "").strip()
        banos = request.form.get("banos", "").strip()
        metros2 = request.form.get("metros2", "").strip()
        update_data = {
            "titulo": request.form.get("titulo").strip(),
            "descripcion": request.form.get("descripcion", "").strip(),
            "precio": float(request.form.get("precio", 0)),
            "ubicacion": request.form.get("ubicacion").strip(),
            "habitaciones": int(habitaciones) if habitaciones else None,
            "banos": float(banos) if banos else None,
            "metros2": float(metros2) if metros2 else None,
            "imagen_url": json.dumps(imagenes_existentes)
        }
        supabase.table("propiedades").update(update_data).eq("id", prop_id).eq("vendedor", id_clean).execute()
        return redirect(url_for('inventario', cliente_id=id_clean))
    except Exception as e:
        return f"Error: {e}", 500

@app.route("/eliminar_propiedad/<cliente_id>/<int:prop_id>", methods=["POST"])
def eliminar_propiedad(cliente_id, prop_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean: return "Error 403: No autorizado.", 403
    vendedor = get_cliente(id_clean)
    if not vendedor: return "Error 404: Vendedor no encontrado.", 404
    try:
        supabase.table("propiedades").delete().eq("id", prop_id).eq("vendedor", id_clean).execute()
        return redirect(url_for('inventario', cliente_id=id_clean))
    except Exception as e:
        return f"Error: {e}", 500

@app.route("/herramientas/<cliente_id>")
def herramientas(cliente_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean:
        return redirect(url_for('login', cliente_id=id_clean))
    vendedor = get_cliente(id_clean)
    if not vendedor: return "Error 404: Vendedor no encontrado.", 404
    idioma = session.get('idioma', get_idioma_default(vendedor))
    textos = DICCIONARIO.get(idioma, DICCIONARIO['es'])
    return render_template("herramientas.html", cliente=vendedor, textos=textos, idioma_actual=idioma)

@app.route("/stats/<cliente_id>")
def stats(cliente_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean:
        return redirect(url_for('login', cliente_id=id_clean))
    vendedor = get_cliente(id_clean)
    if not vendedor: return "Error 404: Vendedor no encontrado.", 404
    periodo = request.args.get('periodo', 'todo')
    stats_data = obtener_stats(id_clean, periodo)
    if stats_data is None: return "Error al obtener estadísticas.", 500
    idioma = session.get('idioma', get_idioma_default(vendedor))
    textos = DICCIONARIO.get(idioma, DICCIONARIO['es'])
    return render_template("stats.html", cliente=vendedor, stats=stats_data, textos=textos, idioma_actual=idioma)

@app.route("/descargar_pdf/<cliente_id>", methods=["GET"])
def descargar_pdf(cliente_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean: return "Error 403: No autorizado.", 403
    vendedor = get_cliente(id_clean)
    if not vendedor: return "Error 404: Vendedor no encontrado.", 404
    periodo = request.args.get('periodo', 'todo')
    idioma = session.get('idioma', get_idioma_default(vendedor))
    textos = DICCIONARIO.get(idioma, DICCIONARIO['es'])
    try:
        pdf_bytes = generar_pdf_leads(id_clean, periodo, vendedor['nombre'], textos=textos)
        if pdf_bytes is None: return "Error al generar PDF.", 500
        pdf_bytes.seek(0)
        nombre_archivo = f"Leads_{vendedor['nombre']}_{periodo}_{datetime.now().strftime('%Y%m%d')}.pdf"
        return send_file(pdf_bytes, mimetype="application/pdf", as_attachment=True, download_name=nombre_archivo)
    except Exception as e:
        return f"Error: {e}", 500

@app.route("/marcar_cliente/<cliente_id>/<int:lead_id>", methods=["POST"])
def marcar_cliente(cliente_id, lead_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean: return "Error 403: No autorizado.", 403
    vendedor = get_cliente(id_clean)
    if not vendedor: return "Error 404: Vendedor no encontrado.", 404
    try:
        resultado = supabase.table("leads").select("*").eq("id", lead_id).execute()
        if resultado.data:
            lead = resultado.data[0]
            supabase.table("leads").update({
                "temperatura": "MUY_CALIENTE", "clasificacion": "💎 CLIENTE",
                "seguimiento_enviado": True
            }).eq("id", lead_id).execute()
            notificar_vendedor_cliente_marcado(
                cliente_id=id_clean, nombre=lead.get("nombre"), telefono=lead.get("telefono"),
                zona=lead.get("zona_interes"), presupuesto=lead.get("presupuesto")
            )
        return redirect(url_for('historial', cliente_id=id_clean))
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route("/desmarcar_cliente/<cliente_id>/<int:lead_id>", methods=["POST"])
def desmarcar_cliente(cliente_id, lead_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean: return "Error 403: No autorizado.", 403
    vendedor = get_cliente(id_clean)
    if not vendedor: return "Error 404: Vendedor no encontrado.", 404
    try:
        resultado = supabase.table("leads").select("*").eq("id", lead_id).execute()
        if not resultado.data: return "Lead no encontrado.", 404
        lead = resultado.data[0]
        lead_data = {
            "nombre": lead.get("nombre", ""), "telefono": lead.get("telefono", ""),
            "zona_interes": lead.get("zona_interes", ""), "presupuesto": lead.get("presupuesto", ""),
            "mensaje": lead.get("mensaje", "")
        }
        score_nuevo = motor_scoring_global(lead_data)
        clasificacion_nueva, temperatura_nueva = calificar_lead_profesional(score_nuevo)
        supabase.table("leads").update({
            "score": score_nuevo, "clasificacion": clasificacion_nueva,
            "temperatura": temperatura_nueva, "seguimiento_enviado": False
        }).eq("id", lead_id).execute()
        return redirect(url_for('historial', cliente_id=id_clean))
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route("/access/<cliente_id>")
def seleccion_idioma_login(cliente_id):
    id_clean = cliente_id.lower()
    vendedor = get_cliente(id_clean)
    if not vendedor: return "Error 403", 403
    return render_template("bienvenida_login.html", cliente=vendedor)

@app.route("/login/<cliente_id>", methods=["GET","POST"])
@limiter.limit("5 per minute")
def login(cliente_id):
    id_clean = cliente_id.lower()
    vendedor = get_cliente(id_clean)
    if not vendedor: return "Error 404", 404
    lang = session.get('idioma', get_idioma_default(vendedor))
    textos = DICCIONARIO.get(lang, DICCIONARIO['es'])
    if request.method == "POST":
        if request.form.get("usuario") == vendedor["usuario"] and \
           verificar_password(request.form.get("password"), vendedor["password"]):
            session["cliente"] = id_clean
            session["login_time"] = datetime.now().isoformat()
            return redirect(url_for('seleccion_idioma', cliente_id=id_clean))
        print(f"⚠️ Login fallido para {id_clean} desde {get_remote_address()}")
        return render_template("login.html", error="Credenciales Invalidas", cliente=vendedor, textos=textos)
    return render_template("login.html", cliente=vendedor, textos=textos)

@app.route("/logout/<cliente_id>")
def logout(cliente_id):
    session.clear()
    return redirect(url_for('login', cliente_id=cliente_id.lower()))

@app.route("/idioma/<lang>/<proximo>/<cliente_id>")
def cambiar_idioma(lang, proximo, cliente_id):
    session['idioma'] = lang
    return redirect(url_for(proximo, cliente_id=cliente_id.lower()))

@app.route("/")
def index():
    return "PropTech Global Engine V4.0 [Active Mode] 🌐🚀"

@app.errorhandler(429)
def demasiados_intentos(e):
    return """
    <html><body style='font-family:sans-serif;text-align:center;padding:50px;background:#f8f9fa'>
    <h2 style='color:#e74c3c'>⛔ Demasiados intentos</h2>
    <p>Has excedido el límite de intentos de acceso.</p>
    <p>Por favor espera 1 minuto antes de intentar de nuevo.</p>
    </body></html>
    """, 429

if __name__ == "__main__":
    app.run(debug=False)
