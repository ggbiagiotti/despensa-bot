import json
import os
import urllib.request
from functools import wraps

from flask import Flask, g, jsonify, request, send_from_directory

import database as db

flask_app = Flask(__name__, static_folder="static")
flask_app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-despensa-2025")
TOKEN             = os.environ.get("TELEGRAM_TOKEN", "")
GOOGLE_CLIENT_ID  = os.environ.get("GOOGLE_CLIENT_ID", "")


# ── Auth helpers ─────────────────────────────────────────────────────────────

def _token_from_request():
    h = request.headers.get("Authorization", "")
    if h.startswith("Bearer "):
        return h[7:]
    return request.args.get("token") or (request.json or {}).get("token")


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = _token_from_request()
        usuario = db.get_usuario_desde_token(token)
        if not usuario:
            return jsonify({"error": "No autenticado"}), 401
        g.usuario = usuario
        return f(*args, **kwargs)
    return decorated


def require_superadmin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = _token_from_request()
        usuario = db.get_usuario_desde_token(token)
        if not usuario:
            return jsonify({"error": "No autenticado"}), 401
        if usuario["rol"] != "superadmin":
            return jsonify({"error": "Acceso denegado"}), 403
        g.usuario = usuario
        return f(*args, **kwargs)
    return decorated


def _check_access(chat_id):
    """Verifica acceso del usuario autenticado al chat_id. Superadmin siempre pasa."""
    token = _token_from_request()
    if not token:
        return chat_id == "preview-demo"
    usuario = db.get_usuario_desde_token(token)
    if not usuario:
        return chat_id == "preview-demo"
    if usuario["rol"] == "superadmin":
        return True
    return db.usuario_tiene_acceso(chat_id, usuario["id"])


def _verify_google_token(credential):
    """Verifica un ID token de Google via tokeninfo endpoint."""
    url = f"https://oauth2.googleapis.com/tokeninfo?id_token={credential}"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            info = json.loads(r.read())
        if GOOGLE_CLIENT_ID and info.get("aud") != GOOGLE_CLIENT_ID:
            return None
        return info
    except Exception:
        return None


# ── Mini App HTML ─────────────────────────────────────────────────────────────

@flask_app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ══ INVENTARIO ════════════════════════════════════════════════════════════════

@flask_app.route("/api/items")
def get_items():
    chat_id = request.args.get("chat_id")
    if not chat_id:
        return jsonify({"error": "chat_id requerido"}), 400
    return jsonify([_inv(r) for r in db.listar(chat_id)])


@flask_app.route("/api/items", methods=["POST"])
def add_item():
    data = request.json or {}
    chat_id = data.get("chat_id")
    nombre  = (data.get("nombre") or "").strip()
    if not chat_id or not nombre:
        return jsonify({"error": "chat_id y nombre son obligatorios"}), 400
    db.agregar(
        chat_id=chat_id,
        nombre=nombre,
        marca=data.get("marca") or None,
        cantidad=data.get("cantidad") or None,
        fecha_compra=data.get("fecha_compra") or None,
        fecha_vence=data.get("fecha_vence") or None,
        comentario=data.get("comentario") or None,
        usuario=data.get("usuario") or "App",
        unidades=int(data.get("unidades") or 1),
    )
    return jsonify({"ok": True})


@flask_app.route("/api/items/<int:item_id>", methods=["DELETE"])
def delete_item(item_id):
    chat_id = request.args.get("chat_id")
    if not chat_id:
        return jsonify({"error": "chat_id requerido"}), 400
    db.eliminar(item_id, chat_id)
    return jsonify({"ok": True})


@flask_app.route("/api/expiring")
def get_expiring():
    chat_id = request.args.get("chat_id")
    dias    = int(request.args.get("dias", 7))
    if not chat_id:
        return jsonify({"error": "chat_id requerido"}), 400
    return jsonify({
        "expiring": [_inv(r) for r in db.por_vencer(chat_id, dias=dias)],
        "expired":  [_inv(r) for r in db.vencidos(chat_id)],
    })


@flask_app.route("/api/search")
def search_items():
    chat_id = request.args.get("chat_id")
    q       = request.args.get("q", "")
    if not chat_id:
        return jsonify({"error": "chat_id requerido"}), 400
    return jsonify([_inv(r) for r in db.buscar(chat_id, q)])


@flask_app.route("/api/suggestions")
def get_suggestions():
    chat_id = request.args.get("chat_id")
    if not chat_id:
        return jsonify({"error": "chat_id requerido"}), 400
    return jsonify(db.get_suggestions(chat_id))


@flask_app.route("/api/abiertos")
def get_abiertos():
    chat_id = request.args.get("chat_id")
    if not chat_id:
        return jsonify({"error": "chat_id requerido"}), 400
    return jsonify([_inv(r) for r in db.listar_abiertos(chat_id)])


# ── Abrir / consumo / vaciar ─────────────────────────────────────────────────

@flask_app.route("/api/items/<int:item_id>/abrir", methods=["POST"])
def abrir_item(item_id):
    data    = request.json or {}
    chat_id = data.get("chat_id")
    consumo = data.get("consumo", "lleno")
    if not chat_id:
        return jsonify({"error": "chat_id requerido"}), 400
    db.insumo_abrir(item_id, chat_id, consumo)
    return jsonify({"ok": True})


@flask_app.route("/api/items/<int:item_id>/consumo", methods=["POST"])
def set_consumo(item_id):
    data    = request.json or {}
    chat_id = data.get("chat_id")
    consumo = data.get("consumo")
    if not chat_id or not consumo:
        return jsonify({"error": "faltan datos"}), 400
    db.insumo_consumo(item_id, chat_id, consumo)
    return jsonify({"ok": True})


@flask_app.route("/api/items/<int:item_id>/vaciar", methods=["POST"])
def vaciar_item(item_id):
    data    = request.json or {}
    chat_id = data.get("chat_id")
    if not chat_id:
        return jsonify({"error": "chat_id requerido"}), 400
    result = db.insumo_vaciar(item_id, chat_id)
    return jsonify({"ok": True, "result": result})


# ── Foto proxy ───────────────────────────────────────────────────────────────

@flask_app.route("/api/photo/<int:item_id>")
def get_photo(item_id):
    chat_id = request.args.get("chat_id")
    if not chat_id or not TOKEN:
        return "", 404
    row = db.get_by_id(item_id, chat_id)
    if not row or not row["photo_file_id"]:
        return "", 404
    try:
        api_url = f"https://api.telegram.org/bot{TOKEN}/getFile?file_id={row['photo_file_id']}"
        with urllib.request.urlopen(api_url) as resp:
            info = json.loads(resp.read())
        file_path = info["result"]["file_path"]
        photo_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
        with urllib.request.urlopen(photo_url) as resp:
            data = resp.read()
        return data, 200, {"Content-Type": "image/jpeg", "Cache-Control": "max-age=3600"}
    except Exception:
        return "", 404


# ══ LISTA DE COMPRAS ══════════════════════════════════════════════════════════

@flask_app.route("/api/compras")
def get_compras():
    chat_id = request.args.get("chat_id")
    if not chat_id:
        return jsonify({"error": "chat_id requerido"}), 400
    return jsonify([_compra(r) for r in db.lista_listar(chat_id)])


@flask_app.route("/api/compras", methods=["POST"])
def add_compra():
    data    = request.json or {}
    chat_id = data.get("chat_id")
    nombre  = (data.get("nombre") or "").strip()
    if not chat_id or not nombre:
        return jsonify({"error": "chat_id y nombre son obligatorios"}), 400
    db.lista_agregar(
        chat_id=chat_id,
        nombre=nombre,
        marca=data.get("marca") or None,
        unidades=int(data.get("unidades") or 1),
        cantidad=data.get("cantidad") or None,
        comentario=data.get("comentario") or None,
        usuario=data.get("usuario") or "App",
    )
    return jsonify({"ok": True})


@flask_app.route("/api/compras/<int:item_id>/toggle", methods=["POST"])
def toggle_compra(item_id):
    data     = request.json or {}
    chat_id  = data.get("chat_id")
    cant_real = data.get("cant_real") or None
    if not chat_id:
        return jsonify({"error": "chat_id requerido"}), 400
    nuevo = db.lista_toggle(item_id, chat_id, cant_real)
    return jsonify({"ok": True, "comprado": nuevo})


@flask_app.route("/api/compras/<int:item_id>/cant_real", methods=["POST"])
def update_cant_real(item_id):
    data      = request.json or {}
    chat_id   = data.get("chat_id")
    cant_real = data.get("cant_real")
    if not chat_id:
        return jsonify({"error": "chat_id requerido"}), 400
    db.lista_set_cant_real(item_id, chat_id, cant_real)
    return jsonify({"ok": True})


@flask_app.route("/api/compras/<int:item_id>", methods=["PUT"])
def update_compra(item_id):
    data    = request.json or {}
    chat_id = data.get("chat_id")
    nombre  = (data.get("nombre") or "").strip()
    if not chat_id or not nombre:
        return jsonify({"error": "chat_id y nombre son obligatorios"}), 400
    db.lista_actualizar(
        item_id, chat_id,
        nombre=nombre,
        marca=data.get("marca") or None,
        unidades=int(data.get("unidades") or 1),
        cantidad=data.get("cantidad") or None,
        comentario=data.get("comentario") or None,
    )
    return jsonify({"ok": True})


@flask_app.route("/api/compras/<int:item_id>", methods=["DELETE"])
def delete_compra(item_id):
    chat_id = request.args.get("chat_id")
    if not chat_id:
        return jsonify({"error": "chat_id requerido"}), 400
    db.lista_eliminar(item_id, chat_id)
    return jsonify({"ok": True})


@flask_app.route("/api/compras/inventariar", methods=["POST"])
def inventariar():
    data       = request.json or {}
    chat_id    = data.get("chat_id")
    usuario    = data.get("usuario") or "App"
    items_data = data.get("items") or []
    if not chat_id:
        return jsonify({"error": "chat_id requerido"}), 400
    nombres = db.lista_inventariar(chat_id, items_data, usuario)
    return jsonify({"ok": True, "agregados": nombres})


# ══ CONFIG ════════════════════════════════════════════════════════════════════

@flask_app.route("/api/config")
def get_config():
    return jsonify({"google_client_id": GOOGLE_CLIENT_ID})


# ══ AUTH ══════════════════════════════════════════════════════════════════════

@flask_app.route("/api/auth/register", methods=["POST"])
def auth_register():
    data     = request.json or {}
    nombre   = (data.get("nombre") or "").strip()
    email    = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not nombre or not email or len(password) < 6:
        return jsonify({"error": "Nombre, email y contraseña (mín. 6 chars) son obligatorios"}), 400
    if db.get_usuario_by_email(email):
        return jsonify({"error": "Ya existe una cuenta con ese email"}), 409
    usuario = db.crear_usuario(nombre=nombre, email=email, password=password)
    token   = db.crear_sesion(usuario["id"])
    return jsonify({"ok": True, "token": token, "usuario": _u(usuario)})


@flask_app.route("/api/auth/login", methods=["POST"])
def auth_login():
    data     = request.json or {}
    email    = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    usuario  = db.get_usuario_by_email(email)
    if not usuario or not db.verificar_password(usuario, password):
        return jsonify({"error": "Email o contraseña incorrectos"}), 401
    if not usuario["activo"]:
        return jsonify({"error": "Cuenta desactivada"}), 403
    token = db.crear_sesion(usuario["id"])
    return jsonify({"ok": True, "token": token, "usuario": _u(usuario)})


@flask_app.route("/api/auth/google", methods=["POST"])
def auth_google():
    data       = request.json or {}
    credential = data.get("credential") or ""
    if not credential:
        return jsonify({"error": "Token Google requerido"}), 400
    info = _verify_google_token(credential)
    if not info:
        return jsonify({"error": "Token Google inválido"}), 401
    google_id = info.get("sub")
    email     = info.get("email", "").lower()
    nombre    = info.get("given_name") or info.get("name") or email.split("@")[0]
    avatar    = info.get("picture")
    usuario = db.get_usuario_by_google_id(google_id)
    if not usuario and email:
        usuario = db.get_usuario_by_email(email)
    if usuario:
        db.update_usuario(usuario["id"], google_avatar=avatar)
        usuario = db.get_usuario_by_id(usuario["id"])
    else:
        usuario = db.crear_usuario(nombre=nombre, email=email,
                                   google_id=google_id, google_avatar=avatar)
    if not usuario["activo"]:
        return jsonify({"error": "Cuenta desactivada"}), 403
    token = db.crear_sesion(usuario["id"])
    return jsonify({"ok": True, "token": token, "usuario": _u(usuario)})


@flask_app.route("/api/auth/telegram", methods=["POST"])
def auth_telegram():
    """Auth automático desde la Mini App de Telegram."""
    data        = request.json or {}
    telegram_id = data.get("telegram_id")
    nombre      = (data.get("nombre") or "").strip() or "Usuario"
    chat_id     = data.get("chat_id")
    if not telegram_id:
        return jsonify({"error": "telegram_id requerido"}), 400
    usuario = db.get_usuario_by_telegram_id(telegram_id)
    if not usuario:
        usuario = db.crear_usuario(nombre=nombre, telegram_id=telegram_id)
    # Asegurar que exista la vivienda para este chat_id de Telegram
    if chat_id and chat_id != "preview-demo":
        viv = db.get_vivienda_by_chat_id(chat_id)
        if not viv:
            vid, _ = db.crear_vivienda(f"Casa {str(chat_id)[-4:]}", owner_id=usuario["id"])
            db.update_vivienda(vid)  # no-op; vivienda ya creada con owner
        else:
            db.agregar_usuario_vivienda(viv["id"], usuario["id"],
                                        rol="usuario", estado="activo")
    token = db.crear_sesion(usuario["id"])
    return jsonify({"ok": True, "token": token, "usuario": _u(usuario)})


@flask_app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    token = _token_from_request()
    if token:
        db.delete_sesion(token)
    return jsonify({"ok": True})


@flask_app.route("/api/me")
@require_auth
def get_me():
    viviendas = db.listar_viviendas_usuario(g.usuario["id"])
    return jsonify({
        "usuario": _u(g.usuario),
        "viviendas": [_v(v) for v in viviendas],
    })


# ══ VIVIENDAS ══════════════════════════════════════════════════════════════════

@flask_app.route("/api/viviendas")
@require_auth
def get_viviendas():
    if g.usuario["rol"] == "superadmin":
        return jsonify([_v(v) for v in db.listar_todas_viviendas()])
    return jsonify([_v(v) for v in db.listar_viviendas_usuario(g.usuario["id"])])


@flask_app.route("/api/viviendas", methods=["POST"])
@require_auth
def crear_vivienda_api():
    data   = request.json or {}
    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        return jsonify({"error": "Nombre requerido"}), 400
    vid, chat_id = db.crear_vivienda(nombre, data.get("descripcion"),
                                     owner_id=g.usuario["id"])
    return jsonify({"ok": True, "id": vid, "chat_id": chat_id})


@flask_app.route("/api/viviendas/<int:vid>", methods=["PUT"])
@require_auth
def update_vivienda_api(vid):
    data = request.json or {}
    if g.usuario["rol"] != "superadmin" and not db.es_moderador_vivienda(
        (db.get_vivienda_by_id(vid) or {}).get("chat_id", ""), g.usuario["id"]
    ):
        return jsonify({"error": "Sin permiso"}), 403
    db.update_vivienda(vid, nombre=data.get("nombre"), descripcion=data.get("descripcion"))
    return jsonify({"ok": True})


@flask_app.route("/api/viviendas/<int:vid>", methods=["DELETE"])
@require_superadmin
def delete_vivienda_api(vid):
    db.delete_vivienda(vid)
    return jsonify({"ok": True})


@flask_app.route("/api/viviendas/<int:vid>/usuarios")
@require_auth
def get_usuarios_vivienda(vid):
    viv = db.get_vivienda_by_id(vid)
    if not viv:
        return jsonify({"error": "Vivienda no encontrada"}), 404
    if g.usuario["rol"] != "superadmin" and not db.es_moderador_vivienda(
        viv["chat_id"], g.usuario["id"]
    ):
        return jsonify({"error": "Sin permiso"}), 403
    return jsonify([_vu(u) for u in db.listar_usuarios_vivienda(vid)])


@flask_app.route("/api/viviendas/<int:vid>/usuarios/<int:uid>", methods=["PUT"])
@require_auth
def update_usuario_vivienda(vid, uid):
    data = request.json or {}
    viv  = db.get_vivienda_by_id(vid)
    if not viv:
        return jsonify({"error": "Vivienda no encontrada"}), 404
    if g.usuario["rol"] != "superadmin" and not db.es_moderador_vivienda(
        viv["chat_id"], g.usuario["id"]
    ):
        return jsonify({"error": "Sin permiso"}), 403
    db.update_vivienda_usuario(vid, uid,
                               estado=data.get("estado"),
                               rol=data.get("rol"))
    return jsonify({"ok": True})


@flask_app.route("/api/viviendas/<int:vid>/usuarios/<int:uid>", methods=["DELETE"])
@require_auth
def remove_usuario_vivienda_api(vid, uid):
    viv = db.get_vivienda_by_id(vid)
    if not viv:
        return jsonify({"error": "Vivienda no encontrada"}), 404
    if g.usuario["rol"] != "superadmin" and not db.es_moderador_vivienda(
        viv["chat_id"], g.usuario["id"]
    ):
        return jsonify({"error": "Sin permiso"}), 403
    db.remove_usuario_vivienda(vid, uid)
    return jsonify({"ok": True})


@flask_app.route("/api/viviendas/<int:vid>/invitar", methods=["POST"])
@require_auth
def invitar_a_vivienda(vid):
    viv = db.get_vivienda_by_id(vid)
    if not viv:
        return jsonify({"error": "Vivienda no encontrada"}), 404
    if g.usuario["rol"] != "superadmin" and not db.es_moderador_vivienda(
        viv["chat_id"], g.usuario["id"]
    ):
        return jsonify({"error": "Sin permiso"}), 403
    data  = request.json or {}
    token = db.crear_invitacion(vid, g.usuario["id"],
                                rol=data.get("rol", "usuario"),
                                email_destino=data.get("email"))
    link  = f"{request.host_url}?invite={token}"
    return jsonify({"ok": True, "token": token, "link": link})


@flask_app.route("/api/invitacion/<token>")
def check_invitacion(token):
    inv = db.get_invitacion(token)
    if not inv:
        return jsonify({"error": "Invitación inválida o expirada"}), 404
    return jsonify({"vivienda": inv["vivienda_nombre"], "rol": inv["rol"]})


@flask_app.route("/api/invitacion/<token>/usar", methods=["POST"])
@require_auth
def usar_invitacion_api(token):
    inv = db.usar_invitacion(token, g.usuario["id"])
    if not inv:
        return jsonify({"error": "Invitación inválida, expirada o ya usada"}), 400
    return jsonify({"ok": True, "vivienda": inv["vivienda_nombre"],
                    "chat_id": inv["chat_id"]})


# ══ ADMIN ══════════════════════════════════════════════════════════════════════

@flask_app.route("/api/admin/usuarios")
@require_superadmin
def admin_get_usuarios():
    return jsonify([_u(u) for u in db.listar_usuarios()])


@flask_app.route("/api/admin/usuarios/<int:uid>", methods=["PUT"])
@require_superadmin
def admin_update_usuario(uid):
    data = request.json or {}
    db.update_usuario(uid, rol=data.get("rol"), activo=data.get("activo"))
    return jsonify({"ok": True})


@flask_app.route("/api/admin/usuarios/<int:uid>", methods=["DELETE"])
@require_superadmin
def admin_delete_usuario(uid):
    if uid == g.usuario["id"]:
        return jsonify({"error": "No podés eliminarte a vos mismo"}), 400
    db.delete_usuario(uid)
    return jsonify({"ok": True})


@flask_app.route("/api/admin/viviendas")
@require_superadmin
def admin_get_viviendas():
    return jsonify([_v(v) for v in db.listar_todas_viviendas()])


# ── helpers ───────────────────────────────────────────────────────────────────

def _u(r):
    return {
        "id":       r["id"],
        "nombre":   r["nombre"],
        "apellido": r["apellido"],
        "email":    r["email"],
        "rol":      r["rol"],
        "activo":   bool(r["activo"]),
        "avatar":   r["google_avatar"],
        "telegram": bool(r["telegram_id"]),
    }


def _v(r):
    return {
        "id":          r["id"],
        "nombre":      r["nombre"],
        "chat_id":     r["chat_id"],
        "descripcion": r["descripcion"],
        "n_usuarios":  r["n_usuarios"] if "n_usuarios" in r.keys() else None,
        "mi_rol":      r["mi_rol"] if "mi_rol" in r.keys() else None,
    }


def _vu(r):
    return {
        "id":         r["id"],
        "nombre":     r["nombre"],
        "apellido":   r["apellido"],
        "email":      r["email"],
        "avatar":     r["google_avatar"],
        "telegram":   bool(r["telegram_id"]),
        "rol":        r["rol"],
        "estado":     r["estado"],
        "created_at": r["created_at"],
    }


def _inv(r):
    return {
        "id":           r["id"],
        "nombre":       r["nombre"],
        "marca":        r["marca"],
        "cantidad":     r["cantidad"],
        "unidades":     r["unidades"] or 1,
        "abiertas":     r["abiertas"] or 0,
        "consumo":      r["consumo"],
        "fecha_compra": r["fecha_compra"],
        "fecha_vence":  r["fecha_vence"],
        "comentario":   r["comentario"],
        "agregado_por": r["agregado_por"],
        "has_photo":    bool(r["photo_file_id"]),
    }


def _compra(r):
    return {
        "id":          r["id"],
        "nombre":      r["nombre"],
        "marca":       r["marca"],
        "unidades":    r["unidades"] or 1,
        "cantidad":    r["cantidad"],
        "comprado":    bool(r["comprado"]),
        "cant_real":   r["cant_real"],
        "comentario":  r["comentario"],
        "agregado_por":r["agregado_por"],
    }
