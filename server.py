"""Servidor local da tier list; utiliza apenas a biblioteca padrão do Python."""

import argparse
import base64
import binascii
import json
import re
import sqlite3
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_REQUEST_BYTES = 14 * 1024 * 1024 + 4096
TIERS = ("S", "A", "B", "C", "D")
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


class APIError(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def position(tier, slot):
    if tier not in TIERS or type(slot) is not int or not 0 <= slot < 8:
        raise APIError(400, "Escolha uma categoria de S a D e uma caixa de 0 a 7.")
    return tier, slot


def image_type(data):
    if len(data) >= 33 and data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR":
        return "image/png"
    if len(data) >= 12 and data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9"):
        return "image/jpeg"
    if len(data) >= 14 and data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(data) >= 20 and data[:4] == b"RIFF" and data[8:12] == b"WEBP" and data[12:16] in (b"VP8 ", b"VP8L", b"VP8X"):
        return "image/webp"
    raise APIError(400, "Formato inválido. Envie uma imagem PNG, JPEG, WebP ou GIF.")


def image_record(row):
    return {"id": row["id"], "name": row["name"], "url": f'/api/images/{row["id"]}',
            "tier": row["tier"], "slot": row["slot"]}


def state(db, board_id=1):
    return {"images": [image_record(row) for row in db.execute(
        "SELECT id, name, tier, slot FROM images WHERE board_id = ? ORDER BY id", (board_id,))]}


def board_id_from(value):
    if type(value) is not int or not 0 < value < 2**63:
        raise APIError(400, "Identificador da tier list inválido.")
    return value


def existing_board(db, value):
    board_id = board_id_from(value)
    if db.execute("SELECT 1 FROM boards WHERE id = ?", (board_id,)).fetchone() is None:
        raise APIError(404, "Tier list não encontrada.")
    return board_id


def board_record(row):
    return {"id": row["id"], "name": row["name"]}


def board_list(db):
    return {"boards": [board_record(row) for row in db.execute("SELECT id,name FROM boards ORDER BY id")]}


class TierServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, db_path):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute("PRAGMA foreign_keys = ON")
            with db:
                db.execute("""CREATE TABLE IF NOT EXISTS boards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL
                )""")
                db.execute("INSERT OR IGNORE INTO boards(id,name) VALUES(1,'Minha tier list')")
                old_images = db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'images'").fetchone()
                if old_images and not any(column[1] == "board_id" for column in db.execute("PRAGMA table_info(images)")):
                    # Preserve the old ranking and its image bytes as the first board.
                    db.execute("""CREATE TABLE images_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        board_id INTEGER NOT NULL REFERENCES boards(id),
                        name TEXT NOT NULL, mime TEXT NOT NULL, data BLOB NOT NULL,
                        tier TEXT, slot INTEGER,
                        CHECK ((tier IS NULL AND slot IS NULL) OR
                               (tier IN ('S','A','B','C','D') AND slot BETWEEN 0 AND 7)),
                        UNIQUE (board_id, tier, slot)
                    )""")
                    db.execute("""INSERT INTO images_new(id,board_id,name,mime,data,tier,slot)
                        SELECT id,1,name,mime,data,tier,slot FROM images""")
                    db.execute("DROP TABLE images")
                    db.execute("ALTER TABLE images_new RENAME TO images")
                else:
                    db.execute("""CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER NOT NULL REFERENCES boards(id),
                name TEXT NOT NULL,
                mime TEXT NOT NULL,
                data BLOB NOT NULL,
                tier TEXT,
                slot INTEGER,
                CHECK ((tier IS NULL AND slot IS NULL) OR
                       (tier IS NOT NULL AND slot IS NOT NULL AND
                        tier IN ('S','A','B','C','D') AND slot BETWEEN 0 AND 7)),
                UNIQUE (board_id, tier, slot)
            )""")
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "TierList/1.0"

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def reply(self, status, data, mime="application/json; charset=utf-8"):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' blob:; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(data)

    def check_source(self):
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if port == 80:
            hosts.update({"localhost", "127.0.0.1"})
        host = self.headers.get("Host", "").lower()
        if host not in hosts:
            raise APIError(403, "Este servidor aceita apenas acesso local.")
        origin = self.headers.get("Origin")
        if origin is not None and origin != f"http://{host}":
            raise APIError(403, "Origem da requisição não permitida.")
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise APIError(403, "Origem da requisição não permitida.")

    def read_json(self):
        if self.headers.get("Transfer-Encoding"):
            raise APIError(400, "Use um corpo JSON com tamanho definido.")
        if self.headers.get_content_type() != "application/json":
            raise APIError(415, "Envie os dados no formato JSON.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise APIError(400, "Tamanho da requisição inválido.") from None
        if length <= 0:
            raise APIError(400, "O corpo da requisição está vazio.")
        if length > MAX_REQUEST_BYTES:
            raise APIError(413, "A foto deve ter no máximo 10 MB.")
        try:
            body = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeError, RecursionError):
            raise APIError(400, "JSON inválido.") from None
        if not isinstance(body, dict):
            raise APIError(400, "Envie um objeto JSON.")
        return body

    def current_board(self, db):
        query = parse_qs(urlsplit(self.path).query)
        ids = query.get("boardId")
        if ids is None:
            return existing_board(db, 1)
        if len(ids) != 1 or not ids[0].isdigit():
            raise APIError(400, "Identificador da tier list inválido.")
        return existing_board(db, int(ids[0]))

    def dispatch(self):
        db = None
        try:
            self.check_source()
            path = urlsplit(self.path).path
            if self.command == "GET" and path in STATIC:
                filename, mime = STATIC[path]
                self.reply(200, (ROOT / filename).read_bytes(), mime)
                return
            db = sqlite3.connect(self.server.db_path, timeout=15)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            if self.command == "GET" and path == "/api/state":
                self.reply(200, state(db, self.current_board(db)))
            elif self.command == "GET" and path == "/api/boards":
                self.reply(200, board_list(db))
            elif self.command == "POST" and path == "/api/boards":
                self.create_board(db)
            elif self.command == "DELETE" and (match := re.fullmatch(r"/api/boards/([0-9]+)", path)):
                self.delete_board(db, int(match[1]))
            elif self.command == "GET" and (match := re.fullmatch(r"/api/images/([0-9]+)", path)):
                image = db.execute("SELECT mime, data FROM images WHERE id = ?", (match[1],)).fetchone()
                if image is None:
                    raise APIError(404, "Foto não encontrada.")
                self.reply(200, image["data"], image["mime"])
            elif self.command == "DELETE" and (match := re.fullmatch(r"/api/images/([0-9]+)", path)):
                board_id = self.current_board(db)
                db.execute("BEGIN IMMEDIATE")
                cursor = db.execute("DELETE FROM images WHERE id = ? AND board_id = ?", (match[1], board_id))
                if cursor.rowcount == 0:
                    raise APIError(404, "Foto não encontrada nesta tier list.")
                result = state(db, board_id)
                db.commit()
                self.reply(200, result)
            elif self.command == "POST" and path == "/api/images":
                self.upload(db)
            elif self.command == "PUT" and path == "/api/slots":
                self.move(db)
            elif self.command == "DELETE" and (match := re.fullmatch(r"/api/slots/([^/]+)/([0-9]+)", path)):
                tier, slot = position(match[1], int(match[2]))
                board_id = self.current_board(db)
                db.execute("BEGIN IMMEDIATE")
                db.execute("UPDATE images SET tier = NULL, slot = NULL WHERE board_id = ? AND tier = ? AND slot = ?", (board_id, tier, slot))
                result = state(db, board_id)
                db.commit()
                self.reply(200, result)
            else:
                raise APIError(404, "Endereço não encontrado.")
        except APIError as error:
            self.reply(error.status, {"error": str(error)})
        except (sqlite3.Error, OSError):
            self.reply(500, {"error": "Não foi possível ler ou salvar os dados. Verifique o espaço e as permissões da pasta."})
        except (ValueError, OverflowError):
            self.reply(400, {"error": "Dados inválidos na requisição."})
        finally:
            if db is not None:
                db.close()

    def upload(self, db):
        body = self.read_json()
        name, encoded = body.get("name"), body.get("data")
        if not isinstance(name, str) or not name.strip() or len(name) > 255 or any(ord(c) < 32 for c in name):
            raise APIError(400, "Informe um nome de foto válido com até 255 caracteres.")
        if not isinstance(encoded, str):
            raise APIError(400, "Envie os dados da foto em base64.")
        if len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
            raise APIError(413, "A foto deve ter no máximo 10 MB.")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise APIError(400, "Os dados da foto são inválidos.") from None
        if len(data) > MAX_IMAGE_BYTES:
            raise APIError(413, "A foto deve ter no máximo 10 MB.")
        mime = image_type(data)
        tier, slot = body.get("tier"), body.get("slot")
        if tier is not None or slot is not None:
            position(tier, slot)
        board_id = existing_board(db, body.get("boardId", 1))
        db.execute("BEGIN IMMEDIATE")
        if tier is not None:
            db.execute("UPDATE images SET tier = NULL, slot = NULL WHERE board_id = ? AND tier = ? AND slot = ?", (board_id, tier, slot))
        cursor = db.execute("INSERT INTO images (board_id,name,mime,data,tier,slot) VALUES (?,?,?,?,?,?)",
                            (board_id, name.strip(), mime, data, tier, slot))
        row = db.execute("SELECT id,name,tier,slot FROM images WHERE id = ?", (cursor.lastrowid,)).fetchone()
        db.commit()
        self.reply(201, {"image": image_record(row)})

    def move(self, db):
        body = self.read_json()
        tier, slot = position(body.get("tier"), body.get("slot"))
        board_id = existing_board(db, body.get("boardId", 1))
        image_id = body.get("imageId")
        if type(image_id) is not int or not 0 < image_id < 2**63:
            raise APIError(400, "Identificador da foto inválido.")
        db.execute("BEGIN IMMEDIATE")
        source = db.execute("SELECT tier,slot FROM images WHERE id = ? AND board_id = ?", (image_id, board_id)).fetchone()
        if source is None:
            raise APIError(404, "Foto não encontrada nesta tier list.")
        occupant = db.execute("SELECT id FROM images WHERE board_id = ? AND tier = ? AND slot = ?", (board_id, tier, slot)).fetchone()
        if occupant is None or occupant["id"] != image_id:
            db.execute("UPDATE images SET tier = NULL, slot = NULL WHERE id = ?", (image_id,))
            if occupant is not None:
                db.execute("UPDATE images SET tier = ?, slot = ? WHERE id = ?", (source["tier"], source["slot"], occupant["id"]))
            db.execute("UPDATE images SET tier = ?, slot = ? WHERE id = ?", (tier, slot, image_id))
        result = state(db, board_id)
        db.commit()
        self.reply(200, result)

    def create_board(self, db):
        name = self.read_json().get("name")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60 or any(ord(c) < 32 for c in name):
            raise APIError(400, "Dê um nome à tier list com até 60 caracteres.")
        db.execute("BEGIN IMMEDIATE")
        cursor = db.execute("INSERT INTO boards(name) VALUES(?)", (name.strip(),))
        board = db.execute("SELECT id,name FROM boards WHERE id = ?", (cursor.lastrowid,)).fetchone()
        db.commit()
        self.reply(201, {"board": board_record(board)})

    def delete_board(self, db, board_id):
        board_id = existing_board(db, board_id)
        if board_id == 1:
            raise APIError(409, "A primeira tier list é protegida e não pode ser excluída.")
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM images WHERE board_id = ?", (board_id,))
        db.execute("DELETE FROM boards WHERE id = ?", (board_id,))
        db.commit()
        self.reply(200, board_list(db))

    do_GET = dispatch
    do_POST = dispatch
    do_PUT = dispatch
    do_DELETE = dispatch


def create_server(host="127.0.0.1", port=8006, db_path=None):
    if host != "127.0.0.1":
        raise ValueError("Use 127.0.0.1 para manter o servidor local.")
    return TierServer((host, port), db_path or ROOT / "data" / "tierlist.sqlite3")


def main():
    parser = argparse.ArgumentParser(description="Tier list resenhuda com SQLite")
    parser.add_argument("--port", type=int, default=8006)
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "tierlist.sqlite3")
    args = parser.parse_args()
    try:
        server = create_server(port=args.port, db_path=args.db)
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.exit(1, f"Não foi possível iniciar o servidor: {error}\nTente outra porta com --port 8001.\n")
    print(f"Abra http://127.0.0.1:{server.server_port}", flush=True)
    print(f"Banco de dados: {server.db_path}\nPressione Ctrl+C para encerrar.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
