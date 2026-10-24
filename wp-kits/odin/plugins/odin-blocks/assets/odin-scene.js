// Odin: escena 3D de fondo (three.js). Tipo según la clase del body: odin-scene-default|shop|food|house.
import * as THREE from './vendor/three.module.min.js';

const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
const cfg = Object.assign({ particles: 3000, rings: true, speed: 1, side: 'right' }, window.odinScene3D || {});

// Colores de la configuración global de Odin (variables CSS); si no son hex se usa el de ODIN.01.
const cssColor = (name, fallback) => {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return /^#[0-9a-f]{3,6}$/i.test(v) ? v : fallback;
};

// Escena 3D de fondo: núcleo geométrico, anillos orbitales y campo de partículas
const canvas = document.getElementById('scene') || document.body.insertBefore(Object.assign(document.createElement('canvas'), { id: 'scene' }), document.body.firstChild);
canvas.setAttribute('aria-hidden', 'true');
let renderer;
try {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'low-power' });
} catch {
  canvas.remove(); // sin WebGL la página sigue funcionando con el fondo plano
}

if (renderer) {
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(cssColor('--bg', '#070b14'), 0.045);
  const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 100);
  camera.position.set(0, 0, 9);

  const blue = new THREE.Color(cssColor('--primary', '#3b82f6'));
  const gold = new THREE.Color(cssColor('--accent', '#f5b841'));

  const core = new THREE.Group();
  const solid = new THREE.MeshStandardMaterial({ color: 0x0f1a33, metalness: 0.6, roughness: 0.25, flatShading: true });
  const sceneType = (Array.prototype.find.call(document.body.classList, (c) => c.startsWith('odin-scene-')) || '').slice(11);
  // Piezas del modelo de cada negocio: arrancan dispersas, se arman al cargar y se desarman al bajar
  const parts = [];
  const part = (geo, [x, y, z], [rx, ry, rz] = [0, 0, 0], accent = false) => {
    const g = new THREE.Group();
    g.add(new THREE.Mesh(geo, solid));
    g.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo, 20), new THREE.LineBasicMaterial({ color: accent ? gold : blue })));
    const n = parts.length + 1;
    const dir = new THREE.Vector3(Math.sin(n * 2.4), Math.cos(n * 1.7), Math.sin(n * 3.1)).normalize();
    parts.push({ g, home: new THREE.Vector3(x, y, z), rot: new THREE.Euler(rx, ry, rz),
      off: dir.multiplyScalar(4 + (n % 3)), spin: new THREE.Vector3(n * 1.3, n * 0.9, n * 0.7) });
    core.add(g);
  };
  // Piezas de la escena: vienen de Odin → Fondo 3D (formas, tamaño, posición, giro en grados, color acento).
  const SHAPES = { box: THREE.BoxGeometry, cone: THREE.ConeGeometry, cylinder: THREE.CylinderGeometry, sphere: THREE.SphereGeometry, torus: THREE.TorusGeometry,
    icosahedron: THREE.IcosahedronGeometry, octahedron: THREE.OctahedronGeometry, dodecahedron: THREE.DodecahedronGeometry, torusknot: THREE.TorusKnotGeometry };
  const ANGLE_ARGS = { torus: [4], sphere: [3, 4, 5, 6], cylinder: [6, 7], cone: [5, 6] }; // argumentos que son ángulos (en grados)
  const rad = (d) => (d * Math.PI) / 180;
  (cfg.parts || []).forEach((d) => {
    const G = SHAPES[d.shape];
    if (!G) return;
    const args = (d.args || []).map((v, i) => ((ANGLE_ARGS[d.shape] || []).includes(i) ? rad(v) : v));
    part(new G(...args), d.pos || [0, 0, 0], (d.rot || [0, 0, 0]).map(rad), !!d.accent);
  });
  if (!parts.length) {
    core.add(new THREE.Mesh(new THREE.IcosahedronGeometry(1.8, 1), solid));
    core.add(new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.IcosahedronGeometry(1.82, 1)),
      new THREE.LineBasicMaterial({ color: blue, transparent: true, opacity: 0.9 }),
    ));
    core.add(new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.IcosahedronGeometry(2.6, 0)),
      new THREE.LineBasicMaterial({ color: gold, transparent: true, opacity: 0.35 }),
    ));
  }
  scene.add(core);
  const assemble = (t) => {
    // 0 = disperso, 1 = armado. Se arma en ~2,4 s al cargar y se desarma al bajar la primera pantalla
    const load = reduceMotion ? 1 : Math.min(1, t / 2.4);
    const a = (1 - (1 - load) ** 3) * (1 - 0.85 * Math.min(1, scrollY / (innerHeight * 0.8)));
    parts.forEach((p, i) => {
      const e = Math.min(1, Math.max(0, a * 1.5 - i * 0.07));
      const k = 1 - e;
      p.g.position.copy(p.home).addScaledVector(p.off, k);
      p.g.rotation.set(p.rot.x + p.spin.x * k, p.rot.y + p.spin.y * k, p.rot.z + p.spin.z * k);
    });
  };

  const rings = [2.9, 3.5, 4.2].map((r, i) => {
    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(r, 0.012, 8, 160),
      new THREE.MeshBasicMaterial({ color: i === 1 ? gold : blue, transparent: true, opacity: 0.5 }),
    );
    ring.rotation.set(Math.PI / 2 + i * 0.4, i * 0.6, 0);
    if (cfg.rings) scene.add(ring);
    return ring;
  });

  const COUNT = Math.round(cfg.particles * (innerWidth < 760 ? 0.4 : 1));
  const pos = new Float32Array(COUNT * 3);
  for (let i = 0; i < COUNT; i++) {
    const rad = 5 + Math.random() * 18;
    const th = Math.random() * Math.PI * 2;
    const ph = Math.acos(2 * Math.random() - 1);
    pos.set([rad * Math.sin(ph) * Math.cos(th), rad * Math.sin(ph) * Math.sin(th), rad * Math.cos(ph)], i * 3);
  }
  const pGeo = new THREE.BufferGeometry();
  pGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  const particles = new THREE.Points(pGeo, new THREE.PointsMaterial({ color: 0x9ec5ff, size: 0.035, transparent: true, opacity: 0.8 }));
  scene.add(particles);

  scene.add(new THREE.AmbientLight(0xffffff, 0.35));
  const key = new THREE.PointLight(blue, 60, 30); key.position.set(4, 3, 5); scene.add(key);
  const rim = new THREE.PointLight(gold, 40, 30); rim.position.set(-5, -2, 2); scene.add(rim);

  const resize = () => {
    const w = innerWidth, h = innerHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    // En pantallas angostas el núcleo va detrás del texto y más pequeño
    core.position.x = w < 900 || cfg.side === 'center' ? 0 : 3.2;
    core.scale.setScalar(w < 900 ? 0.75 : 1);
    rings.forEach((r) => { r.position.x = core.position.x; r.scale.setScalar(core.scale.x); });
  };
  addEventListener('resize', resize);
  resize();

  const pointer = { x: 0, y: 0 };
  addEventListener('pointermove', (e) => {
    pointer.x = e.clientX / innerWidth - 0.5;
    pointer.y = e.clientY / innerHeight - 0.5;
  }, { passive: true });

  const clock = new THREE.Clock();
  const render = () => {
    const t = clock.getElapsedTime() * cfg.speed;
    const scroll = scrollY / Math.max(1, document.body.scrollHeight - innerHeight);
    if (parts.length) {
      assemble(t);
      core.rotation.set(0.3, t * 0.35, 0); // los modelos giran sobre su eje para que se lean como objetos
    } else {
      core.rotation.set(t * 0.12 + scroll * 2, t * 0.18 + scroll * 3, 0);
    }
    rings.forEach((r, i) => { r.rotation.z = t * (0.05 + i * 0.03) * (i % 2 ? -1 : 1); });
    particles.rotation.y = t * 0.02 + scroll * 0.6;
    camera.position.x += (pointer.x * 1.2 - camera.position.x) * 0.04;
    camera.position.y += (-pointer.y * 0.8 - camera.position.y) * 0.04;
    camera.position.z = 9 + scroll * 4;
    camera.lookAt(0, 0, 0);
    // Pasada la portada la escena se atenúa para no competir con el texto
    canvas.style.opacity = 1 - 0.6 * Math.min(1, scrollY / innerHeight);
    renderer.render(scene, camera);
  };

  if (reduceMotion) {
    render();
    addEventListener('resize', render);
  } else {
    renderer.setAnimationLoop(render);
    // Pausa cuando la pestaña no está visible para no gastar batería
    document.addEventListener('visibilitychange', () => renderer.setAnimationLoop(document.hidden ? null : render));
  }
}
