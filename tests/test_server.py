import base64
import http.client
import json
import sqlite3
import struct
import tempfile
import threading
import unittest
import zlib
from contextlib import closing
from pathlib import Path

from server import MAX_REQUEST_BYTES, create_server


def png(red=185, green=54, blue=54):
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    pixels = (b'\0' + bytes([red, green, blue]) * 64) * 64
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 64, 64, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db_path = Path(self.directory.name) / 'test.sqlite3'
        self.start_server()

    def start_server(self):
        self.server = create_server(port=0, db_path=self.db_path)
        self.server.RequestHandlerClass.log_message = lambda *args: None
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def tearDown(self):
        self.stop_server()
        self.directory.cleanup()

    def request(self, method, path, body=None, headers=None, raw=False):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        payload = json.dumps(body).encode() if body is not None and not raw else body
        connection.request(method, path, body=payload,
                           headers=headers or {'Content-Type': 'application/json'})
        response = connection.getresponse()
        data = response.read()
        status, mime = response.status, response.getheader('Content-Type')
        connection.close()
        return status, json.loads(data) if 'application/json' in mime else data, mime

    def upload(self, name='foto.png', **location):
        status, result, _ = self.request('POST', '/api/images', {
            'name': name, 'data': base64.b64encode(png()).decode(), **location})
        self.assertEqual(status, 201, result)
        return result['image']

    def move(self, image, tier, slot):
        status, result, _ = self.request('PUT', '/api/slots', {'imageId': image['id'], 'tier': tier, 'slot': slot})
        self.assertEqual(status, 200, result)
        return {entry['id']: entry for entry in result['images']}

    def test_upload_bytes_and_restart_persistence(self):
        image = self.upload('ação.png', tier='S', slot=7)
        status, data, mime = self.request('GET', image['url'])
        self.assertEqual((status, data, mime), (200, png(), 'image/png'))
        self.stop_server()
        self.start_server()
        status, result, _ = self.request('GET', '/api/state')
        self.assertEqual(status, 200)
        self.assertEqual(result['images'], [image])
        with closing(sqlite3.connect(self.db_path)) as db:
            self.assertEqual(db.execute('SELECT data FROM images').fetchone()[0], png())

    def test_swaps_and_return_to_library(self):
        one = self.upload(tier='S', slot=0)
        two = self.upload('outra.png', tier='B', slot=2)
        state = self.move(one, 'B', 2)
        self.assertEqual((state[two['id']]['tier'], state[two['id']]['slot']), ('S', 0))
        self.assertEqual((state[one['id']]['tier'], state[one['id']]['slot']), ('B', 2))
        # Moving onto oneself is a no-op.
        self.assertEqual(self.move(one, 'B', 2), state)
        three = self.upload('nova.png')
        state = self.move(three, 'B', 2)
        self.assertIsNone(state[one['id']]['tier'])
        status, result, _ = self.request('DELETE', '/api/slots/B/2')
        self.assertEqual(status, 200)
        self.assertIsNone(next(item for item in result['images'] if item['id'] == three['id'])['tier'])
        self.assertEqual(self.request('GET', three['url'])[1], png())

    def test_direct_import_releases_previous_photo(self):
        one = self.upload(tier='A', slot=1)
        two = self.upload(tier='A', slot=1)
        _, result, _ = self.request('GET', '/api/state')
        state = {item['id']: item for item in result['images']}
        self.assertIsNone(state[one['id']]['tier'])
        self.assertEqual(state[two['id']]['tier'], 'A')

    def test_separate_boards_and_permanent_photo_deletion(self):
        first = self.upload('primeira.png', tier='S', slot=0)
        status, created, _ = self.request('POST', '/api/boards', {'name': 'Melhores jogos'})
        self.assertEqual(status, 201)
        second_board = created['board']['id']
        self.assertNotEqual(second_board, 1)
        status, uploaded, _ = self.request('POST', '/api/images', {
            'boardId': second_board, 'name': 'outra.png',
            'data': base64.b64encode(png()).decode(), 'tier': 'S', 'slot': 0})
        self.assertEqual(status, 201)
        second = uploaded['image']
        self.assertEqual(self.request('GET', '/api/state?boardId=1')[1]['images'], [first])
        self.assertEqual(self.request('GET', f'/api/state?boardId={second_board}')[1]['images'], [second])
        self.assertEqual(self.request('PUT', '/api/slots', {
            'boardId': second_board, 'imageId': first['id'], 'tier': 'A', 'slot': 0})[0], 404)
        self.assertEqual(self.request('DELETE', f'/api/images/{first["id"]}?boardId={second_board}')[0], 404)
        self.assertEqual(self.request('DELETE', f'/api/images/{second["id"]}?boardId={second_board}')[0], 200)
        self.assertEqual(self.request('GET', second['url'])[0], 404)
        self.assertEqual(self.request('GET', '/api/state?boardId=1')[1]['images'], [first])
        self.stop_server()
        self.start_server()
        self.assertEqual(self.request('GET', '/api/boards')[1]['boards'], [
            {'id': 1, 'name': 'Minha tier list'}, created['board']])
        self.assertEqual(self.request('GET', f'/api/state?boardId={second_board}')[1]['images'], [])

    def test_migrates_existing_database_without_losing_photos(self):
        self.stop_server()
        self.db_path.unlink()
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute('''CREATE TABLE images (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                mime TEXT NOT NULL, data BLOB NOT NULL, tier TEXT, slot INTEGER,
                UNIQUE(tier,slot))''')
            db.execute('INSERT INTO images(name,mime,data,tier,slot) VALUES (?,?,?,?,?)',
                       ('antiga.png', 'image/png', png(), 'B', 3))
            db.commit()
        self.start_server()
        state = self.request('GET', '/api/state?boardId=1')[1]['images']
        self.assertEqual((state[0]['name'], state[0]['tier'], state[0]['slot']), ('antiga.png', 'B', 3))
        self.assertEqual(self.request('GET', state[0]['url'])[1], png())
        self.assertEqual(self.request('GET', '/api/boards')[1]['boards'][0]['name'], 'Minha tier list')

    def test_rejects_invalid_board_and_name(self):
        for name in ['', ' ', 'x' * 61, 3]:
            self.assertEqual(self.request('POST', '/api/boards', {'name': name})[0], 400)
        self.assertEqual(self.request('GET', '/api/state?boardId=999')[0], 404)
        self.assertEqual(self.request('GET', '/api/state?boardId=abc')[0], 400)
        self.assertEqual(self.request('POST', '/api/images', {
            'boardId': 999, 'name': 'x.png', 'data': base64.b64encode(png()).decode()})[0], 404)

    def test_invalid_requests_do_not_change_database(self):
        image = self.upload(tier='D', slot=0)
        for tier, slot, image_id in [('Z', 0, image['id']), ('S', 8, image['id']),
                                     ('A', -1, image['id']), ('S', True, image['id']),
                                     ([], 0, image['id']), ('S', 1, True), ('S', 1, 2**70)]:
            with self.subTest(tier=tier, slot=slot, image_id=image_id):
                self.assertEqual(self.request('PUT', '/api/slots', {
                    'imageId': image_id, 'tier': tier, 'slot': slot})[0], 400)
        self.assertEqual(self.request('PUT', '/api/slots', {'imageId': 999, 'tier': 'S', 'slot': 0})[0], 404)
        for body in [[], {}, {'name': 'a', 'data': '%%%invalid'}, {'name': 'a', 'data': 'SGVsbG8='},
                     {'name': '', 'data': base64.b64encode(png()).decode()}]:
            self.assertEqual(self.request('POST', '/api/images', body)[0], 400)
        self.assertEqual(self.request('POST', '/api/images', b'{broken', raw=True)[0], 400)
        self.assertEqual(self.request('GET', '/api/state')[1]['images'], [image])

    def test_limits_origins_and_static_allowlist(self):
        self.assertEqual(self.request('POST', '/api/images', b'', raw=True,
            headers={'Content-Type': 'application/json', 'Content-Length': str(MAX_REQUEST_BYTES + 1)})[0], 413)
        self.assertEqual(self.request('POST', '/api/images', {}, headers={'Content-Type': 'text/plain'})[0], 415)
        self.assertEqual(self.request('GET', '/api/state', headers={'Origin': 'https://example.com'})[0], 403)
        self.assertEqual(self.request('GET', '/api/state', headers={'Host': 'example.com'})[0], 403)
        origin = f'http://127.0.0.1:{self.server.server_port}'
        self.assertEqual(self.request('GET', '/api/state', headers={'Origin': origin})[0], 200)
        for path in ['/server.py', '/data/tierlist.sqlite3', '/../server.py', '/%2e%2e/server.py', '/api/images/999']:
            self.assertEqual(self.request('GET', path)[0], 404, path)
        for path in ['/', '/app.js', '/style.css']:
            self.assertEqual(self.request('GET', path)[0], 200, path)


if __name__ == '__main__':
    unittest.main()
