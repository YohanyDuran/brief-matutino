#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VACANTES — Fase 3
=================
Busca ofertas laborales en los portales oficiales de la gran minería y
devuelve el bloque de texto listo para pegar en el brief matutino.

SCRAPER B — SAP SuccessFactors RMK
-----------------------------------
Las cinco empresas de abajo corren sobre el mismo motor (SuccessFactors
Recruiting Marketing, ex Jobs2Web), así que comparten un solo scraper.

Codelco estaba clasificada en el CLAUDE.md como "Scraper A / career8", pero
sus enlaces internos apuntan a jobs2web con `?locale=`: es RMK, y va acá.

SOBRE robots.txt — leer antes de agregar fuentes
------------------------------------------------
`career8.successfactors.com` prohíbe TODO rastreo (`Disallow: /`, solo
`/login` permitido), así que NO se usa pese a ser el portal de fondo. Las
cinco entradas públicas de acá comparten un robots.txt permisivo, idéntico
entre ellas, que solo bloquea rutas funcionales:

    Disallow: /applybutton/  /talentcommunity/  /emailsubscribe/
    Disallow: /services/     /preapply/         /unsubscribe/
    Disallow: /error         /reset/            /email/image/

La búsqueda de ofertas NO está bloqueada. Verificado sitio por sitio.

No existe API JSON ni feed RSS en ninguna: se probaron /tile-search-results/,
/search-results/, ?format=json, RSS y JSON-LD. Por eso se parsea HTML, que la
regla 4 del proyecto permite solo cuando no hay alternativa.

DOS VISTAS DISTINTAS
--------------------
RMK se configura por cliente y hay dos maquetados:
  - Tarjetas  (`li.job-tile`)   → Codelco, Lundin
  - Tabla     (`tr.data-row`)   → BHP, Kinross
El extractor busca los enlaces `/job/` y sube hasta la fila que los contiene,
así funciona con ambos sin código separado por empresa.

FILOSOFÍA DE ERRORES: si una fuente se cae, las demás siguen. Solo si fallan
TODAS se levanta la excepción, y ahí `main()` lo reporta como fuente caída
pero el brief se envía igual con los otros bloques.
"""

import html
import re
import time
import unicodedata
from datetime import date, datetime, timedelta

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# FUENTES
# ---------------------------------------------------------------------------

# solo_chile=True  -> el portal ya publica únicamente vacantes en Chile.
# solo_chile=False -> es un portal global; hay que filtrar por ubicación.
FUENTES = [
    {"nombre": "Codelco",       "base": "https://empleos.codelco.cl",       "solo_chile": True},
    {"nombre": "BHP",           "base": "https://careers.bhp.com",          "solo_chile": False},
    {"nombre": "Teck",          "base": "https://jobs.teck.com",            "solo_chile": False},
    {"nombre": "Kinross",       "base": "https://jobs.kinross.com",         "solo_chile": False},
    {"nombre": "Lundin Mining", "base": "https://jobs.lundinmining.com",    "solo_chile": False},
]

CABECERAS = {
    "User-Agent": (
        "BriefMatutino/1.0 "
        "(+https://github.com/YohanyDuran/brief-matutino) python-requests"
    )
}

TIMEOUT = 30
PAUSA = 1.5                # segundos entre requests; no martillar
PAGINAS_POR_FUENTE = 3     # RMK pagina de a 25; 3 páginas ≈ 75 avisos
MAX_DETALLES = 8           # solo se abre el aviso de las que calzan
MAX_EN_MENSAJE = 10
DIAS_RECORDAR = 30

# Las que solo nombran tus palabras clave en la fila del listado, sin tenerlas
# en el cargo. Resultaron ruidosas, así que van apagadas por defecto.
MOSTRAR_MENCIONES = False
MIN_MENCIONES = 2
MAX_MENCIONES = 5

# Perfil objetivo. Se buscan como frases completas, sin tildes y en minúscula.
PALABRAS_CLAVE = [
    "mejora continua",
    "excelencia operacional",
    "operational excellence",
    "lean manufacturing",
    "lean",
    "six sigma",
    "agente de cambio",
    "change management",
    "gestion del cambio",
    "productividad",
    "optimizacion de procesos",
    "continuous improvement",
    "business process",
    "transformacion operacional",
    "mejoramiento continuo",
    "process improvement",
]

# Señales de que una vacante es en Chile. Se aplica solo a los portales
# globales: nombres de faena chilena, regiones, ciudades y el código de país.
SENALES_CHILE = [
    "chile", "escondida", "spence", "cerro colorado", "quebrada blanca",
    "carmen de andacollo", "andacollo", "candelaria", "caserones",
    "la coipa", "lobo-marte", "lobo marte", "collahuasi", "salares norte",
    "antofagasta", "calama", "copiapo", "santiago", "iquique", "rancagua",
    "los andes", "valparaiso", "la serena", "coquimbo", "vallenar",
    "diego de almagro", "el salvador", "chuquicamata",
    # OJO: no agregar "region" a secas. Matcheaba "Inchiri region,
    # Mauritania" y colaba vacantes africanas de Kinross.
]

MESES_ABREV = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}


# ---------------------------------------------------------------------------
# UTILIDADES DE TEXTO
# ---------------------------------------------------------------------------

def normalizar(texto: str) -> str:
    """
    Deja el texto comparable: sin tildes, en minúscula y con los espacios
    colapsados. Así 'Optimización' encuentra 'optimizacion' y 'OPTIMIZACIÓN'.
    """
    if not texto:
        return ""
    descompuesto = unicodedata.normalize("NFD", texto)
    sin_tildes = "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sin_tildes.lower()).strip()


def contiene_frase(texto_normalizado: str, frase: str) -> bool:
    """
    Busca la frase completa respetando límites de palabra.

    Con esto 'lean' no matchea dentro de otra palabra, y 'mejora continua'
    exige las dos palabras juntas y en ese orden, no una suelta por ahí.
    """
    patron = r"\b" + re.escape(frase).replace(r"\ ", r"\s+") + r"\b"
    return re.search(patron, texto_normalizado) is not None


def _url_segura(url: str) -> str:
    """
    Deja la URL en una forma que WhatsApp y Telegram reconozcan entera.

    Los avisos de Codelco incluyen nombres como "Bernardo O'Higgins". Si el
    apóstrofo va crudo, WhatsApp corta el enlace ahí y queda inútil. Lo mismo
    con espacios, comillas y paréntesis. Se codifican de vuelta.
    """
    reemplazos = {
        "'": "%27", '"': "%22", " ": "%20",
        "(": "%28", ")": "%29", "<": "%3C", ">": "%3E",
    }
    for crudo, codificado in reemplazos.items():
        url = url.replace(crudo, codificado)
    return url


def es_de_chile(texto: str) -> bool:
    """
    True si la fila del aviso apunta a Chile.

    Se usa solo en los portales globales. Lundin, por ejemplo, escribe la
    ubicación como 'Copiapó, AT, CL' vs 'Alto Horizonte, GO, BR', así que el
    código de país de dos letras es la señal más confiable cuando está.
    """
    t = normalizar(texto)
    if re.search(r",\s*cl\b", t):
        return True
    return any(s in t for s in SENALES_CHILE)


MESES_LARGOS = ("enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
                "septiembre|setiembre|octubre|noviembre|diciembre")


def _parece_fecha(texto: str) -> bool:
    """
    True si el texto tiene pinta de fecha: un nombre de mes y un año de 4
    dígitos. Sirve para no dejar pasar basura donde va una fecha.
    """
    t = normalizar(texto)
    return bool(re.search(MESES_LARGOS, t) and re.search(r"\b\d{4}\b", t))


def _fecha_valida(texto: str) -> bool:
    """True si el texto es una fecha ISO legible. Las corruptas se descartan."""
    try:
        date.fromisoformat(texto)
        return True
    except (ValueError, TypeError):
        return False


def parsear_fecha(texto: str):
    """Convierte '20 ago 2026' en un date. Devuelve None si no se entiende."""
    m = re.search(r"(\d{1,2})\s+([a-zA-Z]{3})\w*\.?\s+(\d{4})", normalizar(texto))
    if not m:
        return None
    mes = MESES_ABREV.get(m.group(2)[:3])
    if not mes:
        return None
    try:
        return date(int(m.group(3)), mes, int(m.group(1)))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# DESCARGA Y EXTRACCIÓN
# ---------------------------------------------------------------------------

def _pedir(url: str) -> str:
    respuesta = requests.get(url, headers=CABECERAS, timeout=TIMEOUT)
    respuesta.raise_for_status()
    return respuesta.text


def _fila_contenedora(enlace):
    """
    Sube desde el enlace del cargo hasta la fila que lo contiene.

    Ojo: NO cortar al ver 'job' en la clase. En Kinross el propio enlace vive
    dentro de un <span class="jobTitle">, y cortar ahí devuelve solo el título
    sin la ubicación ni la fecha. Se sube hasta un <tr> o <li> de verdad.
    """
    nodo = enlace
    for _ in range(8):
        if nodo.parent is None:
            break
        nodo = nodo.parent
        clases = " ".join(nodo.get("class", []))
        if nodo.name in ("tr", "li") or "job-tile" in clases or "data-row" in clases:
            return nodo
    return enlace.parent or enlace


def listar_rmk(fuente: dict) -> list:
    """
    Trae las vacantes de un portal RMK, paginando de a una página por request.

    Funciona con las dos vistas del motor (tarjetas y tabla) porque se apoya
    en los enlaces `/job/`, que están en ambas, y no en un maquetado concreto.
    """
    base = fuente["base"]
    vacantes, vistos = [], set()

    for pagina in range(PAGINAS_POR_FUENTE):
        if pagina > 0:
            time.sleep(PAUSA)

        sopa = BeautifulSoup(
            _pedir(f"{base}/search/?q=&startrow={pagina * 25}"), "html.parser"
        )

        nuevos_en_pagina = 0
        for enlace in sopa.select('a[href*="/job/"]'):
            ruta = enlace.get("href", "")
            m = re.search(r"/job/[^/]*?/(\d+)/?", ruta)
            if not m:
                continue

            job_id = f"{fuente['nombre']}:{m.group(1)}"
            if job_id in vistos:
                continue

            cargo = enlace.get_text(" ", strip=True)
            if not cargo:
                continue

            vistos.add(job_id)
            nuevos_en_pagina += 1

            fila = _fila_contenedora(enlace)
            contexto = re.sub(r"\s+", " ", fila.get_text(" | ", strip=True))

            vacantes.append({
                "id": job_id,
                "cargo": html.unescape(cargo),
                "empresa": fuente["nombre"],
                "contexto": html.unescape(contexto),
                "url": _url_segura(html.unescape(
                    ruta if ruta.startswith("http") else base + ruta)),
                # Se completan en detallar(), solo para las que calzan:
                "lugar": "",
                "jornada": "",
                "contrato": "",
                "cierre": "",
                "fecha_txt": "",
                "descripcion": "",
            })

        # Si la página no aportó nada nuevo, ya no hay más resultados.
        if nuevos_en_pagina == 0:
            break

    return vacantes


# Etiquetas del cuerpo del aviso. Ojo con el orden: 'hora de cierre...' va
# ANTES que 'cierre...' para que gane la más larga. Y el \w* es imprescindible:
# sin él, 'postulaci' no cubre 'postulaciones' y el corte falla.
ETIQUETAS = (
    r"lugar de trabajo|jornada laboral|n[uú]mero de vacantes|"
    r"hora de cierre de postulaci\w*|cierre de postulaci\w*|"
    r"contrato|cargo contractual|condiciones ofrecidas|requisitos|"
    r"renta|beneficios"
)
FIN_CAMPO = rf"(?=\s*(?:{ETIQUETAS})\s*:|\.|$)"

CAMPOS_DETALLE = [
    ("lugar", rf"lugar de trabajo\s*:\s*(.{{3,90}}?){FIN_CAMPO}"),
    ("jornada", rf"jornada laboral\s*:\s*(.{{3,90}}?){FIN_CAMPO}"),
    ("contrato", rf"\bcontrato\s*:\s*(.{{3,60}}?){FIN_CAMPO}"),
    ("cierre", rf"cierre de postulaci\w*\s*:\s*(.{{3,60}}?){FIN_CAMPO}"),
]


def detallar(vacante: dict) -> dict:
    """
    Entra al aviso y completa faena, jornada, contrato y fecha de cierre.

    Estas etiquetas siguen la plantilla de Codelco. En los otros portales
    puede que no existan, y está bien: los campos quedan vacíos y el
    formateador simplemente no los muestra. Mejor incompleta que perdida.
    """
    try:
        sopa = BeautifulSoup(_pedir(vacante["url"]), "html.parser")
        texto = sopa.get_text(" ", strip=True)
        vacante["descripcion"] = texto

        plano = re.sub(r"\s+", " ", texto)
        for campo, patron in CAMPOS_DETALLE:
            m = re.search(patron, plano, re.IGNORECASE)
            if not m:
                continue
            valor = html.unescape(m.group(1)).strip(" .,;:")

            # Red de seguridad: si el "cierre" no parece fecha, se descarta.
            if campo == "cierre" and not _parece_fecha(valor):
                continue

            vacante[campo] = valor
    except (requests.RequestException, ValueError) as e:
        print(f"    No pude abrir el detalle de '{vacante['cargo'][:40]}': {e}")

    return vacante


# ---------------------------------------------------------------------------
# FILTRO DE RELEVANCIA
# ---------------------------------------------------------------------------

def evaluar(vacante: dict) -> dict:
    """
    Clasifica la vacante en tres niveles:

      "calza"   La palabra clave está en el CARGO. Es del rubro que buscas.
      "mencion" Aparece solo en el resto de la fila. Ojo: las mineras ponen
                "mejora continua" de relleno en casi todo, así que esto NO
                significa que el cargo sea del rubro.
      "no"      No aplica.

    Por qué el título manda: un "Superintendente de Fundición" puede nombrar
    mejora continua tres veces y aun así no ser un cargo de mejora continua.
    El cargo es el dato duro; el resto es contexto.
    """
    titulo = normalizar(vacante["cargo"])
    resto = normalizar(vacante.get("contexto", "") + " " + vacante.get("descripcion", ""))

    en_titulo = [k for k in PALABRAS_CLAVE if contiene_frase(titulo, k)]
    en_resto = [k for k in PALABRAS_CLAVE if contiene_frase(resto, k)]

    vacante["hits_titulo"] = en_titulo
    vacante["hits_resto"] = en_resto
    vacante["puntaje"] = len(en_titulo) * 10 + len(en_resto)

    if en_titulo:
        vacante["nivel"] = "calza"
    elif len(en_resto) >= MIN_MENCIONES:
        vacante["nivel"] = "mencion"
    else:
        vacante["nivel"] = "no"

    return vacante


# ---------------------------------------------------------------------------
# FORMATO
# ---------------------------------------------------------------------------

# Nombres de columna que aparecen como texto en la fila del listado. No son
# datos, son rótulos, y hay que ignorarlos al buscar la ubicación.
ETIQUETAS_DE_FILA = {
    "titulo", "title", "region", "location", "ubicacion", "fecha", "date",
    "business unit", "department", "posting start date", "id de proceso",
    "codigo postal", "distancia", "tipo", "reset",
}


def _ubicacion(vacante: dict) -> str:
    """La faena si se alcanzó a leer del aviso; si no, lo que diga la fila."""
    if vacante["lugar"]:
        return vacante["lugar"]
    # De la fila del listado, quedarse con el trozo que parece ubicación.
    # Hay que saltarse las etiquetas: la fila viene como
    # "Región | 5ta.Reg.Valparaíso", y sin esto devolvía "Región".
    for trozo in vacante.get("contexto", "").split(" | "):
        limpio = trozo.strip()
        if not limpio or normalizar(limpio) in ETIQUETAS_DE_FILA:
            continue
        if es_de_chile(limpio) and len(limpio) < 60 and limpio != vacante["cargo"]:
            return limpio
    return ""


def resumir(vacante: dict) -> str:
    """Una línea para las menciones: cargo, dónde, y el link."""
    ubicacion = _ubicacion(vacante)
    cabeza = f"{vacante['cargo']} ({vacante['empresa']})"
    if ubicacion:
        cabeza += f" — {ubicacion}"
    return f"{cabeza}\n  {vacante['url']}"


def formatear(vacante: dict, es_nueva: bool) -> str:
    marca = "🆕 " if es_nueva else ""
    lineas = [f"{marca}*{vacante['cargo']}*"]

    detalle = " · ".join(x for x in [vacante["empresa"], _ubicacion(vacante)] if x)
    if detalle:
        lineas.append(detalle)

    extra = " · ".join(x for x in [vacante["jornada"], vacante["contrato"]] if x)
    if extra:
        lineas.append(extra)

    if vacante["cierre"]:
        lineas.append(f"Cierra: {vacante['cierre']}")

    lineas.append(vacante["url"])
    return "\n".join(lineas)


# ---------------------------------------------------------------------------
# BLOQUE PARA EL BRIEF
# ---------------------------------------------------------------------------

def recolectar() -> list:
    """
    Recorre todas las fuentes y devuelve las vacantes de Chile.

    Si una fuente falla, se anota y se sigue con las demás. Solo si fallan
    TODAS se levanta la excepción.
    """
    todas, caidas = [], []

    for i, fuente in enumerate(FUENTES):
        if i > 0:
            time.sleep(PAUSA)
        try:
            crudas = listar_rmk(fuente)
            if fuente["solo_chile"]:
                chilenas = crudas
            else:
                chilenas = [v for v in crudas
                            if es_de_chile(v["contexto"] + " " + v["cargo"])]
            print(f"  {fuente['nombre']:14} {len(crudas):3} avisos -> "
                  f"{len(chilenas):3} en Chile")
            todas.extend(chilenas)
        except Exception as e:                      # noqa: BLE001
            print(f"  {fuente['nombre']:14} FALLO: {type(e).__name__}: {str(e)[:70]}")
            caidas.append(fuente["nombre"])

    if len(caidas) == len(FUENTES):
        raise RuntimeError(f"Fallaron todas las fuentes: {', '.join(caidas)}")

    return todas


def bloque_vacantes(estado: dict, hoy: date) -> str:
    """
    Arma la sección de vacantes del brief.

    Los domingos entrega el resumen semanal: todas las vigentes que calzan,
    no solo las nuevas.
    """
    estado.setdefault("vacantes_enviadas", {})

    # Se olvidan las vacantes vistas hace mucho, para que estado.json no
    # crezca sin fin. Mismo criterio que usan las frases y las palabras.
    limite = hoy - timedelta(days=DIAS_RECORDAR)
    estado["vacantes_enviadas"] = {
        k: f for k, f in estado["vacantes_enviadas"].items()
        if _fecha_valida(f) and date.fromisoformat(f) > limite
    }

    todas = recolectar()
    evaluadas = [evaluar(v) for v in todas]
    evaluadas.sort(key=lambda v: v["puntaje"], reverse=True)

    calzan = [v for v in evaluadas if v["nivel"] == "calza"]
    menciones = [v for v in evaluadas if v["nivel"] == "mencion"]
    print(f"Total en Chile: {len(todas)} | Calzan en el cargo: {len(calzan)}"
          f" | Menciones: {len(menciones)}")

    # El detalle cuesta un request por aviso, así que solo se abren las que
    # calzan: nunca son muchas, y son las únicas que se muestran completas.
    for i, vacante in enumerate(calzan[:MAX_DETALLES]):
        if i > 0:
            time.sleep(PAUSA)
        detallar(vacante)

    vistas = estado["vacantes_enviadas"]
    es_domingo = hoy.weekday() == 6

    if es_domingo:
        titulo = "💼 *Resumen semanal de vacantes*"
        principales, secundarias = calzan, menciones
    else:
        titulo = "💼 *Vacantes*"
        principales = [v for v in calzan if v["id"] not in vistas]
        secundarias = [v for v in menciones if v["id"] not in vistas]

    partes = [titulo]

    if principales:
        for vacante in principales[:MAX_EN_MENSAJE]:
            partes.append(formatear(vacante, es_nueva=vacante["id"] not in vistas))
        sobrantes = len(principales) - MAX_EN_MENSAJE
        if sobrantes > 0:
            partes.append(f"…y {sobrantes} más en los portales.")
    elif es_domingo:
        partes.append("No hay vacantes vigentes con tu perfil en el cargo.")
    else:
        partes.append("Hoy no hay vacantes nuevas con tu perfil en el cargo.")

    if MOSTRAR_MENCIONES and secundarias:
        partes.append(
            "_Solo mencionan tus palabras clave, el cargo es de otra área:_\n"
            + "\n".join(f"• {resumir(v)}" for v in secundarias[:MAX_MENCIONES])
        )

    # Se marcan como vistas DESPUÉS de armar el texto, para que el 🆕 salga
    # bien en este mensaje.
    for vacante in principales[:MAX_EN_MENSAJE] + secundarias[:MAX_MENCIONES]:
        vistas[vacante["id"]] = hoy.isoformat()

    return "\n\n".join(partes)


# ---------------------------------------------------------------------------
# PRUEBA MANUAL:  python vacantes.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(bloque_vacantes({}, datetime.now().date()))
