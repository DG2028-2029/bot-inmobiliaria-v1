"""
planes.py — Configuración de planes (Bot Inmobiliaria V1)

TODO lo que tenga que ver con QUÉ incluye cada plan y cuáles son sus límites
vive aquí. Para cambiar un límite o mover una función de un plan a otro, solo
se edita este archivo. No tiene precios a propósito: los precios se definen
con tus clientes y se cobran fuera del código (por ahora a mano).

Este archivo NO usa Flask ni Supabase: son funciones puras, fáciles de probar.
"""
import os
from datetime import datetime, timedelta, timezone

DIAS_GRACIA = 7    # días con todo funcionando después de vencer, antes de pasar a solo lectura
DIAS_PRUEBA = 14   # duración de la prueba gratis

# ------------------------------------------------------------
# Funciones del sistema (clave -> nombre para mostrar al cliente)
# ------------------------------------------------------------
FUNCIONES = {
    # Básicas (todos los planes)
    'leads':               'Leads, historial y tablero kanban',
    'score_leads':         'Score automático de leads',
    'respuestas':          'Mensajes sugeridos (¿Qué decir?)',
    'exportar':            'Exportar leads a Excel y PDF',
    'inventario':          'Inventario de propiedades',
    # Profesional
    'visitas':             'Agenda de visitas y recordatorios',
    'portal':              'Portal del prospecto',
    'matching':            'Matching de leads y propiedades',
    'score_propiedades':   'Score de calidad de propiedades',
    'push':                'Notificaciones push',
    'reporte_semanal':     'Reporte semanal por correo',
    'seguimiento_auto':    'Seguimiento automático por correo',
    'estadisticas':        'Estadísticas',
    'rol_gerente':         'Rol de gerente',
    # Agencia
    'marca_propia':        'Colores y marca propia',
    'soporte_prioritario': 'Soporte prioritario',
    # Extra (fuera de los planes por ahora)
    'chatbot':             'Chatbot de IA',
}

FUNCIONES_BASE = {'leads', 'score_leads', 'respuestas', 'exportar', 'inventario'}
FUNCIONES_PRO = FUNCIONES_BASE | {
    'visitas', 'portal', 'matching', 'score_propiedades', 'push',
    'reporte_semanal', 'seguimiento_auto', 'estadisticas', 'rol_gerente',
}
FUNCIONES_AGENCIA = FUNCIONES_PRO | {'marca_propia', 'soporte_prioritario'}
FUNCIONES_TODAS = set(FUNCIONES.keys())

# None = ilimitado
PLANES = {
    'fundador': {
        'nombre': 'Fundador',
        'funciones': FUNCIONES_TODAS,
        'limites': {'asesores': None, 'propiedades': None},
    },
    'esencial': {
        'nombre': 'Esencial',
        'funciones': FUNCIONES_BASE,
        'limites': {'asesores': 3, 'propiedades': 30},
    },
    'profesional': {
        'nombre': 'Profesional',
        'funciones': FUNCIONES_PRO,
        'limites': {'asesores': 10, 'propiedades': 150},
    },
    'agencia': {
        'nombre': 'Agencia',
        'funciones': FUNCIONES_AGENCIA,
        'limites': {'asesores': 30, 'propiedades': None},
    },
}

# Planes que se ofrecen al público (Fundador es solo para tus primeros clientes)
ORDEN_PLANES = ['esencial', 'profesional', 'agencia']

ESTADOS_PLAN = ['prueba', 'activo', 'gracia', 'vencido', 'cancelado']

ESTADO_TEXTOS = {
    'prueba':    'Prueba gratis',
    'activo':    'Activo',
    'gracia':    'Pago pendiente',
    'vencido':   'Vencido (solo lectura)',
    'cancelado': 'Cancelado (solo lectura)',
}

# ------------------------------------------------------------
# Promoción de instalación gratis (se controla con una variable de
# entorno en Render: PROMO_INSTALACION_HASTA=2027-03-31). Si está vacía,
# la instalación se cobra normal.
# ------------------------------------------------------------
def promo_instalacion(hoy=None):
    """Devuelve (activa, fecha_texto)."""
    fecha_txt = (os.environ.get("PROMO_INSTALACION_HASTA") or "").strip()
    if not fecha_txt:
        return (False, "")
    try:
        limite = datetime.strptime(fecha_txt, "%Y-%m-%d").date()
    except ValueError:
        return (False, "")
    hoy = hoy or datetime.now(timezone.utc).date()
    return (hoy <= limite, fecha_txt)


# ------------------------------------------------------------
# Mensajes (es / en)
# ------------------------------------------------------------
MENSAJES = {
    'es': {
        'funcion_no_incluida': 'Esta función no está incluida en tu plan actual.',
        'limite_asesores': 'Llegaste al límite de asesores de tu plan.',
        'limite_propiedades': 'Llegaste al límite de propiedades de tu plan.',
        'solo_lectura': 'Tu plan está vencido: tu cuenta está en modo solo lectura. Puedes ver y exportar tus datos, pero no crear ni modificar.',
    },
    'en': {
        'funcion_no_incluida': 'This feature is not included in your current plan.',
        'limite_asesores': 'You have reached the agent limit of your plan.',
        'limite_propiedades': 'You have reached the property limit of your plan.',
        'solo_lectura': 'Your plan has expired: your account is read-only. You can view and export your data, but not create or edit.',
    },
}


def mensaje_bloqueo(clave, idioma='es'):
    """Texto amable para cuando el plan bloquea algo. `clave` puede ser una
    clave de mensaje (limite_asesores...) o una función de FUNCIONES."""
    textos = MENSAJES.get(idioma, MENSAJES['es'])
    if clave in FUNCIONES:
        return f"{textos['funcion_no_incluida']} ({FUNCIONES[clave]})"
    return textos.get(clave, textos['funcion_no_incluida'])


# ------------------------------------------------------------
# Lógica del estado del plan
# ------------------------------------------------------------
def _parse_fecha(valor):
    """Convierte lo que devuelve Supabase (texto ISO) a datetime UTC sin tzinfo."""
    if not valor:
        return None
    if isinstance(valor, datetime):
        dt = valor
    else:
        try:
            dt = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _extras_dict(cliente):
    """limites_extra puede venir como dict (jsonb) o como texto JSON."""
    import json
    extras = (cliente or {}).get('limites_extra') or {}
    if isinstance(extras, str):
        try:
            extras = json.loads(extras)
        except ValueError:
            extras = {}
    return extras if isinstance(extras, dict) else {}


def _entero(valor):
    try:
        return max(0, int(valor))
    except (TypeError, ValueError):
        return 0


def calcular_plan_info(cliente, ahora=None):
    """
    A partir de la fila del cliente (tabla clientes) calcula qué puede hacer
    ahora mismo. Si no hay cliente o faltan datos, devuelve el plan Fundador
    (todo abierto): ante un fallo, nunca se castiga al cliente.
    """
    cliente = cliente or {}
    ahora = ahora or datetime.utcnow()

    plan = cliente.get('plan') or 'fundador'
    if plan not in PLANES:
        plan = 'fundador'
    estado = cliente.get('plan_estado') or 'activo'
    if estado not in ESTADOS_PLAN:
        estado = 'activo'
    vence = _parse_fecha(cliente.get('plan_vence'))
    extras = _extras_dict(cliente)

    # Estado efectivo (se calcula al vuelo, no hace falta un cron)
    efectivo = estado
    if vence and ahora > vence:
        if estado == 'prueba':
            efectivo = 'vencido'
        elif estado in ('activo', 'gracia'):
            efectivo = 'gracia' if ahora <= vence + timedelta(days=DIAS_GRACIA) else 'vencido'

    # Funciones y límites base
    if estado == 'prueba':
        # La prueba abre todo (menos extras) con los límites del plan elegido
        funciones = set(FUNCIONES_AGENCIA)
        plan_limites = plan if plan in ('agencia', 'fundador') else 'profesional'
    else:
        funciones = set(PLANES[plan]['funciones'])
        plan_limites = plan

    limites = dict(PLANES[plan_limites]['limites'])
    for recurso in ('asesores', 'propiedades'):
        if limites.get(recurso) is not None:
            limites[recurso] += _entero(extras.get(recurso))

    # Funciones extra asignadas a mano a este cliente
    for f in extras.get('funciones', []) or []:
        if f in FUNCIONES:
            funciones.add(f)

    dias_restantes = None
    if vence:
        dias_restantes = (vence - ahora).days

    return {
        'plan': plan,
        'plan_nombre': PLANES[plan]['nombre'],
        'estado': estado,
        'estado_efectivo': efectivo,
        'estado_texto': ESTADO_TEXTOS.get(efectivo, efectivo),
        'vence': vence,
        'vence_texto': vence.strftime("%Y-%m-%d") if vence else "",
        'dias_restantes': dias_restantes,
        'en_gracia': efectivo == 'gracia',
        'solo_lectura': efectivo in ('vencido', 'cancelado'),
        'funciones': funciones,
        'limites': limites,
        'extras': {
            'asesores': _entero(extras.get('asesores')),
            'propiedades': _entero(extras.get('propiedades')),
            'funciones': [f for f in (extras.get('funciones') or []) if f in FUNCIONES],
        },
    }


def limite_alcanzado(info, recurso, uso_actual):
    """True si ya no se puede crear otro (None = ilimitado)."""
    limite = info['limites'].get(recurso)
    return limite is not None and uso_actual >= limite
