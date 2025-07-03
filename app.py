# ============================================================================
# app.py – Scraper Promiedos + La14HD (partidos + streams)
# ============================================================================
# ➟ Ahora soporta 3 vistas de Promiedos: HOY (/), AYER (/ayer) y MAÑANA (/man)
# ➟ Genera 3 archivos JSON independientes:  
#       • partidos.json          (hoy   – default)  
#       • partidos_ayer.json     (ayer)             
#       • partidos_man.json      (mañana)           
#     que el frontend consume desde main.js.
# ➟ Lógica de scraping para cada día es idéntica; solo cambia la URL base y
#   el archivo de salida.  
# ➟ Se ejecuta todo en un loop cada 60 s.
# ----------------------------------------------------------------------------
# Última actualización: 2025‑06‑18 20:35 (-03:00)
# ----------------------------------------------------------------------------

from __future__ import annotations

import json
import time
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.edge.options import Options
from selenium.webdriver.edge.service import Service

from flask import Flask, jsonify, request
from flask_cors import CORS

from flask import Flask, jsonify, request
from flask_cors import CORS
import threading
import time
import json
from pathlib import Path
from datetime import datetime

app = Flask(__name__)
CORS(app)


# ────────────────────────────── Configuración ───────────────────────────────

URL_PROMIEDOS = "https://www.promiedos.com.ar/"  # «/ayer» o «/man» se añaden dinámicamente
URL_EVENTOS = "https://la14hd.com/eventos/"
URL_LA14HD = "https://la14hd.com/"

PATH_DRIVER = "msedgedriver.exe"  # o chromedriver
HEADLESS = True  # cambiar a False para depurar
TIEMPO_ESPERA = 20  # segundos wait Selenium
INTERVALO_LOOP = 30  # segundos entre iteraciones

# Archivos de salida ------------------------------------------
SALIDA_PARTIDOS_HOY = Path("partidos.json")
SALIDA_PARTIDOS_AYER = Path("partidos_ayer.json")
SALIDA_PARTIDOS_MAN = Path("partidos_man.json")
SALIDA_CANALES = Path("canales.json")

# Añadir estas constantes al inicio del archivo, en la sección de configuración
SALIDA_DETALLES_HOY = Path("detalles_partidos_hoy.json")
SALIDA_DETALLES_AYER = Path("detalles_partidos_ayer.json")
SALIDA_DETALLES_MAN = Path("detalles_partidos_man.json")

# Mapping para los archivos de detalles
DIAS_DETALLES = {
    "": ("hoy", SALIDA_DETALLES_HOY),
    "ayer": ("ayer", SALIDA_DETALLES_AYER),
    "man": ("man", SALIDA_DETALLES_MAN),
}

# Clases CSS relevantes en Promiedos ---------------------------
CLS_ENCAB_LIGA = "event-header_left"
CLS_PARTIDO = "item_item"
CLS_EQUIPO = "command_title"
CLS_LOGO = "comand-imageteam"
CLS_MINUTO = "time_block"
CLS_SCORE = "scores_scoreseventresult"
CLS_GOLES_UL = "list-goals"

URL_PROMEDIOSINFO = "https://promediosinfo.com/"
PROMEDIOSINFO_LIGAS = [
    "liga/argentina.html",
    "liga/premier-league.html",
    "liga/la-liga.html",
    "liga/bundesliga.html",
    "liga/primera-b-nacional.html",
    "liga/brasileirao.html",
    "liga/portugal.html",
    "liga/arabia-saudita.html",
    "liga/ligue-1.html",
    "liga/eredivisie.html",
    "liga/uruguay.html",
    "liga/paraguay.html",
    "liga/chile.html",
    "liga/colombia.html",
    "liga/ecuador.html",
    "liga/peru.html",
    "liga/liga-mx.html",
    "liga/mls.html",
    "liga/segunda-division-espana.html",
    "liga/turquia.html",
    "liga/championship.html"
]

SALIDA_TABLAS_POSICIONES = Path("tablas_posiciones.json")

# Mapping slug → Path para iterar fácilmente ------------------
DIAS = {
    "": ("hoy", SALIDA_PARTIDOS_HOY),  # ruta vacía = hoy
    "ayer": ("ayer", SALIDA_PARTIDOS_AYER),
    "man": ("man", SALIDA_PARTIDOS_MAN),
}

# ────────────────────────────── Utilidades ──────────────────────────────────

def log(mensaje: str) -> None:
    """Imprime mensaje con timestamp HH:MM:SS"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {mensaje}")


def timestamp_iso() -> str:
    """Devuelve timestamp actual en ISO 8601 (segundos)"""
    return datetime.now().isoformat(timespec="seconds")


def crear_driver() -> webdriver.Edge:
    """Inicializa WebDriver Edge/Chrome en modo headless/new."""
    opts = Options()
    if HEADLESS:
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
    return webdriver.Edge(service=Service(PATH_DRIVER), options=opts)


def slug(txt: str) -> str:
    """Convierte cadena a slug simplificado (sin tildes, minúsculas, sin signos)."""
    txt = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode()
    txt = re.sub(r"[^a-z0-9 ]+", " ", txt.lower())
    return re.sub(r"\s+", " ", txt).strip()


def extraer_goleadores(nodo_partido) -> Tuple[List[str], List[str]]:
    """
    Intenta extraer los goleadores para cada equipo.
    Devuelve dos listas (goleadores1, goleadores2). Funciona para:
      • <ul class="list-goals"><li>Jugador 23'</li> ...</ul>   (Promiedos)
    Si no encuentra nada, devuelve listas vacías.
    """
    goleadores1, goleadores2 = [], []
    try:
        uls = nodo_partido.find_elements(By.CSS_SELECTOR, f"ul.{CLS_GOLES_UL}")
        if len(uls) >= 2:
            lis1 = uls[0].find_elements(By.TAG_NAME, "li")
            lis2 = uls[1].find_elements(By.TAG_NAME, "li")
            goleadores1 = [li.text.strip() for li in lis1 if li.text.strip()]
            goleadores2 = [li.text.strip() for li in lis2 if li.text.strip()]
    except Exception:
        pass
    return goleadores1, goleadores2


# Añadir esta nueva función
def scrapear_tablas_posiciones() -> None:
    """Scrapea las tablas de posiciones y las fechas con partidos de PromediosInfo para las ligas/copas especificadas."""
    driver = crear_driver()
    tablas_data = {}
    
    try:
        for liga in PROMEDIOSINFO_LIGAS:
            url = URL_PROMEDIOSINFO + liga
            log(f"Visitando {url}...")
            try:
                driver.get(url)
                WebDriverWait(driver, TIEMPO_ESPERA).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".table.is-fullwidth.tablePos.mb-5, #points"))
                )
                
                if "liga/" in liga:
                    # Buscar exactamente las dos primeras tablas de posiciones (no más)
                    tablas = driver.find_elements(By.CSS_SELECTOR, ".table.is-fullwidth.tablePos.mb-5")[:2]  # <-- Solo las 2 primeras
                    zonas = {}
                    
                    for i, tabla in enumerate(tablas, start=1):
                        zona = "A" if i == 1 else "B"  # Primera tabla = Zona A, segunda = Zona B
                        filas = []
                        
                        for fila in tabla.find_elements(By.CSS_SELECTOR, "tbody tr"):
                            celdas = fila.find_elements(By.TAG_NAME, "td")
                            if len(celdas) > 3:
                                fila_data = {
                                    "posicion": celdas[0].text.strip(),
                                    "equipo": celdas[1].text.strip(),
                                    "pts": celdas[2].text.strip(),
                                    "pj": celdas[3].text.strip(),
                                    "pg": celdas[4].text.strip() if len(celdas) > 4 else "",
                                    "pe": celdas[5].text.strip() if len(celdas) > 5 else "",
                                    "pp": celdas[6].text.strip() if len(celdas) > 6 else ""
                                }
                                filas.append(fila_data)
                        
                        zonas[f"Zona {zona}"] = filas
                    
                    # Si solo hay una tabla, la guardamos como "Zona Única"
                    if len(tablas) == 1:
                        tablas_data[liga] = {"Zona Única": zonas["Zona A"]}
                    else:
                        tablas_data[liga] = zonas
                    
                    # 2. Scrapear fechas con partidos (versión corregida)
                    fechas = []
                    lineas_fecha = driver.find_elements(By.CSS_SELECTOR, ".table.is-fullwidth.mb-6.noselect")
                    
                    for linea in lineas_fecha:
                        try:
                            # Obtener el título de la fecha (ej: "Fecha 12")
                            titulo_fecha = linea.find_element(By.CSS_SELECTOR, "thead th").text.strip()
                            
                            # Obtener los partidos de esta fecha
                            partidos = []
                            for fila in linea.find_elements(By.CSS_SELECTOR, "tbody tr"):
                                try:
                                    # Extraer datos con los selectores específicos
                                    local = fila.find_element(By.CSS_SELECTOR, ".team.tr").text.strip()
                                    visitante = fila.find_element(By.CSS_SELECTOR, ".team.tl").text.strip()
                                    hora = fila.find_element(By.CSS_SELECTOR, ".hours.time").text.strip()
                                    
                                    # Resultado y estado son opcionales
                                    resultado = ""
                                    estado = ""
                                    
                                    try:
                                        resultado = fila.find_element(By.CSS_SELECTOR, ".result").text.strip()
                                    except:
                                        pass
                                    
                                    try:
                                        estado = fila.find_element(By.CSS_SELECTOR, ".status").text.strip()
                                    except:
                                        pass
                                    
                                    partido = {
                                        "local": local,
                                        "visitante": visitante,
                                        "hora": hora,
                                        "resultado": resultado,
                                        "estado": estado
                                    }
                                    partidos.append(partido)
                                except Exception as e:
                                    log(f"Error procesando fila de partido: {e}")
                                    continue
                            
                            if partidos:
                                fechas.append({
                                    "titulo": titulo_fecha,
                                    "partidos": partidos
                                })
                        except Exception as e:
                            log(f"Error procesando fecha: {e}")
                            continue
                    
                    # Combinar datos de tablas y fechas
                    tablas_data[liga] = {
                        "tablas": zonas if zonas else {"Zona Única": filas} if len(tablas) == 1 else {},
                        "fechas": fechas
                    }
                
                else:
                    # Scrapear sección de puntos para copas
                    puntos_section = driver.find_element(By.ID, "points")
                    tablas_data[liga] = {
                        "contenido": puntos_section.text.strip(),
                        "html": puntos_section.get_attribute("innerHTML").strip(),
                        "fechas": []  # Las copas generalmente no tienen fechas
                    }
                
            except Exception as e:
                log(f"Error scraping {liga}: {e}")
                tablas_data[liga] = {"error": str(e)}
                continue
    
    finally:
        driver.quit()
    
    # Guardar los datos
    datos = {
        "timestamp": timestamp_iso(),
        "tablas": tablas_data
    }
    
    SALIDA_TABLAS_POSICIONES.write_text(
        json.dumps(datos, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    log(f"{SALIDA_TABLAS_POSICIONES} escrito (tablas={len(tablas_data)})")

# ───────────────────── Guardar eventos en JSON separado ─────────────────────

def guardar_eventos(eventos_dict: Dict[str, str]) -> None:
    """Guarda el mapping de eventos en un JSON separado."""
    datos = {
        "timestamp": timestamp_iso(),
        "eventos": eventos_dict,
    }
    Path("eventos.json").write_text(
        json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log("eventos.json escrito correctamente")

# ───────────────────── Scraping La14HD / eventos ────────────────────────────

def scrapear_eventos() -> None:
    driver = crear_driver()
    log("Visitando la14hd.com/eventos/ ...")
    driver.get(URL_EVENTOS)

    WebDriverWait(driver, TIEMPO_ESPERA).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".event-name"))
    )

    mapping: Dict[str, str] = {}
    eventos = driver.find_elements(By.CSS_SELECTOR, ".event")
    for ev in eventos:
        try:
            titulo = ev.find_element(By.CSS_SELECTOR, ".event-name").text.strip()
            link = ev.find_element(By.CSS_SELECTOR, ".iframe-link").get_attribute("value")
            if titulo and link:
                mapping[slug(titulo)] = link
        except Exception:
            continue

    driver.quit()
    log(f"Streams capturados en eventos: {len(mapping)}")
    guardar_eventos(mapping)  # ✅ Asegurate que esto esté así





def scrapear_detalles_partido(url: str, driver: webdriver.Edge) -> Dict[str, Any]:
    """Scrapea los detalles adicionales de una página de partido individual."""
    detalles = {
        "eventos_calendario": [],
        "stats": [],
        "alineaciones": {
            "local": [],
            "visitante": []
        }
    }
    
    try:
        log(f"Visitando detalles del partido: {url}")
        driver.get(url)
        
        # Esperar a que cargue la página
        WebDriverWait(driver, TIEMPO_ESPERA).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".events-items, .content-block, .team-lineups")))
        
        # 1. Scrapear eventos del calendario
        try:
            eventos_items = driver.find_elements(By.CSS_SELECTOR, ".events-items .calendario-events__items")
            for evento in eventos_items:
                try:
                    texto = evento.text.strip()
                    img = evento.find_element(By.TAG_NAME, "img").get_attribute("src") if evento.find_elements(By.TAG_NAME, "img") else None
                    if texto or img:
                        detalles["eventos_calendario"].append({
                            "texto": texto,
                            "imagen": img
                        })
                except Exception as e:
                    log(f"Error procesando evento individual: {e}")
        except Exception as e:
            log(f"Error al scrapear eventos del calendario: {e}")
        
        # 2. Scrapear estadísticas
        try:
            stats_blocks = driver.find_elements(By.CSS_SELECTOR, ".content-block.min .content-block__body .stats_item__4HYCD")
            detalles["stats"] = [stat.text.strip() for stat in stats_blocks if stat.text.strip()]
        except Exception as e:
            log(f"Error al scrapear estadísticas: {e}")
        
        # 3. Scrapear alineaciones (versión corregida)
        try:
            # Buscar la sección de alineaciones
            lineup_section = driver.find_element(By.CSS_SELECTOR, ".team-lineups")
            
            # Alineación local - usar selectores más específicos
            local_section = lineup_section.find_element(By.CSS_SELECTOR, ".team-lineup:first-child")
            jugadores_local = local_section.find_elements(By.CSS_SELECTOR, ".player-name")
            detalles["alineaciones"]["local"] = [j.text.strip() for j in jugadores_local if j.text.strip()]
            
            # Alineación visitante - usar selectores más específicos
            visitante_section = lineup_section.find_element(By.CSS_SELECTOR, ".team-lineup:last-child")
            jugadores_visitante = visitante_section.find_elements(By.CSS_SELECTOR, ".player-name")
            detalles["alineaciones"]["visitante"] = [j.text.strip() for j in jugadores_visitante if j.text.strip()]
            
            # Validación para evitar datos duplicados
            if (detalles["alineaciones"]["local"] and 
                detalles["alineaciones"]["visitante"] and 
                detalles["alineaciones"]["local"] == detalles["alineaciones"]["visitante"]):
                log("¡Advertencia! Alineaciones idénticas detectadas, limpiando datos")
                detalles["alineaciones"]["local"] = []
                detalles["alineaciones"]["visitante"] = []
                
        except Exception as e:
            log(f"Error al scrapear alineaciones: {e}")
            # Intentar método alternativo si el principal falla
            try:
                # Método alternativo para alineaciones
                all_players = driver.find_elements(By.CSS_SELECTOR, ".player_player__name__ZrMOH")
                if all_players:
                    mitad = len(all_players) // 2
                    detalles["alineaciones"]["local"] = [p.text.strip() for p in all_players[:mitad] if p.text.strip()]
                    detalles["alineaciones"]["visitante"] = [p.text.strip() for p in all_players[mitad:] if p.text.strip()]
            except Exception as alt_e:
                log(f"Error en método alternativo para alineaciones: {alt_e}")
    
    except Exception as e:
        log(f"Error general al scrapear detalles del partido: {e}")
        detalles["error"] = str(e)
    
    return detalles

def scrapear_detalles_partidos(dia_path: str, salida_path: Path) -> None:
    """Scrapea los detalles de los partidos para un día específico y los guarda en un archivo separado."""
    # Cargar los partidos del archivo correspondiente
    archivo_partidos = DIAS[dia_path][1]
    if not archivo_partidos.exists():
        log(f"Archivo {archivo_partidos} no encontrado, omitiendo detalles...")
        return
    
    try:
        with open(archivo_partidos, 'r', encoding='utf-8') as f:
            datos_partidos = json.load(f)
    except Exception as e:
        log(f"Error al cargar {archivo_partidos}: {e}")
        return
    
    # Preparar el driver
    driver = crear_driver()
    detalles_partidos = []
    
    try:
        # Iterar sobre todas las ligas y partidos
        for liga in datos_partidos.get("ligas", []):
            for partido in liga.get("partidos", []):
                if partido.get("href"):
                    url = URL_PROMIEDOS + partido["href"]
                    try:
                        detalles = scrapear_detalles_partido(url, driver)
                        detalles_partidos.append({
                            "href": partido["href"],
                            "equipo1": partido.get("equipo1"),
                            "equipo2": partido.get("equipo2"),
                            "detalles": detalles
                        })
                        time.sleep(1)  # Pequeño delay entre partidos
                    except Exception as e:
                        log(f"Error al scrapear detalles para {url}: {e}")
                        detalles_partidos.append({
                            "href": partido["href"],
                            "error": str(e)
                        })
    finally:
        driver.quit()
    
    # Guardar los detalles en el archivo correspondiente
    datos = {
        "timestamp": timestamp_iso(),
        "partidos_con_detalles": len(detalles_partidos),
        "detalles": detalles_partidos
    }
    
    salida_path.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"{salida_path} actualizado (partidos con detalles: {len(detalles_partidos)})")

# ───────────────────── Scraping Promiedos (genérico) ────────────────────────

def scrapear_partidos(dia_path: str, salida_path: Path) -> None:
    """Scrapea Promiedos para un día concreto y guarda en salida_path."""

    url = URL_PROMIEDOS + dia_path  # dia_path = "", "ayer", "man"
    dia_etiqueta = DIAS[dia_path][0]
    log(f"Visitando Promiedos ({dia_etiqueta}) … → {url}")

    driver = crear_driver()
    driver.get(url)

    # Esperamos a que cargue al menos un header de partido
    WebDriverWait(driver, TIEMPO_ESPERA).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, f"[class*='{CLS_ENCAB_LIGA}']"))
    )

    main = driver.find_element(By.TAG_NAME, "main")
    nodos = main.find_elements(By.CSS_SELECTOR, "*")

    ligas: List[Dict[str, Any]] = []
    liga_actual: str | None = None
    partidos: List[Dict[str, Any]] = []

    for nodo in nodos:
        clase: str = nodo.get_attribute("class") or ""

        # 1) Nuevo header de liga ------------------------------------------------
        if CLS_ENCAB_LIGA in clase:
            if liga_actual:
                ligas.append({"liga": liga_actual, "partidos": partidos})
            liga_actual = nodo.text.strip()
            partidos = []
            continue

        # 2) Nodo partido --------------------------------------------------------
        if CLS_PARTIDO in clase:
            # 2.0 Href --------------------------------------------------------------
            # 2.0 Href --------------------------------------------------------------
            href = None
            try:
                href = nodo.get_attribute("href")
                if href and href.startswith("https://www.promiedos.com.ar"):
                    href = href.replace("https://www.promiedos.com.ar", "")
            except Exception as e:
                log(f"❌ Error capturando href: {e}")



            # 2.1 Equipos --------------------------------------------------
            equipos = nodo.find_elements(By.CSS_SELECTOR, f"span[class*='{CLS_EQUIPO}']")
            if len(equipos) != 2:
                continue  # partido malformado
            equipo1, equipo2 = (e.text.strip() for e in equipos)

            # 2.2 Logos -----------------------------------------------------
            logos = nodo.find_elements(By.CSS_SELECTOR, f"div.{CLS_LOGO} img.team")
            logo1 = logos[0].get_attribute("src") if len(logos) >= 1 else None
            logo2 = logos[1].get_attribute("src") if len(logos) >= 2 else None

            # 2.3 Minuto / estado ------------------------------------------
            minuto = None
            try:
                minuto_div = nodo.find_element(By.CSS_SELECTOR, f"div[class*='{CLS_MINUTO}']")
                minuto = minuto_div.text.strip()
            except Exception:
                pass

            # 2.4 Resultado -------------------------------------------------
            goles1 = goles2 = None
            try:
                spans = nodo.find_elements(By.CSS_SELECTOR, f"span[class*='{CLS_SCORE}']")
                if len(spans) >= 2:
                    t1, t2 = (s.text.strip() for s in spans)
                    goles1 = t1 if t1.isdigit() else None
                    goles2 = t2 if t2.isdigit() else None
            except Exception:
                pass

            # 2.5 Goleadores -----------------------------------------------
            goleadores1, goleadores2 = [], []
            try:
                for bloque in nodo.find_elements(By.CSS_SELECTOR, "div[class*='gols_itemLeft'] span[class*='gols_block']"):
                    minuto1 = bloque.find_element(By.CSS_SELECTOR, "span.green").text.strip()
                    jugador = bloque.find_element(By.TAG_NAME, "p").text.strip()
                    if minuto1 and jugador:
                        if not minuto1.endswith("'"):
                            minuto1 += "'"
                        goleadores1.append(f"{minuto1} {jugador}")

                for bloque in nodo.find_elements(By.CSS_SELECTOR, "div[class*='gols_itemRight'] span[class*='gols_block']"):
                    minuto2 = bloque.find_element(By.CSS_SELECTOR, "span.green").text.strip()
                    jugador = bloque.find_element(By.TAG_NAME, "p").text.strip()
                    if minuto2 and jugador:
                        if not minuto2.endswith("'"):
                            minuto2 += "'"
                        goleadores2.append(f"{minuto2} {jugador}")

                # Deduplicamos preservando orden
                goleadores1 = list(dict.fromkeys(goleadores1))
                goleadores2 = list(dict.fromkeys(goleadores2))
            except Exception:
                pass

            # 2.6 Agregamos al listado -------------------------------------
            partidos.append(
                {
                    "equipo1": equipo1,
                    "logo1": logo1,
                    "goles1": goles1,
                    "goleadores1": goleadores1,
                    "equipo2": equipo2,
                    "logo2": logo2,
                    "goles2": goles2,
                    "goleadores2": goleadores2,
                    "minuto": minuto,
                    "href": href,  # ✅ <--- agregado
                }
            )

    # Añadimos la última liga pendiente ----------------------------------------
    if liga_actual:
        ligas.append({"liga": liga_actual, "partidos": partidos})

    driver.quit()

    # Serializamos a JSON ------------------------------------------------------
    datos = {"timestamp": timestamp_iso(), "ligas": ligas}
    salida_path.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"{salida_path} actualizado (ligas: {len(ligas)})")

# ───────────────────── Scraping Canales base (La14HD) ───────────────────────

def scrapear_canales() -> None:
    driver = crear_driver()
    log("Visitando la14hd.com (canales) ...")
    driver.get(URL_LA14HD)

    WebDriverWait(driver, TIEMPO_ESPERA).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-canal]"))
    )

    canales: List[Dict[str, str]] = []
    for div in driver.find_elements(By.CSS_SELECTOR, "div[data-canal]"):
        try:
            canal = div.get_attribute("data-canal").strip()
            link = div.find_element(By.TAG_NAME, "a").get_attribute("href").strip()
            canales.append({"canal": canal, "link": link})
        except Exception:
            continue

    driver.quit()
    SALIDA_CANALES.write_text(
        json.dumps({"timestamp": timestamp_iso(), "canales": canales}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log(f"{SALIDA_CANALES} escrito (canales={len(canales)})")

# ───────────────────────────── Loop principal ───────────────────────────────

def necesita_actualizar_dia(salida_path: Path, dia_path: str) -> bool:
    """Verifica si el archivo del día necesita ser actualizado."""
    if not salida_path.exists():
        return True
    
    try:
        datos = json.loads(salida_path.read_text(encoding="utf-8"))
        fecha_actualizacion = datetime.fromisoformat(datos["timestamp"])
        
        # Para hoy, actualizar siempre
        if dia_path == "":
            return True
            
        # Para ayer/mañana, actualizar si tiene más de 1 hora
        return (datetime.now() - fecha_actualizacion).total_seconds() > 3600
    except Exception:
        return True

def iteracion_frecuente() -> None:
    """Ejecuta una iteración completa para HOY, AYER y MAÑANA."""
    # Siempre actualiza hoy
    scrapear_partidos("", SALIDA_PARTIDOS_HOY)
    scrapear_detalles_partidos("", SALIDA_DETALLES_HOY)
    
    # Para ayer y mañana, verifica si necesita actualización
    for path_suffix, (_, salida) in DIAS.items():
        if path_suffix:  # Solo para "ayer" y "man" (no vacío)
            if necesita_actualizar_dia(salida):
                scrapear_partidos(path_suffix, salida)
                scrapear_detalles_partidos(path_suffix, DIAS_DETALLES[path_suffix][1])
            else:
                log(f"{salida} ya actualizado hoy, omitiendo...")

def iteracion_infrecuente() -> None:
    """Ejecuta las actualizaciones menos frecuentes (canales y eventos)."""
    scrapear_eventos()
    scrapear_canales()
    scrapear_tablas_posiciones()
    scrapear_detalles_partidos("", SALIDA_DETALLES_HOY)
    
    # También podemos actualizar los detalles de todos los días en las iteraciones infrecuentes
    for path_suffix, (_, salida) in DIAS_DETALLES.items():
        scrapear_detalles_partidos(path_suffix, salida)





# CONFIGURAR FLASK
app = Flask(__name__)
CORS(app)

# ========== FLASK ENDPOINTS ==========
@app.route('/results')
@app.route('/results/<path:dia>')
def api_resultados(dia=None):
    dia_path = "" if not dia else dia
    salida = DIAS.get(dia_path, DIAS[""])[1]

    if necesita_actualizar_dia(salida, dia_path):
        scrapear_partidos(dia_path, salida)

    try:
        with open(salida, 'r', encoding='utf-8') as f:
            datos = json.load(f)
        return jsonify(datos)
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route('/standings', methods=['GET'])
def api_tablas():
    if not SALIDA_TABLAS_POSICIONES.exists():
        scrapear_tablas_posiciones()

    try:
        with open(SALIDA_TABLAS_POSICIONES, 'r', encoding='utf-8') as f:
            datos = json.load(f)
        return jsonify(datos)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/games')
@app.route('/games/<path:dia>')
def api_detalles_jornada(dia=None):
    dia_path = "" if not dia else dia
    salida = DIAS_DETALLES.get(dia_path, DIAS_DETALLES[""])[1]

    if necesita_actualizar_dia(salida, dia_path):
        scrapear_detalles_partidos(dia_path, salida)

    try:
        with open(salida, 'r', encoding='utf-8') as f:
            datos = json.load(f)
        return jsonify(datos)
    except Exception as e:
        return jsonify({"error": str(e)}), 500





@app.route('/eventos', methods=['GET'])
def api_eventos():
    try:
        scrapear_eventos()
        with open("eventos.json", "r", encoding="utf-8") as f:
            datos = json.load(f)
        return jsonify(datos)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/canales', methods=['GET'])
def api_canales():
    try:
        scrapear_canales()
        with open(SALIDA_CANALES, "r", encoding="utf-8") as f:
            datos = json.load(f)
        return jsonify(datos)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========== LOOP DE SCRAPING EN SEGUNDO PLANO ==========
INTERVALO_LOOP = 30  # segundos

def loop_scraping():
    contador = 0
    log("🧠 Hilo de scraping iniciado")
    while True:
        try:
            log(f"🌀 Iteración #{contador}")
            for path_suffix, (_, salida) in DIAS.items():
                if necesita_actualizar_dia(salida, path_suffix):
                    scrapear_partidos(path_suffix, salida)
                    log(f"✅ {salida} actualizado")

            for path_suffix, (_, salida) in DIAS_DETALLES.items():
                scrapear_detalles_partidos(path_suffix, salida)

            if contador % 10 == 0:
                scrapear_eventos()
                scrapear_canales()
                scrapear_tablas_posiciones()
                log("✅ Actualización infrecuente completada")

            contador += 1
        except Exception as exc:
            log(f"❌ Error general en loop: {exc}")
        time.sleep(INTERVALO_LOOP)

# ========== INICIO DE SERVIDOR ==========
#*
# Esto permite que Vercel importe la app sin ejecutar nada extra
app = app
