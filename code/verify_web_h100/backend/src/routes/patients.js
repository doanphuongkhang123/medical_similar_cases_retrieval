import { Router } from "express";
import { listPatients, getPatient } from "../data/rawPatients.js";
const router = Router();
router.get("/", (req, res) => res.json(listPatients()));
router.get("/:id", (req, res) => {
  const patient = getPatient(req.params.id);
  if (!patient) return res.status(404).json({ error: "Không tìm thấy hồ sơ bệnh nhân." });
  res.json(patient);
});
export default router;
