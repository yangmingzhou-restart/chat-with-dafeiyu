"""Local persistence and Windows-user-bound credentials. Never returns saved keys to UI."""
import base64
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sqlite3
import time
import uuid

from .studio_config import ChatSettings, ROOT


def protect(value: str, decrypt=False):
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    data = base64.b64decode(value) if decrypt else value.encode('utf-8')
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.windll.crypt32
    if decrypt:
        ok = crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    else:
        ok = crypt.CryptProtectData(ctypes.byref(source), 'DAFE voice studio', None, None, None, 1, ctypes.byref(target))
    if not ok:
        raise RuntimeError('Windows凭据加解密失败')
    try:
        result = ctypes.string_at(target.data, target.size)
        return result.decode('utf-8') if decrypt else base64.b64encode(result).decode('ascii')
    finally:
        ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


class Store:
    def __init__(self, path=None):
        path = Path(path or ROOT / '.private/studio.sqlite3')
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,name TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS chats(id TEXT PRIMARY KEY,title TEXT NOT NULL,project TEXT REFERENCES projects(id),
                config TEXT NOT NULL,summary TEXT NOT NULL DEFAULT '',covered INTEGER NOT NULL DEFAULT 0,updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT,chat TEXT REFERENCES chats(id),
                turn TEXT NOT NULL,role TEXT NOT NULL,content TEXT NOT NULL,state TEXT NOT NULL,created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS message_chat ON messages(chat,id);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS connections(id TEXT PRIMARY KEY,config TEXT NOT NULL,secret TEXT);
        ''')
        if self.get('defaults') is None:
            self.put('defaults', ChatSettings().model_dump())
        if not self.db.execute('SELECT 1 FROM connections WHERE id=?', ('deepseek',)).fetchone():
            key_path = ROOT / '.private/deepseek.key'
            key = key_path.read_text(encoding='utf-8-sig').strip() if key_path.exists() else ''
            self.save_connection('deepseek', dict(name='DeepSeek', preset='deepseek', kinds=['llm'],
                base_url='https://api.deepseek.com/v1', api_key=key))
        if not self.chats():
            chat = self.create_chat('和大肥鱼聊聊')
            self.put('active', chat['id'])
        # Interrupted responses never masquerade as finished context after a restart.
        self.db.execute("UPDATE messages SET state='interrupted' WHERE state='streaming'")
        self.db.commit()

    def get(self, key):
        row = self.db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, json.dumps(value, ensure_ascii=False)))

    def projects(self):
        return [dict(r) for r in self.db.execute('SELECT * FROM projects ORDER BY name')]

    def project(self, name, id=None):
        id = id or uuid.uuid4().hex
        with self.db:
            self.db.execute('INSERT INTO projects VALUES(?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name', (id, name))
        return id

    def chats(self):
        return [dict(r) for r in self.db.execute('SELECT id,title,project,updated FROM chats ORDER BY updated DESC')]

    def chat(self, id):
        row = self.db.execute('SELECT * FROM chats WHERE id=?', (id,)).fetchone()
        if not row:
            raise KeyError('对话不存在')
        result = dict(row)
        result['config'] = json.loads(result['config'])
        result['messages'] = [dict(m) for m in self.db.execute('SELECT * FROM messages WHERE chat=? ORDER BY id', (id,))]
        return result

    def create_chat(self, title='新对话', project=None):
        id = uuid.uuid4().hex
        with self.db:
            self.db.execute('INSERT INTO chats(id,title,project,config,updated) VALUES(?,?,?,?,?)',
                            (id, title, project, json.dumps(self.get('defaults'), ensure_ascii=False), time.time()))
        return self.chat(id)

    def update_chat(self, id, *, title=None, project=..., config=None):
        self.chat(id)
        with self.db:
            if title is not None:
                self.db.execute('UPDATE chats SET title=? WHERE id=?', (title, id))
            if project is not ...:
                self.db.execute('UPDATE chats SET project=? WHERE id=?', (project, id))
            if config is not None:
                self.db.execute('UPDATE chats SET config=? WHERE id=?', (json.dumps(config, ensure_ascii=False), id))
            self.db.execute('UPDATE chats SET updated=? WHERE id=?', (time.time(), id))

    def message(self, chat, turn, role, content='', state='complete'):
        with self.db:
            cursor = self.db.execute('INSERT INTO messages(chat,turn,role,content,state,created) VALUES(?,?,?,?,?,?)',
                                     (chat, turn, role, content, state, time.time()))
            self.db.execute('UPDATE chats SET updated=? WHERE id=?', (time.time(), chat))
        return cursor.lastrowid

    def update_message(self, id, content, state):
        with self.db:
            self.db.execute('UPDATE messages SET content=?,state=? WHERE id=?', (content, state, id))

    def summary(self, chat, content, covered):
        with self.db:
            self.db.execute('UPDATE chats SET summary=?,covered=? WHERE id=?', (content, covered, chat))

    def save_connection(self, id, config):
        config = dict(config)
        key = config.pop('api_key', None)
        old = self.db.execute('SELECT secret FROM connections WHERE id=?', (id,)).fetchone()
        secret = protect(key) if key else (old[0] if old else None)
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO connections VALUES(?,?,?)', (id, json.dumps(config), secret))

    def connections(self):
        return [dict(id=r['id'], **json.loads(r['config']), has_key=bool(r['secret']))
                for r in self.db.execute('SELECT * FROM connections')]

    def connection(self, id):
        row = self.db.execute('SELECT * FROM connections WHERE id=?', (id,)).fetchone()
        if not row:
            raise ValueError('请先配置模型连接')
        return dict(json.loads(row['config']), api_key=protect(row['secret'], True) if row['secret'] else '')
