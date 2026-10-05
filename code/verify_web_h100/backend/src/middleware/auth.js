import { getSession } from "../data/auth.js";

export function bearerToken(req) {
  const match = String(req.get("authorization") || "").match(/^Bearer\s+(.+)$/i);
  return match?.[1] || "";
}

export function requireAuth(req, res, next) {
  const user = getSession(bearerToken(req));
  if (!user) return res.status(401).json({ error: "Phiên đăng nhập không hợp lệ hoặc đã hết hạn." });
  req.user = user;
  next();
}

export function requireAdmin(req, res, next) {
  if (req.user?.role !== "admin") {
    return res.status(403).json({ error: "Chỉ quản trị viên được thực hiện thao tác này." });
  }
  next();
}
