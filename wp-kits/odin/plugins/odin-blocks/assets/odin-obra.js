// Odin: casa que se construye por etapas según el avance del scroll del contenedor padre (widget «Obra 3D»).
import * as THREE from './vendor/three.module.min.js';

const stage = document.querySelector('.obra__stage');
const canvas = stage && stage.querySelector('canvas');
const obra = stage && stage.parentElement;
const etapaNum = stage && stage.querySelector('.obra__num');
const etapaBar = stage && stage.querySelector('.obra__bar');
const etapas = stage ? Math.max(1, parseInt(stage.dataset.stages, 10) || 6) : 6;
const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

// Petróleo y dorado salen de la configuración global de Odin (--primary, --accent).
const cssHex = (name, fallback) => {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return /^#[0-9a-f]{6}$/i.test(v) ? parseInt(v.slice(1), 16) : fallback;
};
const C = {
  petroleo: cssHex('--primary', 0x062f3b), dorado: cssHex('--accent', 0xcda04f), salvia: 0x87958a,
  blanco: 0xf7f6f2, piso: 0xeeebe3, hormigon: 0xc9c5bb, madera: 0xa8784a,
};

let renderer;
if (canvas) try {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
} catch (e) {
  stage.classList.add('no-3d');
}

if (renderer) init();

function init() {
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0xf1efe9, 38, 70);
  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 200);

  // Luz
  scene.add(new THREE.HemisphereLight(0xffffff, 0xd8d2c4, 1.6));
  const sol = new THREE.DirectionalLight(0xfff4e0, 2.2);
  sol.position.set(-14, 22, 12);
  sol.castShadow = true;
  sol.shadow.mapSize.set(1024, 1024);
  Object.assign(sol.shadow.camera, { left: -16, right: 16, top: 16, bottom: -16, near: 1, far: 60 });
  sol.shadow.bias = -0.0006;
  scene.add(sol);

  const mat = (color, extra = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.85, metalness: 0, transparent: true, ...extra });
  const box = (w, h, d, material) => {
    const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
    m.castShadow = m.receiveShadow = true;
    return m;
  };

  // Terreno
  const suelo = new THREE.Mesh(new THREE.PlaneGeometry(140, 140), new THREE.MeshStandardMaterial({ color: C.piso, roughness: 1 }));
  suelo.rotation.x = -Math.PI / 2;
  suelo.receiveShadow = true;
  scene.add(suelo);

  const grid = new THREE.GridHelper(40, 40, C.salvia, C.salvia);
  grid.material.transparent = true;
  grid.position.y = 0.01;
  scene.add(grid);

  // Lote replanteado: estacas y cinta dorada
  const lote = new THREE.Group();
  const esq = [[-8, -6], [8, -6], [8, 6], [-8, 6]];
  const estacaMat = mat(C.petroleo);
  esq.forEach(([x, z]) => { const e = box(0.18, 1.2, 0.18, estacaMat); e.position.set(x, 0.6, z); lote.add(e); });
  const cinta = new THREE.LineLoop(
    new THREE.BufferGeometry().setFromPoints(esq.map(([x, z]) => new THREE.Vector3(x, 0.9, z))),
    new THREE.LineBasicMaterial({ color: C.dorado, transparent: true })
  );
  lote.add(cinta);
  scene.add(lote);

  // Piezas de la casa. Cada una guarda su posición final y la etapa en la que aparece.
  const casa = new THREE.Group();
  scene.add(casa);
  const piezas = [];
  const pieza = (mesh, desde, hasta, modo) => {
    const mats = [];
    mesh.traverse((o) => { if (o.material) mats.push(o.material); });
    piezas.push({ mesh, desde, hasta, modo, y: mesh.position.y, mats });
    casa.add(mesh);
    return mesh;
  };

  const base = box(13, 0.5, 9, mat(C.hormigon));
  base.position.set(0, 0.25, 0);
  pieza(base, 0.30, 0.38, 'emerge');

  const colMat = mat(C.hormigon);
  const cols = [[-6, -4], [-2, -4], [2, -4], [6, -4], [-6, 4], [-2, 4], [2, 4], [6, 4]];
  cols.forEach(([x, z], i) => { const c = box(0.4, 3.1, 0.4, colMat); c.position.set(x, 2.05, z); pieza(c, 0.36 + i * 0.012, 0.44 + i * 0.012, 'crece'); });

  const losa = box(13, 0.35, 9, mat(C.hormigon));
  losa.position.set(0, 3.6, 0);
  pieza(losa, 0.45, 0.52, 'baja');

  // Planta baja blanca, retranqueada para dejar ver el vidrio
  const pb = box(8, 3.1, 7.2, mat(C.blanco));
  pb.position.set(-2, 2.05, -0.3);
  pieza(pb, 0.52, 0.6, 'crece');

  // Volumen alto en azul petróleo, en voladizo
  const alto = box(9.5, 2.8, 7.6, mat(C.petroleo, { roughness: 0.6 }));
  alto.position.set(2.2, 5.2, 0);
  pieza(alto, 0.56, 0.66, 'baja');

  // Marco dorado de la fachada (eco de la línea dorada del logo)
  const oro = mat(C.dorado, { metalness: 0.35, roughness: 0.45 });
  const marco = new THREE.Group();
  [[0, 1.55, 6.6, 0.18], [0, -1.55, 6.6, 0.18], [-3.2, 0, 0.18, 3.1], [3.2, 0, 0.18, 3.1]].forEach(([x, y, w, h]) => {
    const b = box(w, h, 0.3, oro); b.position.set(x, y, 0); marco.add(b);
  });
  marco.position.set(3, 2.05, 4.25);
  pieza(marco, 0.64, 0.7, 'baja');

  // Vidrios
  [[3, 2.05, 4.1, 6.2, 2.9, 0.05], [7.1, 2.05, 0, 0.05, 2.9, 7.6], [2.2, 5.2, 3.85, 7, 1.6, 0.05], [-2.6, 5.2, 3.85, 3, 1.6, 0.05]].forEach(([x, y, z, w, h, d]) => {
    const v = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), new THREE.MeshStandardMaterial({ color: 0x9fb8bd, roughness: 0.08, metalness: 0.2, transparent: true }));
    v.position.set(x, y, z);
    pieza(v, 0.66, 0.74, 'aparece');
  });

  // Interiorismo: muebles y luz cálida
  const interior = new THREE.Group();
  const intMats = [];
  const sMat = mat(C.dorado, { roughness: 0.7 });
  const sillon = new THREE.Group();
  [[0, 0.35, 0, 1.6, 0.5, 0.9], [0, 0.85, -0.38, 1.6, 0.9, 0.18], [-0.75, 0.6, 0, 0.18, 0.5, 0.9], [0.75, 0.6, 0, 0.18, 0.5, 0.9]].forEach(([x, y, z, w, h, d]) => {
    const b = box(w, h, d, sMat); b.position.set(x, y, z); sillon.add(b);
  });
  sillon.position.set(2.2, 0.5, 1.2);
  const mesa = box(2.4, 0.08, 1.1, mat(C.madera, { roughness: 0.6 }));
  mesa.position.set(5, 1.3, 1);
  const alfombra = box(3.4, 0.03, 2.4, mat(C.salvia));
  alfombra.position.set(2.6, 0.52, 1.6);
  interior.add(sillon, mesa, alfombra);
  intMats.push(sMat, mesa.material, alfombra.material);
  const lampMat = new THREE.MeshStandardMaterial({ color: 0xffe2a8, emissive: 0xffc46b, emissiveIntensity: 0, transparent: true });
  intMats.push(lampMat);
  [[2.2, 5.2, 0.6], [5, 3.2, 1], [-1.4, 5.2, 0.6]].forEach(([x, y, z]) => {
    const l = new THREE.Mesh(new THREE.SphereGeometry(0.28, 20, 14), lampMat); l.position.set(x, y, z); interior.add(l);
  });
  const calida = new THREE.PointLight(0xffc46b, 0, 14, 1.6);
  calida.position.set(3.5, 3, 1.5);
  interior.add(calida);
  casa.add(interior);

  // Jardín
  const jardin = new THREE.Group();
  const verde = mat(C.salvia, { roughness: 0.95, transparent: false });
  [[-9.5, -3], [-10.5, 2.5], [10, -4.5], [11, 3.5], [-7, 9.5], [12.5, 7]].forEach(([x, z], i) => {
    const t = new THREE.Group();
    const tronco = box(0.2, 1.2, 0.2, mat(C.madera, { transparent: false })); tronco.position.y = 0.6;
    const copa = new THREE.Mesh(new THREE.IcosahedronGeometry(1.1 + (i % 3) * 0.25, 0), verde);
    copa.position.y = 2; copa.castShadow = true;
    t.add(tronco, copa); t.position.set(x, 0, z); t.userData.i = i;
    jardin.add(t);
  });
  const seto = box(9, 0.7, 0.7, verde); seto.position.set(-2, 0.35, 6.6); seto.userData.i = 3; jardin.add(seto);
  const camino = box(1.6, 0.04, 4, mat(C.hormigon, { transparent: false })); camino.position.set(3, 0.02, 7); camino.userData.i = 0; jardin.add(camino);
  scene.add(jardin);

  // Plano en líneas doradas de la casa terminada: la idea antes de la obra
  const lineaMat = new THREE.LineBasicMaterial({ color: C.dorado, transparent: true, opacity: 0 });
  [base, losa, pb, alto].forEach((m) => {
    const l = new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry), lineaMat);
    l.position.copy(m.position);
    scene.add(l);
  });

  const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
  const tramo = (p, a, b) => clamp((p - a) / (b - a));
  const suave = (t) => t * t * (3 - 2 * t);
  const MIN = 0.001;

  function aplicar(p) {
    grid.material.opacity = 0.5 * Math.max(0.35, tramo(p, 0, 0.08)) * (1 - tramo(p, 0.3, 0.45));
    lote.visible = p < 0.45;
    cinta.material.opacity = tramo(p, 0.04, 0.14) * (1 - tramo(p, 0.36, 0.44));
    lote.children.forEach((e, i) => { if (e.isMesh) e.scale.y = Math.max(MIN, suave(tramo(p, 0.03 + i * 0.02, 0.1 + i * 0.02))); });

    lineaMat.opacity = 0.9 * (1 - tramo(p, 0.6, 0.72));

    for (const { mesh, desde, hasta, modo, y, mats } of piezas) {
      const t = suave(tramo(p, desde, hasta));
      mesh.visible = t > MIN;
      if (modo === 'crece') {
        mesh.scale.y = Math.max(MIN, t);
        mesh.position.y = y - (1 - t) * mesh.geometry.parameters.height / 2;
      } else if (modo === 'emerge') mesh.position.y = y - (1 - t) * 0.6;
      else if (modo === 'baja') mesh.position.y = y + (1 - t) * 5;
      const op = modo === 'aparece' ? 0.42 * t : modo === 'baja' ? t : Math.min(1, t * 2);
      for (const m of mats) { m.opacity = op; m.depthWrite = op > 0.95 || modo === 'aparece'; }
    }

    const tin = suave(tramo(p, 0.72, 0.86));
    interior.visible = tin > MIN;
    for (const m of intMats) m.opacity = tin;
    const luz = suave(tramo(p, 0.8, 0.92));
    lampMat.emissiveIntensity = 2.2 * luz;
    calida.intensity = 26 * luz;

    for (const o of jardin.children) {
      const i = o.userData.i;
      const t = suave(tramo(p, 0.84 + i * 0.015, 0.93 + i * 0.012));
      o.visible = t > MIN;
      o.scale.setScalar(Math.max(MIN, t));
    }

    // Luz de tarde al final de la obra
    const tarde = tramo(p, 0.86, 1);
    sol.color.setHSL(0.1, 0.6 + 0.3 * tarde, 0.93 - 0.18 * tarde);
    sol.intensity = 2.2 - 0.9 * tarde;
  }

  // Cámara: órbita alrededor del lote que se acerca a medida que la obra avanza
  const objetivo = new THREE.Vector3(1, 2.4, 0);
  function camara(p, t) {
    const ang = 0.95 - p * 1.55 + (reduce ? 0 : Math.sin(t * 0.00025) * 0.04);
    const radio = (40 - p * 9) * Math.max(1, 1.25 / camera.aspect);
    camera.position.set(Math.sin(ang) * radio, 22 - p * 14, Math.cos(ang) * radio);
    camera.lookAt(objetivo);
  }

  function medir() {
    const w = stage.clientWidth, h = stage.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(medir).observe(stage);
  medir();

  function progreso() {
    const recorrido = obra.offsetHeight - innerHeight;
    return clamp(-obra.getBoundingClientRect().top / Math.max(1, recorrido));
  }

  let visible = true;
  new IntersectionObserver(([e]) => { visible = e.isIntersecting; }).observe(stage);

  let actual = progreso();
  let ultimo = -1;
  function frame(t) {
    requestAnimationFrame(frame);
    if (!visible) return;
    const meta = progreso();
    actual = reduce ? meta : actual + (meta - actual) * 0.08;
    aplicar(actual);
    camara(actual, t);
    renderer.render(scene, camera);

    const paso = Math.min(etapas, Math.floor(meta * etapas * 1.1));
    if (paso !== ultimo) { ultimo = paso; etapaNum.textContent = String(paso).padStart(2, '0'); }
    etapaBar.style.width = `${meta * 100}%`;
  }
  requestAnimationFrame(frame);
}
