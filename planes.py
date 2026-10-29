"""
planes.py — Configuración de planes (Bot Inmobiliaria V1)

TODO lo que tenga que ver con QUÉ incluye cada plan y cuáles son sus límites
vive aquí. Para cambiar un límite o mover una función de un plan a otro, solo
se edita este archivo. No tiene precios a propósito: los precios se definen
con tus clientes y se cobran fuera del código (por ahora a mano).

Este archivo NO usa Flask ni Supabase: son funciones puras, fáciles de probar.

PRECIOS: viven en el bloque PRECIOS_USD de más abajo. Los precios de lista son los
"normales"; el descuento de lanzamiento se aplica por cliente (clientes.descuento_pct).
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
# PRECIOS DE LISTA (USD al mes). Para cambiarlos, edita SOLO este bloque.
# El descuento de cada cliente se guarda aparte (clientes.descuento_pct).
# ------------------------------------------------------------
PRECIOS_USD = {
    'esencial':    {'global': 49,  'latam': 25},
    'profesional': {'global': 119, 'latam': 59},
    'agencia':     {'global': 249, 'latam': 119},
}
ASESOR_EXTRA_USD = {'global': 5, 'latam': 3}   # por asesor adicional, al mes
MESES_GRATIS_ANUAL = 2                         # pagando el año: 12 - 2 = 10 mensualidades

# Cuota de instalación (pago único). LatAm: 1 mensualidad de lista, con acompañamiento.
# EE. UU./Europa: registro por su cuenta, sin cuota.
INSTALACION_USD = {
    'esencial':    {'global': 0, 'latam': 25},
    'profesional': {'global': 0, 'latam': 59},
    'agencia':     {'global': 0, 'latam': 119},
}

PAISES_LATAM = {
    'Argentina', 'Bolivia', 'Brasil', 'Chile', 'Colombia', 'Costa Rica', 'Cuba', 'Ecuador',
    'El Salvador', 'Guatemala', 'Honduras', 'México', 'Nicaragua', 'Panamá', 'Paraguay',
    'Perú', 'República Dominicana', 'Uruguay', 'Venezuela',
}


def region_precio(pais):
    """'latam' o 'global' según el país del cliente (sin país: se asume latam)."""
    pais = (pais or '').strip()
    if not pais:
        return 'latam'
    return 'latam' if pais in PAISES_LATAM else 'global'


def _pct(valor):
    try:
        return min(100, max(0, int(valor)))
    except (TypeError, ValueError):
        return 0


def calcular_precio_cliente(cliente):
    """
    Lo que paga un cliente según su plan, su región y su descuento permanente.
    Devuelve None para el plan Fundador (sin cobro).
    """
    cliente = cliente or {}
    plan = cliente.get('plan') or 'fundador'
    if plan not in PRECIOS_USD:
        return None
    region = region_precio(cliente.get('pais'))
    pct = _pct(cliente.get('descuento_pct'))
    factor = (100 - pct) / 100
    lista = PRECIOS_USD[plan][region]
    final = round(lista * factor, 2)
    inst_lista = INSTALACION_USD[plan][region]
    inst_gratis = bool(cliente.get('instalacion_gratis'))
    return {
        'plan': plan,
        'region': region,
        'region_texto': 'Latinoamérica' if region == 'latam' else 'EE. UU., Canadá y Europa',
        'lista': lista,
        'descuento_pct': pct,
        'final': final,
        'ahorro': round(lista - final, 2),
        'anual': round(final * (12 - MESES_GRATIS_ANUAL), 2),
        'asesor_extra': round(ASESOR_EXTRA_USD[region] * factor, 2),
        'instalacion_lista': inst_lista,
        'instalacion_gratis': inst_gratis,
        'instalacion_final': 0 if inst_gratis else inst_lista,
    }


# ------------------------------------------------------------
# OFERTA DE LANZAMIENTO — un interruptor que se maneja desde el panel de admin
# (tabla `configuracion`). No tiene fecha de fin. Cuando se aplica a un cliente,
# el descuento y la instalación gratis quedan guardados EN ese cliente, así que
# apagar la oferta después no le quita lo que ya se le dio.
# ------------------------------------------------------------
OFERTA_CLAVE = 'oferta_lanzamiento'


def normalizar_oferta(valor):
    """Convierte lo guardado (dict o texto JSON) en una oferta limpia y segura."""
    import json
    if isinstance(valor, str):
        try:
            valor = json.loads(valor)
        except ValueError:
            valor = {}
    if not isinstance(valor, dict):
        valor = {}
    return {
        'activa': bool(valor.get('activa')),
        'descuento_pct': _pct(valor.get('descuento_pct')),
        'instalacion_gratis': bool(valor.get('instalacion_gratis')),
    }


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
