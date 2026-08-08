from flask import Flask, request, render_template, redirect, session, url_for, send_file, jsonify
from supabase import create_client
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import check_password_hash
import os
import re
import json
import urllib.request
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
                {'titulo': '💬 Consultivo', 'msg': f"Hola {nombre}, vi tu interés en propiedades en {zona}. Antes de enviarte opciones, ¿me puedes contar un poco más sobre lo que buscas? Así te mando exactamente lo que necesitas."},
                {'titulo': '📸 Propuesta directa', 'msg': f"Hola {nombre}! Tengo 3 propiedades en {zona} que podrían encajar con lo que buscas. ¿Te las envío ahora mismo con fotos y precios?"},
            ],
            'dia1_caliente': [
                {'titulo': '🔥 Llamada directa (recomendado)', 'msg': f"Hola {nombre}, le contacto porque ayer vi su interés en {zona} y hoy recibimos una propiedad que encaja perfectamente con {p}. ¿Le puedo enviar los detalles?"},
                {'titulo': '🏠 Agendar visita', 'msg': f"Hola {nombre}! Tengo propiedades en {zona} listas para visitar esta semana. ¿Cuándo le queda bien? Puedo acompañarle personalmente."},
                {'titulo': '💎 Exclusividad', 'msg': f"Hola {nombre}, tengo una propiedad en {zona} que acaba de entrar al mercado y aún no está publicada. Con su presupuesto de {p} encaja perfecto. ¿Le interesa verla primero?"},
            ],
            'dias3': [
                {'titulo': '📬 Micro-compromiso (recomendado)', 'msg': f"Hola {nombre}, ¿le puedo enviar 2-3 opciones en {zona} con fotos ahora mismo? Sin compromiso, solo para que vea si algo le llama la atención."},
                {'titulo': '💎 Alto valor', 'msg': f"Hola {nombre}, con un presupuesto de {p} en {zona} tiene acceso a propiedades con excelente potencial de valorización. Tengo 2 opciones exclusivas. ¿Las revisamos juntos esta semana?"},
                {'titulo': '📞 Cita rápida', 'msg': f"Hola {nombre}, ¿me permite 10 minutos esta semana? Tengo opciones nuevas en {zona} que creo le van a interesar mucho. ¿Cuándo le queda bien?"},
            ],
            'dias7': [
                {'titulo': '🔄 Nuevo contexto (recomendado)', 'msg': f"Hola {nombre}, ¿cómo está? Le escribo porque el mercado en {zona} cambió esta semana — bajaron 2 propiedades de precio. ¿Sigue buscando o ya encontró algo?"},
                {'titulo': '❓ Pregunta honesta', 'msg': f"Hola {nombre}, ¿sigue interesado en propiedades en {zona} o sus planes cambiaron? Solo quiero saber para enfocar mi búsqueda correctamente."},
                {'titulo': '📸 Novedad', 'msg': f"Hola {nombre}! Acaba de entrar una propiedad en {zona} que me recordó a lo que buscaba. ¿Se la muestro? No tiene ningún compromiso."},
            ],
            'dias14': [
                {'titulo': '⏰ FOMO (recomendado)', 'msg': f"Hola {nombre}, una propiedad que tenía en mente para usted en {zona} recibió una oferta hoy. Antes de que se cierre, ¿le gustaría verla? Si no es el momento, no hay problema."},
                {'titulo': '📞 Llamada directa', 'msg': f"Hola {nombre}, ¿podemos hablar 5 minutos esta semana? Tengo algo en {zona} dentro de {p} que creo que le va a gustar mucho."},
                {'titulo': '💰 Precio bajó', 'msg': f"Hola {nombre}, buenas noticias — una propiedad en {zona} bajó de precio esta semana. ¿Le interesa verla ahora?"},
            ],
            'dias30': [
                {'titulo': '🔄 Reactivación honesta (recomendado)', 'msg': f"Hola {nombre}, ¿sigue considerando una propiedad en {zona} o sus planes cambiaron? Solo quiero asegurarme de enfocar mi búsqueda en lo que realmente necesita."},
                {'titulo': '🆕 Ángulo nuevo', 'msg': f"Hola {nombre}, han entrado propiedades nuevas en {zona} con características diferentes a lo que le había mostrado antes. ¿Vale la pena que le envíe algunas opciones?"},
                {'titulo': '🤝 Sin presión', 'msg': f"Hola {nombre}, espero que esté muy bien. No le escribo para venderle nada — solo para saber si puedo serle útil en algo relacionado con propiedades en {zona}."},
            ],
            'ultimo': [
                {'titulo': '📊 Última oportunidad (recomendado)', 'msg': f"Hola {nombre}, le escribo por última vez. Si ya encontró su propiedad, me alegra mucho. Si todavía busca en {zona}, estoy aquí. ¿En qué momento está?"},
                {'titulo': '🚪 Puerta abierta', 'msg': f"Hola {nombre}, entiendo que el momento quizás no era el correcto. Cuando retome su búsqueda en {zona}, con gusto le ayudo. ¡Hasta pronto!"},
                {'titulo': '🎯 Referidos', 'msg': f"Hola {nombre}, aunque quizás usted ya no busque en {zona}, ¿conoce a alguien que sí esté buscando? Con gusto le atiendo."},
            ],
        },
        'en': {
            'cliente': [
                {'titulo': '💎 Referrals (recommended)', 'msg': f"Hi {nombre}, hope everything is great with your property. Do you know anyone looking in {zona}? I'd be happy to help them with the same dedication."},
                {'titulo': '🏠 New opportunity', 'msg': f"Hi {nombre}, a new exclusive property just came in at {zona} that might interest you or someone you know. Want me to share the details?"},
                {'titulo': '✅ Check-in', 'msg': f"Hi {nombre}, how's everything going with your property? Just wanted to say hi and remind you I'm always available for any future questions."},
            ],
            'nuevo': [
                {'titulo': '⚡ Speed (recommended)', 'msg': f"Hi {nombre}! I just saw your inquiry about properties in {zona}. I have great options for you. Do you have 5 minutes right now?"},
                {'titulo': '💬 Consultative', 'msg': f"Hi {nombre}, I saw your interest in properties in {zona}. Before I send you options, could you tell me a bit more about what you're looking for?"},
                {'titulo': '📸 Direct proposal', 'msg': f"Hi {nombre}! I have 3 properties in {zona} that might fit what you're looking for. Want me to send them right now with photos and prices?"},
            ],
            'dia1_caliente': [
                {'titulo': '🔥 Direct contact (recommended)', 'msg': f"Hi {nombre}, I'm reaching out because yesterday I saw your interest in {zona} and today we got a property that fits perfectly within {p}. Can I send you the details?"},
                {'titulo': '🏠 Schedule a visit', 'msg': f"Hi {nombre}! I have properties in {zona} ready to visit this week. When works for you? I can accompany you personally."},
                {'titulo': '💎 Exclusivity', 'msg': f"Hi {nombre}, I have a property in {zona} that just hit the market and isn't listed publicly yet. Your budget of {p} fits perfectly. Want to see it first?"},
            ],
            'dias3': [
                {'titulo': '📬 Micro-commitment (recommended)', 'msg': f"Hi {nombre}, can I send you 2-3 options in {zona} with photos right now? No commitment, just to see if anything catches your eye."},
                {'titulo': '💎 High value', 'msg': f"Hi {nombre}, with a budget of {p} in {zona} you have access to properties with excellent appreciation potential. I have 2 exclusive options. Want to review them together this week?"},
                {'titulo': '📞 Quick call', 'msg': f"Hi {nombre}, can I have 10 minutes this week? I have new options in {zona} that I think you'll really like. When works for you?"},
            ],
            'dias7': [
                {'titulo': '🔄 New context (recommended)', 'msg': f"Hi {nombre}, how are you? I'm reaching out because the market in {zona} changed this week — 2 properties dropped in price. Are you still looking?"},
                {'titulo': '❓ Honest question', 'msg': f"Hi {nombre}, are you still interested in properties in {zona} or have your plans changed? Just want to know so I can focus my search correctly."},
                {'titulo': '📸 New listing', 'msg': f"Hi {nombre}! A property just came in {zona} that reminded me of what you were looking for. Want me to show you? No commitment at all."},
            ],
            'dias14': [
                {'titulo': '⏰ FOMO (recommended)', 'msg': f"Hi {nombre}, a property I had in mind for you in {zona} received an offer today. Before it closes, would you like to see it? If it's not the right time, no problem at all."},
                {'titulo': '📞 Direct call', 'msg': f"Hi {nombre}, could we talk for 5 minutes this week? I have something in {zona} within {p} that I think you'll really like."},
                {'titulo': '💰 Price dropped', 'msg': f"Hi {nombre}, good news — a property in {zona} dropped in price this week. Are you interested in seeing it now?"},
            ],
            'dias30': [
                {'titulo': '🔄 Honest reactivation (recommended)', 'msg': f"Hi {nombre}, are you still considering a property in {zona} or have your plans changed? I just want to make sure I'm focusing my search on what you really need."},
                {'titulo': '🆕 New angle', 'msg': f"Hi {nombre}, new properties have come in at {zona} with different features from what I had shown you before. Worth sending you some options?"},
                {'titulo': '🤝 No pressure', 'msg': f"Hi {nombre}, hope you're doing great. I'm not writing to sell you anything — just to know if I can be helpful with anything related to properties in {zona}."},
            ],
            'ultimo': [
                {'titulo': '📊 Last chance (recommended)', 'msg': f"Hi {nombre}, this is my last message. If you've already found your property, I'm really glad. If you're still looking in {zona}, I'm here. Where are you in the process?"},
                {'titulo': '🚪 Open door', 'msg': f"Hi {nombre}, I understand the timing might not have been right. Whenever you resume your search in {zona}, I'll be happy to help. Take care!"},
                {'titulo': '🎯 Referrals', 'msg': f"Hi {nombre}, even if you're no longer looking in {zona}, do you know anyone who might be? I'd be glad to help them."},
            ],
        },
        'fr': {
            'cliente': [
                {'titulo': '💎 Références (recommandé)', 'msg': f"Bonjour {nombre}, j'espère que tout se passe bien avec votre propriété. Connaissez-vous quelqu'un qui cherche à {zona}? Je serais ravi de les aider."},
                {'titulo': '🏠 Nouvelle opportunité', 'msg': f"Bonjour {nombre}, une propriété exclusive vient d'arriver à {zona} qui pourrait vous intéresser ou intéresser quelqu'un de votre entourage. Je vous en parle?"},
                {'titulo': '✅ Prise de nouvelles', 'msg': f"Bonjour {nombre}, comment se passe votre propriété? Je voulais juste vous saluer et vous rappeler que je reste disponible pour toute question."},
            ],
            'nuevo': [
                {'titulo': '⚡ Rapidité (recommandé)', 'msg': f"Bonjour {nombre}! Je viens de voir votre demande concernant des propriétés à {zona}. J'ai des options parfaites pour vous. Avez-vous 5 minutes maintenant?"},
                {'titulo': '💬 Consultatif', 'msg': f"Bonjour {nombre}, j'ai vu votre intérêt pour des propriétés à {zona}. Avant de vous envoyer des options, pouvez-vous me dire ce que vous recherchez exactement?"},
                {'titulo': '📸 Proposition directe', 'msg': f"Bonjour {nombre}! J'ai 3 propriétés à {zona} qui pourraient correspondre à ce que vous cherchez. Je vous les envoie maintenant avec photos et prix?"},
            ],
            'dia1_caliente': [
                {'titulo': '🔥 Appel direct (recommandé)', 'msg': f"Bonjour {nombre}, je vous contacte car hier j'ai vu votre intérêt pour {zona} et aujourd'hui nous avons une propriété qui correspond parfaitement à {p}. Je vous envoie les détails?"},
                {'titulo': '🏠 Planifier une visite', 'msg': f"Bonjour {nombre}! J'ai des propriétés à {zona} disponibles pour visite cette semaine. Quand êtes-vous disponible? Je peux vous accompagner."},
                {'titulo': '💎 Exclusivité', 'msg': f"Bonjour {nombre}, j'ai une propriété à {zona} qui vient d'arriver et n'est pas encore publiée. Votre budget de {p} correspond parfaitement. Vous voulez la voir en premier?"},
            ],
            'dias3': [
                {'titulo': '📬 Micro-engagement (recommandé)', 'msg': f"Bonjour {nombre}, puis-je vous envoyer 2-3 options à {zona} avec photos maintenant? Sans engagement, juste pour voir si quelque chose vous plaît."},
                {'titulo': '💎 Haute valeur', 'msg': f"Bonjour {nombre}, avec un budget de {p} à {zona} vous avez accès à des propriétés avec excellent potentiel de valorisation. J'ai 2 options exclusives. On les revoit ensemble?"},
                {'titulo': '📞 Appel rapide', 'msg': f"Bonjour {nombre}, puis-je avoir 10 minutes cette semaine? J'ai de nouvelles options à {zona} qui je crois vont beaucoup vous plaire."},
            ],
            'dias7': [
                {'titulo': '🔄 Nouveau contexte (recommandé)', 'msg': f"Bonjour {nombre}, comment allez-vous? Je vous écris car le marché à {zona} a changé cette semaine — 2 propriétés ont baissé de prix. Cherchez-vous toujours?"},
                {'titulo': '❓ Question honnête', 'msg': f"Bonjour {nombre}, êtes-vous toujours intéressé par des propriétés à {zona} ou vos projets ont-ils changé?"},
                {'titulo': '📸 Nouveauté', 'msg': f"Bonjour {nombre}! Une propriété vient d'arriver à {zona} qui m'a rappelé ce que vous cherchiez. Je vous la montre? Aucun engagement."},
            ],
            'dias14': [
                {'titulo': '⏰ FOMO (recommandé)', 'msg': f"Bonjour {nombre}, une propriété que j'avais en tête pour vous à {zona} a reçu une offre aujourd'hui. Avant qu'elle se ferme, souhaitez-vous la voir?"},
                {'titulo': '📞 Appel direct', 'msg': f"Bonjour {nombre}, pouvons-nous parler 5 minutes cette semaine? J'ai quelque chose à {zona} dans {p} qui je crois va beaucoup vous plaire."},
                {'titulo': '💰 Prix baissé', 'msg': f"Bonjour {nombre}, bonne nouvelle — une propriété à {zona} a baissé de prix cette semaine. Vous êtes intéressé à la voir maintenant?"},
            ],
            'dias30': [
                {'titulo': '🔄 Réactivation honnête (recommandé)', 'msg': f"Bonjour {nombre}, envisagez-vous toujours une propriété à {zona} ou vos projets ont-ils changé?"},
                {'titulo': '🆕 Nouvel angle', 'msg': f"Bonjour {nombre}, de nouvelles propriétés sont arrivées à {zona} avec des caractéristiques différentes. Ça vaut la peine que je vous envoie quelques options?"},
                {'titulo': '🤝 Sans pression', 'msg': f"Bonjour {nombre}, j'espère que vous allez bien. Je ne vous écris pas pour vendre — juste pour savoir si je peux vous être utile pour des propriétés à {zona}."},
            ],
            'ultimo': [
                {'titulo': '📊 Dernière chance (recommandé)', 'msg': f"Bonjour {nombre}, c'est mon dernier message. Si vous avez déjà trouvé votre propriété, je suis vraiment content. Si vous cherchez encore à {zona}, je suis là."},
                {'titulo': '🚪 Porte ouverte', 'msg': f"Bonjour {nombre}, je comprends que le moment n'était peut-être pas le bon. Quand vous reprendrez votre recherche à {zona}, je serai heureux de vous aider."},
                {'titulo': '🎯 Références', 'msg': f"Bonjour {nombre}, même si vous ne cherchez plus à {zona}, connaissez-vous quelqu'un qui cherche?"},
            ],
        },
        'de': {
            'cliente': [
                {'titulo': '💎 Empfehlungen (empfohlen)', 'msg': f"Hallo {nombre}, ich hoffe alles läuft gut mit Ihrer Immobilie. Kennen Sie jemanden, der in {zona} sucht? Ich helfe gerne mit der gleichen Hingabe."},
                {'titulo': '🏠 Neue Gelegenheit', 'msg': f"Hallo {nombre}, eine exklusive Immobilie in {zona} ist gerade auf den Markt gekommen. Soll ich Ihnen Details schicken?"},
                {'titulo': '✅ Check-in', 'msg': f"Hallo {nombre}, wie läuft alles mit Ihrer Immobilie? Ich wollte mich nur melden und daran erinnern, dass ich immer zur Verfügung stehe."},
            ],
            'nuevo': [
                {'titulo': '⚡ Schnelligkeit (empfohlen)', 'msg': f"Hallo {nombre}! Ich habe gerade Ihre Anfrage zu Immobilien in {zona} gesehen. Ich habe perfekte Optionen für Sie. Haben Sie jetzt 5 Minuten?"},
                {'titulo': '💬 Beratend', 'msg': f"Hallo {nombre}, ich habe Ihr Interesse an Immobilien in {zona} gesehen. Könnten Sie mir etwas mehr darüber erzählen, was Sie suchen?"},
                {'titulo': '📸 Direktes Angebot', 'msg': f"Hallo {nombre}! Ich habe 3 Immobilien in {zona}, die zu Ihnen passen könnten. Soll ich sie Ihnen jetzt mit Fotos und Preisen schicken?"},
            ],
            'dia1_caliente': [
                {'titulo': '🔥 Direkter Anruf (empfohlen)', 'msg': f"Hallo {nombre}, ich melde mich, weil ich gestern Ihr Interesse an {zona} gesehen habe und wir heute eine Immobilie bekommen haben, die perfekt zu {p} passt."},
                {'titulo': '🏠 Besichtigung planen', 'msg': f"Hallo {nombre}! Ich habe Immobilien in {zona}, die diese Woche besichtigt werden können. Wann hätten Sie Zeit?"},
                {'titulo': '💎 Exklusivität', 'msg': f"Hallo {nombre}, ich habe eine Immobilie in {zona}, die noch nicht öffentlich ist. Ihr Budget von {p} passt perfekt. Möchten Sie sie zuerst sehen?"},
            ],
            'dias3': [
                {'titulo': '📬 Micro-Commitment (empfohlen)', 'msg': f"Hallo {nombre}, darf ich Ihnen jetzt 2-3 Optionen in {zona} mit Fotos schicken? Ohne Verpflichtung, nur um zu sehen, ob etwas Ihr Interesse weckt."},
                {'titulo': '💎 Hoher Wert', 'msg': f"Hallo {nombre}, mit einem Budget von {p} in {zona} haben Sie Zugang zu Immobilien mit ausgezeichnetem Wertsteigerungspotenzial. Sollen wir sie diese Woche besprechen?"},
                {'titulo': '📞 Schneller Anruf', 'msg': f"Hallo {nombre}, darf ich Sie diese Woche 10 Minuten in Anspruch nehmen? Ich habe neue Optionen in {zona}, die Ihnen sehr gefallen werden."},
            ],
            'dias7': [
                {'titulo': '🔄 Neuer Kontext (empfohlen)', 'msg': f"Hallo {nombre}, wie geht es Ihnen? Ich schreibe, weil sich der Markt in {zona} diese Woche verändert hat — 2 Immobilien sind im Preis gefallen. Suchen Sie noch?"},
                {'titulo': '❓ Ehrliche Frage', 'msg': f"Hallo {nombre}, interessieren Sie sich noch für Immobilien in {zona} oder haben sich Ihre Pläne geändert?"},
                {'titulo': '📸 Neuheit', 'msg': f"Hallo {nombre}! Eine Immobilie in {zona} ist gerade reingekommen, die mich an das erinnerte, was Sie suchten. Soll ich sie Ihnen zeigen?"},
            ],
            'dias14': [
                {'titulo': '⏰ FOMO (empfohlen)', 'msg': f"Hallo {nombre}, eine Immobilie in {zona}, die ich für Sie im Sinn hatte, hat heute ein Angebot erhalten. Möchten Sie sie sehen, bevor sie abgeschlossen wird?"},
                {'titulo': '📞 Direkter Anruf', 'msg': f"Hallo {nombre}, könnten wir diese Woche 5 Minuten sprechen? Ich habe etwas in {zona} für {p}, das Ihnen sehr gefallen wird."},
                {'titulo': '💰 Preis gesunken', 'msg': f"Hallo {nombre}, gute Nachrichten — eine Immobilie in {zona} ist diese Woche im Preis gesunken. Möchten Sie sie jetzt sehen?"},
            ],
            'dias30': [
                {'titulo': '🔄 Ehrliche Reaktivierung (empfohlen)', 'msg': f"Hallo {nombre}, denken Sie noch an eine Immobilie in {zona} oder haben sich Ihre Pläne geändert?"},
                {'titulo': '🆕 Neuer Ansatz', 'msg': f"Hallo {nombre}, es sind neue Immobilien in {zona} mit anderen Merkmalen reingekommen. Lohnt es sich, Ihnen einige Optionen zu schicken?"},
                {'titulo': '🤝 Kein Druck', 'msg': f"Hallo {nombre}, ich hoffe, es geht Ihnen gut. Ich schreibe nicht um zu verkaufen — nur um zu wissen, ob ich Ihnen bei Immobilien in {zona} behilflich sein kann."},
            ],
            'ultimo': [
                {'titulo': '📊 Letzte Chance (empfohlen)', 'msg': f"Hallo {nombre}, dies ist meine letzte Nachricht. Wenn Sie bereits Ihre Immobilie gefunden haben, freue ich mich. Wenn Sie noch in {zona} suchen, bin ich hier."},
                {'titulo': '🚪 Offene Tür', 'msg': f"Hallo {nombre}, ich verstehe, dass der Zeitpunkt vielleicht nicht der richtige war. Wenn Sie Ihre Suche in {zona} wieder aufnehmen, helfe ich gerne."},
                {'titulo': '🎯 Empfehlungen', 'msg': f"Hallo {nombre}, auch wenn Sie nicht mehr in {zona} suchen, kennen Sie jemanden, der sucht?"},
            ],
        },
        'pt': {
            'cliente': [
                {'titulo': '💎 Indicações (recomendado)', 'msg': f"Olá {nombre}, espero que tudo esteja ótimo com seu imóvel. Você conhece alguém buscando em {zona}? Ficaria feliz em ajudá-lo com a mesma dedicação."},
                {'titulo': '🏠 Nova oportunidade', 'msg': f"Olá {nombre}, acabou de chegar um imóvel exclusivo em {zona} que pode te interessar ou a alguém do seu círculo. Quero te contar?"},
                {'titulo': '✅ Check-in', 'msg': f"Olá {nombre}, como está tudo com seu imóvel? Só queria dar um oi e lembrar que continuo disponível para qualquer dúvida futura."},
            ],
            'nuevo': [
                {'titulo': '⚡ Velocidade (recomendado)', 'msg': f"Olá {nombre}! Acabei de ver sua consulta sobre imóveis em {zona}. Tenho opções perfeitas para você. Tem 5 minutos agora?"},
                {'titulo': '💬 Consultivo', 'msg': f"Olá {nombre}, vi seu interesse em imóveis em {zona}. Antes de enviar opções, pode me contar mais sobre o que procura?"},
                {'titulo': '📸 Proposta direta', 'msg': f"Olá {nombre}! Tenho 3 imóveis em {zona} que podem combinar com o que você procura. Te envio agora com fotos e preços?"},
            ],
            'dia1_caliente': [
                {'titulo': '🔥 Contato direto (recomendado)', 'msg': f"Olá {nombre}, estou entrando em contato porque ontem vi seu interesse em {zona} e hoje recebemos um imóvel que encaixa perfeitamente em {p}. Posso te enviar os detalhes?"},
                {'titulo': '🏠 Agendar visita', 'msg': f"Olá {nombre}! Tenho imóveis em {zona} prontos para visitar esta semana. Quando fica bom para você?"},
                {'titulo': '💎 Exclusividade', 'msg': f"Olá {nombre}, tenho um imóvel em {zona} que acabou de entrar no mercado e ainda não foi publicado. Seu orçamento de {p} encaixa perfeitamente. Quer ver primeiro?"},
            ],
            'dias3': [
                {'titulo': '📬 Micro-compromisso (recomendado)', 'msg': f"Olá {nombre}, posso te enviar 2-3 opções em {zona} com fotos agora? Sem compromisso, só para ver se algo chama atenção."},
                {'titulo': '💎 Alto valor', 'msg': f"Olá {nombre}, com orçamento de {p} em {zona} você tem acesso a imóveis com excelente potencial de valorização. Revisamos juntos esta semana?"},
                {'titulo': '📞 Ligação rápida', 'msg': f"Olá {nombre}, posso ter 10 minutos esta semana? Tenho opções novas em {zona} que acho que vai gostar muito."},
            ],
            'dias7': [
                {'titulo': '🔄 Novo contexto (recomendado)', 'msg': f"Olá {nombre}, tudo bem? Estou escrevendo porque o mercado em {zona} mudou esta semana — 2 imóveis baixaram de preço. Ainda está procurando?"},
                {'titulo': '❓ Pergunta honesta', 'msg': f"Olá {nombre}, ainda tem interesse em imóveis em {zona} ou seus planos mudaram?"},
                {'titulo': '📸 Novidade', 'msg': f"Olá {nombre}! Acabou de entrar um imóvel em {zona} que me lembrou do que você procurava. Te mostro? Sem nenhum compromisso."},
            ],
            'dias14': [
                {'titulo': '⏰ FOMO (recomendado)', 'msg': f"Olá {nombre}, um imóvel que eu tinha em mente para você em {zona} recebeu uma proposta hoje. Antes de fechar, gostaria de ver?"},
                {'titulo': '📞 Ligação direta', 'msg': f"Olá {nombre}, podemos conversar 5 minutos esta semana? Tenho algo em {zona} dentro de {p} que acho que vai gostar muito."},
                {'titulo': '💰 Preço caiu', 'msg': f"Olá {nombre}, boa notícia — um imóvel em {zona} baixou de preço esta semana. Tem interesse em ver agora?"},
            ],
            'dias30': [
                {'titulo': '🔄 Reativação honesta (recomendado)', 'msg': f"Olá {nombre}, ainda está pensando em um imóvel em {zona} ou seus planos mudaram?"},
                {'titulo': '🆕 Novo ângulo', 'msg': f"Olá {nombre}, entraram imóveis novos em {zona} com características diferentes. Vale a pena te enviar algumas opções?"},
                {'titulo': '🤝 Sem pressão', 'msg': f"Olá {nombre}, espero que esteja bem. Não estou escrevendo para vender — só para saber se posso ser útil com algo em {zona}."},
            ],
            'ultimo': [
                {'titulo': '📊 Última chance (recomendado)', 'msg': f"Olá {nombre}, esta é minha última mensagem. Se já encontrou seu imóvel, fico muito feliz. Se ainda procura em {zona}, estou aqui."},
                {'titulo': '🚪 Porta aberta', 'msg': f"Olá {nombre}, entendo que talvez o momento não fosse o certo. Quando retomar sua busca em {zona}, terei prazer em ajudar."},
                {'titulo': '🎯 Indicações', 'msg': f"Olá {nombre}, mesmo que não esteja mais procurando em {zona}, conhece alguém que esteja?"},
            ],
        },
        'zh': {
            'cliente': [
                {'titulo': '💎 推荐（推荐）', 'msg': f"您好 {nombre}，希望您的房产一切顺利。您认识在{zona}找房的人吗？我很乐意以同样的热情为他们服务。"},
                {'titulo': '🏠 新机会', 'msg': f"您好 {nombre}，{zona}刚到了一套独家房源，可能您或您认识的人会感兴趣。要我告诉您详情吗？"},
                {'titulo': '✅ 问候', 'msg': f"您好 {nombre}，您的房产一切都好吗？只是想问候一下，提醒您我随时可以回答您的问题。"},
            ],
            'nuevo': [
                {'titulo': '⚡ 速度（推荐）', 'msg': f"您好 {nombre}！我刚看到您在{zona}找房的咨询。我有非常适合您的选择。您现在有5分钟时间吗？"},
                {'titulo': '💬 顾问式', 'msg': f"您好 {nombre}，我看到您对{zona}的房产感兴趣。在发送选项之前，您能告诉我更多您在寻找什么吗？"},
                {'titulo': '📸 直接提案', 'msg': f"您好 {nombre}！我在{zona}有3套可能符合您需求的房产。现在就把带照片和价格的信息发给您吗？"},
            ],
            'dia1_caliente': [
                {'titulo': '🔥 直接联系（推荐）', 'msg': f"您好 {nombre}，我联系您是因为昨天看到您对{zona}感兴趣，今天我们收到了一套完全符合{p}预算的房产。我可以发详情给您吗？"},
                {'titulo': '🏠 安排参观', 'msg': f"您好 {nombre}！我在{zona}有本周可以参观的房产。什么时候方便？我可以亲自陪您。"},
                {'titulo': '💎 独家', 'msg': f"您好 {nombre}，我在{zona}有一套刚上市尚未公开的房产。您{p}的预算非常匹配。想第一个看吗？"},
            ],
            'dias3': [
                {'titulo': '📬 微承诺（推荐）', 'msg': f"您好 {nombre}，我可以现在发给您{zona}的2-3个带照片的选项吗？没有任何义务，只是看看是否有您感兴趣的。"},
                {'titulo': '💎 高价值', 'msg': f"您好 {nombre}，凭借{p}的预算在{zona}，您可以获得具有出色升值潜力的房产。这周一起看看？"},
                {'titulo': '📞 快速通话', 'msg': f"您好 {nombre}，这周能给我10分钟吗？我在{zona}有新选项，我认为您会非常喜欢。"},
            ],
            'dias7': [
                {'titulo': '🔄 新背景（推荐）', 'msg': f"您好 {nombre}，您好吗？{zona}的市场本周发生了变化——有2套房产降价了。您还在找吗？"},
                {'titulo': '❓ 诚实的问题', 'msg': f"您好 {nombre}，您还对{zona}的房产感兴趣吗，还是您的计划改变了？"},
                {'titulo': '📸 新房源', 'msg': f"您好 {nombre}！{zona}刚来了一套房产，让我想起了您在寻找的。我给您看看吗？完全没有任何义务。"},
            ],
            'dias14': [
                {'titulo': '⏰ 紧迫感（推荐）', 'msg': f"您好 {nombre}，我在{zona}为您考虑的一套房产今天收到了报价。在成交之前，您想看看吗？"},
                {'titulo': '📞 直接通话', 'msg': f"您好 {nombre}，这周我们能通话5分钟吗？我在{zona}有一套在{p}范围内的房产，我认为您会非常喜欢。"},
                {'titulo': '💰 降价了', 'msg': f"您好 {nombre}，好消息——{zona}的一套房产本周降价了。您现在有兴趣看看吗？"},
            ],
            'dias30': [
                {'titulo': '🔄 诚实的重新激活（推荐）', 'msg': f"您好 {nombre}，您还在考虑在{zona}买房吗，还是您的计划改变了？"},
                {'titulo': '🆕 新角度', 'msg': f"您好 {nombre}，{zona}来了一些具有不同特点的新房产。值得给您发一些选项吗？"},
                {'titulo': '🤝 无压力', 'msg': f"您好 {nombre}，希望您一切都好。我写信不是为了推销——只是想知道我是否能在{zona}方面为您提供帮助。"},
            ],
            'ultimo': [
                {'titulo': '📊 最后机会（推荐）', 'msg': f"您好 {nombre}，这是我最后一条消息。如果您已经找到了房产，我真的很高兴。如果您还在{zona}找，我在这里。"},
                {'titulo': '🚪 开放的大门', 'msg': f"您好 {nombre}，我明白时机可能不合适。当您恢复在{zona}的搜索时，我很乐意帮助您。"},
                {'titulo': '🎯 推荐', 'msg': f"您好 {nombre}，即使您不再在{zona}找房，您认识有人在找吗？"},
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


@app.before_request
def verificar_sesion():
    rutas_publicas = ['formulario', 'formulario_asesor', 'index', 'seleccion_idioma_login',
                      'static', 'login', 'cambiar_idioma', 'cron_seguimiento', 'admin_login',
                      'inicio_formulario', 'chat_inmobiliario', 'test_gemini']
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
    except Exception as e:
        print(f"❌ Error creando cliente: {e}")
    return redirect(url_for('admin_panel'))

@app.route("/admin/cliente/editar/<cliente_id>", methods=["POST"])
def admin_editar_cliente(cliente_id):
    if not session.get("admin"):
        return redirect(url_for('admin_panel'))
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
    except Exception as e:
        print(f"❌ Error editando cliente: {e}")
    return redirect(url_for('admin_panel'))

@app.route("/admin/cliente/toggle/<cliente_id>", methods=["POST"])
def admin_toggle_cliente(cliente_id):
    if not session.get("admin"):
        return redirect(url_for('admin_panel'))
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
    try:
        supabase.table("leads").delete().eq("vendedor", cliente_id).execute()
        supabase.table("propiedades").delete().eq("vendedor", cliente_id).execute()
        supabase.table("asesores").delete().eq("cliente_id", cliente_id).execute()
        supabase.table("clientes").delete().eq("id", cliente_id).execute()
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
    try:
        data = {
            "cliente_id": id_clean,
            "nombre": request.form.get("nombre", "").strip(),
            "usuario": request.form.get("usuario", "").strip(),
            "password": request.form.get("password", "").strip(),
            "email": request.form.get("email", "").strip(),
            "activo": True
        }
        supabase.table("asesores").insert(data).execute()
    except Exception as e:
        print(f"❌ Error creando asesor: {e}")
    return redirect(url_for('historial', cliente_id=id_clean))

@app.route("/asesores/<cliente_id>/toggle/<int:asesor_id>", methods=["POST"])
def toggle_asesor(cliente_id, asesor_id):
    id_clean = cliente_id.lower()
    if session.get("cliente") != id_clean or not es_dueno():
        return "No autorizado", 403
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
            "seguimiento_enviado": False,
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

@app.route("/form/<cliente_id>/<asesor_usuario>", methods=["GET","POST"])
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
        idioma = session.get('idioma', get_idioma_default(vendedor))
        return render_template("inventario_publico.html", cliente_id=id_clean,
                               cliente_nombre=vendedor['nombre'], whatsapp=vendedor['whatsapp'],
                               propiedades_json=json.dumps(propiedades),
                               idioma_actual=idioma)
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
        archivos = request.files.getlist("imagenes")[:7]
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
        espacio_disponible = max(0, 7 - len(imagenes_existentes))
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
                "seguimiento_enviado": True, "etapa": "cerrado"
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
        usuario_form = request.form.get("usuario", "").strip()
        password_form = request.form.get("password", "").strip()
        if usuario_form == vendedor["usuario"] and \
           verificar_password(password_form, vendedor["password"]):
            session["cliente"] = id_clean
            session["login_time"] = datetime.now().isoformat()
            session.pop("asesor_id", None)
            session.pop("asesor_nombre", None)
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
                    return redirect(url_for('historial', cliente_id=id_clean))
        except Exception as e:
            print(f"⚠️ Error consultando asesores: {e}")
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

# ✅ DIAGNÓSTICO — prueba varios modelos para encontrar cuál funciona
@app.route("/test-gemini/<cliente_id>")
def test_gemini(cliente_id):
    gemini_key = os.environ.get("GEMINI_API_KEY", "NO KEY")
    # ✅ Lista de modelos a probar en orden
    modelos = [
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-1.5-flash-latest",
        "gemini-1.0-pro",
    ]
    resultados = {}
    for modelo in modelos:
        try:
            payload = {
                "contents": [{"role": "user", "parts": [{"text": "Say: OK"}]}],
                "generationConfig": {"maxOutputTokens": 10}
            }
            api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={gemini_key}"
            req_data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                api_url, data=req_data,
                headers={"Content-Type": "application/json"}, method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode('utf-8'))
            text = result["candidates"][0]["content"]["parts"][0]["text"]
            resultados[modelo] = {"ok": True, "response": text}
        except urllib.error.HTTPError as e:
            resultados[modelo] = {"ok": False, "code": e.code}
        except Exception as e:
            resultados[modelo] = {"ok": False, "error": str(e)[:80]}
    return jsonify({"key_prefix": gemini_key[:12], "results": resultados})

# ✅ CHATBOT CON GEMINI — modelo dinámico
def llamar_gemini(gemini_key, modelo, payload):
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={gemini_key}"
    req_data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        api_url, data=req_data,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read().decode('utf-8'))
    return result["candidates"][0]["content"]["parts"][0]["text"]

@app.route("/api/chat/<cliente_id>", methods=["POST"])
def chat_inmobiliario(cliente_id):
    id_clean = cliente_id.lower()
    vendedor = get_cliente(id_clean)
    if not vendedor:
        return jsonify({"response": "Lo siento, no pude conectarme."}), 200
    try:
        data = request.get_json()
        messages = data.get("messages", [])
        lang = data.get("lang", "es")
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        if not gemini_key:
            return jsonify({"response": "Servicio no disponible temporalmente."}), 200

        lang_nombres = {
            'es': 'español', 'en': 'English', 'fr': 'français',
            'de': 'Deutsch', 'pt': 'português', 'zh': '中文'
        }
        lang_actual = lang_nombres.get(lang, 'español')
        wa = vendedor.get('whatsapp', '')

        props_result = supabase.table("propiedades").select("*").eq("vendedor", id_clean).eq("estado", "disponible").execute()
        propiedades = props_result.data or []
        props_text = ""
        for p in propiedades[:8]:
            try:
                precio = float(p.get('precio', 0))
                line = f"• {p.get('titulo', 'Propiedad')}: ${precio:,.0f}, {p.get('ubicacion', '')}"
            except:
                line = f"• {p.get('titulo', 'Propiedad')}: {p.get('ubicacion', '')}"
            if p.get('habitaciones'): line += f", {p.get('habitaciones')} hab"
            if p.get('banos'): line += f", {p.get('banos')} baños"
            if p.get('metros2'): line += f", {p.get('metros2')}m²"
            if p.get('descripcion'): line += f". {str(p.get('descripcion',''))[:80]}"
            props_text += line + "\n"
        if not props_text:
            props_text = "No hay propiedades listadas actualmente."

        # CTA según idioma
        cta = {
            'es': f"¡Perfecto! 📝 Por favor llena el formulario de contacto arriba para que un asesor te llame hoy mismo. También puedes escribirnos directamente por WhatsApp al {wa} 💬",
            'en': f"Perfect! 📝 Please fill out the contact form above so an advisor can call you today. You can also reach us directly on WhatsApp at {wa} 💬",
            'fr': f"Parfait! 📝 Veuillez remplir le formulaire de contact ci-dessus pour qu'un conseiller vous rappelle aujourd'hui. Vous pouvez aussi nous écrire sur WhatsApp au {wa} 💬",
            'de': f"Perfekt! 📝 Bitte füllen Sie das Kontaktformular oben aus, damit ein Berater Sie heute zurückruft. Sie können uns auch direkt auf WhatsApp unter {wa} schreiben 💬",
            'pt': f"Perfeito! 📝 Por favor preencha o formulário de contato acima para que um consultor ligue para você hoje. Você também pode nos escrever pelo WhatsApp no {wa} 💬",
            'zh': f"太好了！📝 请填写上方的联系表格，顾问将在今天给您回电。您也可以直接在WhatsApp上联系我们：{wa} 💬"
        }.get(lang, f"¡Perfecto! 📝 Llena el formulario arriba o escríbenos por WhatsApp al {wa} 💬")

        system_prompt = f"""CRITICAL: You MUST respond ONLY in {lang_actual}. Every single word must be in {lang_actual}. No exceptions.

You are a charismatic virtual real estate advisor for {vendedor.get('nombre', 'the agency')}. Your mission: convert visitors into qualified prospects who fill the contact form.

AVAILABLE PROPERTIES:
{props_text}

CONVERSATION FLOW:
1. Greet warmly and ask what they're looking for
2. Ask ONE question per message to qualify: zone/area, property type, budget, timeline
3. After 3-4 exchanges, recommend a specific property from the inventory
4. Then push them to fill the form with this EXACT message:
{cta}

RULES:
- RESPOND ONLY IN {lang_actual} — absolutely no other language
- Max 3 sentences per response
- ONE question per message only
- Use emojis occasionally 🏠✨
- Only mention properties from the real inventory above
- After recommending a property, always end with the CTA to fill the form
- WhatsApp: {wa}

COMPANY: {vendedor.get('nombre', 'Real Estate')}"""

        # System prompt como primera vuelta de conversación (compatible con todos los modelos)
        contents = [
            {"role": "user", "parts": [{"text": f"[SYSTEM INSTRUCTIONS - FOLLOW EXACTLY]: {system_prompt}"}]},
            {"role": "model", "parts": [{"text": f"Understood. I will respond only in {lang_actual} and follow all instructions precisely."}]}
        ]
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        payload = {
            "contents": contents,
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 300}
        }

        # ✅ Intenta modelos en orden hasta que uno funcione
        modelos_a_intentar = [
            "gemini-2.0-flash-lite",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-1.5-flash-latest",
            "gemini-1.0-pro",
        ]

        text = None
        for modelo in modelos_a_intentar:
            try:
                text = llamar_gemini(gemini_key, modelo, payload)
                print(f"✅ Modelo exitoso: {modelo}")
                break
            except urllib.error.HTTPError as e:
                print(f"⚠️ Modelo {modelo} falló con {e.code}")
                continue
            except Exception as e:
                print(f"⚠️ Modelo {modelo} error: {e}")
                continue

        if text:
            return jsonify({"response": text})
        else:
            raise Exception("Ningún modelo disponible")

    except Exception as e:
        print(f"❌ Error chat Gemini: {e}")
        error_msgs = {
            'es': f"Estamos teniendo un problema técnico momentáneo 🔧 Por favor escríbenos directamente por WhatsApp y con gusto te atendemos: {vendedor.get('whatsapp', '')} 💬",
            'en': f"We're experiencing a temporary technical issue 🔧 Please write us directly on WhatsApp and we'll be happy to help: {vendedor.get('whatsapp', '')} 💬",
            'fr': f"Nous avons un problème technique momentané 🔧 Veuillez nous écrire directement sur WhatsApp et nous serons ravis de vous aider: {vendedor.get('whatsapp', '')} 💬",
            'de': f"Wir haben ein vorübergehendes technisches Problem 🔧 Bitte schreiben Sie uns direkt auf WhatsApp: {vendedor.get('whatsapp', '')} 💬",
            'pt': f"Estamos com um problema técnico momentâneo 🔧 Por favor nos escreva diretamente pelo WhatsApp: {vendedor.get('whatsapp', '')} 💬",
            'zh': f"我们遇到了暂时的技术问题 🔧 请直接通过WhatsApp联系我们：{vendedor.get('whatsapp', '')} 💬"
        }
        try:
            l = request.get_json(silent=True).get('lang', 'es')
        except:
            l = 'es'
        return jsonify({"response": error_msgs.get(l, error_msgs['es'])}), 200

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
