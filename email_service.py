# ============================================
# SERVICIO DE EMAIL PROFESIONAL
# ============================================
# Notificaciones a vendedor + confirmación a cliente
import requests
from config_clientes import CLIENTES

def enviar_email_cliente(cliente_id, nombre, email_cliente):
    """
    Envía email de confirmación al cliente que llenó el formulario.
    """
    vendedor = CLIENTES.get(cliente_id.lower())
    
    if not vendedor or not vendedor.get("premium_email", False):
        return True
    
    api_key = vendedor.get("email_api_key", "")
    
    if not api_key:
        print("⚠️ Email activado pero sin API KEY configurada")
        return False
    
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "from": "noreply@inmobiliaria.com",
            "to": email_cliente,
            "subject": f"✅ Recibimos tu solicitud, {nombre}",
            "html": f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #2c3e50;">¡Hola {nombre}!</h2>
                <p style="color: #555; font-size: 14px;">Gracias por tu interés en nuestros servicios inmobiliarios.</p>
                <p style="color: #555; font-size: 14px;">Recibimos tu solicitud correctamente y nos pondremos en contacto en <strong>24 horas</strong>.</p>
                <p style="color: #555; font-size: 14px;">Mientras tanto, puedes seguir explorando nuestras propiedades.</p>
                <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                <p style="color: #999; font-size: 12px;">Saludos,<br><strong>{vendedor['nombre']}</strong></p>
            </div>
            """
        }
        
        response = requests.post(
            "https://api.resend.com/emails",
            json=payload,
            headers=headers
        )
        
        if response.status_code == 200:
            print(f"✅ Email confirmación enviado a {email_cliente}")
            return True
        else:
            print(f"❌ Error: {response.text}")
            return False
    
    except Exception as e:
        print(f"❌ Error enviando email: {e}")
        return False


def notificar_vendedor_lead_nuevo(cliente_id, nombre, telefono, zona, presupuesto, mensaje, score):
    """
    Notifica al vendedor cuando se registra un LEAD NUEVO.
    """
    vendedor = CLIENTES.get(cliente_id.lower())
    
    if not vendedor:
        return False
    
    email_vendedor = vendedor.get("email_vendedor", "")
    api_key = vendedor.get("email_api_key", "")
    
    if not email_vendedor or not api_key:
        print(f"⚠️ No se puede notificar - falta email_vendedor o API_KEY")
        return False
    
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        # Determinar nivel de urgencia
        if score >= 85:
            urgencia = "🔥🔥 URGENTE - VIP/INVERSIONISTA"
            color = "#e74c3c"
        elif score >= 65:
            urgencia = "🔥 ALTA - PROSPECTO A"
            color = "#f39c12"
        elif score >= 40:
            urgencia = "🟡 MEDIA - SEGUIMIENTO B"
            color = "#3498db"
        else:
            urgencia = "❄️ BAJA - LEAD FRÍO"
            color = "#95a5a6"
        
        payload = {
            "from": "noreply@inmobiliaria.com",
            "to": email_vendedor,
            "subject": f"🆕 NUEVO LEAD: {nombre} (Score: {score}/100)",
            "html": f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background: {color}; color: white; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
                    <h2 style="margin: 0; font-size: 18px;">{urgencia}</h2>
                </div>
                
                <h3 style="color: #2c3e50; margin-top: 0;">Detalles del Prospecto:</h3>
                
                <table style="width: 100%; border-collapse: collapse;">
                    <tr style="background: #f8f9fa;">
                        <td style="padding: 10px; border: 1px solid #eee; font-weight: bold; color: #2c3e50;">Nombre:</td>
                        <td style="padding: 10px; border: 1px solid #eee;">{nombre}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border: 1px solid #eee; font-weight: bold; color: #2c3e50;">Teléfono:</td>
                        <td style="padding: 10px; border: 1px solid #eee;"><a href="https://wa.me/{telefono}" style="color: #27ae60; text-decoration: none;">📱 {telefono}</a></td>
                    </tr>
                    <tr style="background: #f8f9fa;">
                        <td style="padding: 10px; border: 1px solid #eee; font-weight: bold; color: #2c3e50;">Zona:</td>
                        <td style="padding: 10px; border: 1px solid #eee;">{zona}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border: 1px solid #eee; font-weight: bold; color: #2c3e50;">Presupuesto:</td>
                        <td style="padding: 10px; border: 1px solid #eee;">${presupuesto}</td>
                    </tr>
                    <tr style="background: #f8f9fa;">
                        <td style="padding: 10px; border: 1px solid #eee; font-weight: bold; color: #2c3e50;">Score:</td>
                        <td style="padding: 10px; border: 1px solid #eee;"><strong>{score}/100</strong></td>
                    </tr>
                </table>
                
                <h4 style="color: #2c3e50; margin-top: 20px;">Mensaje:</h4>
                <p style="background: #f8f9fa; padding: 15px; border-radius: 8px; color: #555;">{mensaje}</p>
                
                <div style="background: #ecf0f1; padding: 15px; border-radius: 8px; margin-top: 20px;">
                    <p style="margin: 0; color: #555; font-size: 12px;">
                        ⏰ Registrado: {__import__('datetime').datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
                    </p>
                    <p style="margin: 10px 0 0 0; color: #555; font-size: 12px;">
                        💡 Este lead fue registrado automáticamente en tu CRM
                    </p>
                </div>
                
                <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                <p style="color: #999; font-size: 12px; text-align: center;">Bot Inmobiliaria V1 - Sistema Automático</p>
            </div>
            """
        }
        
        response = requests.post(
            "https://api.resend.com/emails",
            json=payload,
            headers=headers
        )
        
        if response.status_code == 200:
            print(f"✅ Notificación de lead nuevo enviada a {email_vendedor}")
            return True
        else:
            print(f"❌ Error: {response.text}")
            return False
    
    except Exception as e:
        print(f"❌ Error enviando notificación: {e}")
        return False


def notificar_vendedor_cliente_marcado(cliente_id, nombre, telefono, zona, presupuesto):
    """
    Notifica al vendedor cuando se MARCA UN CLIENTE.
    """
    vendedor = CLIENTES.get(cliente_id.lower())
    
    if not vendedor:
        return False
    
    email_vendedor = vendedor.get("email_vendedor", "")
    api_key = vendedor.get("email_api_key", "")
    
    if not email_vendedor or not api_key:
        return False
    
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "from": "noreply@inmobiliaria.com",
            "to": email_vendedor,
            "subject": f"💎 NUEVO CLIENTE: {nombre}",
            "html": f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background: #27ae60; color: white; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
                    <h2 style="margin: 0; font-size: 18px;">💎 CLIENTE CONFIRMADO</h2>
                </div>
                
                <h3 style="color: #2c3e50; margin-top: 0;">¡Felicidades! Nuevo cliente:</h3>
                
                <table style="width: 100%; border-collapse: collapse;">
                    <tr style="background: #f8f9fa;">
                        <td style="padding: 10px; border: 1px solid #eee; font-weight: bold; color: #2c3e50;">Nombre:</td>
                        <td style="padding: 10px; border: 1px solid #eee;"><strong>{nombre}</strong></td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border: 1px solid #eee; font-weight: bold; color: #2c3e50;">Teléfono:</td>
                        <td style="padding: 10px; border: 1px solid #eee;"><a href="https://wa.me/{telefono}" style="color: #27ae60; text-decoration: none;">📱 {telefono}</a></td>
                    </tr>
                    <tr style="background: #f8f9fa;">
                        <td style="padding: 10px; border: 1px solid #eee; font-weight: bold; color: #2c3e50;">Zona de Interés:</td>
                        <td style="padding: 10px; border: 1px solid #eee;">{zona}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border: 1px solid #eee; font-weight: bold; color: #2c3e50;">Presupuesto:</td>
                        <td style="padding: 10px; border: 1px solid #eee;">${presupuesto}</td>
                    </tr>
                </table>
                
                <div style="background: #d5f4e6; padding: 15px; border-radius: 8px; margin-top: 20px; border-left: 4px solid #27ae60;">
                    <p style="margin: 0; color: #27ae60; font-weight: bold;">✅ Este cliente está listo para seguimiento</p>
                    <p style="margin: 10px 0 0 0; color: #555; font-size: 12px;">Te recomendamos contactar en las próximas 24 horas</p>
                </div>
                
                <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                <p style="color: #999; font-size: 12px; text-align: center;">Bot Inmobiliaria V1 - Sistema Automático</p>
            </div>
            """
        }
        
        response = requests.post(
            "https://api.resend.com/emails",
            json=payload,
            headers=headers
        )
        
        if response.status_code == 200:
            print(f"✅ Notificación de cliente marcado enviada a {email_vendedor}")
            return True
        else:
            print(f"❌ Error: {response.text}")
            return False
    
    except Exception as e:
        print(f"❌ Error enviando notificación: {e}")
        return False
