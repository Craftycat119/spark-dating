// Объёмная вязаная «надутая» трубка, как на референсах: WebGL через three.js.
// mountPuff(container, { shape: "knot" | "loops" | "heart" }) → { destroy() }
import * as THREE from "/static/vendor/three/three.module.min.js";

const ORANGE = 0xff5b1f;

/** Фактура вязки: ряды «косичек», рисуем на canvas и используем как карту рельефа. */
function knitTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d");
  g.fillStyle = "#000";
  g.fillRect(0, 0, 128, 128);
  const rows = 4, cols = 4, w = 128 / cols, hgt = 128 / rows;
  for (let r = 0; r < rows; r++) {
    for (let k = 0; k < cols; k++) {
      const x = k * w, y = r * hgt;
      for (const side of [-1, 1]) {
        const grd = g.createRadialGradient(x + w / 2 + side * w * 0.2, y + hgt / 2, 1, x + w / 2 + side * w * 0.2, y + hgt / 2, w * 0.36);
        grd.addColorStop(0, "#fff");
        grd.addColorStop(1, "#000");
        g.save();
        g.translate(x + w / 2 + side * w * 0.2, y + hgt / 2);
        g.rotate(side * 0.55);
        g.scale(0.55, 1.15);
        g.translate(-(x + w / 2 + side * w * 0.2), -(y + hgt / 2));
        g.fillStyle = grd;
        g.beginPath();
        g.arc(x + w / 2 + side * w * 0.2, y + hgt / 2, w * 0.36, 0, Math.PI * 2);
        g.fill();
        g.restore();
      }
    }
  }
  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  return tex;
}

function curveFor(shape) {
  const pts = [];
  if (shape === "heart") {
    for (let i = 0; i < 64; i++) {
      const t = (i / 64) * Math.PI * 2;
      const x = 16 * Math.sin(t) ** 3;
      const y = 13 * Math.cos(t) - 5 * Math.cos(2 * t) - 2 * Math.cos(3 * t) - Math.cos(4 * t);
      pts.push(new THREE.Vector3(x * 0.2, y * 0.2 + 0.6, Math.sin(t * 2) * 0.5));
    }
    return new THREE.CatmullRomCurve3(pts, true, "centripetal");
  }
  if (shape === "knot") {
    // Узел-«трилистник»: плотное переплетение, заполняет экран как скульптура на референсе
    for (let i = 0; i < 160; i++) {
      const t = (i / 160) * Math.PI * 2;
      const r = 2.1 + Math.cos(3 * t);
      pts.push(new THREE.Vector3(r * Math.cos(2 * t) * 1.9, r * Math.sin(2 * t) * 1.9, -Math.sin(3 * t) * 2.2));
    }
    return new THREE.CatmullRomCurve3(pts, true, "centripetal");
  }
  // Петли-«каракули»: вытянутая циклоида, у которой петли наезжают друг на друга
  const turns = 3.2, R = 0.95, d = 1.9;
  for (let i = 0; i <= 140; i++) {
    const th = -0.6 + (i / 140) * turns * Math.PI * 2;
    pts.push(new THREE.Vector3(R * th - d * Math.sin(th) - 9.4, -d * Math.cos(th) * 1.05, Math.sin(th * 0.5) * 1.3));
  }
  return new THREE.CatmullRomCurve3(pts, false, "centripetal");
}

/** Трубка с «перетяжками»: радиус пульсирует вдоль пути, как у набитой ткани. */
function puffyTube(curve, { radius, bulges, closed }) {
  const segs = closed ? 900 : 1100;
  const geo = new THREE.TubeGeometry(curve, segs, radius, 40, closed);
  const pos = geo.attributes.position, nrm = geo.attributes.normal, uv = geo.attributes.uv;
  const p = new THREE.Vector3(), n = new THREE.Vector3();
  for (let i = 0; i < pos.count; i++) {
    p.fromBufferAttribute(pos, i);
    n.fromBufferAttribute(nrm, i);
    const u = uv.getX(i);
    const wave = Math.abs(Math.sin(u * bulges * Math.PI));
    let r = radius * (0.74 + 0.26 * Math.pow(wave, 0.45));
    if (!closed) r *= Math.min(1, u * 40, (1 - u) * 40) ** 0.35; // скруглённые концы
    p.addScaledVector(n, r - radius);
    pos.setXYZ(i, p.x, p.y, p.z);
  }
  geo.computeVertexNormals();
  return geo;
}

export function mountPuff(container, { shape = "knot" } = {}) {
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
  } catch {
    return null; // нет WebGL: остаётся запасной вариант из CSS
  }
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  container.append(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 100);
  camera.position.set(0, 0, shape === "heart" ? 17 : 21);

  scene.add(new THREE.HemisphereLight(0xfff1e6, 0x3a1206, 1.1));
  const key = new THREE.DirectionalLight(0xffffff, 2.6);
  key.position.set(-6, 8, 9);
  scene.add(key);
  const rim = new THREE.DirectionalLight(0xff9a6b, 2.2);
  rim.position.set(7, -3, -6);
  scene.add(rim);

  const knit = knitTexture();
  const closed = shape !== "loops";
  const geo = puffyTube(curveFor(shape), { radius: shape === "knot" ? 1.25 : closed ? 0.95 : 1.05, bulges: shape === "knot" ? 44 : closed ? 26 : 30, closed });
  knit.repeat.set(closed ? 240 : 260, 9);
  const mat = new THREE.MeshPhysicalMaterial({
    color: ORANGE,
    roughness: 0.82,
    sheen: 1,
    sheenRoughness: 0.45,
    sheenColor: new THREE.Color(0xffc2a0),
    bumpMap: knit,
    bumpScale: 1.5,
  });
  geo.computeBoundingBox();
  const size = geo.boundingBox.getSize(new THREE.Vector3());
  geo.center();
  const pad = { heart: 1.12, knot: 0.8, loops: 1.04 }[shape] ?? 1;
  const mesh = new THREE.Mesh(geo, mat);
  const group = new THREE.Group();
  group.add(mesh);
  scene.add(group);

  const resize = () => {
    const w = container.clientWidth, h = container.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    // отодвигаем камеру так, чтобы фигура целиком помещалась в контейнер
    const half = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    const fit = Math.max(size.y / 2 / half, size.x / 2 / (half * camera.aspect));
    camera.position.z = fit * pad + size.z / 2;
    camera.updateProjectionMatrix();
  };
  const ro = new ResizeObserver(resize);
  ro.observe(container);
  resize();

  const target = { x: 0, y: 0 };
  const onPointer = (e) => {
    target.x = (e.clientX / innerWidth - 0.5) * 0.5;
    target.y = (e.clientY / innerHeight - 0.5) * 0.35;
  };
  addEventListener("pointermove", onPointer);

  let visible = true;
  const io = new IntersectionObserver(([en]) => (visible = en.isIntersecting));
  io.observe(container);

  const clock = new THREE.Clock();
  let raf = 0;
  const frame = () => {
    if (!container.isConnected) return destroy();
    raf = requestAnimationFrame(frame);
    if (!visible) return;
    const t = clock.getElapsedTime();
    group.rotation.y += (target.x + Math.sin(t * 0.35) * 0.22 - group.rotation.y) * 0.04;
    group.rotation.x += (target.y + Math.sin(t * 0.27) * 0.08 - group.rotation.x) * 0.04;
    group.position.y = Math.sin(t * 0.8) * 0.15;
    if (shape === "heart") group.scale.setScalar(1 + Math.max(0, Math.sin(t * 2.6)) ** 6 * 0.06);
    renderer.render(scene, camera);
  };
  if (reduce) renderer.render(scene, camera);
  else frame();
  container.classList.add("is-3d");

  function destroy() {
    cancelAnimationFrame(raf);
    ro.disconnect();
    io.disconnect();
    removeEventListener("pointermove", onPointer);
    geo.dispose();
    mat.dispose();
    knit.dispose();
    renderer.dispose();
    renderer.domElement.remove();
  }
  return { destroy };
}
