# Brief matutino — Fase 2

Agente personal que te manda un mensaje diario a las 07:30 (hora de Chile) por Telegram,
con fecha, clima de Angol, frase motivadora y palabra del día.

Corre en **GitHub Actions**, o sea: gratis, sin servidor, sin dejar el computador prendido.

---

## Instalación paso a paso

Sigue el orden. Cada paso toma 2-5 minutos. Total: ~25 minutos.

### Paso 1 — Crear el bot de Telegram

1. Abre Telegram y busca el contacto **@BotFather** (tiene un tilde azul de verificado).
2. Escríbele `/newbot`.
3. Te va a pedir un nombre visible (ej: `Mi Brief Matutino`) y después un nombre de
   usuario que **debe terminar en `bot`** (ej: `brief_angol_bot`).
4. Te responde con un **token**, algo como `7891234567:AAH8xY...`.
   Cópialo y guárdalo: es el `TELEGRAM_BOT_TOKEN`.

### Paso 2 — Conseguir tu chat ID

1. Busca tu bot recién creado en Telegram (por el nombre de usuario que le pusiste).
2. Ábrelo y mándale cualquier mensaje, por ejemplo `hola`.
   **Este paso es obligatorio**: Telegram no deja que un bot te escriba si tú no le
   escribiste primero.
3. Ahora busca el contacto **@userinfobot** y escríbele `/start`.
   Te va a responder con tu `Id`, un número tipo `123456789`.
   Ese es el `TELEGRAM_CHAT_ID`.

### Paso 3 — Crear el repositorio

1. Entra a github.com y crea una cuenta si no tienes.
2. Arriba a la derecha, botón `+` → **New repository**.
3. Nombre: `brief-matutino`. Marca **Private**. Crea el repositorio.

### Paso 4 — Subir los archivos

En la página del repositorio vacío, usa **uploading an existing file** y sube todo
respetando esta estructura:

```
brief-matutino/
├── brief.py
├── requirements.txt
├── README.md
├── datos/
│   ├── frases.json
│   ├── palabras.json
│   └── estado.json
└── .github/
    └── workflows/
        └── brief.yml
```

**Ojo con dos cosas:**

- El archivo `brief.yml` que te pasé va dentro de `.github/workflows/`.
  Para crear esa carpeta en la web de GitHub: **Add file → Create new file**, y en el
  nombre escribe `.github/workflows/brief.yml` (las barras crean las carpetas solas).
  Después pega el contenido.
- La carpeta se llama `.github` **con punto adelante**. Sin el punto no funciona.

### Paso 5 — Guardar los secretos

En tu repositorio: **Settings** (arriba) → en el menú izquierdo **Secrets and variables**
→ **Actions** → botón **New repository secret**.

Crea dos, uno por uno:

| Name | Secret |
|---|---|
| `TELEGRAM_BOT_TOKEN` | el token del Paso 1 |
| `TELEGRAM_CHAT_ID` | el número del Paso 2 |

Los nombres tienen que estar escritos **exactamente así**, en mayúsculas y con guiones bajos.

### Paso 6 — Probar

1. Anda a la pestaña **Actions** de tu repositorio.
2. Si aparece un aviso verde pidiendo habilitar los workflows, acéptalo.
3. En la lista de la izquierda, elige **Brief matutino**.
4. Botón **Run workflow** (a la derecha) → **Run workflow**.
5. Espera ~40 segundos y refresca. Deberías recibir el mensaje en Telegram.

Si no llega, entra a la ejecución y abre el paso **Ejecutar el brief**: ahí sale el error
exacto. El mensaje completo se imprime siempre en el log, aunque el envío falle.

---

## Cómo funciona el horario

Los cron de GitHub corren en UTC y **no** siguen el horario de Chile. Por eso el workflow
tiene dos horarios programados (10:15 y 11:15 UTC): uno acierta en verano y el otro en
invierno. El script mira la hora real de Santiago y solo envía si son entre las 6 y las 9
de la mañana.

Para que nunca te llegue dos veces, `datos/estado.json` guarda la fecha del último envío.
Si ya se envió hoy, la segunda ejecución simplemente no hace nada.

**Un detalle importante:** GitHub atrasa los cron cuando tiene mucha carga. Es normal que
el mensaje llegue entre las 07:15 y las 07:50 en vez de a las 07:30 clavadas. No es un
error, es cómo funciona el plan gratuito.

---

## Cómo se evitan las repeticiones

`datos/estado.json` registra qué frase y qué palabra se usaron cada día. Antes de elegir,
el script descarta todo lo usado en los últimos 60 días. El workflow hace commit de ese
archivo de vuelta al repositorio después de cada envío.

Ese commit diario tiene un beneficio extra: GitHub desactiva los workflows programados
después de 60 días sin actividad en el repositorio, y el commit lo mantiene siempre activo.

Hoy hay 45 frases y 45 palabras. Con una ventana de 60 días eso significa que el catálogo
se recicla antes de completar la ventana; el script maneja ese caso reutilizando lo más
antiguo. Si te molesta, agrega más entradas a los JSON: el formato es evidente y no hay
que tocar el código.

---

## Personalización rápida

| Qué quieres cambiar | Dónde |
|---|---|
| Ciudad del clima | `brief.py`, variables `CIUDAD`, `LATITUD`, `LONGITUD` |
| Hora de llegada | `brief.yml`, las dos líneas `cron` (recuerda: en UTC) |
| Ventana anti-repetición | `brief.py`, `DIAS_SIN_REPETIR` |
| Agregar frases o palabras | `datos/frases.json` y `datos/palabras.json` |
| Textos de recomendación del clima | `brief.py`, función `bloque_clima()` |

---

## Probar en tu computador (opcional)

Si quieres correrlo local antes de subirlo:

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="tu_token"
export TELEGRAM_CHAT_ID="tu_id"
python brief.py --forzar
```

El `--forzar` salta la ventana horaria y el control de "ya se envió hoy".

---

## Lo que viene en la Fase 3

En `brief.py` hay una línea comentada que dice
`# partes.append(bloque_vacantes(estado, hoy))`. Ahí se enchufa la sección de vacantes
sin tocar nada más de la estructura: mismo estado, mismo manejo de errores, mismo envío
con partición automática de mensajes largos.
