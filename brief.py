#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BRIEF MATUTINO — Fase 2
=======================
Arma y envía por Telegram y WhatsApp un mensaje diario con:
  1. Saludo + fecha en español
  2. Clima del día (Open-Meteo, gratis y sin API key)
  3. Frase motivadora (sin repetir en 60 días)
  4. Palabra del día (sin repetir en 60 días)

La sección de vacantes llega en la Fase 3. El bloque ya está reservado
al final del mensaje para que puedas ver dónde va a encajar.

FILOSOFÍA DE ERRORES: si una fuente falla, el mensaje SE ENVÍA IGUAL y
avisa qué falló. Nunca se cae entero por un pedazo.
"""

import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# ---------------------------------------------------------------------------
# CONFIGURACIÓN — lo único que necesitas tocar
# ---------------------------------------------------------------------------

CIUDAD = "Angol"
LATITUD = -37.7958
LONGITUD = -72.7139

ZONA = ZoneInfo("America/Santiago")   # maneja solo el cambio de hora de Chile
DIAS_SIN_REPETIR = 60                 # ventana anti-repetición

# Ventana horaria válida. GitHub Actions atrasa los cron, así que aceptamos
# un rango amplio; la protección real contra mensajes duplicados es el
# registro de "ultimo_envio" en el estado.
HORA_MIN = 6
HORA_MAX = 9

# Secretos: se leen de variables de entorno (GitHub Secrets)
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# WhatsApp vía CallMeBot. Si faltan estos dos, el canal se salta solo.
WA_TELEFONO = os.environ.get("CALLMEBOT_PHONE", "")
WA_APIKEY = os.environ.get("CALLMEBOT_APIKEY", "")

# Rutas
RAIZ = Path(__file__).parent
ARCHIVO_FRASES = RAIZ / "datos" / "frases.json"
ARCHIVO_PALABRAS = RAIZ / "datos" / "palabras.json"
ARCHIVO_ESTADO = RAIZ / "datos" / "estado.json"

# Permite forzar el envío ignorando la ventana horaria: útil para probar.
FORZAR = "--forzar" in sys.argv


# ---------------------------------------------------------------------------
# ESTADO (deduplicación)
# ---------------------------------------------------------------------------

def cargar_estado() -> dict:
    """Lee el estado desde disco. Si no existe o está corrupto, arranca limpio."""
    if not ARCHIVO_ESTADO.exists():
        return {"ultimo_envio": None, "frases_usadas": {}, "palabras_usadas": {}}
    try:
        with open(ARCHIVO_ESTADO, encoding="utf-8") as f:
            estado = json.load(f)
    except (json.JSONDecodeError, OSError):
        # Estado ilegible: preferimos perder el historial antes que no enviar nada.
        return {"ultimo_envio": None, "frases_usadas": {}, "palabras_usadas": {}}

    estado.setdefault("ultimo_envio", None)
    estado.setdefault("frases_usadas", {})
    estado.setdefault("palabras_usadas", {})
    return estado


def guardar_estado(estado: dict) -> None:
    ARCHIVO_ESTADO.parent.mkdir(parents=True, exist_ok=True)
    with open(ARCHIVO_ESTADO, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


def limpiar_vencidos(usados: dict, hoy: date) -> dict:
    """Saca del registro lo que ya salió de la ventana de 60 días."""
    limite = hoy - timedelta(days=DIAS_SIN_REPETIR)
    vigentes = {}
    for clave, fecha_txt in usados.items():
        try:
            if date.fromisoformat(fecha_txt) > limite:
                vigentes[clave] = fecha_txt
        except ValueError:
            continue  # fecha malformada: se descarta
    return vigentes


def elegir_sin_repetir(items: list, usados: dict, hoy: date):
    """
    Devuelve (item, indice) eligiendo el que lleva más tiempo sin usarse.

    No usa random: recorre en orden y toma el primero disponible. Así el ciclo
    es predecible y no dependemos de la suerte para no repetir.
    Si TODOS están usados (catálogo más chico que la ventana), recicla el más antiguo.
    """
    for i, item in enumerate(items):
        if str(i) not in usados:
            return item, i

    # Todo usado: reciclamos el de fecha más antigua.
    mas_antiguo = min(usados, key=lambda k: usados[k])
    indice = int(mas_antiguo)
    return items[indice], indice


# ---------------------------------------------------------------------------
# BLOQUE 1 — FECHA
# ---------------------------------------------------------------------------

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
         "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def bloque_fecha(ahora: datetime) -> str:
    """Formatea la fecha a mano: locale es_CL no está garantizado en el runner."""
    dia_semana = DIAS[ahora.weekday()].capitalize()
    mes = MESES[ahora.month - 1]
    return f"☀️ *Buenos días*\n{dia_semana} {ahora.day} de {mes} de {ahora.year}"


# ---------------------------------------------------------------------------
# BLOQUE 2 — CLIMA (Open-Meteo)
# ---------------------------------------------------------------------------

def bloque_clima() -> str:
    """
    Open-Meteo: gratis, sin registro, sin API key.
    Si falla, lanza excepción y el orquestador lo registra como fuente caída.
    """
    url = "https://api.open-meteo.com/v1/forecast"
    parametros = {
        "latitude": LATITUD,
        "longitude": LONGITUD,
        "daily": "temperature_2m_max,temperature_2m_min,"
                 "precipitation_probability_max,precipitation_sum",
        "timezone": "America/Santiago",
        "forecast_days": 1,
    }

    respuesta = requests.get(url, params=parametros, timeout=20)
    respuesta.raise_for_status()
    diario = respuesta.json()["daily"]

    minima = round(diario["temperature_2m_min"][0])
    maxima = round(diario["temperature_2m_max"][0])
    prob_lluvia = diario["precipitation_probability_max"][0] or 0
    mm = diario["precipitation_sum"][0] or 0

    # Recomendación: primero por probabilidad, después por temperatura.
    if prob_lluvia >= 70:
        consejo = "Lleva paraguas sí o sí 🌧️"
    elif prob_lluvia >= 40:
        consejo = "Anda con paraguas por si acaso 🌂"
    elif minima <= 3:
        consejo = "Va a estar helado en la mañana, abrígate bien 🧣"
    elif maxima >= 30:
        consejo = "Día caluroso: agua y bloqueador 🧴"
    else:
        consejo = "Buen día para andar tranquilo 🙂"

    texto = (
        f"🌡️ *Clima en {CIUDAD}*\n"
        f"Mín {minima}° / Máx {maxima}°\n"
        f"Prob. de lluvia: {prob_lluvia}%"
    )
    if mm > 0:
        texto += f" ({mm} mm)"
    texto += f"\n{consejo}"

    return texto


# ---------------------------------------------------------------------------
# BLOQUE 3 — FRASE MOTIVADORA
# ---------------------------------------------------------------------------

def bloque_frase(estado: dict, hoy: date) -> str:
    with open(ARCHIVO_FRASES, encoding="utf-8") as f:
        frases = json.load(f)

    estado["frases_usadas"] = limpiar_vencidos(estado["frases_usadas"], hoy)
    frase, indice = elegir_sin_repetir(frases, estado["frases_usadas"], hoy)
    estado["frases_usadas"][str(indice)] = hoy.isoformat()

    return f"💭 _{frase['texto']}_\n— {frase['autor']}"


# ---------------------------------------------------------------------------
# BLOQUE 4 — PALABRA DEL DÍA
# ---------------------------------------------------------------------------

def bloque_palabra(estado: dict, hoy: date) -> str:
    with open(ARCHIVO_PALABRAS, encoding="utf-8") as f:
        palabras = json.load(f)

    estado["palabras_usadas"] = limpiar_vencidos(estado["palabras_usadas"], hoy)
    palabra, indice = elegir_sin_repetir(palabras, estado["palabras_usadas"], hoy)
    estado["palabras_usadas"][str(indice)] = hoy.isoformat()

    sinonimos = ", ".join(palabra["sinonimos"])
    return (
        f"📖 *Palabra del día: {palabra['palabra']}*\n"
        f"{palabra['definicion']}\n"
        f"Sinónimos: {sinonimos}\n"
        f"_Ej: {palabra['ejemplo']}_"
    )


# ---------------------------------------------------------------------------
# ENVÍO — TELEGRAM Y WHATSAPP
# ---------------------------------------------------------------------------

LIMITE_WHATSAPP = 1500  # CallMeBot viaja por URL: mejor trozos cortos
LIMITE_TELEGRAM = 4000  # el máximo real es 4096; dejamos holgura


def partir_mensaje(texto: str, limite: int = LIMITE_TELEGRAM) -> list:
    """Corta en trozos respetando los saltos de línea dobles (bloques)."""
    if len(texto) <= limite:
        return [texto]

    partes, actual = [], ""
    for bloque in texto.split("\n\n"):
        if len(actual) + len(bloque) + 2 > limite:
            partes.append(actual.strip())
            actual = bloque + "\n\n"
        else:
            actual += bloque + "\n\n"
    if actual.strip():
        partes.append(actual.strip())
    return partes


def enviar_telegram(texto: str) -> bool:
    """
    Envía por Telegram. Intenta con formato Markdown; si Telegram lo rechaza
    (algún carácter suelto rompe el parser), reintenta en texto plano.
    Mejor un mensaje feo que ningún mensaje.
    """
    if not TOKEN or not CHAT_ID:
        print("ERROR: faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID")
        return False

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    ok_total = True

    for parte in partir_mensaje(texto):
        enviado = False
        for modo in ("Markdown", None):
            datos = {"chat_id": CHAT_ID, "text": parte,
                     "disable_web_page_preview": True}
            if modo:
                datos["parse_mode"] = modo
            try:
                r = requests.post(url, data=datos, timeout=20)
                if r.status_code == 200:
                    enviado = True
                    break
                print(f"Telegram respondió {r.status_code}: {r.text[:200]}")
            except requests.RequestException as e:
                print(f"Error de red al enviar: {e}")
        if not enviado:
            ok_total = False

    return ok_total


def enviar_whatsapp(texto: str) -> bool:
    """
    Envía por WhatsApp usando CallMeBot: gratis y sin las plantillas que exige
    la API oficial de Meta para mensajes no solicitados.

    No hace falta convertir el formato: WhatsApp usa los mismos símbolos que
    Markdown para negrita (*así*) y cursiva (_así_).

    CallMeBot limita la frecuencia de envío, así que si el mensaje va partido
    esperamos unos segundos entre trozo y trozo.
    """
    if not WA_TELEFONO or not WA_APIKEY:
        print("ERROR: faltan CALLMEBOT_PHONE o CALLMEBOT_APIKEY")
        return False

    url = "https://api.callmebot.com/whatsapp.php"
    ok_total = True

    for i, parte in enumerate(partir_mensaje(texto, LIMITE_WHATSAPP)):
        if i > 0:
            time.sleep(6)   # respeta el límite de frecuencia de CallMeBot
        try:
            r = requests.get(
                url,
                params={"phone": WA_TELEFONO, "text": parte, "apikey": WA_APIKEY},
                timeout=30,
            )
            # CallMeBot responde 200 igual cuando hay error, con el detalle
            # dentro del cuerpo. Por eso revisamos las dos cosas.
            cuerpo = r.text[:200]
            if r.status_code != 200 or "ERROR" in cuerpo.upper():
                print(f"CallMeBot respondió {r.status_code}: {cuerpo}")
                ok_total = False
        except requests.RequestException as e:
            print(f"Error de red al enviar por WhatsApp: {e}")
            ok_total = False

    return ok_total


def enviar(texto: str) -> bool:
    """
    Manda el brief por todos los canales que estén configurados.

    Devuelve True si AL MENOS UNO llegó. Así, si WhatsApp falla pero Telegram
    funciona, el día igual se marca como enviado y mañana no se repite.
    Un canal sin secretos no cuenta como falla: simplemente no se usa.
    """
    resultados = []

    if TOKEN and CHAT_ID:
        ok = enviar_telegram(texto)
        print(f"Telegram: {'enviado' if ok else 'FALLÓ'}")
        resultados.append(ok)
    else:
        print("Telegram: sin secretos configurados, se salta.")

    if WA_TELEFONO and WA_APIKEY:
        ok = enviar_whatsapp(texto)
        print(f"WhatsApp: {'enviado' if ok else 'FALLÓ'}")
        resultados.append(ok)
    else:
        print("WhatsApp: sin secretos configurados, se salta.")

    if not resultados:
        print("ERROR: no hay ningún canal configurado.")
        return False

    return any(resultados)


# ---------------------------------------------------------------------------
# ORQUESTADOR
# ---------------------------------------------------------------------------

def main() -> int:
    ahora = datetime.now(ZONA)
    hoy = ahora.date()
    estado = cargar_estado()

    # --- Guardas de ejecución -------------------------------------------------
    if not FORZAR:
        if estado["ultimo_envio"] == hoy.isoformat():
            print(f"Ya se envió el brief de hoy ({hoy}). No hago nada.")
            return 0
        if not (HORA_MIN <= ahora.hour <= HORA_MAX):
            print(f"Son las {ahora.hour}:{ahora.minute:02d} en Chile, "
                  f"fuera de la ventana {HORA_MIN}-{HORA_MAX}. No envío.")
            return 0

    # --- Construcción del mensaje --------------------------------------------
    # Cada bloque va en su propio try: si uno se cae, los demás sobreviven.
    partes = [bloque_fecha(ahora)]
    fallidas = []

    for nombre, funcion in [
        ("Clima", lambda: bloque_clima()),
        ("Frase del día", lambda: bloque_frase(estado, hoy)),
        ("Palabra del día", lambda: bloque_palabra(estado, hoy)),
    ]:
        try:
            partes.append(funcion())
        except Exception as e:                      # noqa: BLE001
            print(f"Falló el bloque '{nombre}': {e}")
            fallidas.append(nombre)

    # Reservado para la Fase 3: acá se inserta la sección de vacantes.
    # partes.append(bloque_vacantes(estado, hoy))

    if fallidas:
        partes.append("⚠️ No pude obtener: " + ", ".join(fallidas))

    mensaje = "\n\n".join(partes)
    print("--- MENSAJE ---")
    print(mensaje)
    print("---------------")

    # --- Envío y persistencia -------------------------------------------------
    if enviar(mensaje):
        # Solo marcamos como enviado si de verdad salió. Si falló, mañana
        # (o en el reintento del segundo cron) se vuelve a intentar.
        estado["ultimo_envio"] = hoy.isoformat()
        guardar_estado(estado)
        print("Brief enviado y estado guardado.")
        return 0

    print("No se pudo enviar el brief.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
