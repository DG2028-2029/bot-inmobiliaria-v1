import requests
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from supabase import create_client
from cryptography.fernet import Fernet

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

# ============================================================
# ✅ TRADUCCIONES — emails que respetan el idioma del cliente
# ============================================================

T_RESET = {
    'es': {
        'titulo': 'Restablecer contraseña', 'tipo_asesor': 'Asesor', 'tipo_dueno': 'Dueño',
        'saludo': 'Hola', 'parrafo': 'Recibimos una solicitud para restablecer la contraseña de tu cuenta ({tipo}) en el panel de {nombre_empresa}. Si fuiste tú, hacé clic en el siguiente botón para crear una nueva contraseña:',
        'boton': '🔑 Crear nueva contraseña',
        'nota': 'Este enlace expira en 1 hora por seguridad. Si no solicitaste este cambio, podés ignorar este correo y tu contraseña actual seguirá funcionando.',
        'footer': 'Solicitado el', 'asunto': '🔐 Restablecer contraseña — {nombre_empresa}'
    },
    'en': {
        'titulo': 'Reset your password', 'tipo_asesor': 'Agent', 'tipo_dueno': 'Owner',
        'saludo': 'Hi', 'parrafo': 'We received a request to reset the password for your ({tipo}) account on {nombre_empresa}\'s panel. If this was you, click the button below to create a new password:',
        'boton': '🔑 Create new password',
        'nota': 'This link expires in 1 hour for security. If you did not request this change, you can ignore this email and your current password will keep working.',
        'footer': 'Requested on', 'asunto': '🔐 Reset your password — {nombre_empresa}'
    },
    'fr': {
        'titulo': 'Réinitialiser le mot de passe', 'tipo_asesor': 'Agent', 'tipo_dueno': 'Propriétaire',
        'saludo': 'Bonjour', 'parrafo': 'Nous avons reçu une demande de réinitialisation du mot de passe de votre compte ({tipo}) sur le panneau de {nombre_empresa}. Si c\'était vous, cliquez sur le bouton ci-dessous pour créer un nouveau mot de passe :',
        'boton': '🔑 Créer un nouveau mot de passe',
        'nota': 'Ce lien expire dans 1 heure par sécurité. Si vous n\'avez pas demandé ce changement, vous pouvez ignorer cet e-mail et votre mot de passe actuel continuera de fonctionner.',
        'footer': 'Demandé le', 'asunto': '🔐 Réinitialiser le mot de passe — {nombre_empresa}'
    },
    'de': {
        'titulo': 'Passwort zurücksetzen', 'tipo_asesor': 'Makler', 'tipo_dueno': 'Inhaber',
        'saludo': 'Hallo', 'parrafo': 'Wir haben eine Anfrage zum Zurücksetzen des Passworts für Ihr Konto ({tipo}) im Panel von {nombre_empresa} erhalten. Wenn Sie das waren, klicken Sie auf die Schaltfläche unten, um ein neues Passwort zu erstellen:',
        'boton': '🔑 Neues Passwort erstellen',
        'nota': 'Dieser Link läuft aus Sicherheitsgründen in 1 Stunde ab. Wenn Sie diese Änderung nicht angefordert haben, können Sie diese E-Mail ignorieren und Ihr aktuelles Passwort funktioniert weiterhin.',
        'footer': 'Angefordert am', 'asunto': '🔐 Passwort zurücksetzen — {nombre_empresa}'
    },
    'pt': {
        'titulo': 'Redefinir senha', 'tipo_asesor': 'Corretor', 'tipo_dueno': 'Proprietário',
        'saludo': 'Olá', 'parrafo': 'Recebemos uma solicitação para redefinir a senha da sua conta ({tipo}) no painel de {nombre_empresa}. Se foi você, clique no botão abaixo para criar uma nova senha:',
        'boton': '🔑 Criar nova senha',
        'nota': 'Este link expira em 1 hora por segurança. Se você não solicitou esta alteração, pode ignorar este e-mail e sua senha atual continuará funcionando.',
        'footer': 'Solicitado em', 'asunto': '🔐 Redefinir senha — {nombre_empresa}'
    },
    'zh': {
        'titulo': '重置密码', 'tipo_asesor': '经纪人', 'tipo_dueno': '业主',
        'saludo': '您好', 'parrafo': '我们收到了重置您在{nombre_empresa}面板上的（{tipo}）账户密码的请求。如果是您本人操作，请点击下方按钮创建新密码：',
        'boton': '🔑 创建新密码',
        'nota': '出于安全考虑，此链接将在1小时后失效。如果您没有请求此更改，可以忽略此邮件，您当前的密码将继续有效。',
        'footer': '请求时间', 'asunto': '🔐 重置密码 — {nombre_empresa}'
    },
}

T_REPORTE = {
    'es': {
        'titulo': 'Reporte Semanal', 'nuevos': '🆕 Leads nuevos esta semana',
        'mejor': '🏆 Mejor lead de la semana:', 'score_txt': 'Score', 'en_zona': 'en',
        'riesgo': 'Tenés {n} lead(s) en riesgo de perderse (14+ días sin convertirse).',
        'footer': 'Reporte automático', 'asunto': '📊 Reporte Semanal — {nombre_empresa}'
    },
    'en': {
        'titulo': 'Weekly Report', 'nuevos': '🆕 New leads this week',
        'mejor': '🏆 Best lead of the week:', 'score_txt': 'Score', 'en_zona': 'in',
        'riesgo': 'You have {n} lead(s) at risk of being lost (14+ days without converting).',
        'footer': 'Automatic report', 'asunto': '📊 Weekly Report — {nombre_empresa}'
    },
    'fr': {
        'titulo': 'Rapport Hebdomadaire', 'nuevos': '🆕 Nouveaux leads cette semaine',
        'mejor': '🏆 Meilleur lead de la semaine :', 'score_txt': 'Score', 'en_zona': 'à',
        'riesgo': 'Vous avez {n} lead(s) en risque de perte (14+ jours sans conversion).',
        'footer': 'Rapport automatique', 'asunto': '📊 Rapport Hebdomadaire — {nombre_empresa}'
    },
    'de': {
        'titulo': 'Wochenbericht', 'nuevos': '🆕 Neue Leads diese Woche',
        'mejor': '🏆 Bester Lead der Woche:', 'score_txt': 'Score', 'en_zona': 'in',
        'riesgo': 'Sie haben {n} Lead(s) in Verlustgefahr (14+ Tage ohne Konvertierung).',
        'footer': 'Automatischer Bericht', 'asunto': '📊 Wochenbericht — {nombre_empresa}'
    },
    'pt': {
        'titulo': 'Relatório Semanal', 'nuevos': '🆕 Novos leads esta semana',
        'mejor': '🏆 Melhor lead da semana:', 'score_txt': 'Score', 'en_zona': 'em',
        'riesgo': 'Você tem {n} lead(s) em risco de se perder (14+ dias sem converter).',
        'footer': 'Relatório automático', 'asunto': '📊 Relatório Semanal — {nombre_empresa}'
    },
    'zh': {
        'titulo': '每周报告', 'nuevos': '🆕 本周新线索',
        'mejor': '🏆 本周最佳线索：', 'score_txt': '评分', 'en_zona': '于',
        'riesgo': '您有{n}条线索面临流失风险（超过14天未转化）。',
        'footer': '自动报告', 'asunto': '📊 每周报告 — {nombre_empresa}'
    },
}

def enviar_email_reset_password(cliente_id, nombre_destinatario, es_asesor, link_reset, lang='es'):
    """
    Envía el email con el link para restablecer contraseña, en el idioma
    del cliente (lang: 'es', 'en', 'fr', 'de', 'pt', 'zh').
    Con onboarding@resend.dev, solo llega bien al email verificado
    de la cuenta de Resend (normalmente el del dueño/vendedor).
    """
    vendedor = _get_cliente(cliente_id)
    if not vendedor:
        return False

    t = T_RESET.get(lang, T_RESET['es'])
    color = vendedor.get("color_primario", "#667eea")
    tipo_cuenta = t['tipo_asesor'] if es_asesor else t['tipo_dueno']
    parrafo = t['parrafo'].format(tipo=tipo_cuenta, nombre_empresa=vendedor['nombre'])

    html = f"""
    <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:600px;margin:0 auto;background:#f8f9fa;padding:0;border-radius:12px;overflow:hidden;">
        <div style="background:{color};padding:22px 30px;text-align:center;">
            <div style="font-size:32px;margin-bottom:6px;">🔐</div>
            <h1 style="color:white;margin:0;font-size:20px;">{t['titulo']}</h1>
            <p style="color:rgba(255,255,255,0.8);margin:6px 0 0;font-size:13px;">{vendedor['nombre']}</p>
        </div>
        <div style="background:white;padding:28px 30px;">
            <p style="color:#555;font-size:15px;">
                {t['saludo']} <strong>{nombre_destinatario}</strong>,
            </p>
            <p style="color:#555;font-size:14px;">
                {parrafo}
            </p>
            <div style="text-align:center;margin:26px 0;">
                <a href="{link_reset}"
                   style="background:{color};color:white;padding:14px 32px;border-radius:8px;text-decoration:none;font-weight:bold;font-size:14px;display:inline-block;">
                    {t['boton']}
                </a>
            </div>
            <p style="color:#999;font-size:12px;">
                {t['nota']}
            </p>
        </div>
        <div style="background:#f8f9fa;padding:14px 30px;text-align:center;border-top:1px solid #eee;">
            <p style="color:#999;font-size:12px;margin:0;">
                {t['footer']} {datetime.now().strftime('%d/%m/%Y a las %H:%M')} — {vendedor['nombre']}
            </p>
        </div>
    </div>
    """
    return _enviar(
        vendedor["email_api_key"],
        vendedor["email_vendedor"],
        t['asunto'].format(nombre_empresa=vendedor['nombre']),
        html
    )

def enviar_reporte_semanal(cliente_id, resumen, lang='es'):
    """
    Envía el reporte semanal automático al dueño del negocio, en el
    idioma del cliente (lang: 'es', 'en', 'fr', 'de', 'pt', 'zh').
    """
    vendedor = _get_cliente(cliente_id)
    if not vendedor or not vendedor.get("premium_email"):
        return False

    t = T_REPORTE.get(lang, T_REPORTE['es'])
    color = vendedor.get("color_primario", "#667eea")
    mejor = resumen.get("mejor_lead")

    mejor_html = ""
    if mejor:
        zona_txt = f" {t['en_zona']} {mejor['zona']}" if mejor.get('zona') else ""
        mejor_html = f"""
        <div style="background:#f0fff4;border-left:4px solid #27ae60;padding:14px 18px;border-radius:6px;margin-top:16px;">
            <p style="margin:0;color:#2c3e50;font-size:13px;">
                {t['mejor']} {mejor['nombre']} — {t['score_txt']} {mejor['score']}/100{zona_txt}
            </p>
        </div>
        """

    riesgo_html = ""
    if resumen.get("en_riesgo", 0) > 0:
        riesgo_texto = t['riesgo'].format(n=resumen['en_riesgo'])
        riesgo_html = f"""
        <div style="background:#fff5f5;border-left:4px solid #c0392b;padding:14px 18px;border-radius:6px;margin-top:12px;">
            <p style="margin:0;color:#7f0000;font-size:13px;font-weight:bold;">
                🚨 {riesgo_texto}
            </p>
        </div>
        """

    html = f"""
    <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:600px;margin:0 auto;background:#f8f9fa;padding:0;border-radius:12px;overflow:hidden;">
        <div style="background:linear-gradient(135deg,{color},#1a1a2e);padding:24px 30px;text-align:center;">
            <div style="font-size:32px;margin-bottom:6px;">📊</div>
            <h1 style="color:white;margin:0;font-size:20px;">{t['titulo']}</h1>
            <p style="color:rgba(255,255,255,0.8);margin:6px 0 0;font-size:13px;">{vendedor['nombre']}</p>
        </div>
        <div style="background:white;padding:26px 30px;">
            <table style="width:100%;border-collapse:collapse;">
                <tr>
                    <td style="padding:12px 0;color:#999;font-size:13px;">{t['nuevos']}</td>
                    <td style="padding:12px 0;color:#2c3e50;font-weight:bold;font-size:18px;text-align:right;">{resumen['nuevos']}</td>
                </tr>
            </table>
            {mejor_html}
            {riesgo_html}
        </div>
        <div style="background:#f8f9fa;padding:14px 30px;text-align:center;border-top:1px solid #eee;">
            <p style="color:#999;font-size:11px;margin:0;">
                {t['footer']} — {datetime.now().strftime('%d/%m/%Y')} — {vendedor['nombre']}
            </p>
        </div>
    </div>
    """
    return _enviar(
        vendedor["email_api_key"],
        vendedor["email_vendedor"],
        t['asunto'].format(nombre_empresa=vendedor['nombre']),
        html
    )

T_VISITA = {
    'es': {
        'titulo_24h': 'Recordatorio: Visita mañana', 'titulo_3h': 'Recordatorio: Visita en 3 horas',
        'saludo': 'Hola', 'con': 'con', 'sin_propiedad': 'propiedad a agendar',
        'msg_24h': 'Tienes una visita programada mañana con este prospecto. Aquí el detalle:',
        'msg_3h': 'Tu visita con este prospecto es en aproximadamente 3 horas. ¡No lo olvides!',
        'fecha_lbl': '📅 Fecha y hora', 'prop_lbl': '🏠 Propiedad', 'tel_lbl': '📱 Teléfono',
        'wa_btn': '📱 Confirmar por WhatsApp', 'footer': 'Recordatorio automático',
        'asunto_24h': '📅 Mañana: visita con {nombre} — {empresa}',
        'asunto_3h': '⏰ En 3 horas: visita con {nombre} — {empresa}',
        'wa_msg': 'Hola {nombre}, le escribo para confirmar nuestra visita programada. ¿Seguimos en pie?'
    },
    'en': {
        'titulo_24h': 'Reminder: Visit tomorrow', 'titulo_3h': 'Reminder: Visit in 3 hours',
        'saludo': 'Hi', 'con': 'with', 'sin_propiedad': 'property to be scheduled',
        'msg_24h': 'You have a visit scheduled tomorrow with this prospect. Details below:',
        'msg_3h': 'Your visit with this prospect is in about 3 hours. Don\'t forget!',
        'fecha_lbl': '📅 Date and time', 'prop_lbl': '🏠 Property', 'tel_lbl': '📱 Phone',
        'wa_btn': '📱 Confirm via WhatsApp', 'footer': 'Automatic reminder',
        'asunto_24h': '📅 Tomorrow: visit with {nombre} — {empresa}',
        'asunto_3h': '⏰ In 3 hours: visit with {nombre} — {empresa}',
        'wa_msg': 'Hi {nombre}, writing to confirm our scheduled visit. Are we still on?'
    },
    'fr': {
        'titulo_24h': 'Rappel : Visite demain', 'titulo_3h': 'Rappel : Visite dans 3 heures',
        'saludo': 'Bonjour', 'con': 'avec', 'sin_propiedad': 'propriété à définir',
        'msg_24h': 'Vous avez une visite prévue demain avec ce prospect. Détails ci-dessous :',
        'msg_3h': 'Votre visite avec ce prospect est dans environ 3 heures. N\'oubliez pas !',
        'fecha_lbl': '📅 Date et heure', 'prop_lbl': '🏠 Propriété', 'tel_lbl': '📱 Téléphone',
        'wa_btn': '📱 Confirmer par WhatsApp', 'footer': 'Rappel automatique',
        'asunto_24h': '📅 Demain : visite avec {nombre} — {empresa}',
        'asunto_3h': '⏰ Dans 3 heures : visite avec {nombre} — {empresa}',
        'wa_msg': 'Bonjour {nombre}, je vous écris pour confirmer notre visite prévue. C\'est toujours bon ?'
    },
    'de': {
        'titulo_24h': 'Erinnerung: Besichtigung morgen', 'titulo_3h': 'Erinnerung: Besichtigung in 3 Stunden',
        'saludo': 'Hallo', 'con': 'mit', 'sin_propiedad': 'noch zu planende Immobilie',
        'msg_24h': 'Sie haben morgen eine Besichtigung mit diesem Interessenten. Details unten:',
        'msg_3h': 'Ihre Besichtigung mit diesem Interessenten ist in etwa 3 Stunden. Nicht vergessen!',
        'fecha_lbl': '📅 Datum und Uhrzeit', 'prop_lbl': '🏠 Immobilie', 'tel_lbl': '📱 Telefon',
        'wa_btn': '📱 Per WhatsApp bestätigen', 'footer': 'Automatische Erinnerung',
        'asunto_24h': '📅 Morgen: Besichtigung mit {nombre} — {empresa}',
        'asunto_3h': '⏰ In 3 Stunden: Besichtigung mit {nombre} — {empresa}',
        'wa_msg': 'Hallo {nombre}, ich schreibe, um unsere geplante Besichtigung zu bestätigen. Bleibt es dabei?'
    },
    'pt': {
        'titulo_24h': 'Lembrete: Visita amanhã', 'titulo_3h': 'Lembrete: Visita em 3 horas',
        'saludo': 'Olá', 'con': 'com', 'sin_propiedad': 'imóvel a definir',
        'msg_24h': 'Você tem uma visita agendada amanhã com este prospecto. Detalhes abaixo:',
        'msg_3h': 'Sua visita com este prospecto é em aproximadamente 3 horas. Não esqueça!',
        'fecha_lbl': '📅 Data e hora', 'prop_lbl': '🏠 Imóvel', 'tel_lbl': '📱 Telefone',
        'wa_btn': '📱 Confirmar via WhatsApp', 'footer': 'Lembrete automático',
        'asunto_24h': '📅 Amanhã: visita com {nombre} — {empresa}',
        'asunto_3h': '⏰ Em 3 horas: visita com {nombre} — {empresa}',
        'wa_msg': 'Olá {nombre}, escrevo para confirmar nossa visita agendada. Continua de pé?'
    },
    'zh': {
        'titulo_24h': '提醒：明天有参观', 'titulo_3h': '提醒：3小时后有参观',
        'saludo': '您好', 'con': '与', 'sin_propiedad': '待定房产',
        'msg_24h': '您明天与该潜在客户有一个预约参观。详情如下：',
        'msg_3h': '您与该潜在客户的参观大约3小时后开始。请不要忘记！',
        'fecha_lbl': '📅 日期和时间', 'prop_lbl': '🏠 房产', 'tel_lbl': '📱 电话',
        'wa_btn': '📱 通过WhatsApp确认', 'footer': '自动提醒',
        'asunto_24h': '📅 明天：与{nombre}的参观 — {empresa}',
        'asunto_3h': '⏰ 3小时后：与{nombre}的参观 — {empresa}',
        'wa_msg': '您好{nombre}，写信确认我们预约的参观。还继续吗？'
    },
}

def enviar_recordatorio_visita(cliente_id, lead_nombre, lead_telefono, fecha_visita_str, propiedad_titulo, tipo, lang='es'):
    """
    Envía recordatorio de visita al VENDEDOR (limitación de onboarding@resend.dev,
    mismo patrón que enviar_seguimiento_automatico). tipo: '24h' o '3h'.
    """
    vendedor = _get_cliente(cliente_id)
    if not vendedor or not vendedor.get("premium_email"):
        return False

    t = T_VISITA.get(lang, T_VISITA['es'])
    color = vendedor.get("color_primario", "#667eea")
    nombre_corto = lead_nombre.split()[0] if lead_nombre else lead_nombre
    titulo = t['titulo_24h'] if tipo == '24h' else t['titulo_3h']
    mensaje_intro = t['msg_24h'] if tipo == '24h' else t['msg_3h']
    asunto_tpl = t['asunto_24h'] if tipo == '24h' else t['asunto_3h']
    prop_txt = propiedad_titulo if propiedad_titulo else t['sin_propiedad']

    wa_msg = requests.utils.quote(t['wa_msg'].format(nombre=nombre_corto))

    html = f"""
    <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:600px;margin:0 auto;background:#f8f9fa;padding:0;border-radius:12px;overflow:hidden;">
        <div style="background:linear-gradient(135deg,{color},#1a1a2e);padding:22px 30px;text-align:center;">
            <div style="font-size:32px;margin-bottom:6px;">📅</div>
            <h1 style="color:white;margin:0;font-size:20px;">{titulo}</h1>
            <p style="color:rgba(255,255,255,0.8);margin:6px 0 0;font-size:13px;">{vendedor['nombre']}</p>
        </div>
        <div style="background:white;padding:24px 30px;">
            <p style="color:#555;font-size:14px;">{mensaje_intro}</p>
            <table style="width:100%;border-collapse:collapse;margin-top:10px;">
                <tr style="border-bottom:1px solid #f0f0f0;">
                    <td style="padding:10px 0;color:#999;font-size:13px;width:35%;">👤 {t['saludo']} — {t['con']}</td>
                    <td style="padding:10px 0;color:#2c3e50;font-weight:bold;font-size:15px;">{lead_nombre}</td>
                </tr>
                <tr style="border-bottom:1px solid #f0f0f0;">
                    <td style="padding:10px 0;color:#999;font-size:13px;">{t['fecha_lbl']}</td>
                    <td style="padding:10px 0;color:#2c3e50;font-weight:bold;font-size:14px;">{fecha_visita_str}</td>
                </tr>
                <tr style="border-bottom:1px solid #f0f0f0;">
                    <td style="padding:10px 0;color:#999;font-size:13px;">{t['prop_lbl']}</td>
                    <td style="padding:10px 0;color:#2c3e50;font-size:14px;">{prop_txt}</td>
                </tr>
                <tr>
                    <td style="padding:10px 0;color:#999;font-size:13px;">{t['tel_lbl']}</td>
                    <td style="padding:10px 0;color:#2c3e50;font-weight:bold;font-size:14px;">{lead_telefono}</td>
                </tr>
            </table>
            <div style="text-align:center;margin-top:22px;">
                <a href="https://wa.me/{lead_telefono}?text={wa_msg}"
                   style="background:#25D366;color:white;padding:13px 28px;border-radius:8px;text-decoration:none;font-weight:bold;font-size:14px;display:inline-block;">
                    {t['wa_btn']}
                </a>
            </div>
        </div>
        <div style="background:#f8f9fa;padding:14px 30px;text-align:center;border-top:1px solid #eee;">
            <p style="color:#999;font-size:11px;margin:0;">
                {t['footer']} — {datetime.now().strftime('%d/%m/%Y a las %H:%M')} — {vendedor['nombre']}
            </p>
        </div>
    </div>
    """
    return _enviar(
        vendedor["email_api_key"],
        vendedor["email_vendedor"],
        asunto_tpl.format(nombre=lead_nombre, empresa=vendedor['nombre']),
        html
    )

# ============================================================
# ✅ ENVÍO DIRECTO AL PROSPECTO (Gmail SMTP por cliente)
# ============================================================

_encryption_key = os.environ.get("ENCRYPTION_KEY", "")
_fernet = Fernet(_encryption_key.encode()) if _encryption_key else None

def _descifrar(texto_cifrado):
    if not texto_cifrado or not _fernet:
        return None
    try:
        return _fernet.decrypt(texto_cifrado.encode()).decode()
    except Exception:
        return None

def _enviar_via_gmail(gmail_email, gmail_app_password, destinatario, asunto, html):
    """Manda un correo real vía smtp.gmail.com, autenticado con una
    contraseña de aplicación de Google. Método oficial, no un truco."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = asunto
        msg["From"] = gmail_email
        msg["To"] = destinatario
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
            server.starttls()
            server.login(gmail_email, gmail_app_password)
            server.sendmail(gmail_email, destinatario, msg.as_string())
        print(f"✅ Email (Gmail) enviado a {destinatario}")
        return True
    except Exception as e:
        print(f"❌ Error enviando por Gmail: {e}")
        return False

def enviar_correo_prospecto(cliente_id, destinatario_email, asunto, html):
    """
    ✅ FUNCIÓN CENTRAL — envía un correo DIRECTO al prospecto (no al
    vendedor), eligiendo el proveedor según lo que tenga configurado
    ese cliente en Supabase (columna proveedor_email).

    - 'google'  → Gmail SMTP con la contraseña de aplicación cifrada del cliente.
    - 'resend'  → 🔜 pendiente (requiere dominio propio verificado).
    - 'ninguno' o vacío → no se envía nada (silencioso, no rompe el flujo).

    Este es el único lugar que hay que tocar el día que se active Resend
    con dominio propio — todo lo demás en el sistema sigue igual.
    """
    if not destinatario_email:
        return False
    vendedor = _get_cliente(cliente_id)
    if not vendedor:
        return False

    proveedor = vendedor.get("proveedor_email", "ninguno")

    if proveedor == "google":
        gmail_email = vendedor.get("gmail_email", "")
        gmail_password = _descifrar(vendedor.get("gmail_app_password_cifrada", ""))
        if not gmail_email or not gmail_password:
            print(f"⚠️ Cliente {cliente_id}: proveedor 'google' configurado pero faltan credenciales")
            return False
        return _enviar_via_gmail(gmail_email, gmail_password, destinatario_email, asunto, html)

    elif proveedor == "resend":
        print(f"ℹ️ Cliente {cliente_id}: proveedor 'resend' aún no implementado para envío directo")
        return False

    else:
        return False

T_VISITA_PROSPECTO = {
    'es': {
        'confirmacion_titulo': '¡Tu visita ha sido agendada!',
        'confirmacion_msg': 'Hola {nombre}, tu visita quedó confirmada. Aquí el detalle:',
        'recordatorio_24h_titulo': 'Recordatorio: tu visita es mañana',
        'recordatorio_24h_msg': 'Hola {nombre}, te recordamos que tu visita es mañana.',
        'recordatorio_3h_titulo': 'Tu visita es en unas horas',
        'recordatorio_3h_msg': 'Hola {nombre}, tu visita es en aproximadamente 3 horas. ¡Te esperamos!',
        'fecha_lbl': '📅 Fecha y hora', 'prop_lbl': '🏠 Propiedad', 'sin_propiedad': 'Por definir',
        'wa_btn': '📱 Escribir por WhatsApp', 'footer': 'Mensaje automático de',
        'asunto_confirmacion': '📅 Visita confirmada — {empresa}',
        'asunto_24h': '📅 Mañana es tu visita — {empresa}',
        'asunto_3h': '⏰ Tu visita es en unas horas — {empresa}',
        'wa_msg': 'Hola, tengo una pregunta sobre mi visita agendada.'
    },
    'en': {
        'confirmacion_titulo': 'Your visit has been scheduled!',
        'confirmacion_msg': 'Hi {nombre}, your visit is confirmed. Details below:',
        'recordatorio_24h_titulo': 'Reminder: your visit is tomorrow',
        'recordatorio_24h_msg': 'Hi {nombre}, just a reminder that your visit is tomorrow.',
        'recordatorio_3h_titulo': 'Your visit is in a few hours',
        'recordatorio_3h_msg': 'Hi {nombre}, your visit is in about 3 hours. See you soon!',
        'fecha_lbl': '📅 Date and time', 'prop_lbl': '🏠 Property', 'sin_propiedad': 'To be defined',
        'wa_btn': '📱 Message on WhatsApp', 'footer': 'Automatic message from',
        'asunto_confirmacion': '📅 Visit confirmed — {empresa}',
        'asunto_24h': '📅 Your visit is tomorrow — {empresa}',
        'asunto_3h': '⏰ Your visit is in a few hours — {empresa}',
        'wa_msg': 'Hi, I have a question about my scheduled visit.'
    },
    'fr': {
        'confirmacion_titulo': 'Votre visite est confirmée !',
        'confirmacion_msg': 'Bonjour {nombre}, votre visite est confirmée. Détails ci-dessous :',
        'recordatorio_24h_titulo': 'Rappel : votre visite est demain',
        'recordatorio_24h_msg': 'Bonjour {nombre}, un petit rappel : votre visite est demain.',
        'recordatorio_3h_titulo': 'Votre visite est dans quelques heures',
        'recordatorio_3h_msg': 'Bonjour {nombre}, votre visite est dans environ 3 heures. À bientôt !',
        'fecha_lbl': '📅 Date et heure', 'prop_lbl': '🏠 Propriété', 'sin_propiedad': 'À définir',
        'wa_btn': '📱 Écrire sur WhatsApp', 'footer': 'Message automatique de',
        'asunto_confirmacion': '📅 Visite confirmée — {empresa}',
        'asunto_24h': '📅 Votre visite est demain — {empresa}',
        'asunto_3h': '⏰ Votre visite est dans quelques heures — {empresa}',
        'wa_msg': "Bonjour, j'ai une question sur ma visite prévue."
    },
    'de': {
        'confirmacion_titulo': 'Ihre Besichtigung ist bestätigt!',
        'confirmacion_msg': 'Hallo {nombre}, Ihre Besichtigung ist bestätigt. Details unten:',
        'recordatorio_24h_titulo': 'Erinnerung: Ihre Besichtigung ist morgen',
        'recordatorio_24h_msg': 'Hallo {nombre}, eine kurze Erinnerung: Ihre Besichtigung ist morgen.',
        'recordatorio_3h_titulo': 'Ihre Besichtigung ist in wenigen Stunden',
        'recordatorio_3h_msg': 'Hallo {nombre}, Ihre Besichtigung ist in etwa 3 Stunden. Bis gleich!',
        'fecha_lbl': '📅 Datum und Uhrzeit', 'prop_lbl': '🏠 Immobilie', 'sin_propiedad': 'Noch offen',
        'wa_btn': '📱 Auf WhatsApp schreiben', 'footer': 'Automatische Nachricht von',
        'asunto_confirmacion': '📅 Besichtigung bestätigt — {empresa}',
        'asunto_24h': '📅 Ihre Besichtigung ist morgen — {empresa}',
        'asunto_3h': '⏰ Ihre Besichtigung ist in wenigen Stunden — {empresa}',
        'wa_msg': 'Hallo, ich habe eine Frage zu meiner geplanten Besichtigung.'
    },
    'pt': {
        'confirmacion_titulo': 'Sua visita foi confirmada!',
        'confirmacion_msg': 'Olá {nombre}, sua visita está confirmada. Detalhes abaixo:',
        'recordatorio_24h_titulo': 'Lembrete: sua visita é amanhã',
        'recordatorio_24h_msg': 'Olá {nombre}, só lembrando que sua visita é amanhã.',
        'recordatorio_3h_titulo': 'Sua visita é em algumas horas',
        'recordatorio_3h_msg': 'Olá {nombre}, sua visita é em aproximadamente 3 horas. Até já!',
        'fecha_lbl': '📅 Data e hora', 'prop_lbl': '🏠 Imóvel', 'sin_propiedad': 'A definir',
        'wa_btn': '📱 Falar no WhatsApp', 'footer': 'Mensagem automática de',
        'asunto_confirmacion': '📅 Visita confirmada — {empresa}',
        'asunto_24h': '📅 Sua visita é amanhã — {empresa}',
        'asunto_3h': '⏰ Sua visita é em algumas horas — {empresa}',
        'wa_msg': 'Olá, tenho uma pergunta sobre minha visita agendada.'
    },
    'zh': {
        'confirmacion_titulo': '您的参观已确认！',
        'confirmacion_msg': '您好{nombre}，您的参观已确认。详情如下：',
        'recordatorio_24h_titulo': '提醒：您的参观是明天',
        'recordatorio_24h_msg': '您好{nombre}，提醒您明天有参观。',
        'recordatorio_3h_titulo': '您的参观将在几小时后',
        'recordatorio_3h_msg': '您好{nombre}，您的参观大约3小时后开始。到时见！',
        'fecha_lbl': '📅 日期和时间', 'prop_lbl': '🏠 房产', 'sin_propiedad': '待定',
        'wa_btn': '📱 通过WhatsApp联系', 'footer': '自动消息来自',
        'asunto_confirmacion': '📅 参观已确认 — {empresa}',
        'asunto_24h': '📅 您的参观是明天 — {empresa}',
        'asunto_3h': '⏰ 您的参观将在几小时后 — {empresa}',
        'wa_msg': '您好，我对我预约的参观有一个问题。'
    },
}

def _plantilla_visita_prospecto(vendedor, lead_nombre, fecha_visita_str, propiedad_titulo, t, titulo, mensaje_intro):
    color = vendedor.get("color_primario", "#667eea")
    wa = vendedor.get("whatsapp", "")
    prop_txt = propiedad_titulo if propiedad_titulo else t['sin_propiedad']
    wa_msg_q = requests.utils.quote(t['wa_msg'])
    wa_html = ""
    if wa:
        wa_html = f"""
            <div style="text-align:center;margin-top:22px;">
                <a href="https://wa.me/{wa}?text={wa_msg_q}"
                   style="background:#25D366;color:white;padding:13px 28px;border-radius:8px;text-decoration:none;font-weight:bold;font-size:14px;display:inline-block;">
                    {t['wa_btn']}
                </a>
            </div>
        """
    return f"""
    <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:600px;margin:0 auto;background:#f8f9fa;padding:0;border-radius:12px;overflow:hidden;">
        <div style="background:linear-gradient(135deg,{color},#1a1a2e);padding:22px 30px;text-align:center;">
            <div style="font-size:32px;margin-bottom:6px;">📅</div>
            <h1 style="color:white;margin:0;font-size:20px;">{titulo}</h1>
            <p style="color:rgba(255,255,255,0.8);margin:6px 0 0;font-size:13px;">{vendedor['nombre']}</p>
        </div>
        <div style="background:white;padding:24px 30px;">
            <p style="color:#555;font-size:14px;">{mensaje_intro}</p>
            <table style="width:100%;border-collapse:collapse;margin-top:10px;">
                <tr style="border-bottom:1px solid #f0f0f0;">
                    <td style="padding:10px 0;color:#999;font-size:13px;width:40%;">{t['fecha_lbl']}</td>
                    <td style="padding:10px 0;color:#2c3e50;font-weight:bold;font-size:14px;">{fecha_visita_str}</td>
                </tr>
                <tr>
                    <td style="padding:10px 0;color:#999;font-size:13px;">{t['prop_lbl']}</td>
                    <td style="padding:10px 0;color:#2c3e50;font-size:14px;">{prop_txt}</td>
                </tr>
            </table>
            {wa_html}
        </div>
        <div style="background:#f8f9fa;padding:14px 30px;text-align:center;border-top:1px solid #eee;">
            <p style="color:#999;font-size:11px;margin:0;">
                {t['footer']} {vendedor['nombre']}
            </p>
        </div>
    </div>
    """

def enviar_confirmacion_visita_prospecto(cliente_id, lead_nombre, lead_email, fecha_visita_str, propiedad_titulo, lang='es'):
    """Correo 1 de 3 (obligatorio) — confirmación inmediata al prospecto cuando se agenda la visita."""
    vendedor = _get_cliente(cliente_id)
    if not vendedor:
        return False
    t = T_VISITA_PROSPECTO.get(lang, T_VISITA_PROSPECTO['es'])
    nombre_corto = lead_nombre.split()[0] if lead_nombre else lead_nombre
    html = _plantilla_visita_prospecto(
        vendedor, lead_nombre, fecha_visita_str, propiedad_titulo, t,
        t['confirmacion_titulo'], t['confirmacion_msg'].format(nombre=nombre_corto)
    )
    asunto = t['asunto_confirmacion'].format(empresa=vendedor['nombre'])
    return enviar_correo_prospecto(cliente_id, lead_email, asunto, html)

def enviar_recordatorio_visita_prospecto(cliente_id, lead_nombre, lead_email, fecha_visita_str, propiedad_titulo, tipo, lang='es'):
    """Correos 2 y 3 de 3 (obligatorios) — recordatorio 24h o 3h antes, directo al prospecto. tipo: '24h' o '3h'."""
    vendedor = _get_cliente(cliente_id)
    if not vendedor:
        return False
    t = T_VISITA_PROSPECTO.get(lang, T_VISITA_PROSPECTO['es'])
    nombre_corto = lead_nombre.split()[0] if lead_nombre else lead_nombre
    if tipo == '24h':
        titulo = t['recordatorio_24h_titulo']
        mensaje = t['recordatorio_24h_msg'].format(nombre=nombre_corto)
        asunto_tpl = t['asunto_24h']
    else:
        titulo = t['recordatorio_3h_titulo']
        mensaje = t['recordatorio_3h_msg'].format(nombre=nombre_corto)
        asunto_tpl = t['asunto_3h']
    html = _plantilla_visita_prospecto(vendedor, lead_nombre, fecha_visita_str, propiedad_titulo, t, titulo, mensaje)
    asunto = asunto_tpl.format(empresa=vendedor['nombre'])
    return enviar_correo_prospecto(cliente_id, lead_email, asunto, html)
