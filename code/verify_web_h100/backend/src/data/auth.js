import crypto from "node:crypto";

import { readDocuments, saveDocument } from "./database.js";
const SESSION_TTL_MS = 12 * 60 * 60 * 1000;
const sessions = new Map();
function readUsers() { return Object.values(readDocuments("users")); }
function writeUsers(users) {
  for (const user of users) saveDocument("users", user.username, user);
}

function normalizeUsername(value) {
  return String(value || "").trim().toLocaleLowerCase("vi");
}

function passwordHash(password, salt = crypto.randomBytes(16).toString("hex")) {
  const hash = crypto.scryptSync(String(password), salt, 64).toString("hex");
  return { salt, hash };
}

function publicUser(user) {
  return { username: user.username, role: user.role, created_at: user.created_at };
}

export function initializeAdmin() {
  const users = readUsers();
  if (users.length) return;
  const username = normalizeUsername(process.env.ADMIN_USERNAME);
  const password = String(process.env.ADMIN_PASSWORD || "");
  if (!username || password.length < 12) {
    throw new Error("Chưa có tài khoản. Hãy cấu hình ADMIN_USERNAME và ADMIN_PASSWORD (ít nhất 12 ký tự).");
  }
  const passwordData = passwordHash(password);
  writeUsers([{
    username,
    role: "admin",
    password_salt: passwordData.salt,
    password_hash: passwordData.hash,
    created_at: new Date().toISOString(),
  }]);
  console.log(`Đã khởi tạo tài khoản quản trị: ${username}`);
}

export function authenticate(username, password) {
  const user = readUsers().find((item) => item.username === normalizeUsername(username));
  if (!user) return null;
  const candidate = Buffer.from(passwordHash(password, user.password_salt).hash, "hex");
  const expected = Buffer.from(user.password_hash, "hex");
  if (candidate.length !== expected.length || !crypto.timingSafeEqual(candidate, expected)) return null;
  return publicUser(user);
}

export function createSession(user) {
  const token = crypto.randomBytes(32).toString("base64url");
  sessions.set(token, { user, expiresAt: Date.now() + SESSION_TTL_MS });
  return token;
}

export function getSession(token) {
  const session = sessions.get(token);
  if (!session) return null;
  if (session.expiresAt <= Date.now()) {
    sessions.delete(token);
    return null;
  }
  return session.user;
}

export function deleteSession(token) {
  sessions.delete(token);
}

export function listUsers() {
  return readUsers().map(publicUser).sort((left, right) => left.username.localeCompare(right.username, "vi"));
}

export function createUser({ username, password, role = "reviewer" }) {
  const normalized = normalizeUsername(username);
  if (!/^[\p{L}\p{N}._-]{3,50}$/u.test(normalized)) {
    const error = new Error("Tên đăng nhập phải dài 3–50 ký tự và chỉ gồm chữ, số, dấu chấm, gạch dưới hoặc gạch ngang.");
    error.status = 400;
    throw error;
  }
  if (String(password || "").length < 12) {
    const error = new Error("Mật khẩu phải có ít nhất 12 ký tự.");
    error.status = 400;
    throw error;
  }
  if (!["admin", "reviewer"].includes(role)) {
    const error = new Error("Vai trò không hợp lệ.");
    error.status = 400;
    throw error;
  }
  const users = readUsers();
  if (users.some((item) => item.username === normalized)) {
    const error = new Error("Tên đăng nhập đã tồn tại.");
    error.status = 409;
    throw error;
  }
  const passwordData = passwordHash(password);
  const user = {
    username: normalized,
    role,
    password_salt: passwordData.salt,
    password_hash: passwordData.hash,
    created_at: new Date().toISOString(),
  };
  writeUsers([...users, user]);
  return publicUser(user);
}
