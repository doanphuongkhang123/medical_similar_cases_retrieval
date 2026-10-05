import { Router } from "express";
import {
  authenticate, createSession, createUser, deleteSession, listUsers,
} from "../data/auth.js";
import { bearerToken, requireAdmin, requireAuth } from "../middleware/auth.js";

const router = Router();

router.post("/login", (req, res) => {
  const user = authenticate(req.body?.username, req.body?.password);
  if (!user) return res.status(401).json({ error: "Tên đăng nhập hoặc mật khẩu không đúng." });
  res.json({ token: createSession(user), user });
});

router.get("/me", requireAuth, (req, res) => res.json({ user: req.user }));

router.post("/logout", requireAuth, (req, res) => {
  deleteSession(bearerToken(req));
  res.status(204).end();
});

router.get("/users", requireAuth, requireAdmin, (req, res) => res.json({ users: listUsers() }));

router.post("/users", requireAuth, requireAdmin, (req, res, next) => {
  try {
    const user = createUser(req.body || {});
    res.status(201).json({ user });
  } catch (error) {
    next(error);
  }
});

export default router;
