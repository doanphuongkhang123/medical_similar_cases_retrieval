import express from "express";
import cors from "cors";
import patientsRouter from "./routes/patients.js";
import comparisonRouter from "./routes/comparison.js";
import imagingRouter from "./routes/imaging.js";
import authRouter from "./routes/auth.js";
import llmRetrievalRouter from "./routes/llmRetrieval.js";
import { initializeAdmin } from "./data/auth.js";
import { requireAuth } from "./middleware/auth.js";


const app = express();
const PORT = process.env.PORT || 4000;

app.use(cors());
app.use(express.json({ limit: "256kb" }));
app.use("/api", (req, res, next) => { res.set("Cache-Control", "no-store"); next(); });
initializeAdmin();
app.get("/api/health", (req, res) => res.json({ ok: true }));
app.use("/api/auth", authRouter);
app.use("/api", requireAuth);
app.use("/api/patients", patientsRouter);
app.use("/api/comparison", comparisonRouter);
app.use("/api/llm-retrieval", llmRetrievalRouter);
app.use("/api/imaging", imagingRouter);

app.use((error, req, res, next) => {
  if (res.headersSent) return next(error);
  const status = error.status || 500;
  if (status >= 500) console.error(error);
  res.status(status).json({ error: error.message || "Lỗi máy chủ" });
});

app.listen(PORT, () => {
  console.log(`Backend đang chạy tại http://localhost:${PORT}`);
});
