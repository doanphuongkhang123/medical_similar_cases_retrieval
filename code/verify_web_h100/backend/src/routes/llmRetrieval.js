import { Router } from "express";
import {
  getLlmRetrievalCall,
  getLlmRetrievalExport,
  listLlmRetrievalCalls,
  saveLlmRetrievalReview,
  validateLlmRetrievalReview,
} from "../data/llmRetrieval.js";
import { requireAdmin } from "../middleware/auth.js";

const router = Router();

function csvCell(value) {
  let text = String(value ?? "");
  if (/^\s*[=+\-@]/.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}

router.get("/", (req, res, next) => {
  try { res.json(listLlmRetrievalCalls()); } catch (error) { next(error); }
});

router.get("/export", requireAdmin, (req, res, next) => {
  try {
    const rows = getLlmRetrievalExport();
    if (req.query.format === "csv") {
      const columns = Object.keys(rows[0] || {
        request_id: "", model_version: "", query_patient_id: "", similar_patient_id: "", rank: "",
        llm_similarities: "", llm_differences: "", llm_limitations: "", retrieval_relevance: "",
        similarities_accuracy: "", differences_accuracy: "", icd_accuracy: "", note: "", reviewer: "", reviewed_at: "",
      });
      const csv = [columns.join(","), ...rows.map((row) => columns.map((column) => csvCell(row[column])).join(","))].join("\n");
      res.attachment("llm-retrieval-verifications.csv").type("text/csv; charset=utf-8").send(`\uFEFF${csv}`);
      return;
    }
    res.attachment("llm-retrieval-verifications.json").json(rows);
  } catch (error) { next(error); }
});

router.get("/:requestId", (req, res, next) => {
  try { res.json(getLlmRetrievalCall(req.params.requestId)); } catch (error) { next(error); }
});

router.post("/:requestId/candidates/:patientId/verify", (req, res, next) => {
  try {
    const validationError = validateLlmRetrievalReview(req.body);
    if (validationError) return res.status(400).json({ error: validationError });
    const saved = saveLlmRetrievalReview(req.params.requestId, req.params.patientId, {
      ...req.body,
      reviewer: req.user.username,
    });
    res.json(saved);
  } catch (error) { next(error); }
});

export default router;
