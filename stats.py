# ============================================
# MÓDULO DE ESTADÍSTICAS (STATS)
# ============================================
# Calcula datos para los gráficos

from supabase import create_client
import os
from datetime import datetime, timedelta

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

def obtener_stats(cliente_id):
    """Obtiene estadísticas del cliente para mostrar en gráficos."""
    
    try:
        # Obtener todos los leads del cliente
        resultado = supabase.table("leads").select("*").eq("vendedor", cliente_id).execute()
        leads = resultado.data
        
        if not leads:
            return {
                "total_leads": 0,
                "leads_este_mes": 0,
                "leads_mes_pasado": 0,
                "tasa_conversion": 0,
                "leads_por_zona": {},
                "leads_por_clasificacion": {}
            }
        
        # Fecha actual
        hoy = datetime.now()
        mes_actual = hoy.month
        año_actual = hoy.year
        
        # Contar leads este mes y mes pasado
        leads_este_mes = 0
        leads_mes_pasado = 0
        
        for lead in leads:
            fecha_str = lead.get("fecha", "").split(" ")[0]  # "2026-05-31"
            if fecha_str:
                try:
                    fecha = datetime.strptime(fecha_str, "%Y-%m-%d")
                    if fecha.month == mes_actual and fecha.year == año_actual:
                        leads_este_mes += 1
                    elif fecha.month == (mes_actual - 1) and fecha.year == año_actual:
                        leads_mes_pasado += 1
                except:
                    pass
        
        # Leads por zona
        leads_por_zona = {}
        for lead in leads:
            zona = lead.get("zona_interes", "Sin zona")
            leads_por_zona[zona] = leads_por_zona.get(zona, 0) + 1
        
        # Leads por clasificación
        leads_por_clasificacion = {}
        for lead in leads:
            clasificacion = lead.get("clasificacion", "Sin clasificar")
            leads_por_clasificacion[clasificacion] = leads_por_clasificacion.get(clasificacion, 0) + 1
        
        # Tasa de conversión (clientes vs total)
        clientes = sum(1 for lead in leads if "CLIENTE" in lead.get("temperatura", ""))
        tasa_conversion = round((clientes / len(leads) * 100), 1) if leads else 0
        
        return {
            "total_leads": len(leads),
            "leads_este_mes": leads_este_mes,
            "leads_mes_pasado": leads_mes_pasado,
            "tasa_conversion": tasa_conversion,
            "leads_por_zona": leads_por_zona,
            "leads_por_clasificacion": leads_por_clasificacion
        }
    
    except Exception as e:
        print(f"Error obteniendo stats: {e}")
        return None
