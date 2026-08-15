import fs from "node:fs/promises";
import path from "node:path";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const ROOT = "/Users/k/Documents/work/SimilarCasesRetrieval";
const TMP = path.join(ROOT, "tmp/presentations/mimic_graph_papers");
const ASSETS = path.join(TMP, "assets");
const OUT = path.join(ROOT, "output/presentations");
const FINAL = path.join(OUT, "mimic_iv_graph_embeddings_gt_behrt_hypemed.pptx");
const RENDER = path.join(TMP, "artifact-render");

const W = 1280;
const H = 720;
const C = {
  black: "#111111",
  muted: "#5B616B",
  rule: "#D8DADF",
  panel: "#F2F2F2",
  white: "#FFFFFF",
  gt: "#4078C0",
  gtLight: "#EAF2FC",
  hype: "#D97841",
  hypeLight: "#FFF1E7",
  green: "#6E9F58",
  greenLight: "#EDF6E8",
  dx: "#C8485A",
  med: "#4078C0",
  proc: "#6E9F58",
  warn: "#9A6A00",
  warnLight: "#FFF5D7",
};

const GT_URL = "https://proceedings.iclr.cc/paper_files/paper/2024/file/a71c1931d3fb8ba564f7458d0657d0b1-Paper-Conference.pdf";
const HYPE_URL = "https://arxiv.org/pdf/2603.18459";

function addText(slide, value, left, top, width, height, options = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    name: options.name,
    position: { left, top, width, height },
    fill: options.fill || "none",
    line: options.line || { style: "solid", fill: "none", width: 0 },
    borderRadius: options.borderRadius,
  });
  shape.text = value;
  shape.text.style = {
    fontSize: options.fontSize || 24,
    typeface: "Helvetica Neue",
    color: options.color || C.black,
    bold: options.bold || false,
    alignment: options.alignment || "left",
    verticalAlignment: options.verticalAlignment || "top",
    autoFit: options.autoFit || "shrinkText",
    insets: options.insets || { top: 0, right: 0, bottom: 0, left: 0 },
  };
  return shape;
}

function addRect(slide, left, top, width, height, fill, options = {}) {
  return slide.shapes.add({
    geometry: options.geometry || "rect",
    name: options.name,
    position: { left, top, width, height },
    fill,
    line: options.line || { style: "solid", fill: C.rule, width: 1 },
    borderRadius: options.borderRadius,
  });
}

function addLine(slide, x1, y1, x2, y2, options = {}) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  return slide.shapes.add({
    geometry: "straightConnector1",
    position: {
      left: Math.min(x1, x2),
      top: Math.min(y1, y2),
      width: Math.abs(dx),
      height: Math.abs(dy),
      verticalFlip: dx * dy < 0,
    },
    fill: "none",
    line: {
      style: options.dashed ? "dashed" : "solid",
      fill: options.color || C.rule,
      width: options.width || 2,
    },
  });
}

function addArrow(slide, left, top, width = 42, height = 20, color = C.black) {
  return slide.shapes.add({
    geometry: "rightArrow",
    position: { left, top, width, height },
    fill: color,
    line: { style: "solid", fill: color, width: 0 },
  });
}

function addCircle(slide, x, y, d, fill, label, options = {}) {
  const shape = slide.shapes.add({
    geometry: "ellipse",
    position: { left: x, top: y, width: d, height: d },
    fill,
    line: { style: "solid", fill: options.lineColor || C.white, width: options.lineWidth || 2 },
  });
  shape.text = label;
  shape.text.style = {
    fontSize: options.fontSize || 18,
    typeface: "Helvetica Neue",
    color: options.textColor || C.white,
    bold: true,
    alignment: "center",
    verticalAlignment: "middle",
    autoFit: "shrinkText",
    insets: { top: 2, right: 2, bottom: 2, left: 2 },
  };
  return shape;
}

function addHeader(slide, title, number, source = "") {
  addText(slide, title, 41, 32, 1198, 82, {
    fontSize: 47,
    bold: true,
    name: "slide-title",
    autoFit: "none",
  });
  if (source) {
    addText(slide, source, 41, 650, 1030, 24, {
      fontSize: 12,
      color: C.muted,
      verticalAlignment: "top",
      name: "visible-source",
      autoFit: "none",
    });
  }
  addText(slide, String(number).padStart(2, "0"), 1184, 653, 55, 28, {
    fontSize: 13,
    alignment: "right",
    verticalAlignment: "bottom",
    name: "slide-number",
  });
}

function addNotes(slide, sources, notes = []) {
  const lines = ["[Sources]", ...sources.map((s) => `- ${s}`), "[/Sources]", ...notes];
  slide.speakerNotes.textFrame.setText(lines.join("\n"));
}

function newSlide() {
  const slide = deck.slides.add();
  slide.background.fill = C.white;
  return slide;
}

function addTwoColumn(slide, leftTitle, leftBody, rightTitle, rightBody, options = {}) {
  const top = options.top || 180;
  const height = options.height || 395;
  addLine(slide, 640, top - 18, 640, top + height, { color: C.rule, width: 1 });
  addText(slide, leftTitle, 41, top, 560, 48, { fontSize: 28, bold: true, color: options.leftColor || C.black });
  addText(slide, leftBody, 41, top + 62, 560, height - 62, { fontSize: 23, color: C.black });
  addText(slide, rightTitle, 679, top, 560, 48, { fontSize: 28, bold: true, color: options.rightColor || C.black });
  addText(slide, rightBody, 679, top + 62, 560, height - 62, { fontSize: 23, color: C.black });
}

function addFourGrid(slide, items, options = {}) {
  const top = options.top || 175;
  const rowH = options.rowH || 205;
  addLine(slide, 640, top, 640, top + rowH * 2, { color: C.rule, width: 1 });
  addLine(slide, 41, top + rowH, 1239, top + rowH, { color: C.rule, width: 1 });
  const frames = [
    [41, top, 560, rowH - 18], [679, top, 560, rowH - 18],
    [41, top + rowH + 18, 560, rowH - 18], [679, top + rowH + 18, 560, rowH - 18],
  ];
  items.forEach((item, idx) => {
    const [x, y, w, h] = frames[idx];
    addText(slide, item.title, x, y, w, 42, { fontSize: 27, bold: true, color: item.color || C.black });
    addText(slide, item.body, x, y + 52, w, h - 52, { fontSize: 21, color: C.black });
  });
}

function addTimeline3(slide, items, top = 170) {
  const cols = [41, 452, 864];
  addLine(slide, 46, 560, 1239, 560, { color: C.black, width: 1 });
  items.forEach((item, idx) => {
    const x = cols[idx];
    addRect(slide, x, top, 375, 350, C.panel, { geometry: "roundRect", line: { style: "solid", fill: C.panel, width: 0 } });
    addText(slide, item.kicker, x + 32, top + 32, 311, 30, { fontSize: 16, bold: true, color: item.color || C.muted });
    addText(slide, item.title, x + 32, top + 77, 311, 65, { fontSize: 28, bold: true });
    addText(slide, item.body, x + 32, top + 152, 311, 165, { fontSize: 20 });
    addCircle(slide, x - 5, 554, 12, C.black, "", { lineWidth: 0 });
    addText(slide, item.label, x, 590, 300, 36, { fontSize: 22, bold: true });
  });
}

async function addImage(slide, fileName, left, top, width, height, alt, fit = "contain") {
  const filePath = path.join(ASSETS, fileName);
  const bytes = await fs.readFile(filePath);
  slide.images.add({
    blob: bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
    contentType: "image/png",
    alt,
    fit,
    position: { left, top, width, height },
  });
}

const deck = Presentation.create({ slideSize: { width: W, height: H } });

// 01 - Title: Codex Grid slide 01 silhouette.
{
  const slide = newSlide();
  addText(slide, "PAPER REVIEW · MIMIC-IV", 41, 41, 620, 48, { fontSize: 22, bold: true, color: C.muted });
  addText(slide, "Biểu diễn đồ thị\ntừ MIMIC-IV", 41, 174, 1050, 235, { fontSize: 78, bold: true, verticalAlignment: "bottom", autoFit: "none" });
  addText(slide, "GT-BEHRT (ICLR 2024) và HypeMed (2026)\nTừ mã EHR đến graph, visit và patient embeddings", 41, 505, 780, 106, { fontSize: 28, color: C.muted });
  addRect(slide, 1115, 42, 124, 12, C.gt, { line: { style: "solid", fill: C.gt, width: 0 } });
  addRect(slide, 1115, 61, 124, 12, C.hype, { line: { style: "solid", fill: C.hype, width: 0 } });
  addNotes(slide, [GT_URL, HYPE_URL]);
}

// 02 - Scope and thesis.
{
  const slide = newSlide();
  addHeader(slide, "Cùng mã EHR, hai cấu trúc đồ thị khác nhau", 2, "Nguồn: GT-BEHRT §2; HypeMed §3-4");
  addText(slide, "Làm thế nào biến các mã rời rạc trong từng lần khám thành vector có ý nghĩa?", 41, 125, 1198, 66, { fontSize: 30, bold: true });
  addTwoColumn(
    slide,
    "GT-BEHRT · graph theo từng visit",
    "- Mỗi visit tạo một graph đầy đủ.\n- Đỉnh = diagnosis / medication / procedure code + <VST>.\n- Cạnh = mọi cặp đỉnh, có type theo cặp loại mã.\n- <VST> đọc ra graph embedding g_t.",
    "HypeMed · hypergraph theo từng miền",
    "- Ba hypergraph toàn cục: D, P, M.\n- Đỉnh = medical entity code.\n- Hyperedge = một visit nối đồng thời mọi code cùng miền.\n- Encoder học cả node embedding Z và visit/hyperedge embedding U.",
    { top: 215, height: 360, leftColor: C.gt, rightColor: C.hype },
  );
  addNotes(slide, [`${GT_URL} (pp. 2-4)`, `${HYPE_URL} (pp. 4-10)`]);
}

// 03 - MIMIC-IV input comparison.
{
  const slide = newSlide();
  addHeader(slide, "Hai paper khác cửa sổ quan sát và mục tiêu", 3, "Nguồn: GT-BEHRT Appendix A.2; HypeMed §3.1, §5.1.1, Table 2");
  addTwoColumn(
    slide,
    "GT-BEHRT · dự báo ICU",
    "Dữ liệu dùng\n- Conditions, medications, procedures từ module hosp.\n- Visit type, tuổi tại visit, ngày trong năm, vị trí visit.\n\nCửa sổ quan sát\n- Chỉ record xuất hiện trước ICU admission.\n\nNhãn\n- Tử vong trong ICU.\n- ICU length of stay > 72 giờ.",
    "HypeMed · gợi ý thuốc",
    "Dữ liệu dùng\n- Diagnosis, procedure, medication multi-hot theo visit.\n- Lịch sử visit có thứ tự.\n\nCửa sổ quan sát\n- Current diagnosis + procedure và các visit trước.\n\nNhãn\n- Medication set của current visit; DDI graph chỉ tham gia loss/safety, không phải MIMIC-IV input.",
    { top: 155, height: 455, leftColor: C.gt, rightColor: C.hype },
  );
  addNotes(slide, [`${GT_URL} (Appendix A.2, p. 14)`, `${HYPE_URL} (§3.1, pp. 4-5; §5.1.1, pp. 13-14)`]);
}

// 04 - GT-BEHRT cohort.
{
  const slide = newSlide();
  addHeader(slide, "GT-BEHRT chỉ nhìn lịch sử trước ICU", 4, "Nguồn: Poulain & Beheshti, 2024, Appendix A.2-A.3");
  addFourGrid(slide, [
    { title: "22.376 bệnh nhân", body: "Cohort downstream từ các bệnh nhân có ICU admission trong MIMIC-IV.", color: C.gt },
    { title: "76.253 bệnh nhân", body: "Cohort pre-training riêng, lớn hơn cohort gắn nhãn downstream.", color: C.gt },
    { title: "Tối thiểu 2 visits", body: "Loại bệnh nhân chỉ có 1 visit để mô hình có tín hiệu thời gian.", color: C.gt },
    { title: "80 / 10 / 10 × 5", body: "Random train / validation / test; lặp 5 seed và báo mean ± std.", color: C.gt },
  ], { top: 168, rowH: 205 });
  addText(slide, "Ranh giới chống leakage của paper: chỉ lấy conditions, medications, procedures và context đã xuất hiện trước ICU admission.", 41, 594, 1135, 44, { fontSize: 20, bold: true, color: C.warn });
  addNotes(slide, [`${GT_URL} (pp. 5, 14-15)`], ["The paper does not list the exact raw MIMIC-IV tables or code crosswalks."]);
}

// 05 - GT graph construction.
{
  const slide = newSlide();
  addHeader(slide, "GT-BEHRT: mỗi visit là complete typed graph", 5, "Nguồn: GT-BEHRT §2.1, Figure 1");
  addText(slide, "Đỉnh", 41, 155, 180, 34, { fontSize: 26, bold: true, color: C.gt });
  addText(slide, "- Mỗi diagnosis / medication / procedure code trong C_t.\n- Thêm virtual node <VST> để đọc toàn graph.\n- Tổng: |C_t| + 1 đỉnh.", 41, 198, 445, 145, { fontSize: 21 });
  addText(slide, "Cạnh", 41, 370, 180, 34, { fontSize: 26, bold: true, color: C.gt });
  addText(slide, "- Vô hướng, nối đầy đủ mọi cặp đỉnh.\n- Type cạnh mã hóa cặp loại code: D-D, D-M, M-P, ...\n- Cạnh <VST>-code dùng một type riêng.\n- Đây là giả định cấu trúc, không phải quan hệ nhân quả.", 41, 412, 490, 175, { fontSize: 21 });

  // Edges first, then nodes.
  const nodes = {
    vst: [850, 335], d1: [690, 210], d2: [1010, 215], m1: [680, 475], p1: [1025, 470],
  };
  const centers = Object.fromEntries(Object.entries(nodes).map(([k, [x, y]]) => [k, [x + 35, y + 35]]));
  const codeKeys = ["d1", "d2", "m1", "p1"];
  for (let i = 0; i < codeKeys.length; i++) {
    for (let j = i + 1; j < codeKeys.length; j++) {
      const a = centers[codeKeys[i]], b = centers[codeKeys[j]];
      addLine(slide, a[0], a[1], b[0], b[1], { color: "#9AA0A8", width: 2 });
    }
  }
  for (const key of codeKeys) {
    const a = centers.vst, b = centers[key];
    addLine(slide, a[0], a[1], b[0], b[1], { color: C.gt, width: 3 });
  }
  addCircle(slide, ...nodes.vst, 70, C.black, "VST", { fontSize: 18 });
  addCircle(slide, ...nodes.d1, 70, C.dx, "D1");
  addCircle(slide, ...nodes.d2, 70, C.dx, "D2");
  addCircle(slide, ...nodes.m1, 70, C.med, "M1");
  addCircle(slide, ...nodes.p1, 70, C.proc, "P1");
  addText(slide, "cạnh code-code: type theo cặp miền", 700, 575, 320, 30, { fontSize: 16, color: C.muted });
  addText(slide, "cạnh VST-code: type riêng", 890, 300, 250, 30, { fontSize: 16, color: C.gt, bold: true });
  addNotes(slide, [`${GT_URL} (§2.1, pp. 2-3)`]);
}

// 06 - GT graph embedding steps.
{
  const slide = newSlide();
  addHeader(slide, "GT-BEHRT: bốn bước thu graph embedding g_t", 6, "Nguồn: GT-BEHRT §2.2, Eq. (1)-(2)");
  addFourGrid(slide, [
    { title: "1 · Lookup embeddings", body: "Medical code và edge type là category. Hai bảng học được ánh xạ chúng thành H⁰ và E_ij trong latent space d chiều.", color: C.gt },
    { title: "2 · Edge-conditioned attention", body: "E_ij W_E được cộng vào Key và Value. Vì vậy attention phụ thuộc đồng thời node feature và loại quan hệ i-j.", color: C.gt },
    { title: "3 · L lớp Graph Transformer", body: "Multi-head attention + feed-forward, pre-layer normalization và residual connection cập nhật toàn bộ node states Hˡ.", color: C.gt },
    { title: "4 · <VST> readout", body: "Không mean/sum pool. Lấy state cuối của virtual node: g_t = Hᴸ_<VST>; node này học cách attend tới code quan trọng.", color: C.gt },
  ], { top: 165, rowH: 215 });
  addNotes(slide, [`${GT_URL} (§2.2, pp. 3-4)`]);
}

// 07 - GT visit to patient embedding, source figure.
{
  const slide = newSlide();
  addHeader(slide, "GT-BEHRT: từ g_t đến patient embedding", 7, "Nguồn: GT-BEHRT Figure 1, §2.2");
  addText(slide, "1 · Context của visit", 41, 170, 420, 38, { fontSize: 26, bold: true, color: C.gt });
  addText(slide, "Lookup bốn vector: position, visit type, age, day-of-year.", 41, 215, 470, 62, { fontSize: 21 });
  addText(slide, "2 · Visit vector", 41, 300, 420, 38, { fontSize: 26, bold: true, color: C.gt });
  addText(slide, "Nối [g_t; Pos_t; Type_t; Age_t; Day_t], rồi linear projection thành v_t.", 41, 345, 500, 82, { fontSize: 21 });
  addText(slide, "3 · Patient vector", 41, 455, 420, 38, { fontSize: 26, bold: true, color: C.gt });
  addText(slide, "Đưa <CLS>, v₁...v_T qua Transformer Encoder. State S_<CLS> là patient representation cho downstream classifier.", 41, 500, 520, 105, { fontSize: 21 });
  addRect(slide, 586, 150, 653, 445, C.gtLight, { geometry: "roundRect", line: { style: "solid", fill: "#B5CAE5", width: 1 } });
  await addImage(slide, "gt_architecture.png", 600, 192, 625, 330, "Figure 1 from GT-BEHRT showing graph visit embeddings and patient Transformer", "contain");
  addText(slide, "Figure 1 · sơ đồ gốc của paper", 610, 535, 420, 30, { fontSize: 14, color: C.muted });
  addNotes(slide, [`${GT_URL} (Figure 1, p. 3; §2.2, pp. 3-4)`]);
}

// 08 - GT pre-training.
{
  const slide = newSlide();
  addHeader(slide, "GT-BEHRT: pre-train node → graph → temporal", 8, "Nguồn: GT-BEHRT §2.3, Figure 4");
  addRect(slide, 41, 151, 660, 438, C.gtLight, { geometry: "roundRect", line: { style: "solid", fill: "#B5CAE5", width: 1 } });
  await addImage(slide, "gt_pretraining.png", 54, 185, 635, 340, "Figure 4 from GT-BEHRT showing two-stage pre-training", "contain");
  addText(slide, "Figure 4 · hai stage pre-training", 64, 540, 360, 28, { fontSize: 14, color: C.muted });
  addText(slide, "Stage 1 · NAM", 745, 165, 430, 38, { fontSize: 27, bold: true, color: C.gt });
  addText(slide, "Mask ngẫu nhiên 15% node; Graph Transformer dự đoán code gốc từ Hᴸ trước pooling. Mục tiêu: node embeddings tốt hơn trong nội bộ visit.", 745, 215, 455, 118, { fontSize: 21 });
  addText(slide, "Stage 2 · MNP + VTP", 745, 365, 430, 38, { fontSize: 27, bold: true, color: C.gt });
  addText(slide, "MNP: bỏ 1 node và các cạnh ở graph có ≥3 node.\nVTP: mask 50% visit types.\nCả hai dự đoán từ output sau graph pooling + patient Transformer, nên nhìn được visit trước/sau.", 745, 415, 455, 162, { fontSize: 21 });
  addNotes(slide, [`${GT_URL} (§2.3, pp. 4-5; Figure 4, p. 16)`]);
}

// 09 - HypeMed data.
{
  const slide = newSlide();
  addHeader(slide, "HypeMed: MIMIC-IV v2.0 cho gợi ý thuốc", 9, "Nguồn: HypeMed §3.1, §5.1.1, Tables 2-3");
  addFourGrid(slide, [
    { title: "9.036 patients", body: "Sau preprocessing và loại bệnh nhân có <2 visits.", color: C.hype },
    { title: "20.616 visits", body: "Trung bình 2,28 visits mỗi bệnh nhân.", color: C.hype },
    { title: "1.892 D · 4.939 P · 131 M", body: "Số diagnosis, procedure và medication codes duy nhất sau lọc.", color: C.hype },
    { title: "13,62 D · 3,55 P · 10,29 M", body: "Số code trung bình của từng miền trên mỗi visit.", color: C.hype },
  ], { top: 160, rowH: 205 });
  addText(slide, "SafeDrug-style preprocessing: lọc entity tần suất thấp, chuẩn hóa diagnosis/procedure sang ICD và medication sang ATC. Paper không nêu threshold/crosswalk cụ thể.", 41, 588, 1160, 54, { fontSize: 20, bold: true, color: C.warn });
  addNotes(slide, [`${HYPE_URL} (§3.1, pp. 4-5; §5.1.1 and Table 2, pp. 13-14; Table 3, p. 16)`]);
}

// 10 - HypeMed hypergraph.
{
  const slide = newSlide();
  addHeader(slide, "HypeMed: medical entity là đỉnh, visit là hyperedge", 10, "Nguồn: HypeMed §3.2, Algorithm 1");
  addText(slide, "Ba hypergraph độc lập", 41, 140, 440, 36, { fontSize: 27, bold: true, color: C.hype });
  addText(slide, "Hᴰ = (Nᴰ,Eᴰ) · Hᴾ = (Nᴾ,Eᴾ) · Hᴹ = (Nᴹ,Eᴹ)", 41, 185, 520, 42, { fontSize: 24 });
  addText(slide, "Đỉnh Nˣ", 41, 265, 170, 34, { fontSize: 25, bold: true });
  addText(slide, "Mỗi diagnosis / procedure / medication code duy nhất là một node trong hypergraph cùng miền.", 41, 307, 480, 82, { fontSize: 21 });
  addText(slide, "Hyperedge Eˣ", 41, 420, 200, 34, { fontSize: 25, bold: true });
  addText(slide, "Duyệt toàn bộ training visits. Với mỗi visit, tạo một hyperedge nối đồng thời mọi code loại X xuất hiện trong visit đó. Không biến thành các cạnh pairwise.", 41, 462, 490, 120, { fontSize: 21 });
  addText(slide, "incidence = code thuộc visit", 41, 602, 440, 30, { fontSize: 18, color: C.hype, bold: true });

  // Hyperedge outlines first.
  const panels = [
    { x: 580, color: C.dx, light: "#FFF0F2", title: "Hᴰ", labels: ["D1", "D2", "D3", "D4"] },
    { x: 805, color: C.proc, light: C.greenLight, title: "Hᴾ", labels: ["P1", "P2", "P3", "P4"] },
    { x: 1030, color: C.med, light: C.gtLight, title: "Hᴹ", labels: ["M1", "M2", "M3", "M4"] },
  ];
  for (const p of panels) {
    addText(slide, p.title, p.x + 70, 145, 80, 34, { fontSize: 26, bold: true, color: p.color, alignment: "center" });
    slide.shapes.add({ geometry: "ellipse", position: { left: p.x + 8, top: 215, width: 190, height: 200 }, fill: "none", line: { style: "solid", fill: p.color, width: 3 } });
    slide.shapes.add({ geometry: "ellipse", position: { left: p.x + 55, top: 345, width: 150, height: 205 }, fill: "none", line: { style: "dashed", fill: p.color, width: 3 } });
    addText(slide, "visit a", p.x + 8, 198, 90, 24, { fontSize: 15, color: p.color, bold: true });
    addText(slide, "visit b", p.x + 115, 545, 90, 24, { fontSize: 15, color: p.color, bold: true });
    const coords = [[p.x + 30, 255], [p.x + 125, 260], [p.x + 82, 390], [p.x + 135, 455]];
    coords.forEach((c, i) => addCircle(slide, c[0], c[1], 48, p.color, p.labels[i], { fontSize: 14 }));
  }
  addNotes(slide, [`${HYPE_URL} (§3.2, pp. 5-6; Algorithm 1)`]);
}

// 11 - KHGE.
{
  const slide = newSlide();
  addHeader(slide, "KHGE ghép message local với tri thức ICD/ATC", 11, "Nguồn: HypeMed §4.1.1, Figure 4");
  addText(slide, "1 · LMPN", 41, 160, 430, 34, { fontSize: 26, bold: true, color: C.hype });
  addText(slide, "Hypergraph attention truyền message node → hyperedge → node. Attention coefficient αᵢⱼ điều khiển trọng số membership.", 41, 203, 480, 92, { fontSize: 20 });
  addText(slide, "2 · KGAN", 41, 320, 430, 34, { fontSize: 26, bold: true, color: C.hype });
  addText(slide, "Khoảng cách đường đi trong cây ICD/ATC được biến thành knowledge-bias matrix Ω và cộng vào logits của global self-attention.", 41, 363, 490, 105, { fontSize: 20 });
  addText(slide, "3 · Fusion + layer average", 41, 490, 460, 34, { fontSize: 26, bold: true, color: C.hype });
  addText(slide, "FFN + residual + LayerNorm hợp nhất local/global. Trung bình representation qua L layers để giảm over-smoothing, thu Z và U.", 41, 533, 495, 90, { fontSize: 20 });
  addRect(slide, 565, 145, 674, 470, C.hypeLight, { geometry: "roundRect", line: { style: "solid", fill: "#E6B597", width: 1 } });
  await addImage(slide, "hypemed_khge.png", 580, 170, 645, 405, "Figure 4 from HypeMed showing KHGE with KGAN and LMPN", "contain");
  addText(slide, "Figure 4 · KHGE trong paper", 585, 582, 340, 24, { fontSize: 14, color: C.muted });
  addNotes(slide, [`${HYPE_URL} (§4.1.1, pp. 7-9; Figure 4, p. 9)`]);
}

// 12 - Hype contrastive training.
{
  const slide = newSlide();
  addHeader(slide, "MedRep học node và visit embeddings bằng InfoNCE", 12, "Nguồn: HypeMed §4.1.2, Algorithm 2, Eq. (4)-(7)");
  addTimeline3(slide, [
    { kicker: "AUGMENT", title: "Tạo hai views", body: "Từ hypergraph gốc, dropout độc lập node, incidence và feature để có H₁, H₂. Phần tử bị drop không tham gia loss.", label: "Bước 1", color: C.hype },
    { kicker: "ENCODE", title: "Chạy KHGE", body: "Mỗi view đi qua cùng encoder để thu (Z₁,U₁) và (Z₂,U₂): node embeddings và hyperedge/visit embeddings.", label: "Bước 2", color: C.hype },
    { kicker: "ALIGN + EXPORT", title: "InfoNCE 3 mức", body: "Node↔node, hyperedge↔hyperedge và membership node↔hyperedge. Sau pre-training, export Zˣ,Uˣ cho D/P/M.", label: "Bước 3", color: C.hype },
  ], 160);
  addNotes(slide, [`${HYPE_URL} (Algorithm 2, p. 8; §4.1.2, pp. 9-10)`]);
}

// 13 - SimMR.
{
  const slide = newSlide();
  addHeader(slide, "SimMR truy hồi similar visits có điều kiện", 13, "Nguồn: HypeMed §4.2, Figure 3");
  addText(slide, "1 · Current visit", 41, 155, 450, 34, { fontSize: 25, bold: true, color: C.hype });
  addText(slide, "Mean-pool entity embeddings từng miền, rồi dùng MHA để thu vᵀ_D, vᵀ_P, vᵀ_M. Health state h_t đến từ diagnosis + procedure.", 41, 198, 500, 92, { fontSize: 20 });
  addText(slide, "2 · Hai kênh evidence", 41, 315, 450, 34, { fontSize: 25, bold: true, color: C.hype });
  addText(slide, "History: attend vào k visit gần nhất của cùng bệnh nhân.\nSimilar: dùng h_t query top-k training visits trong Uᴴ; lấy medication evidence từ Uᴹ tương ứng.", 41, 358, 510, 120, { fontSize: 20 });
  addText(slide, "3 · Fuse + score", 41, 505, 450, 34, { fontSize: 25, bold: true, color: C.hype });
  addText(slide, "MLP-Softmax trộn v_hist và v_sim; dot-product với medication table Zᴹ tạo xác suất thuốc. Embedding tables vẫn trainable khi fine-tune.", 41, 548, 520, 76, { fontSize: 20 });
  addRect(slide, 585, 145, 654, 465, C.hypeLight, { geometry: "roundRect", line: { style: "solid", fill: "#E6B597", width: 1 } });
  await addImage(slide, "hypemed_overall.png", 600, 180, 625, 360, "Figure 3 from HypeMed showing MedRep and SimMR", "contain");
  addText(slide, "Figure 3 · MedRep → SimMR", 605, 550, 340, 24, { fontSize: 14, color: C.muted });
  addNotes(slide, [`${HYPE_URL} (§4.2, pp. 10-12; Figure 3, p. 7)`]);
}

// 14 - Direct comparison.
{
  const slide = newSlide();
  addHeader(slide, "Hai mô hình khác đơn vị graph và embedding đầu ra", 14, "Tổng hợp từ hai paper");
  addTwoColumn(
    slide,
    "GT-BEHRT",
    "Cấu trúc\n- Một ordinary graph cho mỗi visit.\n- Fully connected, typed undirected edges.\n\nEmbedding đọc ra\n- g_t: state của virtual node <VST>.\n- v_t: g_t + 4 context embeddings.\n- S_<CLS>: patient-level embedding.\n\nNguồn quan hệ\n- Học ngầm từ co-occurrence trong chính visit + edge type.",
    "HypeMed",
    "Cấu trúc\n- Ba global hypergraphs theo D/P/M.\n- Visit là hyperedge; incidence là code thuộc visit.\n\nEmbedding đọc ra\n- Zˣ: entity/node embedding.\n- Uˣ: visit/hyperedge embedding.\n- v_t: history + retrieved similar visits.\n\nNguồn quan hệ\n- Co-membership qua nhiều visits + prior khoảng cách ICD/ATC.",
    { top: 145, height: 470, leftColor: C.gt, rightColor: C.hype },
  );
  addNotes(slide, [`${GT_URL} (§2)`, `${HYPE_URL} (§3-4)`]);
}

// 15 - Transfer to SCR.
{
  const slide = newSlide();
  addHeader(slide, "Retrieval: index HypeMed + context GT-BEHRT", 15, "Suy luận thiết kế dựa trên hai paper và phạm vi SimilarCasesRetrieval");
  addFourGrid(slide, [
    { title: "Đơn vị retrieval", body: "Dùng hadm_id/visit embedding làm index. HypeMed Uᴴ là mẫu trực tiếp cho visit-level nearest-neighbor retrieval.", color: C.hype },
    { title: "Input leakage-safe", body: "Giữ nguyên nguyên tắc GT-BEHRT: chỉ dùng dữ liệu trước query time. Diagnosis/outcome tương lai chỉ để đánh giá.", color: C.gt },
    { title: "Context nên bổ sung", body: "Kết hợp graph/hypergraph representation với age, visit type, time-of-year và relative visit position nếu hợp lệ.", color: C.gt },
    { title: "Metric space phải được học", body: "Contrastive pre-training ở node + visit level giúp embedding phục vụ retrieval, thay vì dùng graph encoder chưa huấn luyện.", color: C.hype },
  ], { top: 165, rowH: 215 });
  addNotes(slide, [`${GT_URL} (§2.1-2.3)`, `${HYPE_URL} (§4.1-4.2)`, `${ROOT}/docs/PROJECT_BRIEF.md`], ["This slide is an explicit design inference, not a claim made verbatim by either paper."]);
}

// 16 - Gaps.
{
  const slide = newSlide();
  addHeader(slide, "Paper chưa đủ để tái lập preprocessing MIMIC-IV", 16, "Các khoảng trống được xác định khi đối chiếu main text và appendix");
  addTwoColumn(
    slide,
    "GT-BEHRT chưa công bố",
    "- MIMIC-IV version cụ thể.\n- Raw table → condition / medication / procedure mapping.\n- Chuẩn mã và xử lý ICD-9/ICD-10, drug identifiers.\n- Quy tắc gộp event thành visit ngoài mô tả ‘hosp module’.\n- Chi tiết cohort pre-training.\n- Bảng hyperparameter dùng graph hidden 108 và patient Transformer 540; cần kiểm tra code để chốt tensor dimensions.",
    "HypeMed chưa công bố",
    "- Threshold ‘low-frequency’.\n- Raw MIMIC-IV table mapping và crosswalk ICD/ATC.\n- Train / validation / test split ratio.\n- Dropout rate riêng cho node / incidence / feature.\n- Cách hợp nhất D+P thành health-status subspace Uᴴ.\n- Tie-breaking, metric normalization và index implementation cho top-k retrieval.",
    { top: 155, height: 445, leftColor: C.gt, rightColor: C.hype },
  );
  addText(slide, "Khi triển khai: ghi rõ assumption trong docs/DATA.md và docs/DECISIONS.md; không suy diễn code mapping lâm sàng.", 41, 610, 1140, 36, { fontSize: 20, bold: true, color: C.warn });
  addNotes(slide, [`${GT_URL} (all sections and appendices)`, `${HYPE_URL} (all sections)`]);
}

// 17 - Blueprint.
{
  const slide = newSlide();
  addHeader(slide, "Blueprint: pre-train visit embeddings rồi lập index", 17, "Tổng hợp ứng dụng cho SimilarCasesRetrieval");
  addTimeline3(slide, [
    { kicker: "DATA CONTRACT", title: "Chốt query-time schema", body: "hadm_id, timestamp cutoff, code vocabularies, text/lab modalities và split theo subject_id. Ghi lineage + leakage rules.", label: "Chuẩn hóa", color: C.warn },
    { kicker: "REPRESENTATION", title: "Pre-train visit encoder", body: "Thử GT visit graph hoặc HypeMed-style hypergraph. Học metric bằng self-supervised/contrastive objective; export embeddings kèm metadata.", label: "Học vector", color: C.gt },
    { kicker: "RETRIEVAL", title: "Index + đánh giá", body: "Index chỉ trên reference split. Query top-k bằng cosine/IP; đánh giá relevance, leakage, calibration và qualitative review.", label: "Truy hồi", color: C.hype },
  ], 160);
  addNotes(slide, [`${GT_URL}`, `${HYPE_URL}`, `${ROOT}/docs/PROJECT_BRIEF.md`], ["This is a project recommendation inferred from the reviewed methods."]);
}

await fs.mkdir(OUT, { recursive: true });
await fs.mkdir(RENDER, { recursive: true });

for (const [index, slide] of deck.slides.items.entries()) {
  const stem = `slide-${String(index + 1).padStart(2, "0")}`;
  const png = await deck.export({ slide, format: "png", scale: 1.5 });
  await fs.writeFile(path.join(RENDER, `${stem}.png`), new Uint8Array(await png.arrayBuffer()));
  const layout = await slide.export({ format: "layout" });
  await fs.writeFile(path.join(RENDER, `${stem}.layout.json`), await layout.text());
}

const montage = await deck.export({ format: "webp", montage: true, scale: 1 });
await fs.writeFile(path.join(RENDER, "deck-montage.webp"), new Uint8Array(await montage.arrayBuffer()));

const snapshot = await deck.inspect({ kind: "slide,textbox,shape,image,notes", maxChars: 12000 });
await fs.writeFile(path.join(RENDER, "deck-inspect.ndjson"), snapshot.ndjson);

const pptx = await PresentationFile.exportPptx(deck);
await pptx.save(FINAL);
console.log(FINAL);
