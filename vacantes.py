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
MAX_ADYACENTES = 6         # tope de la lista 'quizás te interese'

# ---------------------------------------------------------------------------
# DICCIONARIO DEL PERFIL
# ---------------------------------------------------------------------------
# Todo se compara normalizado: sin tildes, en minúscula y como frase completa
# con límites de palabra. Por eso van sin tilde y en singular/plural cuando el
# plural no se deduce solo.

# NIVEL 1 — El cargo ES del rubro. Se muestra completo, con 🆕.
PALABRAS_CLAVE = [
    # --- Mejora continua, todas sus formas ---
    "mejora continua", "mejoras continuas", "mejoramiento continuo",
    "mejora de procesos", "mejora operacional", "mejora de gestion",
    "continuous improvement", "continual improvement",
    "process improvement", "business process improvement",
    "performance improvement", "productivity improvement",
    "kaizen",

    # --- Excelencia operacional ---
    "excelencia operacional", "excelencia operativa", "excelencia de procesos",
    "excelencia en gestion", "excelencia del negocio",
    "operational excellence", "operations excellence", "operating excellence",
    "business excellence", "process excellence", "manufacturing excellence",

    # --- Lean / Six Sigma / WCM ---
    "lean", "lean manufacturing", "lean management", "lean construction",
    "lean six sigma", "six sigma", "6 sigma", "black belt", "green belt",
    "world class manufacturing", "wcm", "tps",

    # --- Gestión y agentes de cambio ---
    "agente de cambio", "agentes de cambio", "gestion del cambio",
    "gestion de cambio", "change management", "change agent",
    "organizational change", "cambio organizacional",

    # --- Optimización y reingeniería ---
    "optimizacion de procesos", "optimizacion operacional",
    "optimizacion de gestion", "reingenieria de procesos", "reingenieria",
    "process optimization", "process optimisation", "process reengineering",
    "estandarizacion de procesos", "standardization of processes",

    # --- Productividad y eficiencia ---
    "productividad", "productivity", "eficiencia operacional",
    "eficiencia de procesos", "operational efficiency",

    # --- Transformación ---
    "transformacion operacional", "transformacion de procesos",
    "transformacion del negocio", "operational transformation",
    "business transformation", "transformation",

    # --- Gestión de procesos de negocio ---
    "business process", "business process management", "bpm",
    "gestion de procesos de negocio",
]

# NIVEL 2 — Adyacentes. El cargo no es del rubro, pero está al lado y vale la
# pena echarle un ojo. Se muestran aparte, en una línea, sin 🆕.
PALABRAS_ADYACENTES = [
    # Gestión y procesos en general
    "ingeniero de gestion", "ingeniera de gestion", "control de gestion",
    "gerente de procesos", "jefe de procesos", "ingeniero de procesos",
    "superintendente de procesos", "analista de procesos",
    "process engineer", "process manager", "gestion de operaciones",

    # Puesta en marcha y preparación operacional
    "operational readiness", "preparacion operacional", "puesta en marcha",
    "commissioning", "ramp up", "rampa de produccion",

    # Planificación y gestión del trabajo
    "planificacion y control", "work management", "planning and control",
    "gestion del trabajo", "programacion y control",

    # Proyectos y estrategia
    "pmo", "project management office", "oficina de proyectos",
    "gestion de proyectos", "estrategia operacional", "planificacion estrategica",

    # Datos y automatización aplicados a operaciones
    "transformacion digital", "digital transformation",
    "automatizacion de procesos", "process automation",
    "analitica operacional", "operational analytics",

    # Confiabilidad y mantenimiento de clase mundial
    "confiabilidad operacional", "operational reliability",
    "mantenimiento de clase mundial", "tpm",
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

            # BHP escribe el cargo como "Principal PMO | BHP Chile": la
            # ubicación va dentro del título. Se separa, si no el mensaje
            # termina repitiendo el nombre de la empresa tres veces.
            sufijo_ubicacion = ""
            if " | " in cargo:
                cargo, _, sufijo_ubicacion = cargo.partition(" | ")
                cargo = cargo.strip()

            vistos.add(job_id)
            nuevos_en_pagina += 1

            fila = _fila_contenedora(enlace)
            contexto = re.sub(r"\s+", " ", fila.get_text(" | ", strip=True))

            vacantes.append({
                "id": job_id,
                "cargo": html.unescape(cargo),
                "empresa": fuente["nombre"],
                "contexto": html.unescape(
                    (sufijo_ubicacion + " | " + contexto) if sufijo_ubicacion
                    else contexto),
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
    Clasifica la vacante en cuatro niveles:

      "calza"     Palabra clave del NIVEL 1 en el CARGO. Es del rubro que
                  buscas. Se muestra completa, con 🆕.
      "adyacente" Palabra clave del NIVEL 2 en el CARGO. No es del rubro pero
                  está al lado. Va en una lista aparte, de una línea.
      "mencion"   El cargo no tiene nada, pero el aviso nombra tus palabras
                  clave. Ojo: las mineras ponen "mejora continua" de relleno
                  en casi todo. Apagado por defecto.
      "no"        No aplica.

    Por qué el título manda: un "Superintendente de Fundición" puede nombrar
    mejora continua tres veces y aun así no ser un cargo de mejora continua.
    El cargo es el dato duro; el resto es contexto.
    """
    titulo = normalizar(vacante["cargo"])
    resto = normalizar(vacante.get("contexto", "") + " " + vacante.get("descripcion", ""))

    en_titulo = [k for k in PALABRAS_CLAVE if contiene_frase(titulo, k)]
    adyacentes = [k for k in PALABRAS_ADYACENTES if contiene_frase(titulo, k)]
    en_resto = [k for k in PALABRAS_CLAVE if contiene_frase(resto, k)]

    vacante["hits_titulo"] = en_titulo
    vacante["hits_adyacentes"] = adyacentes
    vacante["hits_resto"] = en_resto
    vacante["puntaje"] = len(en_titulo) * 100 + len(adyacentes) * 10 + len(en_resto)

    if en_titulo:
        vacante["nivel"] = "calza"
    elif adyacentes:
        vacante["nivel"] = "adyacente"
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


def _empresa_y_lugar(vacante: dict) -> str:
    """
    'Empresa · Lugar', sin repetir. Algunos portales ya nombran la empresa en
    la ubicación ('BHP Chile'), y no hay que decirlo dos veces.
    """
    empresa = vacante["empresa"]
    lugar = _ubicacion(vacante)
    if lugar and normalizar(empresa) in normalizar(lugar):
        return lugar
    return " · ".join(x for x in [empresa, lugar] if x)


def resumir(vacante: dict) -> str:
    """Una línea para los adyacentes y las menciones: cargo, dónde y el link."""
    cabeza = vacante["cargo"]
    detalle = _empresa_y_lugar(vacante)
    if detalle:
        cabeza += f" — {detalle}"
    return f"{cabeza}\n  {vacante['url']}"


def formatear(vacante: dict, es_nueva: bool) -> str:
    marca = "🆕 " if es_nueva else ""
    lineas = [f"{marca}*{vacante['cargo']}*"]

    detalle = _empresa_y_lugar(vacante)
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

    # BHP publica el mismo cargo varias veces con IDs distintos (una por cupo).
    # Se muestra una sola vez: el aviso es el mismo para el que postula.
    unicas, firmas = [], set()
    for v in todas:
        firma = (v["empresa"], normalizar(v["cargo"]))
        if firma in firmas:
            continue
        firmas.add(firma)
        unicas.append(v)

    if len(unicas) != len(todas):
        print(f"  (se descartaron {len(todas) - len(unicas)} avisos repetidos)")

    return unicas


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
    adyacentes = [v for v in evaluadas if v["nivel"] == "adyacente"]
    menciones = [v for v in evaluadas if v["nivel"] == "mencion"]
    print(f"Total en Chile: {len(todas)} | Calzan: {len(calzan)}"
          f" | Adyacentes: {len(adyacentes)} | Menciones: {len(menciones)}")

    # El detalle cuesta un request por aviso, así que solo se abren las que
    # calzan: nunca son muchas, y son las únicas que se muestran completas.
    for i, vacante in enumerate(calzan[:MAX_DETALLES]):
        if i > 0:
            time.sleep(PAUSA)
        detallar(vacante)

    vistas = estado["vacantes_enviadas"]
    es_domingo = hoy.weekday() == 6

    nuevo = lambda lista: [v for v in lista if v["id"] not in vistas]  # noqa: E731

    if es_domingo:
        titulo = "💼 *Resumen semanal de vacantes*"
        principales, cercanas, secundarias = calzan, adyacentes, menciones
    else:
        titulo = "💼 *Vacantes*"
        principales, cercanas, secundarias = (
            nuevo(calzan), nuevo(adyacentes), nuevo(menciones))

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

    if cercanas:
        partes.append(
            "_Quizás te interese — cargos del área de al lado:_\n"
            + "\n".join(f"• {resumir(v)}" for v in cercanas[:MAX_ADYACENTES])
        )

    if MOSTRAR_MENCIONES and secundarias:
        partes.append(
            "_Solo mencionan tus palabras clave, el cargo es de otra área:_\n"
            + "\n".join(f"• {resumir(v)}" for v in secundarias[:MAX_MENCIONES])
        )

    # Se marcan como vistas DESPUÉS de armar el texto, para que el 🆕 salga
    # bien en este mensaje.
    mostradas = (principales[:MAX_EN_MENSAJE] + cercanas[:MAX_ADYACENTES]
                 + (secundarias[:MAX_MENCIONES] if MOSTRAR_MENCIONES else []))
    for vacante in mostradas:
        vistas[vacante["id"]] = hoy.isoformat()

    return "\n\n".join(partes)


# ---------------------------------------------------------------------------
# PRUEBA MANUAL:  python vacantes.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(bloque_vacantes({}, datetime.now().date()))
