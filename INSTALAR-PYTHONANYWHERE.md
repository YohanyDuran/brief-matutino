# Correr el brief en PythonAnywhere (plan gratis)

Alternativa a GitHub Actions. Sirve igual: una tarea diaria que ejecuta
`brief.py` y te manda el mensaje por Telegram y WhatsApp.

Ventaja sobre Actions: como PythonAnywhere tiene disco propio, el archivo
`datos/estado.json` se guarda solo. No hace falta el commit diario.

**Las tres APIs que usa el brief estan permitidas en el plan gratis**
(`api.telegram.org`, `api.open-meteo.com`, `api.callmebot.com`). El plan
gratuito solo deja conectarse a sitios de una lista blanca, y las tres estan.

---

## Paso 1 — Crear la cuenta

Anda a https://www.pythonanywhere.com y crea una cuenta con el plan
**"Create a Beginner account"** (gratis, no pide tarjeta).

Anota tu nombre de usuario: lo vas a necesitar en las rutas.

---

## Paso 2 — Bajar el codigo

En el panel, arriba a la derecha, abre **Consoles** -> **Bash**.

Se abre una terminal negra. Pega esto y dale Enter:

```bash
git clone https://github.com/YohanyDuran/brief-matutino.git
```

> Si el repositorio esta en privado, este comando va a pedirte usuario y
> contrasena y no va a funcionar con la contrasena normal de GitHub. En ese
> caso, la via mas simple es subir los archivos a mano desde la pestana
> **Files** del panel.

---

## Paso 3 — Instalar las dependencias

En la misma consola Bash:

```bash
pip3 install --user -r brief-matutino/requirements.txt
```

Demora medio minuto. Si al final dice `Successfully installed requests...`,
quedo listo.

---

## Paso 4 — Cargar tus credenciales

Aca no existen los "Secrets" de GitHub. En vez de eso se usa un archivo
`.env`, que **nunca se sube al repositorio** (esta bloqueado en `.gitignore`).

En la consola Bash:

```bash
nano brief-matutino/.env
```

Se abre un editor de texto. Escribe estas cuatro lineas, reemplazando por
tus valores reales:

```
TELEGRAM_BOT_TOKEN=tu-token-de-botfather
TELEGRAM_CHAT_ID=tu-chat-id
CALLMEBOT_PHONE=+56912345678
CALLMEBOT_APIKEY=tu-apikey-de-callmebot
```

Para guardar: `Ctrl+O`, Enter, y despues `Ctrl+X` para salir.

> Sin comillas, sin espacios alrededor del `=`, y el telefono con `+56`
> y sin espacios.

---

## Paso 5 — Probar que funciona AHORA

Sin esperar a manana. En la consola:

```bash
python3 brief-matutino/brief.py --forzar
```

El `--forzar` se salta la ventana horaria de 6 a 9 de la manana.

Deberias ver el mensaje impreso en pantalla y al final:

```
Telegram: enviado
WhatsApp: enviado
Brief enviado y estado guardado.
```

Y te tienen que llegar los dos mensajes al telefono.

Si alguno dice `FALLO`, el script imprime arriba el motivo exacto.

---

## Paso 6 — Programar la tarea diaria

En el panel, pestana **Tasks**.

En "Schedule a new task" pon el comando (reemplaza `TU-USUARIO`):

```
python3 /home/TU-USUARIO/brief-matutino/brief.py
```

Y la hora: **11:30 UTC**.

### Por que 11:30 UTC

PythonAnywhere programa en UTC, no en hora de Chile, y el plan gratis deja
elegir una sola hora fija al dia.

| Epoca del ano | 11:30 UTC equivale en Chile a |
|---|---|
| Invierno (mayo a agosto, UTC-4) | **07:30** |
| Verano (septiembre a abril, UTC-3) | **08:30** |

Las dos caen dentro de la ventana de 6 a 9 que exige el script, asi que el
mensaje sale igual todo el ano. Si te molesta la hora de verano, en
septiembre cambias la tarea a 10:30 UTC y vuelve a ser 07:30.

---

## Mantenimiento

El plan gratis **desactiva las tareas si no entras a la cuenta en 3 meses**.
PythonAnywhere te manda un correo antes; basta con entrar y apretar el boton
de renovar.

---

## Si despues GitHub se destraba

No hay que deshacer nada. El mismo `brief.py` funciona en los dos lados: si
encuentra un `.env` lo usa, y si no, usa las variables de GitHub Actions.

Eso si, no lo dejes corriendo en los dos al mismo tiempo o te van a llegar
dos mensajes iguales. Para apagar uno:

- **PythonAnywhere**: pestana Tasks -> boton de basurero en la tarea.
- **GitHub**: pestana Actions -> Brief matutino -> menu `...` -> Disable workflow.
