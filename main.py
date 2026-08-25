from flask import Flask, request, render_template, redirect, session, url_for, send_file, jsonify, abort
from supabase import create_client
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import check_password_hash, generate_password_hash
import os
import re
import json
import urllib.request
import time
import secrets
import cloudinary
import cloudinary.uploader
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.units import inch
import config
from traducciones import DICCIONARIO
from paises import PAISES_TIMEZONE
from reporte_semanal import generar_resumen_semanal
from email_service import (enviar_email_cliente, notificar_vendedor_lead_nuevo,
                           notificar_vendedor_cliente_marcado, enviar_seguimiento_automatico,
                           enviar_email_reset_password, enviar_reporte_semanal)
from stats import obtener_stats

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

# ============================================================
# ✅ SEGURIDAD — COOKIES Y SESIONES
# ============================================================
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') != 'development'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20 MB máximo por request

limiter = Limiter(get_remote_address, app=app, default_limits=[], storage_uri="memory://")

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET")
)

# ============================================================
# ✅ TIPOS DE ARCHIVO PERMITIDOS (server-side)
# ============================================================
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp', 'gif'}
ALLOWED_MIMETYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
MAX_FILE_SIZE_MB = 8

def archivo_permitido(archivo):
    """Valida extensión Y magic bytes del archivo."""
    if not archivo or not archivo.filename:
        return False
    ext = archivo.filename.rsplit('.', 1)[-1].lower() if '.' in archivo.filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        return False
    header = archivo.read(12)
    archivo.seek(0)
    magic = {
        b'\xff\xd8\xff': 'jpeg',
        b'\x89PNG': 'png',
        b'RIFF': 'webp',
        b'GIF8': 'gif',
        b'GIF9': 'gif',
    }
    for sig, tipo in magic.items():
        if header.startswith(sig):
            return True
    return False

def limpiar_telefono(tel):
    """Limpia el teléfono para usar en URLs de WhatsApp."""
    if not tel:
        return ''
    return re.sub(r'[^\d+]', '', str(tel)).lstrip('+')

# ============================================================
# ✅ CSRF PROTECTION
# ============================================================
def generar_csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']

def verificar_csrf():
    token_form = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    token_session = session.get('csrf_token')
    if not token_form or not token_session or not secrets.compare_digest(token_form, token_session):
        log_accion('CSRF_FAIL', request.endpoint, get_remote_address())
        abort(403)

app.jinja_env.globals['csrf_token'] = generar_csrf_token

# ============================================================
# ✅ LOGS DE ACCIONES CRÍTICAS
# ============================================================
def log_accion(accion, detalle='', ip='', cliente_id=''):
    try:
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[LOG] {ts} | {accion} | cliente={cliente_id} | ip={ip} | {detalle}")
    except:
        pass

IDIOMA_NOMBRE_A_CODIGO = {
    'español': 'es', 'inglés': 'en', 'ingles': 'en',
    'francés': 'fr', 'frances': 'fr', 'alemán': 'de', 'aleman': 'de',
    'portugués': 'pt', 'portugues': 'pt', 'chino': 'zh',
    'es': 'es', 'en': 'en', 'fr': 'fr', 'de': 'de', 'pt': 'pt', 'zh': 'zh'
}

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
    if not password_guardada or not password_ingresada:
        return False
    if password_guardada.startswith('scrypt:') or password_guardada.startswith('pbkdf2:'):
        return check_password_hash(password_guardada, password_ingresada)
    return secrets.compare_digest(password_ingresada, password_guardada)

def es_dueno():
    return session.get('cliente') and not session.get('asesor_id')

def get_asesores_de_cliente(cliente_id):
    try:
        resultado = supabase.table("asesores").select("*").eq("cliente_id", cliente_id).execute()
        asesores = resultado.data or []
        for a in asesores:
            v = a.get('activo', False)
            if isinstance(v, bool):
                a['activo'] = v
            elif isinstance(v, str):
                a['activo'] = v.lower() in ('true', '1', 'yes')
            else:
                a['activo'] = bool(v)
        return asesores
    except:
        return []

# ============================================================
# ✅ MATCHING AUTOMÁTICO LEADS ↔ PROPIEDADES
# ============================================================
def buscar_leads_matching(propiedad, leads):
    matches = []
    precio_prop = float(propiedad.get('precio', 0) or 0)
    ubicacion_prop = (propiedad.get('ubicacion', '') or '').lower()
    palabras_ubicacion = [w for w in re.split(r'[\s,.-]+', ubicacion_prop) if len(w) > 2]

    for lead in leads:
        clasificacion = lead.get('clasificacion', '')
        if 'CLIENTE' in clasificacion:
            continue
        score_match = 0
        zona_lead = (lead.get('zona_interes', '') or '').lower()
        if zona_lead and ubicacion_prop:
            palabras_zona = [w for w in re.split(r'[\s,.-]+', zona_lead) if len(w) > 2]
            for palabra in palabras_zona:
                if palabra in ubicacion_prop:
                    score_match += 40
                    break
            for palabra in palabras_ubicacion:
                if palabra in zona_lead:
                    score_match += 30
                    break
        try:
            presupuesto_lead = float(re.sub(r'[^\d.]', '', str(lead.get('presupuesto', 0) or 0)))
            if presupuesto_lead > 0 and precio_prop > 0:
                ratio = precio_prop / presupuesto_lead
                if 0.7 <= ratio <= 1.0:
                    score_match += 50
                elif 1.0 < ratio <= 1.2:
                    score_match += 30
                elif 0.5 <= ratio < 0.7:
                    score_match += 20
        except:
            pass
        if score_match >= 30:
            lead['score_match'] = score_match
            matches.append(lead)

    matches.sort(key=lambda x: (x.get('score_match', 0), x.get('score', 0)), reverse=True)
    return matches[:10]

@app.route("/matching/<cliente_id>/<int:prop_id>")
def matching_propiedad(cliente_id, prop_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean:
        return jsonify({"ok": False, "error": "No autorizado"}), 403
    try:
        prop_r = supabase.table("propiedades").select("*").eq("id", prop_id).eq("vendedor", id_clean).execute()
        if not prop_r.data:
            return jsonify({"ok": False, "error": "Propiedad no encontrada"}), 404
        propiedad = prop_r.data[0]
        leads_r = supabase.table("leads").select("*").eq("vendedor", id_clean).execute()
        leads = leads_r.data or []
        matches = buscar_leads_matching(propiedad, leads)
        vendedor = get_cliente(id_clean)
        wa = vendedor.get('whatsapp', '') if vendedor else ''
        return jsonify({
            "ok": True,
            "propiedad": {
                "titulo": propiedad.get('titulo', ''),
                "precio": float(propiedad.get('precio', 0)),
                "ubicacion": propiedad.get('ubicacion', '')
            },
            "total": len(matches),
            "leads": [{
                "id": l.get('id'),
                "nombre": l.get('nombre', ''),
                "telefono": l.get('telefono', ''),
                "zona_interes": l.get('zona_interes', ''),
                "presupuesto": l.get('presupuesto', ''),
                "temperatura": l.get('temperatura', ''),
                "score": l.get('score', 0),
                "score_match": l.get('score_match', 0),
                "whatsapp_url": f"https://wa.me/{limpiar_telefono(l.get('telefono',''))}?text={_encode_wa_msg(l, propiedad)}"
            } for l in matches],
            "whatsapp_empresa": wa
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

def _encode_wa_msg(lead, propiedad):
    import urllib.parse
    nombre = lead.get('nombre', '').split()[0]
    titulo = propiedad.get('titulo', '')
    precio = float(propiedad.get('precio', 0))
    ubicacion = propiedad.get('ubicacion', '')
    msg = f"Hola {nombre}, tengo una propiedad que podría interesarte: {titulo} en {ubicacion} por ${precio:,.0f}. ¿Te gustaría conocer más detalles?"
    return urllib.parse.quote(msg)

def generar_respuesta_sugerida(lead, lang='es'):
    nombre = lead.get('nombre', 'el cliente').split()[0]
    zona = lead.get('zona_interes', 'la zona de interés')
    temperatura = lead.get('temperatura', 'FRIO')
    clasificacion = lead.get('clasificacion', '')
    fecha_str = lead.get('fecha', '')
    try:
        presupuesto = float(re.sub(r'[^\d.]', '', str(lead.get('presupuesto', 0))))
    except:
        presupuesto = 0
    dias = 0
    if fecha_str:
        try:
            fecha = datetime.strptime(fecha_str.split(" ")[0], "%Y-%m-%d")
            dias = (datetime.now() - fecha).days
        except:
            dias = 0
    if presupuesto >= 1000000:
        p = f"${presupuesto/1000000:.1f}M"
    elif presupuesto >= 1000:
        p = f"${presupuesto/1000:.0f}K"
    else:
        p = f"${presupuesto:.0f}" if presupuesto > 0 else ""

    T = {
        'es': {
            'cliente': [
                {'titulo': '💎 Referidos (recomendado)', 'msg': f"Hola {nombre}, espero que todo vaya excelente con su propiedad. ¿Conoce a alguien buscando en {zona}? Con gusto le atiendo con la misma dedicación."},
                {'titulo': '🏠 Nueva oportunidad', 'msg': f"Hola {nombre}, acaba de entrar una propiedad exclusiva en {zona} que creo le puede interesar a usted o a alguien de su círculo. ¿Le cuento?"},
                {'titulo': '✅ Check-in', 'msg': f"Hola {nombre}, ¿cómo va todo con su propiedad? Solo quería saludar y recordarle que sigo disponible para cualquier consulta futura."},
            ],
            'nuevo': [
                {'titulo': '⚡ Velocidad (recomendado)', 'msg': f"¡Hola {nombre}! Acabo de ver tu consulta sobre propiedades en {zona}. Tengo opciones perfectas para ti. ¿Tienes 5 minutos ahora?"},
                {'titulo': '💬 Consultivo', 'msg': f"Hola {nombre}, vi tu interés en propiedades en {zona}. Antes de enviarte opciones, ¿me puedes contar un poco más sobre lo que buscas?"},
                {'titulo': '📸 Propuesta directa', 'msg': f"Hola {nombre}! Tengo 3 propiedades en {zona} que podrían encajar con lo que buscas. ¿Te las envío ahora mismo con fotos y precios?"},
            ],
            'dia1_caliente': [
                {'titulo': '🔥 Llamada directa (recomendado)', 'msg': f"Hola {nombre}, le contacto porque ayer vi su interés en {zona} y hoy recibimos una propiedad que encaja perfectamente con {p}. ¿Le puedo enviar los detalles?"},
                {'titulo': '🏠 Agendar visita', 'msg': f"Hola {nombre}! Tengo propiedades en {zona} listas para visitar esta semana. ¿Cuándo le queda bien?"},
                {'titulo': '💎 Exclusividad', 'msg': f"Hola {nombre}, tengo una propiedad en {zona} que acaba de entrar al mercado. Con su presupuesto de {p} encaja perfecto. ¿Le interesa verla primero?"},
            ],
            'dias3': [
                {'titulo': '📬 Micro-compromiso (recomendado)', 'msg': f"Hola {nombre}, ¿le puedo enviar 2-3 opciones en {zona} con fotos ahora mismo? Sin compromiso."},
                {'titulo': '💎 Alto valor', 'msg': f"Hola {nombre}, con un presupuesto de {p} en {zona} tiene acceso a propiedades con excelente potencial. Tengo 2 opciones exclusivas. ¿Las revisamos?"},
                {'titulo': '📞 Cita rápida', 'msg': f"Hola {nombre}, ¿me permite 10 minutos esta semana? Tengo opciones nuevas en {zona}. ¿Cuándo le queda bien?"},
            ],
            'dias7': [
                {'titulo': '🔄 Nuevo contexto (recomendado)', 'msg': f"Hola {nombre}, ¿cómo está? El mercado en {zona} cambió esta semana — bajaron 2 propiedades de precio. ¿Sigue buscando?"},
                {'titulo': '❓ Pregunta honesta', 'msg': f"Hola {nombre}, ¿sigue interesado en propiedades en {zona} o sus planes cambiaron?"},
                {'titulo': '📸 Novedad', 'msg': f"Hola {nombre}! Acaba de entrar una propiedad en {zona} que me recordó a lo que buscaba. ¿Se la muestro?"},
            ],
            'dias14': [
                {'titulo': '⏰ FOMO (recomendado)', 'msg': f"Hola {nombre}, una propiedad en {zona} recibió una oferta hoy. Antes de que se cierre, ¿le gustaría verla?"},
                {'titulo': '📞 Llamada directa', 'msg': f"Hola {nombre}, ¿podemos hablar 5 minutos? Tengo algo en {zona} dentro de {p} que creo le va a gustar."},
                {'titulo': '💰 Precio bajó', 'msg': f"Hola {nombre}, buenas noticias — una propiedad en {zona} bajó de precio. ¿Le interesa verla?"},
            ],
            'dias30': [
                {'titulo': '🔄 Reactivación honesta (recomendado)', 'msg': f"Hola {nombre}, ¿sigue considerando una propiedad en {zona} o sus planes cambiaron?"},
                {'titulo': '🆕 Ángulo nuevo', 'msg': f"Hola {nombre}, han entrado propiedades nuevas en {zona}. ¿Vale la pena que le envíe algunas opciones?"},
                {'titulo': '🤝 Sin presión', 'msg': f"Hola {nombre}, no le escribo para venderle nada — solo para saber si puedo serle útil en {zona}."},
            ],
            'ultimo': [
                {'titulo': '📊 Última oportunidad (recomendado)', 'msg': f"Hola {nombre}, le escribo por última vez. Si todavía busca en {zona}, estoy aquí."},
                {'titulo': '🚪 Puerta abierta', 'msg': f"Hola {nombre}, cuando retome su búsqueda en {zona}, con gusto le ayudo."},
                {'titulo': '🎯 Referidos', 'msg': f"Hola {nombre}, ¿conoce a alguien que esté buscando en {zona}? Con gusto le atiendo."},
            ],
        },
        'en': {
            'cliente': [
                {'titulo': '💎 Referrals (recommended)', 'msg': f"Hi {nombre}, hope everything is great with your property. Do you know anyone looking in {zona}?"},
                {'titulo': '🏠 New opportunity', 'msg': f"Hi {nombre}, a new exclusive property just came in at {zona}. Want me to share the details?"},
                {'titulo': '✅ Check-in', 'msg': f"Hi {nombre}, how's everything going? Just wanted to remind you I'm always available."},
            ],
            'nuevo': [
                {'titulo': '⚡ Speed (recommended)', 'msg': f"Hi {nombre}! I just saw your inquiry about properties in {zona}. Do you have 5 minutes?"},
                {'titulo': '💬 Consultative', 'msg': f"Hi {nombre}, I saw your interest in {zona}. Could you tell me more about what you're looking for?"},
                {'titulo': '📸 Direct proposal', 'msg': f"Hi {nombre}! I have 3 properties in {zona} that might fit. Want me to send them with photos?"},
            ],
            'dia1_caliente': [
                {'titulo': '🔥 Direct (recommended)', 'msg': f"Hi {nombre}, we got a property in {zona} that fits perfectly within {p}. Can I send details?"},
                {'titulo': '🏠 Schedule visit', 'msg': f"Hi {nombre}! I have properties in {zona} ready to visit. When works for you?"},
                {'titulo': '💎 Exclusivity', 'msg': f"Hi {nombre}, I have an unlisted property in {zona} within {p}. Want to see it first?"},
            ],
            'dias3': [
                {'titulo': '📬 Micro-commitment (recommended)', 'msg': f"Hi {nombre}, can I send 2-3 options in {zona} with photos? No commitment."},
                {'titulo': '💎 High value', 'msg': f"Hi {nombre}, with {p} in {zona} you have access to great properties. Want to review them?"},
                {'titulo': '📞 Quick call', 'msg': f"Hi {nombre}, can I have 10 minutes this week? New options in {zona} that you'll like."},
            ],
            'dias7': [
                {'titulo': '🔄 New context (recommended)', 'msg': f"Hi {nombre}, the market in {zona} changed this week — 2 properties dropped in price. Still looking?"},
                {'titulo': '❓ Honest question', 'msg': f"Hi {nombre}, are you still interested in {zona} or have your plans changed?"},
                {'titulo': '📸 New listing', 'msg': f"Hi {nombre}! A property just came in {zona} that reminded me of what you were looking for."},
            ],
            'dias14': [
                {'titulo': '⏰ FOMO (recommended)', 'msg': f"Hi {nombre}, a property in {zona} I had in mind for you received an offer today. Want to see it?"},
                {'titulo': '📞 Direct call', 'msg': f"Hi {nombre}, could we talk 5 minutes? I have something in {zona} within {p} you'll like."},
                {'titulo': '💰 Price dropped', 'msg': f"Hi {nombre}, good news — a property in {zona} dropped in price. Interested?"},
            ],
            'dias30': [
                {'titulo': '🔄 Honest reactivation (recommended)', 'msg': f"Hi {nombre}, are you still considering a property in {zona}?"},
                {'titulo': '🆕 New angle', 'msg': f"Hi {nombre}, new properties came in {zona}. Worth sending some options?"},
                {'titulo': '🤝 No pressure', 'msg': f"Hi {nombre}, just checking if I can help with anything in {zona}."},
            ],
            'ultimo': [
                {'titulo': '📊 Last message (recommended)', 'msg': f"Hi {nombre}, this is my last message. If you're still looking in {zona}, I'm here."},
                {'titulo': '🚪 Open door', 'msg': f"Hi {nombre}, whenever you resume your search in {zona}, I'll be happy to help."},
                {'titulo': '🎯 Referrals', 'msg': f"Hi {nombre}, do you know anyone looking in {zona}? I'd be glad to help them."},
            ],
        },
        'fr': {
            'cliente': [
                {'titulo': '💎 Références (recommandé)', 'msg': f"Bonjour {nombre}, connaissez-vous quelqu'un cherchant à {zona}?"},
                {'titulo': '🏠 Nouvelle opportunité', 'msg': f"Bonjour {nombre}, une propriété vient d'arriver à {zona}. Vous en parle?"},
                {'titulo': '✅ Prise de nouvelles', 'msg': f"Bonjour {nombre}, comment se passe tout? Je reste disponible pour toute question."},
            ],
            'nuevo': [
                {'titulo': '⚡ Rapidité (recommandé)', 'msg': f"Bonjour {nombre}! Je viens de voir votre demande pour {zona}. Avez-vous 5 minutes?"},
                {'titulo': '💬 Consultatif', 'msg': f"Bonjour {nombre}, que recherchez-vous exactement à {zona}?"},
                {'titulo': '📸 Proposition directe', 'msg': f"Bonjour {nombre}! J'ai 3 propriétés à {zona}. Je vous les envoie avec photos?"},
            ],
            'dia1_caliente': [
                {'titulo': '🔥 Direct (recommandé)', 'msg': f"Bonjour {nombre}, une propriété à {zona} correspond parfaitement à {p}. Je vous envoie les détails?"},
                {'titulo': '🏠 Visite', 'msg': f"Bonjour {nombre}! Propriétés disponibles à {zona} cette semaine. Quand êtes-vous libre?"},
                {'titulo': '💎 Exclusivité', 'msg': f"Bonjour {nombre}, propriété exclusive à {zona} dans {p}. Vous voulez la voir en premier?"},
            ],
            'dias3': [
                {'titulo': '📬 Engagement (recommandé)', 'msg': f"Bonjour {nombre}, je vous envoie 2-3 options à {zona} avec photos? Sans engagement."},
                {'titulo': '💎 Valeur', 'msg': f"Bonjour {nombre}, avec {p} à {zona} vous avez accès à d'excellentes propriétés."},
                {'titulo': '📞 Appel', 'msg': f"Bonjour {nombre}, 10 minutes cette semaine? Nouvelles options à {zona}."},
            ],
            'dias7': [
                {'titulo': '🔄 Contexte (recommandé)', 'msg': f"Bonjour {nombre}, le marché à {zona} a changé — 2 propriétés ont baissé. Vous cherchez encore?"},
                {'titulo': '❓ Honnête', 'msg': f"Bonjour {nombre}, êtes-vous toujours intéressé par {zona}?"},
                {'titulo': '📸 Nouveau', 'msg': f"Bonjour {nombre}! Une propriété à {zona} vient d'arriver. Je vous la montre?"},
            ],
            'dias14': [
                {'titulo': '⏰ FOMO (recommandé)', 'msg': f"Bonjour {nombre}, une propriété à {zona} a reçu une offre. Souhaitez-vous la voir?"},
                {'titulo': '📞 Appel direct', 'msg': f"Bonjour {nombre}, 5 minutes cette semaine? J'ai quelque chose à {zona} dans {p}."},
                {'titulo': '💰 Prix baissé', 'msg': f"Bonjour {nombre}, une propriété à {zona} a baissé de prix. Intéressé?"},
            ],
            'dias30': [
                {'titulo': '🔄 Réactivation (recommandé)', 'msg': f"Bonjour {nombre}, envisagez-vous toujours une propriété à {zona}?"},
                {'titulo': '🆕 Angle nouveau', 'msg': f"Bonjour {nombre}, nouvelles propriétés à {zona}. Je vous envoie des options?"},
                {'titulo': '🤝 Sans pression', 'msg': f"Bonjour {nombre}, puis-je vous aider pour quelque chose à {zona}?"},
            ],
            'ultimo': [
                {'titulo': '📊 Dernier message (recommandé)', 'msg': f"Bonjour {nombre}, dernier message. Si vous cherchez encore à {zona}, je suis là."},
                {'titulo': '🚪 Porte ouverte', 'msg': f"Bonjour {nombre}, quand vous reprendrez votre recherche à {zona}, je serai là."},
                {'titulo': '🎯 Références', 'msg': f"Bonjour {nombre}, connaissez-vous quelqu'un cherchant à {zona}?"},
            ],
        },
        'de': {
            'cliente': [
                {'titulo': '💎 Empfehlungen (empfohlen)', 'msg': f"Hallo {nombre}, kennen Sie jemanden, der in {zona} sucht?"},
                {'titulo': '🏠 Neue Gelegenheit', 'msg': f"Hallo {nombre}, eine Immobilie in {zona} ist gerade auf den Markt. Details?"},
                {'titulo': '✅ Check-in', 'msg': f"Hallo {nombre}, wie läuft alles? Ich stehe jederzeit zur Verfügung."},
            ],
            'nuevo': [
                {'titulo': '⚡ Schnell (empfohlen)', 'msg': f"Hallo {nombre}! Ihre Anfrage für {zona} gesehen. Haben Sie 5 Minuten?"},
                {'titulo': '💬 Beratend', 'msg': f"Hallo {nombre}, was genau suchen Sie in {zona}?"},
                {'titulo': '📸 Direktes Angebot', 'msg': f"Hallo {nombre}! 3 Immobilien in {zona}. Soll ich sie mit Fotos schicken?"},
            ],
            'dia1_caliente': [
                {'titulo': '🔥 Direkt (empfohlen)', 'msg': f"Hallo {nombre}, eine Immobilie in {zona} passt perfekt zu {p}. Details schicken?"},
                {'titulo': '🏠 Besichtigung', 'msg': f"Hallo {nombre}! Immobilien in {zona} diese Woche verfügbar. Wann haben Sie Zeit?"},
                {'titulo': '💎 Exklusiv', 'msg': f"Hallo {nombre}, exklusive Immobilie in {zona} für {p}. Zuerst sehen?"},
            ],
            'dias3': [
                {'titulo': '📬 Commitment (empfohlen)', 'msg': f"Hallo {nombre}, 2-3 Optionen in {zona} mit Fotos? Ohne Verpflichtung."},
                {'titulo': '💎 Wert', 'msg': f"Hallo {nombre}, mit {p} in {zona} haben Sie Zugang zu tollen Immobilien."},
                {'titulo': '📞 Anruf', 'msg': f"Hallo {nombre}, 10 Minuten diese Woche? Neue Optionen in {zona}."},
            ],
            'dias7': [
                {'titulo': '🔄 Kontext (empfohlen)', 'msg': f"Hallo {nombre}, der Markt in {zona} hat sich verändert — 2 Preise gefallen. Suchen Sie noch?"},
                {'titulo': '❓ Ehrlich', 'msg': f"Hallo {nombre}, interessieren Sie sich noch für {zona}?"},
                {'titulo': '📸 Neuheit', 'msg': f"Hallo {nombre}! Eine Immobilie in {zona} ist gerade reingekommen. Zeigen?"},
            ],
            'dias14': [
                {'titulo': '⏰ FOMO (empfohlen)', 'msg': f"Hallo {nombre}, eine Immobilie in {zona} hat ein Angebot erhalten. Sehen?"},
                {'titulo': '📞 Direkter Anruf', 'msg': f"Hallo {nombre}, 5 Minuten diese Woche? Etwas in {zona} für {p}."},
                {'titulo': '💰 Preis gesunken', 'msg': f"Hallo {nombre}, eine Immobilie in {zona} ist günstiger geworden. Interesse?"},
            ],
            'dias30': [
                {'titulo': '🔄 Reaktivierung (empfohlen)', 'msg': f"Hallo {nombre}, denken Sie noch an eine Immobilie in {zona}?"},
                {'titulo': '🆕 Neuer Ansatz', 'msg': f"Hallo {nombre}, neue Immobilien in {zona}. Optionen schicken?"},
                {'titulo': '🤝 Kein Druck', 'msg': f"Hallo {nombre}, kann ich Ihnen bei etwas in {zona} helfen?"},
            ],
            'ultimo': [
                {'titulo': '📊 Letzte Nachricht (empfohlen)', 'msg': f"Hallo {nombre}, letzte Nachricht. Falls Sie noch in {zona} suchen, bin ich hier."},
                {'titulo': '🚪 Offene Tür', 'msg': f"Hallo {nombre}, wenn Sie Ihre Suche in {zona} wieder aufnehmen, helfe ich gerne."},
                {'titulo': '🎯 Empfehlungen', 'msg': f"Hallo {nombre}, kennen Sie jemanden, der in {zona} sucht?"},
            ],
        },
        'pt': {
            'cliente': [
                {'titulo': '💎 Indicações (recomendado)', 'msg': f"Olá {nombre}, conhece alguém buscando em {zona}?"},
                {'titulo': '🏠 Nova oportunidade', 'msg': f"Olá {nombre}, chegou um imóvel em {zona}. Quero te contar?"},
                {'titulo': '✅ Check-in', 'msg': f"Olá {nombre}, tudo bem? Continuo disponível para qualquer dúvida."},
            ],
            'nuevo': [
                {'titulo': '⚡ Velocidade (recomendado)', 'msg': f"Olá {nombre}! Vi sua consulta sobre {zona}. Tem 5 minutos?"},
                {'titulo': '💬 Consultivo', 'msg': f"Olá {nombre}, o que você procura exatamente em {zona}?"},
                {'titulo': '📸 Proposta direta', 'msg': f"Olá {nombre}! Tenho 3 imóveis em {zona}. Te envio com fotos?"},
            ],
            'dia1_caliente': [
                {'titulo': '🔥 Direto (recomendado)', 'msg': f"Olá {nombre}, temos um imóvel em {zona} que encaixa em {p}. Posso enviar detalhes?"},
                {'titulo': '🏠 Visita', 'msg': f"Olá {nombre}! Imóveis em {zona} disponíveis esta semana. Quando fica bom?"},
                {'titulo': '💎 Exclusivo', 'msg': f"Olá {nombre}, imóvel exclusivo em {zona} dentro de {p}. Quer ver primeiro?"},
            ],
            'dias3': [
                {'titulo': '📬 Compromisso (recomendado)', 'msg': f"Olá {nombre}, posso te enviar 2-3 opções em {zona} com fotos? Sem compromisso."},
                {'titulo': '💎 Alto valor', 'msg': f"Olá {nombre}, com {p} em {zona} você tem acesso a ótimos imóveis."},
                {'titulo': '📞 Ligação', 'msg': f"Olá {nombre}, 10 minutos esta semana? Novas opções em {zona}."},
            ],
            'dias7': [
                {'titulo': '🔄 Contexto (recomendado)', 'msg': f"Olá {nombre}, o mercado em {zona} mudou — 2 imóveis baixaram. Ainda procurando?"},
                {'titulo': '❓ Honesto', 'msg': f"Olá {nombre}, ainda tem interesse em {zona}?"},
                {'titulo': '📸 Novidade', 'msg': f"Olá {nombre}! Um imóvel em {zona} acabou de entrar. Te mostro?"},
            ],
            'dias14': [
                {'titulo': '⏰ FOMO (recomendado)', 'msg': f"Olá {nombre}, um imóvel em {zona} recebeu proposta hoje. Gostaria de ver?"},
                {'titulo': '📞 Direto', 'msg': f"Olá {nombre}, 5 minutos esta semana? Tenho algo em {zona} dentro de {p}."},
                {'titulo': '💰 Preço caiu', 'msg': f"Olá {nombre}, um imóvel em {zona} baixou de preço. Interesse?"},
            ],
            'dias30': [
                {'titulo': '🔄 Reativação (recomendado)', 'msg': f"Olá {nombre}, ainda pensa em um imóvel em {zona}?"},
                {'titulo': '🆕 Novo ângulo', 'msg': f"Olá {nombre}, chegaram imóveis novos em {zona}. Vale enviar opções?"},
                {'titulo': '🤝 Sem pressão', 'msg': f"Olá {nombre}, posso ser útil com algo em {zona}?"},
            ],
            'ultimo': [
                {'titulo': '📊 Última mensagem (recomendado)', 'msg': f"Olá {nombre}, última mensagem. Se ainda procura em {zona}, estou aqui."},
                {'titulo': '🚪 Porta aberta', 'msg': f"Olá {nombre}, quando retomar sua busca em {zona}, terei prazer em ajudar."},
                {'titulo': '🎯 Indicações', 'msg': f"Olá {nombre}, conhece alguém buscando em {zona}?"},
            ],
        },
        'zh': {
            'cliente': [
                {'titulo': '💎 推荐（推荐）', 'msg': f"您好 {nombre}，您认识在{zona}找房的人吗？"},
                {'titulo': '🏠 新机会', 'msg': f"您好 {nombre}，{zona}刚来了一套房产，要我告诉您详情吗？"},
                {'titulo': '✅ 问候', 'msg': f"您好 {nombre}，一切都好吗？我随时可以为您服务。"},
            ],
            'nuevo': [
                {'titulo': '⚡ 速度（推荐）', 'msg': f"您好 {nombre}！看到您在{zona}找房。您现在有5分钟吗？"},
                {'titulo': '💬 顾问式', 'msg': f"您好 {nombre}，您在{zona}具体找什么类型的房产？"},
                {'titulo': '📸 直接提案', 'msg': f"您好 {nombre}！我在{zona}有3套房产。现在发给您带照片的信息吗？"},
            ],
            'dia1_caliente': [
                {'titulo': '🔥 直接（推荐）', 'msg': f"您好 {nombre}，{zona}有一套在{p}预算内的房产。我发详情给您？"},
                {'titulo': '🏠 参观', 'msg': f"您好 {nombre}！{zona}本周有房产可以参观。什么时候方便？"},
                {'titulo': '💎 独家', 'msg': f"您好 {nombre}，{zona}有一套独家房产在{p}内。想第一个看吗？"},
            ],
            'dias3': [
                {'titulo': '📬 微承诺（推荐）', 'msg': f"您好 {nombre}，发给您{zona}的2-3个带照片的选项？没有义务。"},
                {'titulo': '💎 高价值', 'msg': f"您好 {nombre}，凭借{p}在{zona}您可以获得很好的房产。"},
                {'titulo': '📞 通话', 'msg': f"您好 {nombre}，这周能给我10分钟吗？{zona}有新选项。"},
            ],
            'dias7': [
                {'titulo': '🔄 新背景（推荐）', 'msg': f"您好 {nombre}，{zona}市场本周变化——2套降价。您还在找吗？"},
                {'titulo': '❓ 诚实', 'msg': f"您好 {nombre}，您还对{zona}感兴趣吗？"},
                {'titulo': '📸 新房源', 'msg': f"您好 {nombre}！{zona}刚来了新房产。我给您看吗？"},
            ],
            'dias14': [
                {'titulo': '⏰ 紧迫（推荐）', 'msg': f"您好 {nombre}，{zona}一套房产今天收到报价。想看吗？"},
                {'titulo': '📞 通话', 'msg': f"您好 {nombre}，这周5分钟？{zona}有适合{p}的房产。"},
                {'titulo': '💰 降价', 'msg': f"您好 {nombre}，{zona}一套房产降价了。有兴趣吗？"},
            ],
            'dias30': [
                {'titulo': '🔄 重新激活（推荐）', 'msg': f"您好 {nombre}，您还在考虑{zona}的房产吗？"},
                {'titulo': '🆕 新角度', 'msg': f"您好 {nombre}，{zona}来了新房产。发些选项给您吗？"},
                {'titulo': '🤝 无压力', 'msg': f"您好 {nombre}，我能在{zona}方面为您提供帮助吗？"},
            ],
            'ultimo': [
                {'titulo': '📊 最后消息（推荐）', 'msg': f"您好 {nombre}，这是最后一条消息。如果还在{zona}找，我在这里。"},
                {'titulo': '🚪 开放', 'msg': f"您好 {nombre}，当您恢复在{zona}的搜索时，我很乐意帮助。"},
                {'titulo': '🎯 推荐', 'msg': f"您好 {nombre}，您认识在{zona}找房的人吗？"},
            ],
        },
    }
    t = T.get(lang, T['es'])
    if 'CLIENTE' in clasificacion: return t['cliente']
    if dias == 0: return t['nuevo']
    if dias <= 1 and temperatura in ['MUY_CALIENTE', 'CALIENTE']: return t['dia1_caliente']
    if dias <= 3: return t['dias3']
    if dias <= 7: return t['dias7']
    if dias <= 14: return t['dias14']
    if dias <= 30: return t['dias30']
    return t['ultimo']

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

def job_reporte_semanal():
    """
    Corre cada hora (vía cron externo). Revisa todos los clientes activos
    con país configurado, y le manda el reporte semanal solo a los que
    en este momento son las 8am del lunes en SU hora local — y que
    todavía no recibieron el reporte de esta semana. El email se envía
    en el idioma configurado para ese cliente.
    """
    print(f"🔄 [{datetime.now().strftime('%Y-%m-%d %H:%M')}] Revisando reportes semanales...")
    try:
        resultado = supabase.table("clientes").select("*").eq("activo", True).execute()
        clientes = resultado.data or []
        for cliente in clientes:
            pais = cliente.get("pais", "")
            tz_name = PAISES_TIMEZONE.get(pais)
            if not tz_name:
                continue

            ahora_local = datetime.now(ZoneInfo(tz_name))

            # Solo lunes (weekday 0) a las 8am en su hora local
            if ahora_local.weekday() != 0 or ahora_local.hour != 8:
                continue

            semana_actual = f"{ahora_local.isocalendar()[0]}-W{ahora_local.isocalendar()[1]:02d}"
            if cliente.get("ultimo_reporte_semana") == semana_actual:
                continue  # Ya se le mandó esta semana

            resumen = generar_resumen_semanal(cliente["id"])
            if resumen is None:
                continue

            lang_cliente = get_idioma_default(cliente)
            enviado = enviar_reporte_semanal(cliente["id"], resumen, lang=lang_cliente)
            if enviado:
                supabase.table("clientes").update({
                    "ultimo_reporte_semana": semana_actual
                }).eq("id", cliente["id"]).execute()
                print(f"✅ Reporte semanal enviado a {cliente.get('nombre')} ({pais}, idioma={lang_cliente})")
    except Exception as e:
        print(f"❌ Error en job_reporte_semanal: {e}")

@app.before_request
def verificar_sesion():
    rutas_publicas = ['formulario', 'formulario_asesor', 'index', 'seleccion_idioma_login',
                      'static', 'login', 'cambiar_idioma', 'cron_seguimiento', 'admin_login',
                      'inicio_formulario', 'chat_inmobiliario', 'test_chat', 'inventario_publico',
                      'recuperar_password', 'reset_password', 'cron_reporte_semanal',
                      'test_reporte_semanal']
    if request.endpoint in rutas_publicas:
        return
    if request.endpoint and request.endpoint.startswith('admin'):
        if not session.get('admin'):
            return redirect(url_for('admin_login'))
        admin_time = session.get('admin_time')
        if admin_time:
            if datetime.now() - datetime.fromisoformat(admin_time) > timedelta(minutes=30):
                session.clear()
                return redirect(url_for('admin_login'))
            # ✅ Renovar el tiempo de actividad del admin en cada acción
            session['admin_time'] = datetime.now().isoformat()
        return
    if 'cliente' in session:
        login_time = session.get('login_time')
        if login_time:
            if datetime.now() - datetime.fromisoformat(login_time) > timedelta(minutes=30):
                cliente_id = session.get('cliente')
                session.clear()
                return redirect(url_for('login', cliente_id=cliente_id or 'roberto'))
            # ✅ Renovar el tiempo de actividad en cada acción (sesión por inactividad)
            session['login_time'] = datetime.now().isoformat()
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
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    return response

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
@limiter.limit("5 per minute")
def admin_login():
    error = None
    if request.method == "POST":
        token_form = request.form.get('csrf_token')
        token_session = session.get('csrf_token')
        if not token_form or not token_session or not secrets.compare_digest(token_form, token_session):
            error = "Error de seguridad. Recarga la página."
            return render_template("admin_login.html", error=error)
        password = request.form.get("password", "")
        admin_pass = os.environ.get("ADMIN_PASSWORD", "admin_diego_2024")
        if secrets.compare_digest(password, admin_pass):
            session["admin"] = True
            session["admin_time"] = datetime.now().isoformat()
            log_accion('ADMIN_LOGIN', 'Login exitoso', get_remote_address())
            return redirect(url_for('admin_panel'))
        log_accion('ADMIN_LOGIN_FAIL', 'Contraseña incorrecta', get_remote_address())
        error = "Contraseña incorrecta"
    return render_template("admin_login.html", error=error)

@app.route("/admin/logout")
def admin_logout():
    log_accion('ADMIN_LOGOUT', '', get_remote_address())
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
        return redirect(url_for('admin_panel'))
    verificar_csrf()
    try:
        cliente_id = request.form.get("id", "").strip().lower().replace(" ", "_")
        if not cliente_id:
            return redirect(url_for('admin_panel'))
        password_raw = request.form.get("password", "").strip()
        password_hash = generate_password_hash(password_raw) if password_raw else generate_password_hash(secrets.token_hex(16))
        data = {
            "id": cliente_id,
            "nombre": request.form.get("nombre", "").strip(),
            "email_vendedor": request.form.get("email_vendedor", "").strip(),
            "whatsapp": request.form.get("whatsapp", "").strip(),
            "usuario": request.form.get("usuario", "").strip(),
            "password": password_hash,
            "idioma_default": request.form.get("idioma_default", "español"),
            "pais": request.form.get("pais", "").strip(),
            "color_primario": request.form.get("color_primario", "#667eea"),
            "premium_email": True,
            "email_api_key": request.form.get("email_api_key", "").strip(),
            "activo": True
        }
        supabase.table("clientes").insert(data).execute()
        log_accion('ADMIN_NUEVO_CLIENTE', f"id={cliente_id}", get_remote_address())
    except Exception as e:
        print(f"❌ Error creando cliente: {e}")
    return redirect(url_for('admin_panel'))

@app.route("/admin/cliente/editar/<cliente_id>", methods=["POST"])
def admin_editar_cliente(cliente_id):
    if not session.get("admin"):
        return redirect(url_for('admin_panel'))
    verificar_csrf()
    try:
        data = {
            "nombre": request.form.get("nombre", "").strip(),
            "email_vendedor": request.form.get("email_vendedor", "").strip(),
            "whatsapp": request.form.get("whatsapp", "").strip(),
            "usuario": request.form.get("usuario", "").strip(),
            "idioma_default": request.form.get("idioma_default", "español"),
            "pais": request.form.get("pais", "").strip(),
            "color_primario": request.form.get("color_primario", "#667eea"),
            "email_api_key": request.form.get("email_api_key", "").strip(),
            "activo": request.form.get("activo") == "on"
        }
        nueva_password = request.form.get("password", "").strip()
        if nueva_password:
            data["password"] = generate_password_hash(nueva_password)
        supabase.table("clientes").update(data).eq("id", cliente_id).execute()
        log_accion('ADMIN_EDITAR_CLIENTE', f"id={cliente_id}", get_remote_address())
    except Exception as e:
        print(f"❌ Error editando cliente: {e}")
    return redirect(url_for('admin_panel'))

@app.route("/admin/cliente/toggle/<cliente_id>", methods=["POST"])
def admin_toggle_cliente(cliente_id):
    if not session.get("admin"):
        return redirect(url_for('admin_panel'))
    verificar_csrf()
    try:
        nuevo_estado = request.form.get("nuevo_estado", "false") == "true"
        supabase.table("clientes").update({"activo": nuevo_estado}).eq("id", cliente_id).execute()
    except Exception as e:
        print(f"❌ Error: {e}")
    return redirect(url_for('admin_panel'))

@app.route("/admin/cliente/borrar/<cliente_id>", methods=["POST"])
def admin_borrar_cliente(cliente_id):
    if not session.get("admin"):
        return redirect(url_for('admin_panel'))
    verificar_csrf()
    try:
        supabase.table("leads").delete().eq("vendedor", cliente_id).execute()
        supabase.table("propiedades").delete().eq("vendedor", cliente_id).execute()
        supabase.table("asesores").delete().eq("cliente_id", cliente_id).execute()
        supabase.table("clientes").delete().eq("id", cliente_id).execute()
        log_accion('ADMIN_BORRAR_CLIENTE', f"id={cliente_id}", get_remote_address())
    except Exception as e:
        print(f"❌ Error eliminando cliente: {e}")
    return redirect(url_for('admin_panel'))

# ============================================================
# GESTIÓN DE ASESORES
# ============================================================

@app.route("/asesores/<cliente_id>/nuevo", methods=["POST"])
def crear_asesor(cliente_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean or not es_dueno():
        return "No autorizado", 403
    verificar_csrf()
    try:
        password_raw = request.form.get("password", "").strip()
        data = {
            "cliente_id": id_clean,
            "nombre": request.form.get("nombre", "").strip(),
            "usuario": request.form.get("usuario", "").strip(),
            "password": generate_password_hash(password_raw) if password_raw else generate_password_hash(secrets.token_hex(16)),
            "email": request.form.get("email", "").strip(),
            "activo": True
        }
        supabase.table("asesores").insert(data).execute()
        log_accion('CREAR_ASESOR', f"cliente={id_clean}", get_remote_address(), id_clean)
    except Exception as e:
        print(f"❌ Error creando asesor: {e}")
    return redirect(url_for('historial', cliente_id=id_clean))

@app.route("/asesores/<cliente_id>/toggle/<int:asesor_id>", methods=["POST"])
def toggle_asesor(cliente_id, asesor_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean or not es_dueno():
        return "No autorizado", 403
    verificar_csrf()
    try:
        nuevo_estado = request.form.get("nuevo_estado", "false") == "true"
        supabase.table("asesores").update({"activo": nuevo_estado}) \
            .eq("id", asesor_id).eq("cliente_id", id_clean).execute()
    except Exception as e:
        print(f"❌ Error toggling asesor: {e}")
    return redirect(url_for('historial', cliente_id=id_clean))

@app.route("/asesores/<cliente_id>/borrar/<int:asesor_id>", methods=["POST"])
def borrar_asesor(cliente_id, asesor_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean or not es_dueno():
        return "No autorizado", 403
    verificar_csrf()
    try:
        supabase.table("leads").update({"asesor_id": None}).eq("asesor_id", asesor_id).execute()
        supabase.table("asesores").delete().eq("id", asesor_id).eq("cliente_id", id_clean).execute()
    except Exception as e:
        print(f"❌ Error eliminando asesor: {e}")
    return redirect(url_for('historial', cliente_id=id_clean))

@app.route("/asesores/<cliente_id>/detalle/<int:asesor_id>")
def detalle_asesor(cliente_id, asesor_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean or not es_dueno():
        return redirect(url_for('login', cliente_id=id_clean))
    vendedor = get_cliente(id_clean)
    if not vendedor: return "Error 404", 404
    try:
        asesor_r = supabase.table("asesores").select("*").eq("id", asesor_id).eq("cliente_id", id_clean).execute()
        if not asesor_r.data: return "Asesor no encontrado", 404
        asesor = asesor_r.data[0]
        asesor['activo'] = bool(asesor.get('activo', False))
        leads_r = supabase.table("leads").select("*").eq("asesor_id", asesor_id).order("score", desc=True).execute()
        leads = leads_r.data or []
        total = len(leads)
        clientes = sum(1 for l in leads if 'CLIENTE' in l.get('clasificacion', ''))
        calientes = sum(1 for l in leads if l.get('temperatura') in ['MUY_CALIENTE', 'CALIENTE'])
        tasa = round((clientes / total * 100), 1) if total > 0 else 0
        hoy = datetime.now()
        for lead in leads:
            try:
                fecha = datetime.strptime(lead.get("fecha", "").split(" ")[0], "%Y-%m-%d")
                lead['dias'] = (hoy - fecha).days
            except:
                lead['dias'] = 0
        color = vendedor.get('color_primario', '#667eea')
        return render_template("asesor_detalle.html",
                               asesor=asesor, leads=leads, vendedor=vendedor,
                               cliente_id=id_clean, color=color,
                               total=total, clientes=clientes,
                               calientes=calientes, tasa=tasa,
                               idioma_actual=session.get('idioma', get_idioma_default(vendedor)))
    except Exception as e:
        return f"Error: {e}", 500

@app.route("/leads/<cliente_id>/asignar/<int:lead_id>", methods=["POST"])
def asignar_asesor_lead(cliente_id, lead_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean or not es_dueno():
        return "No autorizado", 403
    verificar_csrf()
    try:
        asesor_id = request.form.get("asesor_id")
        if asesor_id:
            supabase.table("leads").update({"asesor_id": int(asesor_id)}).eq("id", lead_id).execute()
        else:
            supabase.table("leads").update({"asesor_id": None}).eq("id", lead_id).execute()
    except Exception as e:
        print(f"❌ Error asignando asesor: {e}")
    return redirect(url_for('historial', cliente_id=id_clean))

@app.route("/leads/<cliente_id>/nota/<int:lead_id>", methods=["POST"])
def guardar_nota(cliente_id, lead_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean:
        return "No autorizado", 403
    token_header = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
    if not token_header or not secrets.compare_digest(token_header, session.get('csrf_token', '')):
        return jsonify({"ok": False, "error": "CSRF"}), 403
    try:
        nota = request.form.get("nota", "").strip()
        supabase.table("leads").update({
            "notas": nota,
            "ultimo_contacto": datetime.now().strftime("%Y-%m-%d %H:%M")
        }).eq("id", lead_id).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/leads/<cliente_id>/respuesta/<int:lead_id>")
def respuesta_sugerida(cliente_id, lead_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean:
        return "No autorizado", 403
    try:
        lang = session.get('idioma', 'es')
        resultado = supabase.table("leads").select("*").eq("id", lead_id).execute()
        if resultado.data:
            respuestas = generar_respuesta_sugerida(resultado.data[0], lang)
            return jsonify({"respuestas": respuestas})
        return jsonify({"respuestas": []}), 404
    except Exception as e:
        return jsonify({"respuestas": []}), 500

@app.route("/leads/<cliente_id>/etapa/<int:lead_id>", methods=["POST"])
def actualizar_etapa(cliente_id, lead_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean:
        return "No autorizado", 403
    token_header = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
    if not token_header or not secrets.compare_digest(token_header, session.get('csrf_token', '')):
        return jsonify({"ok": False, "error": "CSRF"}), 403
    try:
        nueva_etapa = request.form.get("etapa", "nuevo")
        etapas_validas = ['nuevo', 'contactado', 'visita', 'propuesta', 'cerrado']
        if nueva_etapa not in etapas_validas:
            return "Etapa inválida", 400
        supabase.table("leads").update({"etapa": nueva_etapa}).eq("id", lead_id).execute()
        return jsonify({"ok": True, "etapa": nueva_etapa})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ============================================================
# ✅ AGENDA DE VISITAS
# ============================================================

@app.route("/visitas/<cliente_id>/nueva/<int:lead_id>", methods=["POST"])
def crear_visita(cliente_id, lead_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean:
        return jsonify({"ok": False, "error": "No autorizado"}), 403
    verificar_csrf()
    try:
        fecha_str = request.form.get("fecha_visita", "").strip()
        propiedad_id = request.form.get("propiedad_id", "").strip()
        notas = request.form.get("notas", "").strip()[:500]

        if not fecha_str:
            return jsonify({"ok": False, "error": "Fecha requerida"}), 400

        try:
            fecha_visita = datetime.strptime(fecha_str, "%Y-%m-%dT%H:%M")
        except ValueError:
            return jsonify({"ok": False, "error": "Formato de fecha inválido"}), 400

        visita_data = {
            "lead_id": lead_id,
            "vendedor": id_clean,
            "propiedad_id": int(propiedad_id) if propiedad_id else None,
            "fecha_visita": fecha_visita.isoformat(),
            "notas": notas,
            "estado": "agendada"
        }
        resultado = supabase.table("visitas").insert(visita_data).execute()
        log_accion('VISITA_CREADA', f"lead_id={lead_id}", get_remote_address(), id_clean)
        return jsonify({"ok": True, "visita": resultado.data[0] if resultado.data else None})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/visitas/<cliente_id>/lead/<int:lead_id>")
def obtener_visitas_lead(cliente_id, lead_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean:
        return jsonify({"ok": False, "error": "No autorizado"}), 403
    try:
        resultado = supabase.table("visitas").select("*").eq("lead_id", lead_id).eq("vendedor", id_clean).order("fecha_visita", desc=False).execute()
        return jsonify({"ok": True, "visitas": resultado.data or []})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/visitas/<cliente_id>/proximas")
def visitas_proximas(cliente_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean:
        return jsonify({"ok": False, "error": "No autorizado"}), 403
    try:
        resultado = supabase.table("visitas").select("*").eq("vendedor", id_clean).eq("estado", "agendada").order("fecha_visita", desc=False).execute()
        return jsonify({"ok": True, "visitas": resultado.data or []})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/visitas/<cliente_id>/cancelar/<int:visita_id>", methods=["POST"])
def cancelar_visita(cliente_id, visita_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean:
        return jsonify({"ok": False, "error": "No autorizado"}), 403
    verificar_csrf()
    try:
        supabase.table("visitas").update({"estado": "cancelada"}).eq("id", visita_id).eq("vendedor", id_clean).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/propiedades/<cliente_id>/lista")
def propiedades_lista_json(cliente_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean:
        return jsonify({"ok": False, "error": "No autorizado"}), 403
    try:
        resultado = supabase.table("propiedades").select("id,titulo").eq("vendedor", id_clean).eq("estado", "disponible").order("titulo").execute()
        return jsonify({"ok": True, "propiedades": resultado.data or []})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ============================================================
# RUTAS PRINCIPALES
# ============================================================

@app.route("/cron/seguimiento/<secret_key>", methods=["GET"])
def cron_seguimiento(secret_key):
    clave_esperada = os.environ.get("CRON_SECRET", "seguimiento_secreto_roberto_2024")
    if not secrets.compare_digest(secret_key, clave_esperada):
        return "No autorizado", 403
    try:
        job_seguimiento_automatico()
        return f"✅ Seguimiento ejecutado: {datetime.now().strftime('%Y-%m-%d %H:%M')}", 200
    except Exception as e:
        return f"❌ Error: {e}", 500

@app.route("/cron/reporte-semanal/<secret_key>", methods=["GET"])
def cron_reporte_semanal(secret_key):
    clave_esperada = os.environ.get("CRON_SECRET", "seguimiento_secreto_roberto_2024")
    if not secrets.compare_digest(secret_key, clave_esperada):
        return "No autorizado", 403
    try:
        job_reporte_semanal()
        return f"✅ Revisión de reportes semanales ejecutada: {datetime.now().strftime('%Y-%m-%d %H:%M')}", 200
    except Exception as e:
        return f"❌ Error: {e}", 500

@app.route("/cron/test-reporte-semanal/<secret_key>/<cliente_id>", methods=["GET"])
def test_reporte_semanal(secret_key, cliente_id):
    """
    RUTA DE PRUEBA — fuerza el envío del reporte semanal a un cliente
    específico, sin importar el día/hora. Úsala solo para probar.
    """
    clave_esperada = os.environ.get("CRON_SECRET", "seguimiento_secreto_roberto_2024")
    if not secrets.compare_digest(secret_key, clave_esperada):
        return "No autorizado", 403
    try:
        cliente = get_cliente(cliente_id)
        if not cliente:
            return "Cliente no encontrado", 404
        resumen = generar_resumen_semanal(cliente_id)
        if resumen is None:
            return "Error generando resumen", 500
        lang_cliente = get_idioma_default(cliente)
        enviado = enviar_reporte_semanal(cliente_id, resumen, lang=lang_cliente)
        return f"✅ Reporte de prueba enviado (idioma={lang_cliente}): {enviado}", 200
    except Exception as e:
        return f"❌ Error: {e}", 500

@app.route("/inicio/<cliente_id>")
def inicio_formulario(cliente_id):
    id_clean = cliente_id.lower()
    vendedor = get_cliente(id_clean)
    if not vendedor: return "Error 404", 404
    return render_template("formulario_bienvenida.html", cliente=vendedor)

@app.route("/cliente/<cliente_id>")
def seleccion_idioma(cliente_id):
    id_clean = cliente_id.lower()
    vendedor = get_cliente(id_clean)
    if not vendedor: return "Error 403: Acceso denegado.", 403
    lang = session.get('idioma', request.accept_languages.best_match(['es', 'en', 'fr', 'de']) or 'es')
    textos = DICCIONARIO.get(lang, DICCIONARIO['es'])
    return render_template("bienvenida.html", cliente=vendedor, textos=textos, idioma_actual=lang)

@app.route("/form/<cliente_id>", methods=["GET","POST"])
@limiter.limit("20 per minute")
def formulario(cliente_id):
    id_clean = cliente_id.lower()
    vendedor = get_cliente(id_clean)
    if not vendedor: return "Error 404: Vendedor no configurado.", 404
    idioma_default = get_idioma_default(vendedor)
    lang = session.get('idioma', idioma_default)
    textos = DICCIONARIO.get(lang, DICCIONARIO['es'])
    if request.method == "POST":
        verificar_csrf()
        nombre = request.form.get("nombre", "").strip()
        telefono = request.form.get("telefono", "").strip()
        zona = request.form.get("zona", "").strip()
        presupuesto = request.form.get("presupuesto", "").strip()
        mensaje = request.form.get("mensaje", "").strip()
        if not nombre or not telefono or not zona or not presupuesto or not mensaje:
            return render_template("formulario.html", enviado=False, cliente_id=id_clean,
                                   textos=textos, cliente_nombre=vendedor['nombre'],
                                   idioma_actual=lang, error="Todos los campos son requeridos.")
        d = {
            "nombre": nombre[:100],
            "telefono": telefono[:30],
            "zona_interes": zona[:100],
            "presupuesto": presupuesto[:30],
            "mensaje": mensaje[:1000],
            "vendedor": id_clean
        }
        score_final = motor_scoring_global(d)
        clasificacion, temperatura = calificar_lead_profesional(score_final)
        email_prospecto = request.form.get("email", "").strip()[:150]
        lead_data = {
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
            **d,
            "clasificacion": clasificacion,
            "score": score_final,
            "temperatura": temperatura,
            "estado": "Nuevo",
            "email": email_prospecto,
            "seguimiento_enviado": False,
            "etapa": "nuevo"
        }
        try:
            supabase.table("leads").insert(lead_data).execute()
            log_accion('NUEVO_LEAD', f"cliente={id_clean} nombre={nombre}", get_remote_address(), id_clean)
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

@app.route("/form/<cliente_id>/<asesor_usuario>", methods=["GET","POST"])
@limiter.limit("20 per minute")
def formulario_asesor(cliente_id, asesor_usuario):
    id_clean = cliente_id.lower()
    vendedor = get_cliente(id_clean)
    if not vendedor: return "Error 404: Vendedor no configurado.", 404
    asesor = None
    try:
        asesor_r = supabase.table("asesores").select("*").eq("cliente_id", id_clean)\
            .eq("usuario", asesor_usuario).eq("activo", True).execute()
        if asesor_r.data:
            asesor = asesor_r.data[0]
    except:
        pass
    idioma_default = get_idioma_default(vendedor)
    lang = session.get('idioma', idioma_default)
    textos = DICCIONARIO.get(lang, DICCIONARIO['es'])
    if request.method == "POST":
        verificar_csrf()
        nombre = request.form.get("nombre", "").strip()
        telefono = request.form.get("telefono", "").strip()
        zona = request.form.get("zona", "").strip()
        presupuesto = request.form.get("presupuesto", "").strip()
        mensaje = request.form.get("mensaje", "").strip()
        if not nombre or not telefono or not zona or not presupuesto or not mensaje:
            return render_template("formulario.html", enviado=False, cliente_id=id_clean,
                                   textos=textos, cliente_nombre=vendedor['nombre'],
                                   idioma_actual=lang, error="Todos los campos son requeridos.")
        d = {
            "nombre": nombre[:100],
            "telefono": telefono[:30],
            "zona_interes": zona[:100],
            "presupuesto": presupuesto[:30],
            "mensaje": mensaje[:1000],
            "vendedor": id_clean
        }
        score_final = motor_scoring_global(d)
        clasificacion, temperatura = calificar_lead_profesional(score_final)
        email_prospecto = request.form.get("email", "").strip()[:150]
        lead_data = {
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
            **d,
            "clasificacion": clasificacion,
            "score": score_final,
            "temperatura": temperatura,
            "estado": "Nuevo",
            "email": email_prospecto,
            "seguimiento_enviado": False,
            "asesor_id": asesor["id"] if asesor else None,
            "etapa": "nuevo"
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
    asesor_id = session.get('asesor_id')
    if asesor_id:
        query = query.eq("asesor_id", asesor_id)
    q = request.args.get('q', '')
    if q: query = query.ilike("nombre", f"%{q}%")
    resultado = query.order("score", desc=True).execute()
    leads = resultado.data or []
    hoy = datetime.now()
    for lead in leads:
        try:
            fecha = datetime.strptime(lead.get("fecha", "").split(" ")[0], "%Y-%m-%d")
            lead['dias'] = (hoy - fecha).days
        except:
            lead['dias'] = 0
    asesores = []
    if es_dueno():
        asesores = get_asesores_de_cliente(id_clean)
    return render_template("historial.html",
                           leads=leads, cliente=vendedor, textos=textos,
                           idioma_actual=idioma, asesores=asesores,
                           es_dueno=es_dueno(),
                           asesor_nombre=session.get('asesor_nombre', ''))

@app.route("/kanban/<cliente_id>")
def kanban(cliente_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean:
        return redirect(url_for('login', cliente_id=id_clean))
    vendedor = get_cliente(id_clean)
    if not vendedor: return "Error 404", 404
    idioma = session.get('idioma', get_idioma_default(vendedor))
    textos = DICCIONARIO.get(idioma, DICCIONARIO['es'])
    query = supabase.table("leads").select("*").eq("vendedor", id_clean)
    asesor_id = session.get('asesor_id')
    if asesor_id:
        query = query.eq("asesor_id", asesor_id)
    resultado = query.order("score", desc=True).execute()
    leads = resultado.data or []
    hoy = datetime.now()
    for lead in leads:
        try:
            fecha = datetime.strptime(lead.get("fecha", "").split(" ")[0], "%Y-%m-%d")
            lead['dias'] = (hoy - fecha).days
        except:
            lead['dias'] = 0
        if not lead.get('etapa'):
            lead['etapa'] = 'nuevo'
    etapas = {
        'nuevo':      [l for l in leads if l.get('etapa') == 'nuevo'],
        'contactado': [l for l in leads if l.get('etapa') == 'contactado'],
        'visita':     [l for l in leads if l.get('etapa') == 'visita'],
        'propuesta':  [l for l in leads if l.get('etapa') == 'propuesta'],
        'cerrado':    [l for l in leads if l.get('etapa') == 'cerrado'],
    }
    asesores = []
    if es_dueno():
        asesores = get_asesores_de_cliente(id_clean)
    return render_template("kanban.html",
                           etapas=etapas, leads=leads,
                           cliente=vendedor, textos=textos,
                           idioma_actual=idioma, asesores=asesores,
                           es_dueno=es_dueno(),
                           asesor_nombre=session.get('asesor_nombre', ''))

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
        match_id = request.args.get('match', '')
        return render_template("inventario.html", cliente_id=id_clean,
                               cliente_nombre=vendedor['nombre'],
                               propiedades_json=json.dumps(propiedades),
                               textos=textos, idioma_actual=idioma,
                               match_id=match_id)
    except Exception as e:
        return render_template("inventario.html", cliente_id=id_clean,
                               cliente_nombre=vendedor['nombre'], propiedades_json='[]',
                               textos=textos, idioma_actual=idioma, match_id='')

@app.route("/propiedades/<cliente_id>", methods=["GET"])
def inventario_publico(cliente_id):
    id_clean = cliente_id.lower()
    vendedor = get_cliente(id_clean)
    if not vendedor: return "Error 404: No encontrado.", 404
    try:
        resultado = supabase.table("propiedades").select("*").eq("vendedor", id_clean).eq("estado", "disponible").order("created_at", desc=True).execute()
        propiedades = resultado.data or []
        idioma = session.get('idioma', get_idioma_default(vendedor))
        return render_template("inventario_publico.html", cliente_id=id_clean,
                               cliente_nombre=vendedor['nombre'], whatsapp=vendedor['whatsapp'],
                               propiedades_json=json.dumps(propiedades),
                               idioma_actual=idioma)
    except Exception as e:
        return f"Error: {e}", 500

@app.route("/agregar_propiedad/<cliente_id>", methods=["POST"])
@limiter.limit("30 per hour")
def agregar_propiedad(cliente_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean: return "Error 403: No autorizado.", 403
    verificar_csrf()
    vendedor = get_cliente(id_clean)
    if not vendedor: return "Error 404: Vendedor no encontrado.", 404
    try:
        imagenes_urls = []
        archivos = request.files.getlist("imagenes")[:7]
        for archivo in archivos:
            if not archivo_permitido(archivo):
                continue
            archivo.seek(0, 2)
            size_mb = archivo.tell() / (1024 * 1024)
            archivo.seek(0)
            if size_mb > MAX_FILE_SIZE_MB:
                continue
            resultado = cloudinary.uploader.upload(archivo,
                folder=f"bot_inmobiliaria/{id_clean}",
                transformation=[{"width": 1200, "height": 900, "crop": "limit", "quality": "auto"}])
            imagenes_urls.append(resultado["secure_url"])

        habitaciones = request.form.get("habitaciones", "").strip()
        banos = request.form.get("banos", "").strip()
        metros2 = request.form.get("metros2", "").strip()
        titulo = request.form.get("titulo", "").strip()[:200]
        ubicacion = request.form.get("ubicacion", "").strip()[:200]
        if not titulo or not ubicacion:
            return "Título y ubicación requeridos", 400

        propiedad_data = {
            "titulo": titulo,
            "descripcion": request.form.get("descripcion", "").strip()[:2000],
            "precio": float(request.form.get("precio", 0)),
            "ubicacion": ubicacion,
            "habitaciones": int(habitaciones) if habitaciones else None,
            "banos": float(banos) if banos else None,
            "metros2": float(metros2) if metros2 else None,
            "imagen_url": json.dumps(imagenes_urls),
            "vendedor": id_clean, "estado": "disponible"
        }
        nueva_prop = supabase.table("propiedades").insert(propiedad_data).execute()
        log_accion('AGREGAR_PROPIEDAD', f"titulo={titulo}", get_remote_address(), id_clean)
        nuevo_id = nueva_prop.data[0]['id'] if nueva_prop.data else ''
        return redirect(url_for('inventario', cliente_id=id_clean, match=nuevo_id))
    except Exception as e:
        return f"Error: {e}", 500

@app.route("/editar_propiedad/<cliente_id>/<int:prop_id>", methods=["POST"])
def editar_propiedad(cliente_id, prop_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean: return "Error 403: No autorizado.", 403
    verificar_csrf()
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
        espacio_disponible = max(0, 7 - len(imagenes_existentes))
        archivos = request.files.getlist("imagenes")[:espacio_disponible]
        for archivo in archivos:
            if not archivo_permitido(archivo):
                continue
            archivo.seek(0, 2)
            size_mb = archivo.tell() / (1024 * 1024)
            archivo.seek(0)
            if size_mb > MAX_FILE_SIZE_MB:
                continue
            resultado = cloudinary.uploader.upload(archivo,
                folder=f"bot_inmobiliaria/{id_clean}",
                transformation=[{"width": 1200, "height": 900, "crop": "limit", "quality": "auto"}])
            imagenes_existentes.append(resultado["secure_url"])
        habitaciones = request.form.get("habitaciones", "").strip()
        banos = request.form.get("banos", "").strip()
        metros2 = request.form.get("metros2", "").strip()
        update_data = {
            "titulo": request.form.get("titulo", "").strip()[:200],
            "descripcion": request.form.get("descripcion", "").strip()[:2000],
            "precio": float(request.form.get("precio", 0)),
            "ubicacion": request.form.get("ubicacion", "").strip()[:200],
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
    verificar_csrf()
    vendedor = get_cliente(id_clean)
    if not vendedor: return "Error 404: Vendedor no encontrado.", 404
    try:
        supabase.table("propiedades").delete().eq("id", prop_id).eq("vendedor", id_clean).execute()
        log_accion('ELIMINAR_PROPIEDAD', f"prop_id={prop_id}", get_remote_address(), id_clean)
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
    verificar_csrf()
    vendedor = get_cliente(id_clean)
    if not vendedor: return "Error 404: Vendedor no encontrado.", 404
    try:
        resultado = supabase.table("leads").select("*").eq("id", lead_id).execute()
        if resultado.data:
            lead = resultado.data[0]
            supabase.table("leads").update({
                "temperatura": "MUY_CALIENTE", "clasificacion": "💎 CLIENTE",
                "seguimiento_enviado": True, "etapa": "cerrado"
            }).eq("id", lead_id).execute()
            log_accion('MARCAR_CLIENTE', f"lead_id={lead_id} nombre={lead.get('nombre')}", get_remote_address(), id_clean)
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
    verificar_csrf()
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
            "temperatura": temperatura_nueva, "seguimiento_enviado": False,
            "etapa": "contactado"
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
        verificar_csrf()
        usuario_form = request.form.get("usuario", "").strip()
        password_form = request.form.get("password", "").strip()
        if usuario_form == vendedor["usuario"] and \
           verificar_password(password_form, vendedor["password"]):
            session["cliente"] = id_clean
            session["login_time"] = datetime.now().isoformat()
            session.pop("asesor_id", None)
            session.pop("asesor_nombre", None)
            log_accion('LOGIN_OK', f"usuario={usuario_form}", get_remote_address(), id_clean)
            return redirect(url_for('seleccion_idioma', cliente_id=id_clean))
        try:
            asesores_r = supabase.table("asesores").select("*") \
                .eq("cliente_id", id_clean) \
                .eq("usuario", usuario_form) \
                .eq("activo", True).execute()
            if asesores_r.data:
                asesor = asesores_r.data[0]
                if verificar_password(password_form, asesor["password"]):
                    session["cliente"] = id_clean
                    session["login_time"] = datetime.now().isoformat()
                    session["asesor_id"] = asesor["id"]
                    session["asesor_nombre"] = asesor["nombre"]
                    log_accion('LOGIN_ASESOR_OK', f"asesor={usuario_form}", get_remote_address(), id_clean)
                    return redirect(url_for('historial', cliente_id=id_clean))
        except Exception as e:
            print(f"⚠️ Error consultando asesores: {e}")
        log_accion('LOGIN_FAIL', f"usuario={usuario_form}", get_remote_address(), id_clean)
        return render_template("login.html", error="Credenciales Invalidas", cliente=vendedor, textos=textos, idioma_actual=lang)
    return render_template("login.html", cliente=vendedor, textos=textos, idioma_actual=lang)

# ============================================================
# ✅ RECUPERACIÓN DE CONTRASEÑA
# ============================================================

ERROR_MSGS_RESET = {
    'es': {'corta': 'La contraseña debe tener al menos 6 caracteres.', 'no_coincide': 'Las contraseñas no coinciden.'},
    'en': {'corta': 'Password must be at least 6 characters.', 'no_coincide': 'Passwords do not match.'},
    'fr': {'corta': 'Le mot de passe doit contenir au moins 6 caractères.', 'no_coincide': 'Les mots de passe ne correspondent pas.'},
    'de': {'corta': 'Das Passwort muss mindestens 6 Zeichen lang sein.', 'no_coincide': 'Die Passwörter stimmen nicht überein.'},
    'pt': {'corta': 'A senha deve ter pelo menos 6 caracteres.', 'no_coincide': 'As senhas não coincidem.'},
    'zh': {'corta': '密码至少需要6个字符。', 'no_coincide': '两次输入的密码不一致。'},
}

@app.route("/recuperar/<cliente_id>", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def recuperar_password(cliente_id):
    id_clean = cliente_id.lower()
    vendedor = get_cliente(id_clean)
    if not vendedor:
        return "Error 404", 404
    lang = session.get('idioma', get_idioma_default(vendedor))
    textos = DICCIONARIO.get(lang, DICCIONARIO['es'])
    mensaje = None
    if request.method == "POST":
        verificar_csrf()
        email_form = request.form.get("email", "").strip().lower()

        encontrado = False
        if email_form == (vendedor.get("email_vendedor", "") or "").strip().lower():
            token = secrets.token_urlsafe(32)
            expira = (datetime.now() + timedelta(hours=1)).isoformat()
            supabase.table("clientes").update({
                "reset_token": token, "reset_token_expira": expira
            }).eq("id", id_clean).execute()
            link = url_for('reset_password', token=token, _external=True)
            enviar_email_reset_password(id_clean, vendedor.get("nombre", ""), False, link, lang=lang)
            encontrado = True
            log_accion('RESET_PASSWORD_SOLICITADO', f"dueño cliente={id_clean}", get_remote_address(), id_clean)

        if not encontrado:
            try:
                asesores_r = supabase.table("asesores").select("*").eq("cliente_id", id_clean).execute()
                for asesor in (asesores_r.data or []):
                    if email_form == (asesor.get("email", "") or "").strip().lower():
                        token = secrets.token_urlsafe(32)
                        expira = (datetime.now() + timedelta(hours=1)).isoformat()
                        supabase.table("asesores").update({
                            "reset_token": token, "reset_token_expira": expira
                        }).eq("id", asesor["id"]).execute()
                        link = url_for('reset_password', token=token, _external=True)
                        enviar_email_reset_password(id_clean, asesor.get("nombre", ""), True, link, lang=lang)
                        encontrado = True
                        log_accion('RESET_PASSWORD_SOLICITADO', f"asesor={asesor.get('usuario')}", get_remote_address(), id_clean)
                        break
            except Exception as e:
                print(f"❌ Error buscando asesor para reset: {e}")

        # ✅ El texto de confirmación ahora lo muestra el template traducido (rt.mensaje_ok)
        mensaje = True
    return render_template("recuperar_password.html", cliente=vendedor, textos=textos,
                           idioma_actual=lang, mensaje=mensaje, cliente_id=id_clean)

@app.route("/reset-password/<token>", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def reset_password(token):
    ahora = datetime.now()
    cuenta = None
    tipo = None

    try:
        r = supabase.table("clientes").select("*").eq("reset_token", token).execute()
        if r.data:
            cuenta = r.data[0]
            tipo = "cliente"
    except:
        pass

    if not cuenta:
        try:
            r = supabase.table("asesores").select("*").eq("reset_token", token).execute()
            if r.data:
                cuenta = r.data[0]
                tipo = "asesor"
        except:
            pass

    # ✅ Determinar el idioma correcto (del dueño, o del dueño del asesor)
    lang_reset = 'es'
    if cuenta and tipo:
        if tipo == "cliente":
            lang_reset = get_idioma_default(cuenta)
        else:
            cliente_padre_id = cuenta.get("cliente_id")
            cliente_padre = get_cliente(cliente_padre_id) if cliente_padre_id else None
            if cliente_padre:
                lang_reset = get_idioma_default(cliente_padre)

    token_valido = False
    if cuenta:
        expira_str = cuenta.get("reset_token_expira")
        if expira_str:
            try:
                expira_dt = datetime.fromisoformat(expira_str.replace("Z", "+00:00")).replace(tzinfo=None)
                if ahora < expira_dt:
                    token_valido = True
            except:
                pass

    if not token_valido:
        return render_template("reset_password.html", token_invalido=True, idioma_actual=lang_reset)

    error = None
    err_t = ERROR_MSGS_RESET.get(lang_reset, ERROR_MSGS_RESET['es'])
    if request.method == "POST":
        verificar_csrf()
        nueva = request.form.get("password", "").strip()
        confirmar = request.form.get("password_confirmar", "").strip()
        if len(nueva) < 6:
            error = err_t['corta']
        elif nueva != confirmar:
            error = err_t['no_coincide']
        else:
            nuevo_hash = generate_password_hash(nueva)
            tabla = "clientes" if tipo == "cliente" else "asesores"
            supabase.table(tabla).update({
                "password": nuevo_hash,
                "reset_token": None,
                "reset_token_expira": None
            }).eq("id", cuenta["id"]).execute()
            log_accion('RESET_PASSWORD_COMPLETADO', f"tipo={tipo}", get_remote_address())
            return render_template("reset_password.html", exito=True, idioma_actual=lang_reset)

    return render_template("reset_password.html", token=token, error=error, idioma_actual=lang_reset)

@app.route("/logout/<cliente_id>")
def logout(cliente_id):
    log_accion('LOGOUT', '', get_remote_address(), session.get('cliente', ''))
    session.clear()
    return redirect(url_for('login', cliente_id=cliente_id.lower()))

@app.route("/idioma/<lang>/<proximo>/<cliente_id>")
def cambiar_idioma(lang, proximo, cliente_id):
    idiomas_validos = ['es', 'en', 'fr', 'de', 'pt', 'zh']
    if lang not in idiomas_validos:
        lang = 'es'
    session['idioma'] = lang
    return redirect(url_for(proximo, cliente_id=cliente_id.lower()))

# ============================================================
# ✅ CHATBOT CON OPENROUTER
# ============================================================

def llamar_openrouter(api_key, messages_payload):
    modelos = [
        "inclusionai/ling-3.0-tiny:free",
        "meta-llama/llama-3.3-8b-instruct:free",
        "mistralai/mistral-7b-instruct:free",
        "google/gemma-2-9b-it:free",
        "nousresearch/hermes-3-llama-3.1-405b:free",
    ]
    for modelo in modelos:
        try:
            payload = {
                "model": modelo,
                "messages": messages_payload,
                "max_tokens": 250,
                "temperature": 0.7
            }
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "https://bot-inmobiliaria-v1.onrender.com",
                    "X-Title": "Bot Inmobiliaria"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                result = json.loads(resp.read().decode('utf-8'))
            text = result["choices"][0]["message"]["content"]
            print(f"✅ OpenRouter modelo exitoso: {modelo}")
            return text
        except urllib.error.HTTPError as e:
            print(f"⚠️ OpenRouter {modelo} falló: {e.code}")
            time.sleep(1)
            continue
        except Exception as e:
            print(f"⚠️ OpenRouter {modelo} error: {e}")
            continue
    return None

@app.route("/test-chat/<cliente_id>")
def test_chat(cliente_id):
    api_key = os.environ.get("OPENROUTER_API_KEY", "NO KEY")
    try:
        result = llamar_openrouter(api_key, [
            {"role": "user", "content": "Say exactly: WORKING"}
        ])
        if result:
            return jsonify({"ok": True, "response": result, "key_prefix": api_key[:12]})
        return jsonify({"ok": False, "error": "Ningún modelo respondió", "key_prefix": api_key[:12]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "key_prefix": api_key[:12]})

@app.route("/api/chat/<cliente_id>", methods=["POST"])
@limiter.limit("30 per minute")
def chat_inmobiliario(cliente_id):
    id_clean = cliente_id.lower()
    vendedor = get_cliente(id_clean)
    if not vendedor:
        return jsonify({"response": "Lo siento, no pude conectarme."}), 200
    try:
        data = request.get_json()
        if not data:
            return jsonify({"response": "Datos inválidos."}), 400
        messages = data.get("messages", [])[:20]
        lang = data.get("lang", "es")
        if lang not in ['es', 'en', 'fr', 'de', 'pt', 'zh']:
            lang = 'es'
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            return jsonify({"response": "Servicio no disponible."}), 200
        lang_nombres = {
            'es': 'español', 'en': 'English', 'fr': 'français',
            'de': 'Deutsch', 'pt': 'português', 'zh': '中文'
        }
        lang_actual = lang_nombres.get(lang, 'español')
        wa = vendedor.get('whatsapp', '')
        props_result = supabase.table("propiedades").select("*").eq("vendedor", id_clean).eq("estado", "disponible").execute()
        propiedades = props_result.data or []
        props_text = ""
        for p in propiedades[:6]:
            try:
                precio = float(p.get('precio', 0))
                line = f"• {p.get('titulo','')}: ${precio:,.0f}, {p.get('ubicacion','')}"
            except:
                line = f"• {p.get('titulo','')}: {p.get('ubicacion','')}"
            if p.get('habitaciones'): line += f", {p.get('habitaciones')}hab"
            if p.get('metros2'): line += f", {p.get('metros2')}m²"
            props_text += line + "\n"
        if not props_text:
            props_text = "Sin propiedades listadas actualmente."
        cta = {
            'es': f"¡Perfecto! 📝 Llena el formulario arriba y te llamamos hoy. O escríbenos por WhatsApp: {wa} 💬",
            'en': f"Perfect! 📝 Fill the form above and we'll call you today. Or WhatsApp: {wa} 💬",
            'fr': f"Parfait! 📝 Remplissez le formulaire ci-dessus. WhatsApp: {wa} 💬",
            'de': f"Perfekt! 📝 Füllen Sie das Formular aus. WhatsApp: {wa} 💬",
            'pt': f"Perfeito! 📝 Preencha o formulário acima. WhatsApp: {wa} 💬",
            'zh': f"太好了！📝 请填写上方表格。WhatsApp: {wa} 💬"
        }.get(lang, f"¡Perfecto! 📝 Llena el formulario arriba. WhatsApp: {wa} 💬")
        system_prompt = f"""You are a real estate advisor for {vendedor.get('nombre','')}. Respond ONLY in {lang_actual}.
PROPERTIES:
{props_text}
INSTRUCTIONS:
- In your FIRST message: greet warmly, then ask ALL these questions in ONE message: name, country, zone/city, budget, property type (house/apartment/land), timeline to buy.
- In your SECOND message: based on answers, recommend 1-2 specific properties and send this: {cta}
- Keep responses under 4 sentences. Be warm and professional like a luxury advisor.
- ONLY respond in {lang_actual}."""
        messages_recientes = messages[-4:] if len(messages) > 4 else messages
        messages_payload = [{"role": "system", "content": system_prompt}]
        for msg in messages_recientes:
            role = "user" if msg.get("role") == "user" else "assistant"
            content = str(msg.get("content", ""))[:500]
            messages_payload.append({"role": role, "content": content})
        text = llamar_openrouter(api_key, messages_payload)
        if text:
            return jsonify({"response": text})
        else:
            raise Exception("Sin respuesta")
    except Exception as e:
        print(f"❌ Error chat: {e}")
        wa = vendedor.get('whatsapp', '') if vendedor else ''
        error_msgs = {
            'es': f"Nuestro asistente está ocupado 🔧 Escríbenos por WhatsApp: {wa} 💬",
            'en': f"Our assistant is busy 🔧 WhatsApp: {wa} 💬",
            'fr': f"Notre assistant est occupé 🔧 WhatsApp: {wa} 💬",
            'de': f"Unser Assistent ist beschäftigt 🔧 WhatsApp: {wa} 💬",
            'pt': f"Nosso assistente está ocupado 🔧 WhatsApp: {wa} 💬",
            'zh': f"助手很忙 🔧 WhatsApp: {wa} 💬"
        }
        try:
            l = request.get_json(silent=True).get('lang', 'es') if request.get_json(silent=True) else 'es'
        except:
            l = 'es'
        return jsonify({"response": error_msgs.get(l, error_msgs['es'])}), 200

@app.route("/")
def index():
    return "PropTech Global Engine V4.0 [Active Mode] 🌐🚀"

@app.errorhandler(403)
def forbidden(e):
    return "<h2>403 — Acceso denegado</h2>", 403

@app.errorhandler(413)
def archivo_muy_grande(e):
    return jsonify({"error": "Archivo demasiado grande. Máximo 20MB total."}), 413

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
