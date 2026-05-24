# ============================================
# SERVICIO DE EMAIL SIMPLE
# ============================================
# Lee de config_clientes.py
# Si premium_email = True, envía email
# Si premium_email = False, no hace nada

import requests
from config_clientes import CLIENTES

def enviar_email_lead(cliente_id, nombre, email_cliente):
    """
    Envía email simple al cliente que llenó el formulario.
    
    Solo funciona si en config_clientes tiene:
    "premium_email": True
    """
    
    vendedor = CLIENTES.get(cliente_id.lower())
    
    # Si no tiene premium_email activado, no hace nada
    if not vendedor or not vendedor.get("premium_email", False):
        return True
    
    # Si llegamos aquí, tiene email activado
    api_key = vendedor.get("email_api_key", "")
    
    if not api_key:
        print("⚠️ Email activado pero sin API KEY configurada")
        return False
    
    try:
        # Usar Resend (gratis, fácil)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "from": "noreply@inmobiliaria.com",
            "to": email_cliente,
            "subject": f"✅ Recibimos tu solicitud, {nombre}",
            "html": f"""
            <h2>¡Hola {nombre}!</h2>
            <p>Gracias por tu interés.</p>
            <p>Recibimos tu solicitud correctamente.</p>
            <p>Nos contactaremos en 24 horas.</p>
            <p>Saludos,<br>Roberto Inmobiliaria</p>
            """
        }
        
        response = requests.post(
            "https://api.resend.com/emails",
            json=payload,
            headers=headers
        )
        
        if response.status_code == 200:
            print(f"✅ Email enviado a {email_cliente}")
            return True
        else:
            print(f"❌ Error: {response.text}")
            return False
    
    except Exception as e:
        print(f"❌ Error enviando email: {e}")
        return False
