# ============================================
# CONFIGURACIÓN DE EMAIL (OPCIONAL)
# ============================================

EMAIL_HABILITADO = False

EMAIL_PROVIDER = "resend"

RESEND_API_KEY = ""

SENDGRID_API_KEY = ""

EMAIL_REMITENTE = "noreply@inmobiliaria.com"
NOMBRE_REMITENTE = "Roberto Inmobiliaria"

EMAIL_CLIENTE_ASUNTO = "✅ Recibimos tu solicitud - {nombre}"

EMAIL_CLIENTE_CUERPO = """
Hola {nombre},

¡Gracias por tu interés!

Recibimos tu solicitud correctamente.
Nos contactaremos en 24 horas.

Saludos,
Roberto Inmobiliaria
"""

NOTIFICAR_VENDEDOR = True
