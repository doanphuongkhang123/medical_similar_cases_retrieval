import { DatabaseSync } from 'node:sqlite';
import fs from 'node:fs';
import path from 'node:path';

export const DATA_DIR = process.env.DATA_DIR || path.resolve('data');
fs.mkdirSync(DATA_DIR, { recursive: true });
export const db = new DatabaseSync(path.join(DATA_DIR, 'review.sqlite3'));
db.exec(`
  PRAGMA journal_mode=WAL;
  PRAGMA synchronous=FULL;
  PRAGMA busy_timeout=5000;
  CREATE TABLE IF NOT EXISTS documents (
    namespace TEXT NOT NULL, key TEXT NOT NULL, payload TEXT NOT NULL,
    PRIMARY KEY(namespace, key)
  );
  CREATE TABLE IF NOT EXISTS review_history (
    id INTEGER PRIMARY KEY, namespace TEXT NOT NULL, key TEXT NOT NULL,
    reviewer TEXT NOT NULL, payload TEXT NOT NULL, at TEXT NOT NULL
  );
  CREATE TABLE IF NOT EXISTS migrations (name TEXT PRIMARY KEY);
`);

export function readDocuments(namespace) {
  return Object.fromEntries(db.prepare('SELECT key, payload FROM documents WHERE namespace=?')
    .all(namespace).map(row => [row.key, JSON.parse(row.payload)]));
}
export function readDocument(namespace, key) {
  const row = db.prepare('SELECT payload FROM documents WHERE namespace=? AND key=?').get(namespace, key);
  return row ? JSON.parse(row.payload) : null;
}
export function saveDocument(namespace, key, value, history = false) {
  db.exec('BEGIN IMMEDIATE');
  try {
    const payload = JSON.stringify(value);
    db.prepare('INSERT INTO documents VALUES(?,?,?) ON CONFLICT(namespace,key) DO UPDATE SET payload=excluded.payload')
      .run(namespace, key, payload);
    if (history) db.prepare('INSERT INTO review_history(namespace,key,reviewer,payload,at) VALUES(?,?,?,?,?)')
      .run(namespace, key, value.reviewer || 'unknown', payload, value.at || new Date().toISOString());
    db.exec('COMMIT');
  } catch (error) { db.exec('ROLLBACK'); throw error; }
  return value;
}

// A malformed legacy file fails loudly. Original JSON files stay untouched.
for (const [filename, namespace, array] of [
  ['users.json', 'users', true], ['verifications.json', 'reviews', false],
  ['llm-retrieval-verifications.json', 'llm_reviews', false],
]) {
  const source = path.join(DATA_DIR, filename);
  if (!fs.existsSync(source) || db.prepare('SELECT name FROM migrations WHERE name=?').get(filename)) continue;
  const parsed = JSON.parse(fs.readFileSync(source, 'utf8'));
  if (array ? !Array.isArray(parsed) : (!parsed || typeof parsed !== 'object' || Array.isArray(parsed))) {
    throw new Error(`Invalid legacy store: ${filename}`);
  }
  const entries = array ? parsed.map(user => [user.username, user]) : Object.entries(parsed);
  db.exec('BEGIN IMMEDIATE');
  try {
    for (const [key, value] of entries) {
      db.prepare('INSERT OR IGNORE INTO documents VALUES(?,?,?)').run(namespace, key, JSON.stringify(value));
      if (namespace !== 'users') db.prepare('INSERT INTO review_history(namespace,key,reviewer,payload,at) VALUES(?,?,?,?,?)')
        .run(namespace, key, value.reviewer || 'unknown', JSON.stringify(value), value.at || new Date().toISOString());
    }
    db.prepare('INSERT INTO migrations VALUES(?)').run(filename);
    db.exec('COMMIT');
  } catch (error) { db.exec('ROLLBACK'); throw error; }
}
