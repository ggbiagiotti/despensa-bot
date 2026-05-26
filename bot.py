import logging
import os
import threading
from datetime import date, datetime, time as t, timedelta

from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, Update,
    KeyboardButton, ReplyKeyboardMarkup, WebAppInfo,
    MenuButtonWebApp,
)
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler,
    ConversationHandler, ContextTypes, MessageHandler, filters,
)

import database as db

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

TOKEN      = os.environ["TELEGRAM_TOKEN"]
DIAS_AVISO = int(os.environ.get("DIAS_AVISO", "7"))
HORA_AVISO = int(os.environ.get("HORA_AVISO", "9"))   # UTC (9 = 6 AM Argentina)

# URL de la Mini App — se detecta automáticamente en Railway
_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
WEBAPP_URL = os.environ.get("WEBAPP_URL", f"https://{_domain}" if _domain else "")

# Estados de conversación /agregar
NOMBRE, MARCA, CANTIDAD, FECHA_COMPRA, FECHA_VENCE, COMENTARIO, FOTO = range(7)


# ─── helpers ────────────────────────────────────────────────────────────────

def parse_fecha(txt: str):
    txt = txt.strip().lower()
    if txt == "hoy":
        return date.today().isoformat()
    if txt in ("mañana", "manana"):
        return (date.today() + timedelta(days=1)).isoformat()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(txt, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def fmt_fecha(iso):
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y")
    except Exception:
        return iso


def semaforo(fecha_vence):
    if not fecha_vence:
        return ""
    diff = (date.fromisoformat(fecha_vence) - date.today()).days
    if diff < 0:
        return " 🔴 VENCIDO"
    if diff == 0:
        return " 🔴 VENCE HOY"
    if diff <= 3:
        return f" 🟠 {diff}d"
    if diff <= 7:
        return f" 🟡 {diff}d"
    return f" 🟢 {diff}d"


def card(row, n=None):
    prefix = f"{n}. " if n else ""
    marca_str = f" ({row['marca']})" if row.get("marca") else ""
    foto_str  = " 📷" if row.get("photo_file_id") else ""
    lines = [f"{prefix}*{row['nombre']}*{marca_str}{semaforo(row['fecha_vence'])}{foto_str}"]
    if row["cantidad"]:
        lines.append(f"   Cant.: {row['cantidad']}")
    lines.append(f"   Compra: {fmt_fecha(row['fecha_compra'])}")
    if row["fecha_vence"]:
        lines.append(f"   Vence: {fmt_fecha(row['fecha_vence'])}")
    if row["comentario"]:
        lines.append(f"   💬 {row['comentario']}")
    if row["agregado_por"]:
        lines.append(f"   👤 {row['agregado_por']}")
    return "\n".join(lines)


async def send_long(message, text):
    if len(text) <= 4096:
        await message.reply_text(text, parse_mode="Markdown")
        return
    chunk = ""
    for line in text.split("\n"):
        if len(chunk) + len(line) + 1 > 4000:
            await message.reply_text(chunk, parse_mode="Markdown")
            chunk = ""
        chunk += line + "\n"
    if chunk:
        await message.reply_text(chunk, parse_mode="Markdown")


def main_keyboard():
    """Teclado persistente con botón de la Mini App (si está disponible)."""
    if WEBAPP_URL:
        btn = KeyboardButton("🏠 Abrir Despensa", web_app=WebAppInfo(url=WEBAPP_URL))
        return ReplyKeyboardMarkup([[btn]], resize_keyboard=True)
    return None


# ─── /start y /ayuda ────────────────────────────────────────────────────────

MENU = (
    "🏠 *Bot de la Despensa*\n\n"
    "/agregar — Cargar un nuevo insumo\n"
    "/listar — Ver todo lo que hay\n"
    "/vencer — Ver lo que vence pronto\n"
    "/buscar nombre — Buscar un producto\n"
    "/eliminar — Borrar un insumo\n"
    "/ayuda — Esta ayuda\n\n"
    "Agregame a un grupo familiar para que todos puedan usar la despensa juntos 🏡"
)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = main_keyboard()
    await update.message.reply_text(MENU, parse_mode="Markdown", reply_markup=kb)


async def cmd_ayuda(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(MENU, parse_mode="Markdown")


# ─── /agregar ───────────────────────────────────────────────────────────────

async def cmd_agregar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    ctx.user_data["chat_id"] = update.effective_chat.id
    ctx.user_data["usuario"] = update.effective_user.first_name or "?"
    await update.message.reply_text(
        "📦 *Nuevo insumo*\n\n¿Cómo se llama el producto?",
        parse_mode="Markdown",
    )
    return NOMBRE


async def on_nombre(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["nombre"] = update.message.text.strip()
    kb = [[InlineKeyboardButton("Saltar", callback_data="skip_marca")]]
    await update.message.reply_text(
        "🏷️ ¿Cuál es la marca? Ej: *Arcor*, *Marolio*\nO tocá *Saltar*.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )
    return MARCA


async def on_marca(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["marca"] = update.message.text.strip()
    return await ask_cantidad(update.message)


async def cb_skip_marca(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    ctx.user_data["marca"] = None
    return await ask_cantidad(update.callback_query.message)


async def ask_cantidad(message):
    kb = [[InlineKeyboardButton("Saltar", callback_data="skip_cant")]]
    await message.reply_text(
        "📦 ¿Cuánto tenés? Ej: *2 kg*, *1 caja*, *500 g*\nO tocá *Saltar*.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )
    return CANTIDAD


async def on_cantidad(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["cantidad"] = update.message.text.strip()
    return await ask_fecha_compra(update.message)


async def cb_skip_cant(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    ctx.user_data["cantidad"] = None
    return await ask_fecha_compra(update.callback_query.message)


async def ask_fecha_compra(message):
    kb = [[InlineKeyboardButton("Hoy", callback_data="fc_hoy")]]
    await message.reply_text(
        "📅 ¿Cuándo lo compraste?\nFormato: *dd/mm/aaaa* — o tocá *Hoy*.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )
    return FECHA_COMPRA


async def on_fecha_compra(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    f = parse_fecha(update.message.text)
    if not f:
        await update.message.reply_text("❌ Formato inválido. Usá dd/mm/aaaa (ej: 20/05/2025)")
        return FECHA_COMPRA
    ctx.user_data["fecha_compra"] = f
    return await ask_fecha_vence(update.message)


async def cb_fc_hoy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    ctx.user_data["fecha_compra"] = date.today().isoformat()
    return await ask_fecha_vence(update.callback_query.message)


async def ask_fecha_vence(message):
    kb = [[InlineKeyboardButton("Sin vencimiento", callback_data="fv_none")]]
    await message.reply_text(
        "📅 ¿Cuándo vence?\nFormato: *dd/mm/aaaa* — o tocá *Sin vencimiento*.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )
    return FECHA_VENCE


async def on_fecha_vence(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    f = parse_fecha(update.message.text)
    if not f:
        await update.message.reply_text("❌ Formato inválido. Usá dd/mm/aaaa (ej: 20/06/2026)")
        return FECHA_VENCE
    ctx.user_data["fecha_vence"] = f
    return await ask_comentario(update.message)


async def cb_fv_none(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    ctx.user_data["fecha_vence"] = None
    return await ask_comentario(update.callback_query.message)


async def ask_comentario(message):
    kb = [[InlineKeyboardButton("Sin comentario", callback_data="com_none")]]
    await message.reply_text(
        "💬 ¿Algún comentario? Ej: *para las tortas*, *del super chino*\nO tocá *Sin comentario*.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )
    return COMENTARIO


async def on_comentario(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["comentario"] = update.message.text.strip()
    return await ask_foto(update.message)


async def cb_com_none(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    ctx.user_data["comentario"] = None
    return await ask_foto(update.callback_query.message)


async def ask_foto(message):
    kb = [[InlineKeyboardButton("Sin foto", callback_data="foto_none")]]
    await message.reply_text(
        "📸 ¿Querés agregar una foto del producto?\nEnviala ahora o tocá *Sin foto*.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )
    return FOTO


async def on_foto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # Tomar la foto de mayor resolución
    photo = update.message.photo[-1]
    ctx.user_data["photo_file_id"] = photo.file_id
    return await guardar(update.message, ctx)


async def cb_foto_none(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    ctx.user_data["photo_file_id"] = None
    return await guardar(update.callback_query.message, ctx)


async def guardar(message, ctx):
    d = ctx.user_data
    db.agregar(
        chat_id=d["chat_id"],
        nombre=d["nombre"],
        marca=d.get("marca"),
        cantidad=d.get("cantidad"),
        fecha_compra=d.get("fecha_compra"),
        fecha_vence=d.get("fecha_vence"),
        comentario=d.get("comentario"),
        usuario=d["usuario"],
        photo_file_id=d.get("photo_file_id"),
    )
    marca_str = f" ({d['marca']})" if d.get("marca") else ""
    resumen = (
        f"✅ *{d['nombre']}*{marca_str} guardado!\n"
        f"   Cant.: {d.get('cantidad') or '—'}\n"
        f"   Compra: {fmt_fecha(d.get('fecha_compra'))}\n"
        f"   Vence: {fmt_fecha(d.get('fecha_vence'))}\n"
        f"   💬 {d.get('comentario') or '—'}\n"
        f"   {'📷 Con foto' if d.get('photo_file_id') else '📷 Sin foto'}"
    )
    await message.reply_text(resumen, parse_mode="Markdown")
    ctx.user_data.clear()
    return ConversationHandler.END


async def cmd_cancelar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("❌ Operación cancelada.")
    return ConversationHandler.END


# ─── /listar ────────────────────────────────────────────────────────────────

async def cmd_listar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = db.listar(update.effective_chat.id)
    if not rows:
        await update.message.reply_text(
            "📭 La despensa está vacía. Usá /agregar para cargar insumos."
        )
        return
    header = f"🛒 *Despensa — {len(rows)} insumos*\n\n"
    body = "\n\n".join(card(r, i + 1) for i, r in enumerate(rows))
    await send_long(update.message, header + body)


# ─── /foto ──────────────────────────────────────────────────────────────────

async def cmd_foto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Muestra la foto de un insumo: /foto <número de la lista>"""
    if not ctx.args:
        await update.message.reply_text("Usá: /foto número\nEjemplo: /foto 3")
        return
    chat_id = update.effective_chat.id
    rows = db.listar(chat_id)
    try:
        idx = int(ctx.args[0]) - 1
        row = rows[idx]
    except (ValueError, IndexError):
        await update.message.reply_text("❌ Número inválido. Usá /listar para ver los números.")
        return
    if not row["photo_file_id"]:
        await update.message.reply_text(f"❌ *{row['nombre']}* no tiene foto.", parse_mode="Markdown")
        return
    await update.message.reply_photo(
        photo=row["photo_file_id"],
        caption=f"📷 *{row['nombre']}*" + (f" ({row['marca']})" if row.get("marca") else ""),
        parse_mode="Markdown",
    )


# ─── /vencer ────────────────────────────────────────────────────────────────

async def cmd_vencer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    proximos = db.por_vencer(chat_id, dias=DIAS_AVISO)
    venc = db.vencidos(chat_id)
    if not proximos and not venc:
        await update.message.reply_text(
            f"✅ No hay vencidos ni productos por vencer en los próximos {DIAS_AVISO} días."
        )
        return
    msg = "⚠️ *Alertas de vencimiento*\n\n"
    if venc:
        msg += f"🔴 *Vencidos ({len(venc)}):*\n"
        for r in venc:
            marca = f" ({r['marca']})" if r.get("marca") else ""
            msg += f"  • {r['nombre']}{marca} — venció el {fmt_fecha(r['fecha_vence'])}\n"
        msg += "\n"
    if proximos:
        msg += f"🟡 *Vencen en {DIAS_AVISO} días ({len(proximos)}):*\n"
        for r in proximos:
            marca = f" ({r['marca']})" if r.get("marca") else ""
            msg += f"  • {r['nombre']}{marca} — {fmt_fecha(r['fecha_vence'])}{semaforo(r['fecha_vence'])}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")


# ─── /buscar ────────────────────────────────────────────────────────────────

async def cmd_buscar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usá: /buscar nombre\nEjemplo: /buscar azucar")
        return
    query = " ".join(ctx.args)
    rows = db.buscar(update.effective_chat.id, query)
    if not rows:
        await update.message.reply_text(
            f"🔍 Sin resultados para *{query}*.", parse_mode="Markdown"
        )
        return
    txt = f"🔍 *{len(rows)} resultado(s) para '{query}':*\n\n"
    txt += "\n\n".join(card(r, i + 1) for i, r in enumerate(rows))
    await send_long(update.message, txt)


# ─── /eliminar ──────────────────────────────────────────────────────────────

async def cmd_eliminar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = db.listar(update.effective_chat.id)
    if not rows:
        await update.message.reply_text("📭 La despensa está vacía.")
        return
    botones = []
    for r in rows[:20]:
        label = r["nombre"]
        if r.get("marca"):
            label += f" ({r['marca']})"
        if r["fecha_vence"]:
            label += f" — {fmt_fecha(r['fecha_vence'])}"
        botones.append([InlineKeyboardButton(label, callback_data=f"del_{r['id']}")])
    botones.append([InlineKeyboardButton("❌ Cancelar", callback_data="del_cancel")])
    await update.message.reply_text(
        "🗑️ *¿Qué querés eliminar?* Tocá el producto:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(botones),
    )


async def cb_eliminar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "del_cancel":
        await q.edit_message_text("❌ Cancelado.")
        return
    item_id = int(q.data.split("_")[1])
    chat_id = q.message.chat_id
    row = db.get_by_id(item_id, chat_id)
    if row:
        db.eliminar(item_id, chat_id)
        await q.edit_message_text(f"✅ *{row['nombre']}* eliminado.", parse_mode="Markdown")
    else:
        await q.edit_message_text("❌ No encontré ese insumo.")


# ─── aviso diario ────────────────────────────────────────────────────────────

async def aviso_diario(ctx: ContextTypes.DEFAULT_TYPE):
    for chat_id in db.todos_los_chats():
        proximos = db.por_vencer(chat_id, dias=DIAS_AVISO)
        venc = db.vencidos(chat_id)
        if not proximos and not venc:
            continue
        msg = "⏰ *Recordatorio diario de la despensa*\n\n"
        if venc:
            msg += "🔴 *Vencidos:*\n"
            for r in venc:
                msg += f"  • {r['nombre']} (venció {fmt_fecha(r['fecha_vence'])})\n"
            msg += "\n"
        if proximos:
            msg += "🟡 *Por vencer pronto:*\n"
            for r in proximos:
                msg += f"  • {r['nombre']} — {fmt_fecha(r['fecha_vence'])}\n"
        try:
            await ctx.bot.send_message(int(chat_id), msg, parse_mode="Markdown")
        except Exception as e:
            log.warning("No pude avisar a %s: %s", chat_id, e)


# ─── Flask webapp (hilo separado) ────────────────────────────────────────────

def run_webapp():
    from webapp import flask_app
    port = int(os.environ.get("PORT", 8080))
    log.info("Mini App corriendo en puerto %s", port)
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


# ─── main ────────────────────────────────────────────────────────────────────

async def post_init(app):
    """Configura el botón de menú con la Mini App al arrancar."""
    if WEBAPP_URL:
        try:
            await app.bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="🏠 Despensa",
                    web_app=WebAppInfo(url=WEBAPP_URL),
                )
            )
            log.info("Botón de menú configurado: %s", WEBAPP_URL)
        except Exception as e:
            log.warning("No pude configurar el botón de menú: %s", e)


def main():
    db.init_db()

    # Arrancar Flask en hilo separado
    t_web = threading.Thread(target=run_webapp, daemon=True)
    t_web.start()

    app = Application.builder().token(TOKEN).post_init(post_init).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("agregar", cmd_agregar)],
        states={
            NOMBRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_nombre)],
            MARCA: [
                CallbackQueryHandler(cb_skip_marca, pattern="^skip_marca$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_marca),
            ],
            CANTIDAD: [
                CallbackQueryHandler(cb_skip_cant, pattern="^skip_cant$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_cantidad),
            ],
            FECHA_COMPRA: [
                CallbackQueryHandler(cb_fc_hoy, pattern="^fc_hoy$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_fecha_compra),
            ],
            FECHA_VENCE: [
                CallbackQueryHandler(cb_fv_none, pattern="^fv_none$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_fecha_vence),
            ],
            COMENTARIO: [
                CallbackQueryHandler(cb_com_none, pattern="^com_none$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_comentario),
            ],
            FOTO: [
                CallbackQueryHandler(cb_foto_none, pattern="^foto_none$"),
                MessageHandler(filters.PHOTO, on_foto),
            ],
        },
        fallbacks=[CommandHandler("cancelar", cmd_cancelar)],
        per_user=True,
        per_chat=True,
        conversation_timeout=300,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("ayuda",    cmd_ayuda))
    app.add_handler(CommandHandler("listar",   cmd_listar))
    app.add_handler(CommandHandler("foto",     cmd_foto))
    app.add_handler(CommandHandler("vencer",   cmd_vencer))
    app.add_handler(CommandHandler("buscar",   cmd_buscar))
    app.add_handler(CommandHandler("eliminar", cmd_eliminar))
    app.add_handler(CallbackQueryHandler(cb_eliminar, pattern="^del_"))

    app.job_queue.run_daily(aviso_diario, time=t(hour=HORA_AVISO, minute=0))

    log.info("Bot iniciado ✅  |  Mini App: %s", WEBAPP_URL or "no configurada")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
