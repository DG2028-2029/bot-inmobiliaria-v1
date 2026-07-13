import requests
import os
import re
from datetime import datetime
from supabase import create_client

RESEND_API_URL = "https://api.resend.com/emails"
REMITENTE = "onboarding@resend.dev"

# --- SUPABASE ---
def _get_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    return create_client(url, key)

def _get_cliente(cliente_id):
    try:
        supabase = _get_supabase()
        r = supabase.table("clientes").select("*").eq("id", cliente_id).eq("activo", True).execute()
        if r.data:
            return r.data[0]
        return None
    except Exception as e:
        print(f"❌ Error obteniendo cliente {cliente_id}: {e}")
        return None

# --- ENVÍO BASE ---
def _enviar(api_key, to, subject, html):
    try:
        r = requests.post(
            RESEND_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={"from": REMITENTE, "to": [to], "subject": subject, "html": html}
        )
        print(f"✅ Email enviado a {to} | Status: {r.status_code}")
        return r.status_code == 200
    except Exception as e:
        print(f"❌ Error enviando email: {e}")
        return False

# --- EMAIL 1: Confirmación al prospecto cuando llega ---
def enviar_email_cliente(cliente_id, nombre_prospecto, email_prospecto):
    vendedor = _get_cliente(cliente_id)
    if not vendedor or not vendedor.get("premium_email"):
        return
    color = vendedor.get("color_primario", "#667eea")
    html = f"""
    <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:600px;margin:0 auto;background:#f8f9fa;padding:0;border-radius:12px;overflow:hidden;">
        <div style="background:{color};padding:28px 30px;text-align:center;">
            <h1 style="color:white;margin:0;font-size:22px;">🏠 {vendedor['nombre']}</h1>
        </div>
        <div style="background:white;padding:28px 30px;">
            <h2 style="color:#2c3e50;font-size:18px;">Hola, <strong>{nombre_prospecto}</strong> 👋</h2>
            <p style="color:#555;font-size:15px;line-height:1.7;">
                Recibimos tu información correctamente. Uno de nuestros asesores especializados
                revisará tu consulta y se pondrá en contacto contigo <strong>en las próximas horas</strong>.
            </p>
            <div style="background:#f8f9fa;border-left:4px solid {color};padding:14px 18px;border-radius:6px;margin:20px 0;">
                <p style="margin:0;color:#2c3e50;font-size:14px;">
                    💡 <strong>¿Sabías que?</strong> Los compradores que responden rápido suelen
                    encontrar mejores oportunidades. Mantente atento a nuestra llamada.
                </p>
            </div>
            <p style="color:#555;font-size:14px;">
                Si tienes alguna pregunta urgente, escríbenos directamente:
            </p>
            <div style="text-align:center;margin:24px 0;">
                <a href="https://wa.me/{vendedor.get('whatsapp','')}"
                   style="background:#25D366;color:white;padding:13px 28px;border-radius:8px;text-decoration:none;font-weight:bold;font-size:14px;display:inline-block;">
                    💬 Escribir por WhatsApp
                </a>
            </div>
        </div>
        <div style="background:#f8f9fa;padding:16px 30px;text-align:center;border-top:1px solid #eee;">
            <p style="color:#999;font-size:12px;margin:0;">— Equipo {vendedor['nombre']}</p>
        </div>
    </div>
    """
    _enviar(
        vendedor["email_api_key"],
        email_prospecto,
        f"✅ Recibimos tu información — {vendedor['nombre']}",
        html
    )

# --- EMAIL 2: Notificación al vendedor cuando llega lead nuevo ---
def notificar_vendedor_lead_nuevo(cliente_id, nombre, telefono, zona, presupuesto, mensaje, score, email_prospecto=""):
    vendedor = _get_cliente(cliente_id)
    if not vendedor or not vendedor.get("premium_email"):
        return
    color = vendedor.get("color_primario", "#667eea")
    color_score = "#27ae60" if score >= 65 else ("#f39c12" if score >= 35 else "#e74c3c")
    emoji_score = "🔥" if score >= 65 else ("🟡" if score >= 35 else "❄️")
    nivel = "ALTO — Contactar en los próximos 30 minutos" if score >= 65 else ("MEDIO — Seguimiento esta semana" if score >= 35 else "BAJO — Seguimiento automático activado")

    try:
        presupuesto_num = float(re.sub(r'[^\d.]', '', str(presupuesto)))
        presupuesto_fmt = f"${presupuesto_num:,.0f}"
    except:
        presupuesto_fmt = f"${presupuesto}"

    html = f"""
    <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:600px;margin:0 auto;background:#f8f9fa;padding:0;border-radius:12px;overflow:hidden;">
        <div style="background:{color};padding:22px 30px;display:flex;justify-content:space-between;align-items:center;">
            <h1 style="color:white;margin:0;font-size:20px;">🎯 Nuevo Lead — {vendedor['nombre']}</h1>
            <span style="background:rgba(255,255,255,0.25);color:white;padding:6px 14px;border-radius:20px;font-size:13px;font-weight:bold;">
                {emoji_score} Score: {score}/100
            </span>
        </div>
        <div style="background:white;padding:24px 30px;">
            <div style="background:{color_score};color:white;padding:12px 16px;border-radius:8px;margin-bottom:20px;text-align:center;">
                <strong>⚡ Prioridad {nivel}</strong>
            </div>
            <table style="width:100%;border-collapse:collapse;">
                <tr style="border-bottom:1px solid #f0f0f0;">
                    <td style="padding:10px 0;color:#999;font-size:13px;width:35%;">👤 Nombre</td>
                    <td style="padding:10px 0;color:#2c3e50;font-weight:bold;font-size:14px;">{nombre}</td>
                </tr>
                <tr style="border-bottom:1px solid #f0f0f0;">
                    <td style="padding:10px 0;color:#999;font-size:13px;">📱 Teléfono</td>
                    <td style="padding:10px 0;color:#2c3e50;font-weight:bold;font-size:14px;">{telefono}</td>
                </tr>
                <tr style="border-bottom:1px solid #f0f0f0;">
                    <td style="padding:10px 0;color:#999;font-size:13px;">📍 Zona</td>
                    <td style="padding:10px 0;color:#2c3e50;font-size:14px;">{zona}</td>
                </tr>
                <tr style="border-bottom:1px solid #f0f0f0;">
                    <td style="padding:10px 0;color:#999;font-size:13px;">💰 Presupuesto</td>
                    <td style="padding:10px 0;color:#27ae60;font-weight:bold;font-size:14px;">{presupuesto_fmt}</td>
                </tr>
                {'<tr style="border-bottom:1px solid #f0f0f0;"><td style="padding:10px 0;color:#999;font-size:13px;">📧 Email</td><td style="padding:10px 0;color:#2c3e50;font-size:14px;">' + email_prospecto + '</td></tr>' if email_prospecto else ''}
                <tr>
                    <td style="padding:10px 0;color:#999;font-size:13px;vertical-align:top;">💬 Mensaje</td>
                    <td style="padding:10px 0;color:#555;font-size:13px;font-style:italic;">"{mensaje}"</td>
                </tr>
            </table>
            <div style="text-align:center;margin-top:24px;">
                <a href="https://wa.me/{telefono}?text={requests.utils.quote(f'Hola {nombre}, vi tu consulta sobre propiedades en {zona}. ¿Tienes un momento para hablar?')}"
                   style="background:#25D366;color:white;padding:13px 28px;border-radius:8px;text-decoration:none;font-weight:bold;font-size:14px;display:inline-block;">
                    💬 Contactar por WhatsApp ahora
                </a>
            </div>
        </div>
        <div style="background:#f8f9fa;padding:14px 30px;text-align:center;border-top:1px solid #eee;">
            <p style="color:#999;font-size:12px;margin:0;">
                Recibido el {datetime.now().strftime('%d/%m/%Y a las %H:%M')} — {vendedor['nombre']}
            </p>
        </div>
    </div>
    """
    _enviar(
        vendedor["email_api_key"],
        vendedor["email_vendedor"],
        f"{emoji_score} Nuevo Lead: {nombre} — Score {score}/100 | {vendedor['nombre']}",
        html
    )

# --- EMAIL 3: Confirmación al vendedor cuando marca un cliente ---
def notificar_vendedor_cliente_marcado(cliente_id, nombre, telefono, zona, presupuesto):
    vendedor = _get_cliente(cliente_id)
    if not vendedor or not vendedor.get("premium_email"):
        return
    color = vendedor.get("color_primario", "#667eea")
    try:
        presupuesto_num = float(re.sub(r'[^\d.]', '', str(presupuesto)))
        presupuesto_fmt = f"${presupuesto_num:,.0f}"
    except:
        presupuesto_fmt = f"${presupuesto}"

    html = f"""
    <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:600px;margin:0 auto;background:#f8f9fa;padding:0;border-radius:12px;overflow:hidden;">
        <div style="background:linear-gradient(135deg,{color},#1a1a2e);padding:28px 30px;text-align:center;">
            <div style="font-size:48px;margin-bottom:10px;">💎</div>
            <h1 style="color:white;margin:0;font-size:22px;">¡Nuevo Cliente Confirmado!</h1>
            <p style="color:rgba(255,255,255,0.8);margin:6px 0 0;font-size:14px;">{vendedor['nombre']}</p>
        </div>
        <div style="background:white;padding:28px 30px;">
            <p style="color:#555;font-size:15px;text-align:center;">
                🎉 <strong>{nombre}</strong> ha sido marcado como cliente en tu sistema.
            </p>
            <table style="width:100%;border-collapse:collapse;margin-top:16px;">
                <tr style="border-bottom:1px solid #f0f0f0;">
                    <td style="padding:10px 0;color:#999;font-size:13px;width:40%;">👤 Cliente</td>
                    <td style="padding:10px 0;color:#2c3e50;font-weight:bold;">{nombre}</td>
                </tr>
                <tr style="border-bottom:1px solid #f0f0f0;">
                    <td style="padding:10px 0;color:#999;font-size:13px;">📱 Teléfono</td>
                    <td style="padding:10px 0;color:#2c3e50;">{telefono}</td>
                </tr>
                <tr style="border-bottom:1px solid #f0f0f0;">
                    <td style="padding:10px 0;color:#999;font-size:13px;">📍 Zona</td>
                    <td style="padding:10px 0;color:#2c3e50;">{zona}</td>
                </tr>
                <tr>
                    <td style="padding:10px 0;color:#999;font-size:13px;">💰 Presupuesto</td>
                    <td style="padding:10px 0;color:#27ae60;font-weight:bold;">{presupuesto_fmt}</td>
                </tr>
            </table>
            <div style="background:#f0fff4;border-left:4px solid #27ae60;padding:14px 18px;border-radius:6px;margin-top:20px;">
                <p style="margin:0;color:#2c3e50;font-size:13px;">
                    💡 <strong>Siguiente paso:</strong> Solicita referidos. Un cliente satisfecho
                    es tu mejor fuente de nuevos clientes. Pregúntale si conoce a alguien más buscando propiedad en {zona}.
                </p>
            </div>
        </div>
        <div style="background:#f8f9fa;padding:14px 30px;text-align:center;border-top:1px solid #eee;">
            <p style="color:#999;font-size:12px;margin:0;">
                Registrado el {datetime.now().strftime('%d/%m/%Y a las %H:%M')} — {vendedor['nombre']}
            </p>
        </div>
    </div>
    """
    _enviar(
        vendedor["email_api_key"],
        vendedor["email_vendedor"],
        f"💎 ¡Nuevo Cliente Cerrado! {nombre} — {vendedor['nombre']}",
        html
    )

# --- EMAIL 4: Seguimiento automático a los 3 días con técnica de venta ---
def enviar_seguimiento_automatico(cliente_id, nombre, telefono, email_prospecto, zona, presupuesto):
    vendedor = _get_cliente(cliente_id)
    if not vendedor or not vendedor.get("premium_email"):
        return False
    if not email_prospecto:
        return False

    color = vendedor.get("color_primario", "#667eea")
    nombre_corto = nombre.split()[0] if nombre else nombre

    try:
        presupuesto_num = float(re.sub(r'[^\d.]', '', str(presupuesto)))
        presupuesto_fmt = f"${presupuesto_num:,.0f}"
        if presupuesto_num >= 1000000:
            urgencia = "Con un presupuesto como el suyo, las mejores propiedades en " + zona + " se mueven rápido."
        elif presupuesto_num >= 150000:
            urgencia = "En " + zona + " hay opciones excelentes en su rango que no duran mucho en el mercado."
        else:
            urgencia = "Hay propiedades disponibles en " + zona + " que podrían encajar perfectamente con lo que busca."
    except:
        presupuesto_fmt = f"${presupuesto}"
        urgencia = f"Hay propiedades disponibles en {zona} que podrían interesarle."

    html = f"""
    <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:600px;margin:0 auto;background:#f8f9fa;padding:0;border-radius:12px;overflow:hidden;">
        <div style="background:{color};padding:24px 30px;text-align:center;">
            <div style="font-size:36px;margin-bottom:8px;">🏠</div>
            <h1 style="color:white;margin:0;font-size:20px;">{vendedor['nombre']}</h1>
        </div>
        <div style="background:white;padding:28px 30px;">
            <h2 style="color:#2c3e50;font-size:18px;margin-bottom:16px;">
                Hola <strong>{nombre_corto}</strong>, ¿todavía buscas en {zona}?
            </h2>
            <p style="color:#555;font-size:15px;line-height:1.8;">
                Hace unos días nos escribiste sobre propiedades en <strong>{zona}</strong>
                con un presupuesto de <strong>{presupuesto_fmt}</strong>.
            </p>
            <p style="color:#555;font-size:15px;line-height:1.8;margin-top:10px;">
                {urgencia}
            </p>
            <div style="background:#fff8e1;border-left:4px solid #f39c12;padding:14px 18px;border-radius:6px;margin:20px 0;">
                <p style="margin:0;color:#856404;font-size:14px;font-weight:bold;">
                    ⏰ Las propiedades en {zona} que más nos piden tienen alta demanda este mes.
                    Si quiere asegurar las mejores opciones, este es el momento.
                </p>
            </div>
            <p style="color:#555;font-size:14px;line-height:1.7;">
                ¿Le gustaría que le enviemos opciones personalizadas o agendamos una llamada
                de 10 minutos esta semana?
            </p>
            <div style="text-align:center;margin:28px 0 10px;">
                <a href="https://wa.me/{telefono}?text={requests.utils.quote(f'Hola {nombre_corto}, soy del equipo de {vendedor[chr(39)+chr(110)+chr(111)+chr(109)+chr(98)+chr(114)+chr(101)+chr(39)]}. Le escribo porque tenemos propiedades nuevas en {zona} que podrían interesarle. ¿Tiene un momento para hablar?')}"
                   style="background:#25D366;color:white;padding:14px 32px;border-radius:8px;text-decoration:none;font-weight:bold;font-size:14px;display:inline-block;margin-bottom:12px;">
                    💬 Sí, quiero ver opciones por WhatsApp
                </a>
                <br>
                <a href="mailto:{vendedor['email_vendedor']}"
                   style="color:{color};font-size:13px;text-decoration:none;">
                    📧 O responda este email directamente
                </a>
            </div>
        </div>
        <div style="background:#f8f9fa;padding:16px 30px;border-top:1px solid #eee;">
            <p style="color:#999;font-size:11px;margin:0;text-align:center;">
                Recibió este mensaje porque registró su interés en propiedades con {vendedor['nombre']}.<br>
                Si ya encontró lo que buscaba, ignore este mensaje.
            </p>
        </div>
    </div>
    """
    return _enviar(
        vendedor["email_api_key"],
        email_prospecto,
        f"¿Todavía buscas en {zona}? Tenemos opciones para ti — {vendedor['nombre']}",
        html
    )
