import requests
import os
import re
from datetime import datetime
from supabase import create_client

RESEND_API_URL = "https://api.resend.com/emails"
REMITENTE = "onboarding@resend.dev"

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
        if r.status_code in (200, 201):
            print(f"✅ Email enviado a {to} | Status: {r.status_code}")
            return True
        else:
            print(f"❌ Resend rechazó el email | Status: {r.status_code} | Error: {r.text}")
            return False
    except Exception as e:
        print(f"❌ Error enviando email: {e}")
        return False

def enviar_email_cliente(cliente_id, nombre_prospecto, email_prospecto):
    """
    DESACTIVADO temporalmente — con onboarding@resend.dev no se puede mandar
    al prospecto, solo al email verificado del vendedor. El vendedor ya recibe
    la notificación completa via notificar_vendedor_lead_nuevo().
    Cuando tengas dominio propio en Resend, reactiva esta función.
    """
    print(f"ℹ️ Email confirmación a prospecto omitido (sin dominio propio en Resend)")
    return

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

    wa_msg = requests.utils.quote(
        f'Hola {nombre}, vi tu consulta sobre propiedades en {zona}. ¿Tienes un momento para hablar?'
    )

    html = f"""
    <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:600px;margin:0 auto;background:#f8f9fa;padding:0;border-radius:12px;overflow:hidden;">
        <div style="background:{color};padding:22px 30px;text-align:center;">
            <h1 style="color:white;margin:0;font-size:20px;">🎯 Nuevo Lead — {vendedor['nombre']}</h1>
            <span style="background:rgba(255,255,255,0.25);color:white;padding:6px 14px;border-radius:20px;font-size:13px;font-weight:bold;display:inline-block;margin-top:8px;">
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
                <a href="https://wa.me/{telefono}?text={wa_msg}"
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

def enviar_seguimiento_automatico(cliente_id, nombre, telefono, email_prospecto, zona, presupuesto):
    """
    Con onboarding@resend.dev solo se puede enviar al email verificado del vendedor.
    Mandamos recordatorio AL VENDEDOR con info del prospecto y botón WhatsApp directo.
    Cuando tengas dominio propio en Resend: cambia vendedor["email_vendedor"] por email_prospecto.
    """
    vendedor = _get_cliente(cliente_id)
    if not vendedor or not vendedor.get("premium_email"):
        return False

    color = vendedor.get("color_primario", "#667eea")
    nombre_corto = nombre.split()[0] if nombre else nombre

    try:
        presupuesto_num = float(re.sub(r'[^\d.]', '', str(presupuesto)))
        presupuesto_fmt = f"${presupuesto_num:,.0f}"
        if presupuesto_num >= 1000000:
            urgencia = f"Lead de alto valor — {presupuesto_fmt}. Prioridad máxima."
            prioridad_color = "#e74c3c"
        elif presupuesto_num >= 150000:
            urgencia = f"Presupuesto sólido de {presupuesto_fmt}. Vale la pena contactar hoy."
            prioridad_color = "#f39c12"
        else:
            urgencia = f"Presupuesto de {presupuesto_fmt}. Seguimiento estándar."
            prioridad_color = "#3498db"
    except:
        presupuesto_fmt = f"${presupuesto}"
        urgencia = "Revisar presupuesto directamente con el prospecto."
        prioridad_color = "#3498db"

    wa_msg = requests.utils.quote(
        f'Hola {nombre_corto}, soy de {vendedor["nombre"]}. '
        f'Le escribo porque hace unos días registró su interés en propiedades en {zona}. '
        f'¿Sigue buscando? Tenemos opciones nuevas que podrían interesarle.'
    )

    html = f"""
    <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:600px;margin:0 auto;background:#f8f9fa;padding:0;border-radius:12px;overflow:hidden;">
        <div style="background:linear-gradient(135deg,{color},#1a1a2e);padding:22px 30px;text-align:center;">
            <div style="font-size:32px;margin-bottom:6px;">⏰</div>
            <h1 style="color:white;margin:0;font-size:20px;">Recordatorio de Seguimiento</h1>
            <p style="color:rgba(255,255,255,0.8);margin:6px 0 0;font-size:13px;">{vendedor['nombre']}</p>
        </div>
        <div style="background:white;padding:24px 30px;">
            <div style="background:#fff8e1;border-left:4px solid #f39c12;padding:14px 18px;border-radius:6px;margin-bottom:20px;">
                <p style="margin:0;color:#856404;font-size:14px;font-weight:bold;">
                    🔔 Este prospecto lleva más de 3 días registrado sin convertirse.
                    Es momento de contactarlo directamente.
                </p>
            </div>
            <table style="width:100%;border-collapse:collapse;">
                <tr style="border-bottom:1px solid #f0f0f0;">
                    <td style="padding:10px 0;color:#999;font-size:13px;width:35%;">👤 Nombre</td>
                    <td style="padding:10px 0;color:#2c3e50;font-weight:bold;font-size:15px;">{nombre}</td>
                </tr>
                <tr style="border-bottom:1px solid #f0f0f0;">
                    <td style="padding:10px 0;color:#999;font-size:13px;">📱 Teléfono</td>
                    <td style="padding:10px 0;color:#2c3e50;font-weight:bold;font-size:15px;">{telefono}</td>
                </tr>
                <tr style="border-bottom:1px solid #f0f0f0;">
                    <td style="padding:10px 0;color:#999;font-size:13px;">📧 Email</td>
                    <td style="padding:10px 0;color:#2c3e50;font-size:14px;">{email_prospecto}</td>
                </tr>
                <tr style="border-bottom:1px solid #f0f0f0;">
                    <td style="padding:10px 0;color:#999;font-size:13px;">📍 Zona</td>
                    <td style="padding:10px 0;color:#2c3e50;font-size:14px;">{zona}</td>
                </tr>
                <tr style="border-bottom:1px solid #f0f0f0;">
                    <td style="padding:10px 0;color:#999;font-size:13px;">💰 Presupuesto</td>
                    <td style="padding:10px 0;color:#27ae60;font-weight:bold;font-size:14px;">{presupuesto_fmt}</td>
                </tr>
                <tr>
                    <td style="padding:10px 0;color:#999;font-size:13px;">📊 Prioridad</td>
                    <td style="padding:10px 0;font-size:13px;">
                        <span style="background:{prioridad_color};color:white;padding:3px 10px;border-radius:20px;font-size:12px;font-weight:bold;">
                            {urgencia}
                        </span>
                    </td>
                </tr>
            </table>
            <div style="background:#f0fff4;border-left:4px solid #27ae60;padding:14px 18px;border-radius:6px;margin:20px 0;">
                <p style="margin:0;color:#2c3e50;font-size:13px;">
                    💡 <strong>Mensaje sugerido:</strong><br><br>
                    <em>"Hola {nombre_corto}, hace unos días buscabas propiedades en {zona}.
                    Tenemos opciones nuevas que podrían interesarte. ¿Tienes 5 minutos esta semana?"</em>
                </p>
            </div>
            <div style="text-align:center;margin-top:20px;">
                <a href="https://wa.me/{telefono}?text={wa_msg}"
                   style="background:#25D366;color:white;padding:14px 32px;border-radius:8px;text-decoration:none;font-weight:bold;font-size:14px;display:inline-block;">
                    📱 Contactar a {nombre_corto} por WhatsApp
                </a>
            </div>
        </div>
        <div style="background:#f8f9fa;padding:14px 30px;border-top:1px solid #eee;">
            <p style="color:#999;font-size:11px;margin:0;text-align:center;">
                Recordatorio automático — {datetime.now().strftime('%d/%m/%Y a las %H:%M')} — {vendedor['nombre']}
            </p>
        </div>
    </div>
    """
    return _enviar(
        vendedor["email_api_key"],
        vendedor["email_vendedor"],
        f"⏰ Seguimiento: {nombre} en {zona} — contactar hoy | {vendedor['nombre']}",
        html
    )
