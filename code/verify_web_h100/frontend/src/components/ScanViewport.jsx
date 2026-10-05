import React, { useEffect, useRef, useState } from "react";
import { API_ORIGIN, apiFetch } from "../api.js";
import { C } from "../theme.js";

export default function ScanViewport({ series, modality, patient }) {
  const drag = useRef(null);
  const [view, setView] = useState({ x: 0, y: 0, zoom: 1 });
  const [slice, setSlice] = useState(Math.floor((series.sliceCount || 1) / 2));
  const [imageUrl, setImageUrl] = useState("");
  const [error, setError] = useState("");
  const [resolution, setResolution] = useState("preview");
  const [windowPreset, setWindowPreset] = useState("auto");
  const [center, setCenter] = useState(40);
  const [width, setWidth] = useState(400);
  const presets = { lung: [-600, 1500], soft: [40, 400], brain: [40, 80], bone: [300, 1500] };

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl;
    setImageUrl(""); setError("");
    const params = new URLSearchParams({ slice, resolution });
    const windowValues = windowPreset === "custom" ? [center, width] : presets[windowPreset];
    if (windowValues) { params.set("windowCenter", windowValues[0]); params.set("windowWidth", windowValues[1]); }
    const timer = setTimeout(async () => {
      try {
        const response = await apiFetch(`${API_ORIGIN}${series.sliceUrl.replace("/slice?", "/png?")}&${params}`, { signal: controller.signal });
        if (!response.ok) throw new Error((await response.json()).error || "Không tải được ảnh");
        const blob = await response.blob();
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob); setImageUrl(objectUrl);
      } catch (e) { if (e.name !== "AbortError") setError(e.message || "Không tải được ảnh"); }
    }, 80);
    return () => { clearTimeout(timer); controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [series.sliceUrl, slice, resolution, windowPreset, center, width]);

  const onDown = event => { drag.current = { x: event.clientX, y: event.clientY, startX: view.x, startY: view.y }; event.currentTarget.setPointerCapture(event.pointerId); };
  const onMove = event => { if (drag.current) setView(old => ({ ...old, x: drag.current.startX + event.clientX - drag.current.x, y: drag.current.startY + event.clientY - drag.current.y })); };
  const onUp = () => { drag.current = null; };
  return <div style={{ display: "grid", gap: 8 }}>
    <div style={{ display: "flex", gap: 12, flexWrap: "wrap", fontSize: 12 }}>
      <label>Chất lượng <select aria-label="Chất lượng ảnh" value={resolution} onChange={e => setResolution(e.target.value)}><option value="preview">Xem nhanh</option><option value="original">Độ phân giải gốc</option></select></label>
      <label>Window/level <select aria-label="Window/level" value={windowPreset} onChange={e => setWindowPreset(e.target.value)}><option value="auto">Mặc định</option>{modality === "CT" && <><option value="lung">Phổi</option><option value="soft">Mô mềm</option><option value="brain">Não</option><option value="bone">Xương</option></>}<option value="custom">Tùy chỉnh</option></select></label>
      {windowPreset === "custom" && <><label>Center <input aria-label="Window center" type="number" value={center} onChange={e => setCenter(Number(e.target.value))} style={{ width: 75 }} /></label><label>Width <input aria-label="Window width" type="number" min="1" value={width} onChange={e => setWidth(Math.max(1, Number(e.target.value)))} style={{ width: 75 }} /></label></>}
      <label>Zoom <input aria-label="Zoom ảnh" type="range" min="1" max="5" step="0.1" value={view.zoom} onChange={e => setView(old => ({ ...old, zoom: Number(e.target.value) }))} /></label>
      <button onClick={() => setView({ x: 0, y: 0, zoom: 1 })}>Reset</button>
    </div>
    <div onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onDoubleClick={() => setView({ x: 0, y: 0, zoom: 1 })} style={{ background: C.scanBg, position: "relative", overflow: "hidden", aspectRatio: "4 / 3", borderRadius: 6, cursor: "grab", touchAction: "none" }}>
      {imageUrl ? <img alt={`${modality} ${series.label} — lát ${slice + 1}`} src={imageUrl} onError={() => setError("Không hiển thị được ảnh")} style={{ width: "100%", height: "100%", objectFit: "contain", transform: `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`, pointerEvents: "none" }} /> : <div role="status" style={{ height: "100%", display: "grid", placeItems: "center", color: "#8FE0D4" }}>{error || "Đang tải lát ảnh…"}</div>}
      <div style={{ position: "absolute", top: 8, left: 10, color: "#8FE0D4", fontSize: 11, pointerEvents: "none" }}>{patient.id} · {modality} · {slice + 1}/{series.sliceCount}</div>
    </div>
    {(series.sliceCount || 1) > 1 && <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>Lát <input aria-label="Lát ảnh" type="range" min="0" max={series.sliceCount - 1} value={slice} onChange={e => setSlice(Number(e.target.value))} style={{ flex: 1 }} /><input aria-label="Số lát ảnh" type="number" min="1" max={series.sliceCount} value={slice + 1} onChange={e => setSlice(Math.max(0, Math.min(series.sliceCount - 1, Number(e.target.value) - 1)))} style={{ width: 70 }} />/{series.sliceCount}</label>}
  </div>;
}
