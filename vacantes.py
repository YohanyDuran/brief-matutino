#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VACANTES — Fase 3
=================
Busca ofertas laborales en los portales oficiales de la gran minería y
devuelve el bloque de texto listo para pegar en el brief matutino.

Fuentes implementadas:
  - Codelco (todas las divisiones), vía https://empleos.codelco.cl

SOBRE robots.txt — leer antes de agregar fuentes
------------------------------------------------
`career8.successfactors.com` prohíbe TODO rastreo:

    User-agent: *
    Disallow: /
    Allow: /login

Por eso NO se usa, aunque sea el portal que está detrás. En su lugar se usa
`empleos.codelco.cl`, la entrada pública, cuyo robots.txt solo bloquea rutas
funcionales (/services/, /applybutton/, /talentcommunity/, /preapply/, ...)
y deja libre la búsqueda de ofertas.

No existe API JSON ni feed RSS: se comprobó uno por uno. Por eso se parsea
HTML, que la regla 4 del proyecto permite solo cuando no hay alternativa.

FILOSOFÍA DE ERRORES: igual que el resto del brief. Si esto falla, revienta
hacia arriba y `main()` lo reporta como fuente caída, pero el mensaje se
envía igual con los otros bloques.
"""

import html
import re
import time
import unicodedata
from datetime import date, datetime, timedelta

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# CONFIGURACIÓN
# ---------------------------------------------------------------------------

# Solo el fragmento con la lista de avisos, no la página entera.
URL_LISTADO = "https://empleos.codelco.cl/tile-search-results/"
URL_BASE = "https://empleos.codelco.cl"

# User-Agent identificable, como exige la regla 5. Sin datos personales: el
# repositorio es público.
CABECERAS = {
    "User-Agent": (
        "BriefMatutino/1.0 "
        "(+https://github.com/YohanyDuran/brief-matutino) python-requests"
    )
}

TIMEOUT = 25
PAUSA_ENTRE_AVISOS = 1.5   # segundos; no martillar el servidor
MAX_DETALLES = 15          # tope duro de requests de detalle por corrida
MAX_EN_MENSAJE = 10        # tope de vacantes mostradas, según requisitos
DIAS_RECORDAR = 30         # cuánto tiempo se recuerda una vacante ya enviada

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


def _fecha_valida(texto: str) -> bool:
    """True si el texto es una fecha ISO legible. Las corruptas se descartan."""
    try:
        date.fromisoformat(texto)
        return True
    except (ValueError, TypeError):
        return False


MESES_LARGOS = ("enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
                "septiembre|setiembre|octubre|noviembre|diciembre")


def _parece_fecha(texto: str) -> bool:
    """
    True si el texto tiene pinta de fecha: un nombre de mes y un año de 4
    dígitos. Sirve para no dejar pasar basura donde va una fecha.
    """
    t = normalizar(texto)
    return bool(re.search(MESES_LARGOS, t) and re.search(r"\b\d{4}\b", t))


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
# DESCARGA
# ---------------------------------------------------------------------------

def _pedir(url: str) -> str:
    respuesta = requests.get(url, headers=CABECERAS, timeout=TIMEOUT)
    respuesta.raise_for_status()
    return respuesta.text


def _texto_del_campo(tile, clase: str) -> str:
    """
    Saca el valor de un campo del aviso, quitándole la etiqueta.

    En el HTML cada campo viene como:
        <div class="section-field date">
            <span class="section-label">Fecha</span> 20 ago 2026
        </div>
    """
    elemento = tile.select_one(f".section-field.{clase}")
    if not elemento:
        return ""
    etiqueta = elemento.select_one(".section-label")
    if etiqueta:
        etiqueta.extract()
    return re.sub(r"\s+", " ", elemento.get_text(" ", strip=True)).strip()


def listar_codelco() -> list:
    """
    Trae TODAS las vacantes abiertas en un solo request.

    A propósito no se usa el buscador del servidor (`?q=`): se comprobó que
    hace match difuso por palabra suelta y devuelve casi todo el catálogo.
    El filtrado se hace acá, que es predecible.
    """
    # Ojo: no llamar 'html' a esta variable, taparía al módulo html.
    fragmento = _pedir(f"{URL_LISTADO}?q=&startrow=0")
    sopa = BeautifulSoup(f"<ul>{fragmento}</ul>", "html.parser")

    vacantes = []
    for tile in sopa.select("li.job-tile"):
        enlace = tile.select_one("a.jobTitle-link")
        if not enlace:
            continue

        ruta = tile.get("data-url") or enlace.get("href") or ""
        if not ruta:
            continue

        # El id va en una clase tipo "job-id-1421576700". Es estable, y es
        # lo que usamos para deduplicar.
        clases = " ".join(tile.get("class", []))
        m_id = re.search(r"job-id-(\d+)", clases)

        vacantes.append({
            "id": m_id.group(1) if m_id else ruta,
            "cargo": html.unescape(enlace.get_text(" ", strip=True)),
            "empresa": "Codelco",
            "region": _texto_del_campo(tile, "customfield2"),
            "proceso": _texto_del_campo(tile, "customfield1"),
            "fecha_txt": _texto_del_campo(tile, "date"),
            "url": html.unescape(ruta if ruta.startswith("http")
                                 else URL_BASE + ruta),
            # Se completan en detallar():
            "lugar": "",
            "jornada": "",
            "contrato": "",
            "cierre": "",
            "descripcion": "",
        })

    return vacantes


# Los campos del aviso vienen seguidos, y no siempre separados por punto. Si
# se corta "hasta el punto", un campo se come al siguiente. Por eso cada valor
# se corta en cuanto aparece la etiqueta del campo que viene después.
# Ojo con el orden: 'hora de cierre...' va ANTES que 'cierre...' para que gane
# la etiqueta más larga. Y el \w* final es imprescindible: sin él, 'postulaci'
# no cubre 'postulaciones' y el corte falla justo donde más importa.
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

    Estos datos NO vienen en el listado; hay que pedir la página del aviso.
    Codelco usa una plantilla fija ('Lugar de trabajo:', 'Jornada laboral:'),
    así que se extraen por etiqueta.

    Si algo falla, se devuelve la vacante tal cual: es mejor mostrarla
    incompleta que perderla.
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

            # Red de seguridad: si el "cierre" no parece una fecha, se descarta.
            # Sin esto, un cambio de plantilla podría colar la hora ("23:59 hrs")
            # en el lugar de la fecha sin que nadie se entere.
            if campo == "cierre" and not _parece_fecha(valor):
                continue

            vacante[campo] = valor
    except (requests.RequestException, ValueError) as e:
        print(f"  No pude abrir el detalle de '{vacante['cargo']}': {e}")

    return vacante


# ---------------------------------------------------------------------------
# FILTRO DE RELEVANCIA
# ---------------------------------------------------------------------------

def evaluar(vacante: dict) -> dict:
    """
    Decide si la vacante califica y con qué puntaje.

    Reglas, según el perfil objetivo del proyecto:
      - El título pesa mucho más que la descripción.
      - Califica si pega en el TÍTULO, o si pega en DOS palabras clave
        distintas en la descripción.

    Esa segunda condición es la que evita los falsos positivos: un cargo
    operativo que menciona 'productividad' una vez de pasada no califica.
    """
    titulo = normalizar(vacante["cargo"])
    cuerpo = normalizar(vacante.get("descripcion", ""))

    en_titulo = [k for k in PALABRAS_CLAVE if contiene_frase(titulo, k)]
    en_cuerpo = [k for k in PALABRAS_CLAVE if contiene_frase(cuerpo, k)]

    vacante["hits_titulo"] = en_titulo
    vacante["hits_cuerpo"] = en_cuerpo
    vacante["puntaje"] = len(en_titulo) * 10 + len(en_cuerpo)
    vacante["califica"] = bool(en_titulo) or len(en_cuerpo) >= 2

    return vacante


# ---------------------------------------------------------------------------
# FORMATO
# ---------------------------------------------------------------------------

def formatear(vacante: dict, es_nueva: bool) -> str:
    marca = "🆕 " if es_nueva else ""
    lineas = [f"{marca}*{vacante['cargo']}*"]

    ubicacion = vacante["lugar"] or vacante["region"]
    detalle = " · ".join(x for x in [vacante["empresa"], ubicacion] if x)
    if detalle:
        lineas.append(detalle)

    extra = " · ".join(x for x in [vacante["jornada"], vacante["contrato"]] if x)
    if extra:
        lineas.append(extra)

    pie = []
    if vacante["fecha_txt"]:
        pie.append(f"Publicado: {vacante['fecha_txt']}")
    if vacante["cierre"]:
        pie.append(f"Cierra: {vacante['cierre']}")
    if pie:
        lineas.append(" · ".join(pie))

    lineas.append(vacante["url"])
    return "\n".join(lineas)


# ---------------------------------------------------------------------------
# BLOQUE PARA EL BRIEF
# ---------------------------------------------------------------------------

def bloque_vacantes(estado: dict, hoy: date) -> str:
    """
    Arma la sección de vacantes del brief.

    Los domingos entrega el resumen semanal: todas las vigentes que califican,
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

    todas = listar_codelco()
    print(f"Vacantes encontradas en Codelco: {len(todas)}")

    # El detalle cuesta un request por aviso, así que se limita.
    for i, vacante in enumerate(todas[:MAX_DETALLES]):
        if i > 0:
            time.sleep(PAUSA_ENTRE_AVISOS)
        detallar(vacante)

    califican = [evaluar(v) for v in todas]
    califican = [v for v in califican if v["califica"]]
    califican.sort(key=lambda v: v["puntaje"], reverse=True)
    print(f"Califican por perfil: {len(califican)}")

    vistas = estado["vacantes_enviadas"]
    nuevas = [v for v in califican if v["id"] not in vistas]

    es_domingo = hoy.weekday() == 6

    if es_domingo:
        titulo = "💼 *Resumen semanal de vacantes*"
        mostrar = califican
    else:
        titulo = "💼 *Vacantes*"
        mostrar = nuevas

    if not mostrar:
        if es_domingo:
            return f"{titulo}\nNo hay vacantes vigentes que calcen con tu perfil."
        return f"{titulo}\nHoy no hay vacantes nuevas para tu perfil."

    partes = [titulo]
    for vacante in mostrar[:MAX_EN_MENSAJE]:
        partes.append(formatear(vacante, es_nueva=vacante["id"] not in vistas))

    sobrantes = len(mostrar) - MAX_EN_MENSAJE
    if sobrantes > 0:
        partes.append(f"…y {sobrantes} más. Revisa el portal para verlas todas.")

    # Se marcan como enviadas DESPUÉS de armar el texto, para que el 🆕 salga
    # bien en este mensaje.
    for vacante in mostrar[:MAX_EN_MENSAJE]:
        vistas[vacante["id"]] = hoy.isoformat()

    return "\n\n".join(partes)


# ---------------------------------------------------------------------------
# PRUEBA MANUAL:  python vacantes.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    estado_prueba = {"vacantes_enviadas": {}}
    print(bloque_vacantes(estado_prueba, datetime.now().date()))
