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

def obtener_stats(cliente_id, periodo="todo"):
    """
    Obtiene estadísticas del cliente para mostrar en gráficos.
    
    periodo: "semana", "mes", "año", "todo"
    """
    
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
                "leads_por_clasificacion": {},
                "periodo": periodo
            }
        
        # Calcular fecha límite según el período
        hoy = datetime.now()
        fecha_limite = hoy
        
        if periodo == "semana":
            fecha_limite = hoy - timedelta(days=7)
        elif periodo == "mes":
            fecha_limite = hoy - timedelta(days=30)
        elif periodo == "año":
            fecha_limite = hoy - timedelta(days=365)
        elif periodo == "todo":
            fecha_limite = datetime(2000, 1, 1)
        
        # Filtrar leads por período (MEJORADO)
        leads_filtrados = []
        for lead in leads:
            fecha_str = lead.get("fecha", "")
            if fecha_str:
                try:
                    # Intenta parsear el formato "2026-05-31 14:30"
                    if " " in fecha_str:
                        fecha = datetime.strptime(fecha_str.split(" ")[0], "%Y-%m-%d")
                    else:
                        fecha = datetime.strptime(fecha_str, "%Y-%m-%d")
                    
                    if fecha >= fecha_limite:
                        leads_filtrados.append(lead)
                except Exception as e:
                    # Si hay error al parsear, incluye el lead de todas formas
                    leads_filtrados.append(lead)
        
        # Si no hay leads filtrados, usa todos (fallback)
        if not leads_filtrados:
            leads_filtrados = leads
        
        if not leads_filtrados:
            return {
                "total_leads": 0,
                "leads_este_mes": 0,
                "leads_mes_pasado": 0,
                "tasa_conversion": 0,
                "leads_por_zona": {},
                "leads_por_clasificacion": {},
                "periodo": periodo
            }
        
        # Contar leads este mes y mes pasado
        mes_actual = hoy.month
        año_actual = hoy.year
        leads_este_mes = 0
        leads_mes_pasado = 0
        
        for lead in leads_filtrados:
            fecha_str = lead.get("fecha", "")
            if fecha_str:
                try:
                    if " " in fecha_str:
                        fecha = datetime.strptime(fecha_str.split(" ")[0], "%Y-%m-%d")
                    else:
                        fecha = datetime.strptime(fecha_str, "%Y-%m-%d")
                    
                    if fecha.month == mes_actual and fecha.year == año_actual:
                        leads_este_mes += 1
                    elif fecha.month == (mes_actual - 1) and fecha.year == año_actual:
                        leads_mes_pasado += 1
                except:
                    pass
        
        # Leads por zona
        leads_por_zona = {}
        for lead in leads_filtrados:
            zona = lead.get("zona_interes", "Sin zona")
            leads_por_zona[zona] = leads_por_zona.get(zona, 0) + 1
        
        # Leads por clasificación
        leads_por_clasificacion = {}
        for lead in leads_filtrados:
            clasificacion = lead.get("clasificacion", "Sin clasificar")
            leads_por_clasificacion[clasificacion] = leads_por_clasificacion.get(clasificacion, 0) + 1
        
        # Tasa de conversión (clientes vs total)
        clientes = sum(1 for lead in leads_filtrados if "CLIENTE" in lead.get("temperatura", "") or "MUY_CALIENTE" in lead.get("temperatura", ""))
        tasa_conversion = round((clientes / len(leads_filtrados) * 100), 1) if leads_filtrados else 0
        
        return {
            "total_leads": len(leads_filtrados),
            "leads_este_mes": leads_este_mes,
            "leads_mes_pasado": leads_mes_pasado,
            "tasa_conversion": tasa_conversion,
            "leads_por_zona": leads_por_zona,
            "leads_por_clasificacion": leads_por_clasificacion,
            "periodo": periodo
        }
    
    except Exception as e:
        print(f"Error obteniendo stats: {e}")
        return None
