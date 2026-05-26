# Guía de instalación — Bot de la Despensa

Seguí estos pasos en orden. No necesitás saber programación.
Tiempo estimado: 20-30 minutos.

---

## PARTE 1 — Crear el bot en Telegram

1. Abrí Telegram en tu celular o computadora.
2. En el buscador escribí `@BotFather` y abrí ese chat (tiene tilde azul de verificado).
3. Escribí `/newbot` y envialo.
4. BotFather te va a pedir el **nombre** del bot (puede ser cualquier cosa, ej: `Despensa Familia García`).
5. Después te pide el **username** (nombre de usuario). Tiene que terminar en `bot`, ej: `despensa_garcia_bot`.
6. Si el nombre está disponible, BotFather te va a dar un mensaje con un **TOKEN** que tiene este aspecto:
   ```
   123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
   ```
7. **Copiá ese token y guardalo** — lo vas a necesitar más adelante.

---

## PARTE 2 — Subir el código a GitHub

1. Entrá a [github.com](https://github.com) y creá una cuenta gratuita si no tenés.
2. Una vez dentro, hacé clic en el botón verde **"New"** (arriba a la izquierda) para crear un repositorio nuevo.
3. En **Repository name** escribí `despensa-bot`.
4. Dejá seleccionado **Public**.
5. Hacé clic en **"Create repository"**.
6. En la página que se abre, buscá el link que dice **"uploading an existing file"** y hacé clic.
7. Arrastrá estos 4 archivos a la zona de carga:
   - `bot.py`
   - `database.py`
   - `requirements.txt`
   - `Procfile`
8. Abajo de todo hacé clic en **"Commit changes"** (botón verde).

¡Listo! Tu código ya está en GitHub.

---

## PARTE 3 — Desplegar el bot en Railway

Railway es el servicio donde va a "vivir" y ejecutarse el bot las 24 horas.
**Costo: ~5 USD/mes** (plan Hobby). Podés pagar con tarjeta internacional.

1. Entrá a [railway.app](https://railway.app) y hacé clic en **"Login"**.
2. Elegí **"Login with GitHub"** — así se conecta con tu cuenta de GitHub.
3. Hacé clic en **"New Project"**.
4. Elegí **"Deploy from GitHub repo"**.
5. Seleccioná el repositorio `despensa-bot` que creaste antes.
6. Railway va a detectar el proyecto automáticamente. Hacé clic en **"Deploy Now"**.

### Agregar el Token del bot (obligatorio)

7. Una vez desplegado, hacé clic en el servicio que aparece.
8. Ir a la pestaña **"Variables"**.
9. Hacé clic en **"New Variable"** y completá:
   - **Name:** `TELEGRAM_TOKEN`
   - **Value:** pegá el token que copiaste de BotFather
10. Hacé clic en **"Add"**.

### Agregar almacenamiento persistente (para que los datos no se borren)

11. En el menú de tu proyecto, hacé clic en **"+ New"** → **"Volume"**.
12. En **"Mount Path"** escribí `/data`.
13. Hacé clic en **"Create"**.
14. Volvé a la pestaña **"Variables"** de tu servicio y agregá otra variable:
    - **Name:** `DB_PATH`
    - **Value:** `/data/despensa.db`
15. Railway va a reiniciar el bot automáticamente.

### Verificar que funciona

16. En la pestaña **"Deployments"** vas a ver los logs. Si ves `Bot iniciado ✅` significa que todo está bien.

---

## PARTE 4 — Usar el bot

1. En Telegram buscá tu bot por el username que elegiste (ej: `@despensa_garcia_bot`).
2. Hacé clic en **"Iniciar"** o escribí `/start`.
3. El bot te va a responder con el menú de comandos.

### Comandos disponibles

| Comando | Qué hace |
|---|---|
| `/agregar` | Agregar un insumo nuevo (el bot te guía paso a paso) |
| `/listar` | Ver todo lo que hay en la despensa |
| `/vencer` | Ver los productos que vencen en los próximos 7 días |
| `/buscar azucar` | Buscar un producto por nombre |
| `/eliminar` | Borrar un producto (te muestra botones para elegir) |
| `/ayuda` | Ver todos los comandos |

### Cómo agregar al grupo familiar

1. Creá un grupo de Telegram con tu familia (o usá uno que ya tengas).
2. En el grupo, tocá el nombre del grupo arriba → **"Agregar miembro"**.
3. Buscá tu bot por su username y agregalo.
4. Una vez en el grupo, cualquier integrante puede escribir `/agregar`, `/listar`, etc.
5. **Las invitaciones** al grupo son simplemente los links de invitación normales de Telegram.
   Para obtener el link: tocá el nombre del grupo → **"Enlace de invitación"** → compartilo.

---

## PARTE 5 — Avisos automáticos de vencimiento

El bot manda automáticamente un mensaje todos los días a las **6 AM (Argentina)** si hay productos por vencer en los próximos 7 días o que ya vencieron.

Para cambiar el horario o los días de anticipación, podés agregar estas variables en Railway:
- `HORA_AVISO` = número de hora en UTC (ej: `9` = 6 AM Argentina, `12` = 9 AM Argentina)
- `DIAS_AVISO` = cuántos días antes avisar (por defecto `7`)

---

## Indicadores de color en `/listar` y `/vencer`

- 🟢 = vence en más de 7 días (todo bien)
- 🟡 = vence en 7 días o menos (atención)
- 🟠 = vence en 3 días o menos (urgente)
- 🔴 = vencido o vence hoy

---

## Problemas frecuentes

**El bot no responde:**
- Verificá que el `TELEGRAM_TOKEN` esté bien copiado en Railway (sin espacios).
- Revisá la pestaña "Deployments" en Railway y buscá errores en los logs.

**Los datos se borraron:**
- Asegurate de haber creado el Volume en Railway y la variable `DB_PATH=/data/despensa.db`.

**Querés reiniciar el bot:**
- En Railway, pestaña "Deployments" → hacé clic en los tres puntos → "Redeploy".
