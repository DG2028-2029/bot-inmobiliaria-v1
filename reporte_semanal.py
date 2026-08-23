# ============================================================
# MÓDULO DE REPORTE SEMANAL AUTOMÁTICO
# ============================================================

from supabase import create_client
import os
from datetime import datetime, timedelta

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

def generar_resumen_semanal(cliente_id):
    """
    Arma el resumen de la última semana para un cliente:
    - Leads nuevos en los últimos 7 días
    - Cuántos ya son clientes (de esos nuevos)
    - Leads en riesgo (14+ días sin convertirse, activos ahora mismo)
    - El lead con mejor score de la semana
    """
    try:
        resultado = supabase.table("leads").select("*").eq("vendedor", cliente_id).execute()
        leads = resultado.data or []

        hoy = datetime.now()
        hace_7_dias = hoy - timedelta(days=7)

        leads_semana = []
        for lead in leads:
            fecha_str = lead.get("fecha", "")
            if fecha_str:
                try:
                    fecha = datetime.strptime(fecha_str.split(" ")[0], "%Y-%m-%d")
                    if fecha >= hace_7_dias:
                        lead['_fecha_dt'] = fecha
                        leads_semana.append(lead)
                except:
                    pass

        nuevos = len(leads_semana)
        convertidos_semana = sum(1 for l in leads_semana if 'CLIENTE' in l.get('clasificacion', ''))

        # Leads en riesgo: activos ahora mismo, sin importar cuándo entraron
        en_riesgo = []
        for lead in leads:
            fecha_str = lead.get("fecha", "")
            if fecha_str and 'CLIENTE' not in lead.get('clasificacion', ''):
                try:
                    fecha = datetime.strptime(fecha_str.split(" ")[0], "%Y-%m-%d")
                    dias = (hoy - fecha).days
                    if dias > 14:
                        en_riesgo.append(lead)
                except:
                    pass

        mejor_lead = None
        if leads_semana:
            mejor_lead = max(leads_semana, key=lambda l: l.get('score', 0))

        return {
            "nuevos": nuevos,
            "convertidos_semana": convertidos_semana,
            "en_riesgo": len(en_riesgo),
            "mejor_lead": {
                "nombre": mejor_lead.get("nombre", ""),
                "score": mejor_lead.get("score", 0),
                "zona": mejor_lead.get("zona_interes", "")
            } if mejor_lead else None
        }
    except Exception as e:
        print(f"❌ Error generando resumen semanal para {cliente_id}: {e}")
        return None
