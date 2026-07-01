import requests
from config_clientes import CLIENTES

RESEND_API_URL = "https://api.resend.com/emails"
REMITENTE = "onboarding@resend.dev"

def _enviar(api_key, to, subject, html):
    try:
        r = requests.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"from": REMITENTE, "to": [to], "subject": subject, "html": html}
        )
        print(f"✅ Email enviado a {to} | Status: {r.status_code}")
        return r.status_code == 200
    except Exception as e:
        print(f"❌ Error enviando email: {e}")
        return False

def enviar_email_cliente(cliente_id, nombre_prospecto, email_prospecto):
    vendedor = CLIENTES.get(cliente_id)
    if not vendedor or not vendedor.get("premium_email"): return
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">
        <h2 style="color:#667eea;">¡Gracias por tu interés! 🏠</h2>
        <p>Hola <strong>{nombre_prospecto}</strong>,</p>
        <p>Hemos recibido tu información. Un asesor de <strong>{vendedor['nombre']}</strong> se pondrá en contacto contigo muy pronto.</p>
        <p>Si tienes alguna pregunta urgente, puedes contactarnos directamente por WhatsApp.</p>
        <br>
        <p style="color:#666;">— Equipo {vendedor['nombre']}</p>
    </div>
    """
    _enviar(vendedor["email_api_key"], email_prospecto, f"Recibimos tu información - {vendedor['nombre']}", html)

def notificar_vendedor_lead_nuevo(cliente_id, nombre, telefono, zona, presupuesto, mensaje, score, email_prospecto=""):
    vendedor = CLIENTES.get(cliente_id)
    if not vendedor or not vendedor.get("premium_email"): return

    color_score = "#27ae60" if score >= 65 else ("#f39c12" if score >= 35 else "#e74c3c")
    emoji_score = "🔥" if score >= 65 else ("🟡" if score >= 35 else "❄️")

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">
        <h2 style="color:#667eea;">🎯 Nuevo Lead Registrado</h2>
        <div style="background:#f8f9fa;padding:16px;border-radius:8px;margin:16px 0;">
            <p><strong>👤 Nombre:</strong> {nombre}</p>
            <p><strong>📱 Teléfono:</strong> {telefono}</p>
            <p><strong>📍 Zona:</strong> {zona}</p>
            <p><strong>💰 Presupuesto:</strong> ${presupuesto}</p>
            <p><strong>💬 Mensaje:</strong> {mensaje}</p>
            {'<p><strong>📧 Email:</strong> ' + email_prospecto + '</p>' if email_prospecto else ''}
        </div>
        <div style="background:{color_score};color:white;padding:12px;border-radius:8px;text-align:center;">
            <strong>{emoji_score} Score de Calidad: {score}/100</strong>
        </div>
        <p style="margin-top:16px;">
            <a href="https://wa.me/{telefono}" style="background:#25D366;color:white;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:bold;">
                💬 Contactar por WhatsApp
            </a>
        </p>
    </div>
    """
    _enviar(vendedor["email_api_key"], vendedor["email_vendedor"], f"{emoji_score} Nuevo Lead: {nombre} (Score: {score}/100)", html)

def notificar_vendedor_cliente_marcado(cliente_id, nombre, telefono, zona, presupuesto):
    vendedor = CLIENTES.get(cliente_id)
    if not vendedor or not vendedor.get("premium_email"): return
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">
        <h2 style="color:#667eea;">💎 ¡Nuevo Cliente Confirmado!</h2>
        <div style="background:#f8f9fa;padding:16px;border-radius:8px;margin:16px 0;">
            <p><strong>👤 Nombre:</strong> {nombre}</p>
            <p><strong>📱 Teléfono:</strong> {telefono}</p>
            <p><strong>📍 Zona:</strong> {zona}</p>
            <p><strong>💰 Presupuesto:</strong> ${presupuesto}</p>
        </div>
        <div style="background:#667eea;color:white;padding:12px;border-radius:8px;text-align:center;">
            <strong>💎 Este lead ha sido marcado como CLIENTE</strong>
        </div>
    </div>
    """
    _enviar(vendedor["email_api_key"], vendedor["email_vendedor"], f"💎 Nuevo Cliente: {nombre}", html)

def enviar_seguimiento_automatico(cliente_id, nombre, telefono, email_prospecto, zona, presupuesto):
    """Envía email de seguimiento automático a los 3 días."""
    vendedor = CLIENTES.get(cliente_id)
    if not vendedor or not vendedor.get("premium_email"): return False
    if not email_prospecto: return False

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">
        <h2 style="color:#667eea;">🏠 ¿Todavía buscas tu propiedad ideal?</h2>
        <p>Hola <strong>{nombre}</strong>,</p>
        <p>Hace unos días registraste tu interés en propiedades en <strong>{zona}</strong> con un presupuesto de <strong>${presupuesto}</strong>.</p>
        <p>Queremos asegurarnos de que encuentres exactamente lo que buscas. Nuestros asesores tienen opciones que podrían interesarte.</p>
        <div style="background:#f8f9fa;padding:16px;border-radius:8px;margin:20px 0;text-align:center;">
            <p style="color:#667eea;font-weight:bold;">¿Le gustaría agendar una visita o recibir más información?</p>
            <a href="https://wa.me/{telefono}" style="background:#25D366;color:white;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:bold;display:inline-block;margin-top:8px;">
                💬 Contactar por WhatsApp
            </a>
        </div>
        <p style="color:#999;font-size:12px;">Si ya encontró lo que buscaba, ignore este mensaje. Nos alegra si fue con nosotros.</p>
        <br>
        <p style="color:#666;">— Equipo {vendedor['nombre']}</p>
    </div>
    """
    return _enviar(vendedor["email_api_key"], email_prospecto, f"¿Todavía buscas tu propiedad? - {vendedor['nombre']}", html)
