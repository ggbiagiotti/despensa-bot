import os
import secrets
import sqlite3
import uuid
from datetime import date, datetime, timedelta

from werkzeug.security import check_password_hash, generate_password_hash

DB_PATH = os.environ.get("DB_PATH", "despensa.db")


def _db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with _db() as con:
        # ── Inventario ───────────────────────────────────────────────────────
        con.execute("""
            CREATE TABLE IF NOT EXISTS insumos (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id       TEXT    NOT NULL,
                nombre        TEXT    NOT NULL,
                marca         TEXT,
                cantidad      TEXT,
                unidades      INTEGER DEFAULT 1,
                abiertas      INTEGER DEFAULT 0,
                consumo       TEXT,
                fecha_compra  TEXT,
                fecha_vence   TEXT,
                comentario    TEXT,
                photo_file_id TEXT,
                agregado_por  TEXT,
                created_at    TEXT DEFAULT (date('now'))
            )
        """)
        for col, defn in [
            ("marca",         "TEXT"),
            ("photo_file_id", "TEXT"),
            ("unidades",      "INTEGER DEFAULT 1"),
            ("abiertas",      "INTEGER DEFAULT 0"),
            ("consumo",       "TEXT"),
        ]:
            try:
                con.execute(f"ALTER TABLE insumos ADD COLUMN {col} {defn}")
            except Exception:
                pass

        # ── Lista de compras ─────────────────────────────────────────────────
        con.execute("""
            CREATE TABLE IF NOT EXISTS lista_compras (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id      TEXT    NOT NULL,
                nombre       TEXT    NOT NULL,
                marca        TEXT,
                unidades     INTEGER DEFAULT 1,
                cantidad     TEXT,
                comprado     INTEGER DEFAULT 0,
                cant_real    TEXT,
                comentario   TEXT,
                agregado_por TEXT,
                created_at   TEXT DEFAULT (date('now'))
            )
        """)
        try:
            con.execute("ALTER TABLE lista_compras ADD COLUMN unidades INTEGER DEFAULT 1")
        except Exception:
            pass

        # ── Usuarios ──────────────────────────────────────────────────────────
        con.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                email         TEXT    UNIQUE,
                nombre        TEXT    NOT NULL,
                apellido      TEXT,
                password_hash TEXT,
                google_id     TEXT    UNIQUE,
                google_avatar TEXT,
                rol           TEXT    DEFAULT 'usuario',
                activo        INTEGER DEFAULT 1,
                telegram_id   TEXT    UNIQUE,
                created_at    TEXT    DEFAULT (datetime('now'))
            )
        """)

        # ── Sesiones ──────────────────────────────────────────────────────────
        con.execute("""
            CREATE TABLE IF NOT EXISTS sesiones (
                token      TEXT    PRIMARY KEY,
                usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
                created_at TEXT    DEFAULT (datetime('now'))
            )
        """)

        # ── Viviendas ─────────────────────────────────────────────────────────
        con.execute("""
            CREATE TABLE IF NOT EXISTS viviendas (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre      TEXT    NOT NULL,
                chat_id     TEXT    UNIQUE NOT NULL,
                descripcion TEXT,
                created_at  TEXT    DEFAULT (datetime('now'))
            )
        """)

        # ── Vivienda-Usuarios ─────────────────────────────────────────────────
        con.execute("""
            CREATE TABLE IF NOT EXISTS vivienda_usuarios (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                vivienda_id  INTEGER NOT NULL REFERENCES viviendas(id),
                usuario_id   INTEGER NOT NULL REFERENCES usuarios(id),
                rol          TEXT    DEFAULT 'usuario',
                estado       TEXT    DEFAULT 'pendiente',
                invitado_por INTEGER REFERENCES usuarios(id),
                created_at   TEXT    DEFAULT (datetime('now')),
                UNIQUE(vivienda_id, usuario_id)
            )
        """)

        # ── Invitaciones ──────────────────────────────────────────────────────
        con.execute("""
            CREATE TABLE IF NOT EXISTS invitaciones (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                token         TEXT    UNIQUE NOT NULL,
                vivienda_id   INTEGER NOT NULL REFERENCES viviendas(id),
                creado_por    INTEGER NOT NULL REFERENCES usuarios(id),
                email_destino TEXT,
                rol           TEXT    DEFAULT 'usuario',
                usado         INTEGER DEFAULT 0,
                expires_at    TEXT,
                created_at    TEXT    DEFAULT (datetime('now'))
            )
        """)

        # Vivienda demo para preview sin auth
        try:
            con.execute("INSERT OR IGNORE INTO viviendas(nombre, chat_id) VALUES(?,?)",
                        ('Demo', 'preview-demo'))
        except Exception:
            pass

        # Migrar chat_ids existentes a viviendas
        chat_ids = [r[0] for r in con.execute(
            "SELECT DISTINCT chat_id FROM insumos"
            " UNION SELECT DISTINCT chat_id FROM lista_compras"
        ).fetchall()]
        for cid in chat_ids:
            try:
                con.execute("INSERT OR IGNORE INTO viviendas(nombre, chat_id) VALUES(?,?)",
                            (f'Vivienda {cid[:8]}', cid))
            except Exception:
                pass

        con.commit()


# ══ INVENTARIO ═══════════════════════════════════════════════════════════════

def agregar(chat_id, nombre, marca, cantidad, fecha_compra, fecha_vence,
            comentario, usuario, photo_file_id=None, unidades=1):
    with _db() as con:
        con.execute(
            "INSERT INTO insumos"
            "(chat_id,nombre,marca,cantidad,unidades,fecha_compra,fecha_vence,"
            " comentario,agregado_por,photo_file_id)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (str(chat_id), nombre, marca, cantidad, max(1, int(unidades or 1)),
             fecha_compra, fecha_vence, comentario, usuario, photo_file_id),
        )
        con.commit()


def listar(chat_id):
    with _db() as con:
        return con.execute(
            "SELECT * FROM insumos WHERE chat_id=?"
            " ORDER BY fecha_vence ASC NULLS LAST, nombre ASC",
            (str(chat_id),),
        ).fetchall()


def listar_abiertos(chat_id):
    with _db() as con:
        return con.execute(
            "SELECT * FROM insumos WHERE chat_id=? AND abiertas>0"
            " ORDER BY nombre ASC",
            (str(chat_id),),
        ).fetchall()


def por_vencer(chat_id, dias=7):
    hoy = date.today().isoformat()
    lim = (date.today() + timedelta(days=dias)).isoformat()
    with _db() as con:
        return con.execute(
            "SELECT * FROM insumos WHERE chat_id=? AND fecha_vence IS NOT NULL"
            " AND fecha_vence >= ? AND fecha_vence <= ? ORDER BY fecha_vence ASC",
            (str(chat_id), hoy, lim),
        ).fetchall()


def vencidos(chat_id):
    hoy = date.today().isoformat()
    with _db() as con:
        return con.execute(
            "SELECT * FROM insumos WHERE chat_id=? AND fecha_vence IS NOT NULL"
            " AND fecha_vence < ?",
            (str(chat_id), hoy),
        ).fetchall()


def eliminar(item_id, chat_id):
    with _db() as con:
        con.execute("DELETE FROM insumos WHERE id=? AND chat_id=?",
                    (item_id, str(chat_id)))
        con.commit()


def buscar(chat_id, query):
    with _db() as con:
        return con.execute(
            "SELECT * FROM insumos WHERE chat_id=? AND nombre LIKE ?"
            " ORDER BY nombre ASC",
            (str(chat_id), f"%{query}%"),
        ).fetchall()


def get_by_id(item_id, chat_id):
    with _db() as con:
        return con.execute(
            "SELECT * FROM insumos WHERE id=? AND chat_id=?",
            (item_id, str(chat_id)),
        ).fetchone()


def get_suggestions(chat_id):
    """Retorna nombres y marcas únicos del inventario y lista de compras."""
    with _db() as con:
        nombres = [r[0] for r in con.execute(
            "SELECT DISTINCT nombre FROM insumos WHERE chat_id=?"
            " UNION SELECT DISTINCT nombre FROM lista_compras WHERE chat_id=?"
            " ORDER BY nombre ASC",
            (str(chat_id), str(chat_id)),
        ).fetchall() if r[0]]
        marcas = [r[0] for r in con.execute(
            "SELECT DISTINCT marca FROM insumos WHERE chat_id=? AND marca IS NOT NULL"
            " UNION SELECT DISTINCT marca FROM lista_compras WHERE chat_id=? AND marca IS NOT NULL"
            " ORDER BY marca ASC",
            (str(chat_id), str(chat_id)),
        ).fetchall() if r[0]]
        return {"nombres": nombres, "marcas": marcas}


def todos_los_chats():
    with _db() as con:
        return [r[0] for r in con.execute(
            "SELECT DISTINCT chat_id FROM insumos"
        ).fetchall()]


# ── Abrir / consumo / vaciar ─────────────────────────────────────────────────

def insumo_abrir(item_id, chat_id, consumo="lleno"):
    """Abre una unidad del producto."""
    with _db() as con:
        con.execute(
            "UPDATE insumos SET abiertas=1, consumo=? WHERE id=? AND chat_id=?",
            (consumo, item_id, str(chat_id)),
        )
        con.commit()


def insumo_consumo(item_id, chat_id, consumo):
    """Actualiza el nivel de consumo del paquete abierto."""
    with _db() as con:
        con.execute(
            "UPDATE insumos SET consumo=? WHERE id=? AND chat_id=?",
            (consumo, item_id, str(chat_id)),
        )
        con.commit()


def insumo_vaciar(item_id, chat_id):
    """Vacía la unidad abierta. Descuenta del stock o elimina si era la última."""
    with _db() as con:
        row = con.execute(
            "SELECT unidades FROM insumos WHERE id=? AND chat_id=?",
            (item_id, str(chat_id)),
        ).fetchone()
        if not row:
            return None
        if row["unidades"] > 1:
            con.execute(
                "UPDATE insumos SET unidades=unidades-1, abiertas=0, consumo=NULL"
                " WHERE id=? AND chat_id=?",
                (item_id, str(chat_id)),
            )
            con.commit()
            return "updated"
        else:
            con.execute("DELETE FROM insumos WHERE id=? AND chat_id=?",
                        (item_id, str(chat_id)))
            con.commit()
            return "deleted"


# ══ LISTA DE COMPRAS ══════════════════════════════════════════════════════════

def lista_agregar(chat_id, nombre, marca, unidades, cantidad, comentario, usuario):
    with _db() as con:
        con.execute(
            "INSERT INTO lista_compras(chat_id,nombre,marca,unidades,cantidad,comentario,agregado_por)"
            " VALUES(?,?,?,?,?,?,?)",
            (str(chat_id), nombre, marca, max(1, int(unidades or 1)), cantidad, comentario, usuario),
        )
        con.commit()


def lista_listar(chat_id):
    with _db() as con:
        return con.execute(
            "SELECT * FROM lista_compras WHERE chat_id=?"
            " ORDER BY comprado ASC, id ASC",
            (str(chat_id),),
        ).fetchall()


def lista_toggle(item_id, chat_id, cant_real=None):
    """Alterna entre comprado/pendiente. Guarda cant_real si se provee."""
    with _db() as con:
        row = con.execute(
            "SELECT comprado FROM lista_compras WHERE id=? AND chat_id=?",
            (item_id, str(chat_id)),
        ).fetchone()
        if not row:
            return None
        nuevo = 0 if row["comprado"] else 1
        con.execute(
            "UPDATE lista_compras SET comprado=?, cant_real=?"
            " WHERE id=? AND chat_id=?",
            (nuevo, cant_real if nuevo == 1 else None, item_id, str(chat_id)),
        )
        con.commit()
        return nuevo


def lista_set_cant_real(item_id, chat_id, cant_real):
    with _db() as con:
        con.execute(
            "UPDATE lista_compras SET cant_real=? WHERE id=? AND chat_id=?",
            (cant_real, item_id, str(chat_id)),
        )
        con.commit()


def lista_eliminar(item_id, chat_id):
    with _db() as con:
        con.execute("DELETE FROM lista_compras WHERE id=? AND chat_id=?",
                    (item_id, str(chat_id)))
        con.commit()


def lista_limpiar_comprados(chat_id):
    with _db() as con:
        con.execute(
            "DELETE FROM lista_compras WHERE chat_id=? AND comprado=1",
            (str(chat_id),),
        )
        con.commit()


def lista_actualizar(item_id, chat_id, nombre, marca, unidades, cantidad, comentario):
    with _db() as con:
        con.execute(
            "UPDATE lista_compras SET nombre=?, marca=?, unidades=?, cantidad=?, comentario=?"
            " WHERE id=? AND chat_id=?",
            (nombre, marca, max(1, int(unidades or 1)), cantidad, comentario,
             item_id, str(chat_id)),
        )
        con.commit()


def lista_inventariar(chat_id, items_data, usuario):
    """Convierte ítems comprados en insumos. Soporta múltiples lotes por vencimiento."""
    with _db() as con:
        comprados = con.execute(
            "SELECT * FROM lista_compras WHERE chat_id=? AND comprado=1",
            (str(chat_id),),
        ).fetchall()
        overrides = {int(d["id"]): d for d in (items_data or [])}
        nombres = []
        for item in comprados:
            ov = overrides.get(item["id"], {})
            lotes = ov.get("lotes") or []
            cantidad = item["cant_real"] or item["cantidad"]
            if lotes:
                total = 0
                for lote in lotes:
                    uni = max(1, int(lote.get("unidades") or 1))
                    fv  = lote.get("fecha_vence") or None
                    con.execute(
                        "INSERT INTO insumos"
                        "(chat_id,nombre,marca,unidades,cantidad,fecha_compra,fecha_vence,comentario,agregado_por)"
                        " VALUES(?,?,?,?,?,?,?,?,?)",
                        (str(chat_id), item["nombre"], item["marca"],
                         uni, cantidad, date.today().isoformat(), fv,
                         item["comentario"], usuario),
                    )
                    total += uni
                restante = int(item["unidades"] or 1) - total
                if restante > 0:
                    con.execute(
                        "UPDATE lista_compras SET unidades=?, comprado=0, cant_real=NULL"
                        " WHERE id=? AND chat_id=?",
                        (restante, item["id"], str(chat_id)),
                    )
                else:
                    con.execute(
                        "DELETE FROM lista_compras WHERE id=? AND chat_id=?",
                        (item["id"], str(chat_id)),
                    )
            else:
                con.execute(
                    "INSERT INTO insumos"
                    "(chat_id,nombre,marca,unidades,cantidad,fecha_compra,fecha_vence,comentario,agregado_por)"
                    " VALUES(?,?,?,?,?,?,?,?,?)",
                    (str(chat_id), item["nombre"], item["marca"],
                     max(1, int(item["unidades"] or 1)), cantidad,
                     date.today().isoformat(), None,
                     item["comentario"], usuario),
                )
                con.execute(
                    "DELETE FROM lista_compras WHERE id=? AND chat_id=?",
                    (item["id"], str(chat_id)),
                )
            nombres.append(item["nombre"])
        con.commit()
        return nombres


# ══════════════════════════════════════════════════════════════════════════════
# USUARIOS
# ══════════════════════════════════════════════════════════════════════════════

def crear_usuario(nombre, email=None, password=None, google_id=None,
                  google_avatar=None, telegram_id=None, rol=None):
    pw_hash = generate_password_hash(password) if password else None
    with _db() as con:
        if rol is None:
            count = con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
            rol = 'superadmin' if count == 0 else 'usuario'
        con.execute(
            "INSERT INTO usuarios(nombre,email,password_hash,google_id,"
            "google_avatar,telegram_id,rol) VALUES(?,?,?,?,?,?,?)",
            (nombre, email, pw_hash, google_id, google_avatar,
             str(telegram_id) if telegram_id else None, rol),
        )
        con.commit()
        return con.execute(
            "SELECT * FROM usuarios WHERE rowid=last_insert_rowid()"
        ).fetchone()


def get_usuario_by_id(uid):
    with _db() as con:
        return con.execute("SELECT * FROM usuarios WHERE id=?", (uid,)).fetchone()


def get_usuario_by_email(email):
    with _db() as con:
        return con.execute(
            "SELECT * FROM usuarios WHERE email=? COLLATE NOCASE", (email,)
        ).fetchone()


def get_usuario_by_google_id(gid):
    with _db() as con:
        return con.execute(
            "SELECT * FROM usuarios WHERE google_id=?", (gid,)
        ).fetchone()


def get_usuario_by_telegram_id(tid):
    with _db() as con:
        return con.execute(
            "SELECT * FROM usuarios WHERE telegram_id=?", (str(tid),)
        ).fetchone()


def verificar_password(row, password):
    if not row or not row["password_hash"]:
        return False
    return check_password_hash(row["password_hash"], password)


def listar_usuarios():
    with _db() as con:
        return con.execute(
            "SELECT * FROM usuarios ORDER BY rol ASC, nombre ASC"
        ).fetchall()


def update_usuario(uid, **kwargs):
    allowed = {"nombre", "apellido", "rol", "activo", "google_avatar", "email"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values())
    with _db() as con:
        con.execute(f"UPDATE usuarios SET {sets} WHERE id=?", (*vals, uid))
        con.commit()


def delete_usuario(uid):
    with _db() as con:
        con.execute("DELETE FROM sesiones WHERE usuario_id=?", (uid,))
        con.execute("DELETE FROM vivienda_usuarios WHERE usuario_id=?", (uid,))
        con.execute("DELETE FROM usuarios WHERE id=?", (uid,))
        con.commit()


# ══════════════════════════════════════════════════════════════════════════════
# SESIONES
# ══════════════════════════════════════════════════════════════════════════════

def crear_sesion(usuario_id):
    token = secrets.token_urlsafe(32)
    with _db() as con:
        con.execute("INSERT INTO sesiones(token,usuario_id) VALUES(?,?)",
                    (token, usuario_id))
        con.commit()
    return token


def get_usuario_desde_token(token):
    if not token:
        return None
    with _db() as con:
        return con.execute(
            "SELECT u.* FROM usuarios u"
            " JOIN sesiones s ON s.usuario_id=u.id"
            " WHERE s.token=? AND u.activo=1",
            (token,),
        ).fetchone()


def delete_sesion(token):
    with _db() as con:
        con.execute("DELETE FROM sesiones WHERE token=?", (token,))
        con.commit()


# ══════════════════════════════════════════════════════════════════════════════
# VIVIENDAS
# ══════════════════════════════════════════════════════════════════════════════

def crear_vivienda(nombre, descripcion=None, owner_id=None):
    chat_id = str(uuid.uuid4())
    with _db() as con:
        con.execute(
            "INSERT INTO viviendas(nombre,chat_id,descripcion) VALUES(?,?,?)",
            (nombre, chat_id, descripcion),
        )
        vid = con.execute(
            "SELECT id FROM viviendas WHERE chat_id=?", (chat_id,)
        ).fetchone()["id"]
        if owner_id:
            con.execute(
                "INSERT INTO vivienda_usuarios(vivienda_id,usuario_id,rol,estado)"
                " VALUES(?,?,?,?)",
                (vid, owner_id, "moderador", "activo"),
            )
        con.commit()
    return vid, chat_id


def get_vivienda_by_id(vid):
    with _db() as con:
        return con.execute(
            "SELECT * FROM viviendas WHERE id=?", (vid,)
        ).fetchone()


def get_vivienda_by_chat_id(chat_id):
    with _db() as con:
        return con.execute(
            "SELECT * FROM viviendas WHERE chat_id=?", (chat_id,)
        ).fetchone()


def listar_todas_viviendas():
    with _db() as con:
        return con.execute(
            "SELECT v.*, COUNT(vu.usuario_id) as n_usuarios"
            " FROM viviendas v"
            " LEFT JOIN vivienda_usuarios vu ON vu.vivienda_id=v.id AND vu.estado='activo'"
            " GROUP BY v.id ORDER BY v.nombre ASC"
        ).fetchall()


def listar_viviendas_usuario(usuario_id):
    with _db() as con:
        return con.execute(
            "SELECT v.*, vu.rol as mi_rol, vu.estado"
            " FROM viviendas v"
            " JOIN vivienda_usuarios vu ON vu.vivienda_id=v.id"
            " WHERE vu.usuario_id=? AND vu.estado='activo'"
            " ORDER BY v.nombre ASC",
            (usuario_id,),
        ).fetchall()


def update_vivienda(vid, nombre=None, descripcion=None):
    with _db() as con:
        if nombre:
            con.execute("UPDATE viviendas SET nombre=? WHERE id=?", (nombre, vid))
        if descripcion is not None:
            con.execute("UPDATE viviendas SET descripcion=? WHERE id=?",
                        (descripcion, vid))
        con.commit()


def delete_vivienda(vid):
    with _db() as con:
        row = con.execute(
            "SELECT chat_id FROM viviendas WHERE id=?", (vid,)
        ).fetchone()
        if row:
            cid = row["chat_id"]
            con.execute("DELETE FROM insumos WHERE chat_id=?", (cid,))
            con.execute("DELETE FROM lista_compras WHERE chat_id=?", (cid,))
        con.execute("DELETE FROM vivienda_usuarios WHERE vivienda_id=?", (vid,))
        con.execute("DELETE FROM invitaciones WHERE vivienda_id=?", (vid,))
        con.execute("DELETE FROM viviendas WHERE id=?", (vid,))
        con.commit()


# ══════════════════════════════════════════════════════════════════════════════
# VIVIENDA-USUARIOS
# ══════════════════════════════════════════════════════════════════════════════

def agregar_usuario_vivienda(vivienda_id, usuario_id, rol="usuario",
                              estado="activo", invitado_por=None):
    with _db() as con:
        try:
            con.execute(
                "INSERT INTO vivienda_usuarios"
                "(vivienda_id,usuario_id,rol,estado,invitado_por) VALUES(?,?,?,?,?)",
                (vivienda_id, usuario_id, rol, estado, invitado_por),
            )
            con.commit()
            return True
        except Exception:
            return False


def listar_usuarios_vivienda(vivienda_id):
    with _db() as con:
        return con.execute(
            "SELECT u.id, u.nombre, u.apellido, u.email, u.google_avatar,"
            "       u.telegram_id, vu.rol, vu.estado, vu.created_at"
            " FROM usuarios u"
            " JOIN vivienda_usuarios vu ON vu.usuario_id=u.id"
            " WHERE vu.vivienda_id=?"
            " ORDER BY vu.estado ASC, u.nombre ASC",
            (vivienda_id,),
        ).fetchall()


def update_vivienda_usuario(vivienda_id, usuario_id, estado=None, rol=None):
    with _db() as con:
        if estado:
            con.execute(
                "UPDATE vivienda_usuarios SET estado=?"
                " WHERE vivienda_id=? AND usuario_id=?",
                (estado, vivienda_id, usuario_id),
            )
        if rol:
            con.execute(
                "UPDATE vivienda_usuarios SET rol=?"
                " WHERE vivienda_id=? AND usuario_id=?",
                (rol, vivienda_id, usuario_id),
            )
        con.commit()


def remove_usuario_vivienda(vivienda_id, usuario_id):
    with _db() as con:
        con.execute(
            "DELETE FROM vivienda_usuarios WHERE vivienda_id=? AND usuario_id=?",
            (vivienda_id, usuario_id),
        )
        con.commit()


def usuario_tiene_acceso(chat_id, usuario_id):
    """True si el usuario tiene acceso activo a la vivienda con ese chat_id."""
    with _db() as con:
        row = con.execute(
            "SELECT 1 FROM vivienda_usuarios vu"
            " JOIN viviendas v ON v.id=vu.vivienda_id"
            " WHERE v.chat_id=? AND vu.usuario_id=? AND vu.estado='activo'",
            (chat_id, usuario_id),
        ).fetchone()
    return row is not None


def es_moderador_vivienda(chat_id, usuario_id):
    with _db() as con:
        row = con.execute(
            "SELECT 1 FROM vivienda_usuarios vu"
            " JOIN viviendas v ON v.id=vu.vivienda_id"
            " WHERE v.chat_id=? AND vu.usuario_id=? AND vu.estado='activo'"
            " AND vu.rol IN ('moderador','superadmin')",
            (chat_id, usuario_id),
        ).fetchone()
    return row is not None


# ══════════════════════════════════════════════════════════════════════════════
# INVITACIONES
# ══════════════════════════════════════════════════════════════════════════════

def crear_invitacion(vivienda_id, creado_por, rol="usuario", email_destino=None):
    token = secrets.token_urlsafe(16)
    expires = (datetime.now() + timedelta(days=7)).isoformat()
    with _db() as con:
        con.execute(
            "INSERT INTO invitaciones"
            "(token,vivienda_id,creado_por,rol,email_destino,expires_at)"
            " VALUES(?,?,?,?,?,?)",
            (token, vivienda_id, creado_por, rol, email_destino, expires),
        )
        con.commit()
    return token


def get_invitacion(token):
    with _db() as con:
        return con.execute(
            "SELECT i.*, v.nombre as vivienda_nombre, v.chat_id, v.id as vid"
            " FROM invitaciones i"
            " JOIN viviendas v ON v.id=i.vivienda_id"
            " WHERE i.token=? AND i.usado=0",
            (token,),
        ).fetchone()


def usar_invitacion(token, usuario_id):
    inv = get_invitacion(token)
    if not inv:
        return None
    if inv["expires_at"] and inv["expires_at"] < datetime.now().isoformat():
        return None
    agregar_usuario_vivienda(
        inv["vivienda_id"], usuario_id,
        rol=inv["rol"], estado="activo",
        invitado_por=inv["creado_por"],
    )
    with _db() as con:
        con.execute("UPDATE invitaciones SET usado=1 WHERE token=?", (token,))
        con.commit()
    return inv
