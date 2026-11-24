// DealDesk hero: a floating night city with listing pins and light-trail traffic.
import * as THREE from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";

const canvas = document.getElementById("city");
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const mobile = matchMedia("(max-width: 820px)").matches;

try { init(); } catch (e) { console.warn("3D scene disabled:", e); }

function init() {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: !mobile, alpha: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(devicePixelRatio, mobile ? 1.25 : 1.75));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;

  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x07070b, 0.028);
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 200);

  // ---------- rig
  const world = new THREE.Group();
  scene.add(world);
  const GOLD = 0xf5b94a, VIOLET = 0x8b7bff, CYAN = 0x4fe3d0, PINK = 0xff5e8a;

  scene.add(new THREE.HemisphereLight(0x8b7bff, 0x07070b, 0.6));
  const key = new THREE.DirectionalLight(0xffd9a0, 0.9); key.position.set(10, 20, 8); scene.add(key);
  const rim = new THREE.PointLight(VIOLET, 60, 60); rim.position.set(-12, 8, -10); scene.add(rim);

  // ---------- platform
  const R = 15;
  const base = new THREE.Mesh(new THREE.CylinderGeometry(R, R * 0.92, 1.2, 96), new THREE.MeshStandardMaterial({ color: 0x0d0c16, roughness: 0.8, metalness: 0.3 }));
  base.position.y = -0.6; world.add(base);
  const edge = new THREE.Mesh(new THREE.TorusGeometry(R, 0.05, 8, 160), new THREE.MeshBasicMaterial({ color: GOLD }));
  edge.rotation.x = Math.PI / 2; world.add(edge);
  const halo = new THREE.Mesh(new THREE.RingGeometry(R + 0.6, R + 3.5, 128), new THREE.MeshBasicMaterial({ color: VIOLET, transparent: true, opacity: 0.08, side: THREE.DoubleSide }));
  halo.rotation.x = -Math.PI / 2; halo.position.y = -0.4; world.add(halo);

  // glowing grid on the ground (shader)
  const gridMat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false,
    uniforms: { uTime: { value: 0 }, uR: { value: R } },
    vertexShader: `varying vec2 vP; void main(){ vP = position.xy; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.); }`,
    fragmentShader: `varying vec2 vP; uniform float uTime; uniform float uR;
      void main(){
        vec2 g = abs(fract(vP*0.5)-0.5)/fwidth(vP*0.5);
        float line = 1.0 - min(min(g.x,g.y),1.0);
        float d = length(vP);
        float wave = smoothstep(1.2,0.0,abs(d - mod(uTime*4.0, uR*1.4)));
        float fade = smoothstep(uR, uR*0.3, d);
        vec3 col = mix(vec3(0.35,0.3,0.9), vec3(1.0,0.75,0.3), wave);
        gl_FragColor = vec4(col, (line*0.22 + wave*0.25*line + wave*0.04) * fade);
      }`,
  });
  gridMat.extensions = { derivatives: true };
  const grid = new THREE.Mesh(new THREE.CircleGeometry(R, 96), gridMat);
  grid.rotation.x = -Math.PI / 2; grid.position.y = 0.01; world.add(grid);

  // ---------- window texture
  function windowTexture() {
    const c = document.createElement("canvas"); c.width = 64; c.height = 128;
    const g = c.getContext("2d"); g.fillStyle = "#000"; g.fillRect(0, 0, 64, 128);
    for (let y = 4; y < 128; y += 8) for (let x = 4; x < 64; x += 8) {
      if (Math.random() < 0.42) { const w = Math.random(); g.fillStyle = w < 0.6 ? "#ffcf7a" : w < 0.85 ? "#9f93ff" : "#7ff0e2"; g.globalAlpha = 0.5 + Math.random() * 0.5; g.fillRect(x, y, 4, 4); }
    }
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.magFilter = THREE.NearestFilter; return t;
  }
  const winTex = windowTexture();

  // ---------- buildings (instanced) — leave roads clear
  const roadHalf = 1.1;
  const onRoad = (x, z) => Math.abs(x) < roadHalf + 0.6 || Math.abs(z) < roadHalf + 0.6 || Math.abs(Math.hypot(x, z) - 9) < roadHalf + 0.5;
  const spots = [];
  for (let x = -13; x <= 13; x += 1.6) for (let z = -13; z <= 13; z += 1.6) {
    const jx = x + (Math.random() - 0.5) * 0.3, jz = z + (Math.random() - 0.5) * 0.3, d = Math.hypot(jx, jz);
    if (d > R - 1.4 || onRoad(jx, jz) || Math.random() < 0.12) continue;
    spots.push([jx, jz, d]);
  }
  const bGeo = new THREE.BoxGeometry(1, 1, 1); bGeo.translate(0, 0.5, 0);
  const bMat = new THREE.MeshStandardMaterial({ color: 0x1a1830, roughness: 0.55, metalness: 0.6, emissive: 0xffffff, emissiveMap: winTex, emissiveIntensity: 1.1 });
  const buildings = new THREE.InstancedMesh(bGeo, bMat, spots.length);
  const m4 = new THREE.Matrix4(), col = new THREE.Color();
  const heights = [];
  spots.forEach(([x, z, d], i) => {
    const centre = Math.max(0, 1 - d / R);
    const h = 0.6 + Math.pow(Math.random(), 2.2) * 7 * centre + centre * 2.2;
    const w = 0.9 + Math.random() * 0.45, dpt = 0.9 + Math.random() * 0.45;
    heights.push(h);
    m4.compose(new THREE.Vector3(x, 0, z), new THREE.Quaternion(), new THREE.Vector3(w, h, dpt));
    buildings.setMatrixAt(i, m4);
    col.setHSL(0.68 + Math.random() * 0.08, 0.35, 0.12 + Math.random() * 0.1); buildings.setColorAt(i, col);
  });
  world.add(buildings);

  // rooftop beacons on the tallest towers
  const tall = spots.map((s, i) => [s, heights[i]]).sort((a, b) => b[1] - a[1]).slice(0, 10);
  const beaconGeo = new THREE.SphereGeometry(0.07, 8, 8);
  const beacons = tall.map(([[x, z], h], i) => {
    const m = new THREE.Mesh(beaconGeo, new THREE.MeshBasicMaterial({ color: i % 3 ? 0xff3b4e : CYAN }));
    m.position.set(x, h + 0.12, z); world.add(m); return m;
  });

  // ---------- roads
  const roadMat = new THREE.MeshStandardMaterial({ color: 0x0a0a10, roughness: 0.9 });
  const roadA = new THREE.Mesh(new THREE.PlaneGeometry(roadHalf * 2, R * 2 - 1), roadMat); roadA.rotation.x = -Math.PI / 2; roadA.position.y = 0.02; world.add(roadA);
  const roadB = roadA.clone(); roadB.rotation.z = Math.PI / 2; world.add(roadB);
  const ring = new THREE.Mesh(new THREE.RingGeometry(9 - roadHalf, 9 + roadHalf, 128), roadMat); ring.rotation.x = -Math.PI / 2; ring.position.y = 0.021; world.add(ring);
  const dash = new THREE.Mesh(new THREE.RingGeometry(8.97, 9.03, 128), new THREE.MeshBasicMaterial({ color: GOLD, transparent: true, opacity: 0.35 }));
  dash.rotation.x = -Math.PI / 2; dash.position.y = 0.03; world.add(dash);

  // ---------- traffic with light trails
  const TRAIL = 22;
  const cars = [];
  function makeCar(path, color, speed, offset) {
    const g = new THREE.Group();
    const bodyM = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.22, 0.26), new THREE.MeshStandardMaterial({ color: 0x15141f, metalness: 0.8, roughness: 0.3 }));
    bodyM.position.y = 0.15; g.add(bodyM);
    const head = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.06, 0.22), new THREE.MeshBasicMaterial({ color: 0xfff3d0 })); head.position.set(0.26, 0.15, 0); g.add(head);
    const tail = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.06, 0.22), new THREE.MeshBasicMaterial({ color: 0xff2a44 })); tail.position.set(-0.26, 0.15, 0); g.add(tail);
    world.add(g);
    const tGeo = new THREE.BufferGeometry();
    const pos = new Float32Array(TRAIL * 3), alpha = new Float32Array(TRAIL);
    for (let i = 0; i < TRAIL; i++) alpha[i] = 1 - i / TRAIL;
    tGeo.setAttribute("position", new THREE.BufferAttribute(pos, 3)); tGeo.setAttribute("alpha", new THREE.BufferAttribute(alpha, 1));
    const tMat = new THREE.ShaderMaterial({ transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, uniforms: { uC: { value: new THREE.Color(color) } },
      vertexShader: `attribute float alpha; varying float vA; void main(){ vA = alpha; vec4 mv = modelViewMatrix*vec4(position,1.); gl_PointSize = 9.0*alpha*(12.0/-mv.z); gl_Position = projectionMatrix*mv; }`,
      fragmentShader: `uniform vec3 uC; varying float vA; void main(){ float d = length(gl_PointCoord-0.5); gl_FragColor = vec4(uC*1.6, smoothstep(0.5,0.0,d)*vA); }` });
    const trail = new THREE.Points(tGeo, tMat); world.add(trail);
    const hist = [];
    cars.push({ g, path, speed, t: offset, trail, hist });
  }
  const ringPath = (dir, r) => (t) => { const a = t * dir; return [Math.cos(a) * r, Math.sin(a) * r, a + (dir > 0 ? Math.PI / 2 : -Math.PI / 2)]; };
  const linePath = (axis, lane, dir) => (t) => { const L = R - 1.6; let s = ((t * dir * 0.6) % 2 + 2) % 2; s = s * L - L; return axis === "x" ? [s * dir, lane, dir > 0 ? 0 : Math.PI] : [lane, s * dir, dir > 0 ? Math.PI / 2 : -Math.PI / 2]; };
  const nCars = mobile ? 6 : 12;
  for (let i = 0; i < nCars; i++) {
    const kind = i % 4, color = [GOLD, CYAN, PINK, VIOLET][i % 4];
    if (kind < 2) makeCar(ringPath(kind ? 1 : -1, kind ? 9.45 : 8.55), color, 0.22 + Math.random() * 0.1, Math.random() * 10);
    else if (kind === 2) makeCar(linePath("x", Math.random() < 0.5 ? 0.45 : -0.45, Math.random() < 0.5 ? 1 : -1), color, 0.35 + Math.random() * 0.15, Math.random() * 10);
    else makeCar(linePath("z", Math.random() < 0.5 ? 0.45 : -0.45, Math.random() < 0.5 ? 1 : -1), color, 0.35 + Math.random() * 0.15, Math.random() * 10);
  }

  // ---------- listing pins
  const pinGroup = new THREE.Group(); world.add(pinGroup);
  const pins = [];
  const pinSpots = spots.filter((s, i) => heights[i] < 2.4 && s[2] > 4 && s[2] < R - 2).sort(() => Math.random() - 0.5).slice(0, mobile ? 5 : 8);
  pinSpots.forEach(([x, z], i) => {
    const color = i % 2 ? GOLD : CYAN;
    const h = spots.indexOf(pinSpots[i]); const top = (heights[h] || 1) + 1.2;
    const p = new THREE.Group();
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.28, 20, 20), new THREE.MeshBasicMaterial({ color }));
    const cone = new THREE.Mesh(new THREE.ConeGeometry(0.2, 0.55, 20), new THREE.MeshBasicMaterial({ color })); cone.rotation.x = Math.PI; cone.position.y = -0.38;
    const dot = new THREE.Mesh(new THREE.SphereGeometry(0.11, 12, 12), new THREE.MeshBasicMaterial({ color: 0x07070b })); dot.position.z = 0.22;
    p.add(head, cone, dot); p.position.set(x, top, z); pinGroup.add(p);
    const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, top, 6), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.35 }));
    beam.position.set(x, top / 2, z); pinGroup.add(beam);
    const pulse = new THREE.Mesh(new THREE.RingGeometry(0.3, 0.38, 40), new THREE.MeshBasicMaterial({ color, transparent: true, side: THREE.DoubleSide }));
    pulse.rotation.x = -Math.PI / 2; pulse.position.set(x, 0.05, z); pinGroup.add(pulse);
    pins.push({ p, pulse, base: top, ph: Math.random() * 6 });
  });

  // ---------- particles
  const PN = mobile ? 400 : 1100;
  const pGeo = new THREE.BufferGeometry(); const pp = new Float32Array(PN * 3);
  for (let i = 0; i < PN; i++) { const a = Math.random() * Math.PI * 2, r = Math.random() * 30; pp[i * 3] = Math.cos(a) * r; pp[i * 3 + 1] = Math.random() * 18; pp[i * 3 + 2] = Math.sin(a) * r; }
  pGeo.setAttribute("position", new THREE.BufferAttribute(pp, 3));
  const dust = new THREE.Points(pGeo, new THREE.PointsMaterial({ color: 0xc9bfff, size: 0.05, transparent: true, opacity: 0.7, depthWrite: false, blending: THREE.AdditiveBlending }));
  scene.add(dust);

  // orbit rings in the sky
  const orbit = new THREE.Mesh(new THREE.TorusGeometry(18, 0.02, 6, 200), new THREE.MeshBasicMaterial({ color: GOLD, transparent: true, opacity: 0.35 }));
  orbit.rotation.set(Math.PI / 2.3, 0.2, 0); orbit.position.y = 4; scene.add(orbit);
  const orbit2 = new THREE.Mesh(new THREE.TorusGeometry(21, 0.015, 6, 200), new THREE.MeshBasicMaterial({ color: VIOLET, transparent: true, opacity: 0.3 }));
  orbit2.rotation.set(Math.PI / 1.8, -0.3, 0); orbit2.position.y = 3; scene.add(orbit2);
  const sat = new THREE.Mesh(new THREE.SphereGeometry(0.18, 12, 12), new THREE.MeshBasicMaterial({ color: GOLD })); scene.add(sat);

  // ---------- post
  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), mobile ? 0.7 : 0.95, 0.6, 0.18);
  composer.addPass(bloom);
  composer.addPass(new OutputPass());

  // ---------- layout / camera framing
  let wide = true;
  function resize() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    renderer.setSize(w, h, false); composer.setSize(w, h); bloom.setSize(w, h);
    camera.aspect = w / h;
    wide = w > 1020;
    camera.updateProjectionMatrix();
  }
  addEventListener("resize", resize); resize();

  let mx = 0, my = 0, cmx = 0, cmy = 0;
  addEventListener("pointermove", (e) => { mx = e.clientX / innerWidth - 0.5; my = e.clientY / innerHeight - 0.5; }, { passive: true });

  let visible = true;
  new IntersectionObserver(([e]) => { visible = e.isIntersecting; }, { threshold: 0 }).observe(canvas);

  const clock = new THREE.Clock();
  const tmp = new THREE.Vector3();
  function frame() { requestAnimationFrame(frame); if (visible) step(Math.min(clock.getDelta(), 0.05), clock.elapsedTime); }
  function step(dt, t) {
    cmx += (mx - cmx) * 0.04; cmy += (my - cmy) * 0.04;

    world.rotation.y = t * 0.045 + cmx * 0.5;
    const scroll = Math.min(1, scrollY / innerHeight);
    const dist = (wide ? 34 : 40) + scroll * 6;
    camera.position.set(Math.sin(0.6) * dist + cmx * 3, 15 + cmy * -4 + scroll * 4, Math.cos(0.6) * dist);
    camera.lookAt(wide ? -7 : 0, wide ? 1.2 : 3.5, 0);

    gridMat.uniforms.uTime.value = t;
    beacons.forEach((b, i) => { b.visible = Math.sin(t * 3 + i * 1.7) > -0.2; });
    pins.forEach((p) => {
      p.p.position.y = p.base + Math.sin(t * 2 + p.ph) * 0.18; p.p.rotation.y = t * 1.5 + p.ph;
      const k = (t * 0.6 + p.ph) % 1; p.pulse.scale.setScalar(1 + k * 4); p.pulse.material.opacity = (1 - k) * 0.8;
    });
    cars.forEach((c) => {
      c.t += dt * c.speed;
      const [x, z, a] = c.path(c.t);
      c.g.position.set(x, 0.02, z); c.g.rotation.y = -a;
      c.hist.unshift([x, 0.17, z]); if (c.hist.length > TRAIL) c.hist.pop();
      const arr = c.trail.geometry.attributes.position.array;
      for (let i = 0; i < TRAIL; i++) { const h = c.hist[Math.min(i, c.hist.length - 1)]; arr[i * 3] = h[0]; arr[i * 3 + 1] = h[1]; arr[i * 3 + 2] = h[2]; }
      // break the trail when a straight-road car wraps around
      for (let i = 1; i < c.hist.length; i++) { const p0 = c.hist[i - 1], p1 = c.hist[i]; if (Math.abs(p0[0] - p1[0]) + Math.abs(p0[2] - p1[2]) > 3) { for (let j = i; j < TRAIL; j++) { arr[j * 3] = p0[0]; arr[j * 3 + 1] = p0[1]; arr[j * 3 + 2] = p0[2]; } break; } }
      c.trail.geometry.attributes.position.needsUpdate = true;
    });
    dust.rotation.y = t * 0.01; dust.position.y = Math.sin(t * 0.3) * 0.3;
    orbit.rotation.z = t * 0.05; orbit2.rotation.z = -t * 0.04;
    tmp.set(Math.cos(t * 0.35) * 18, 0, Math.sin(t * 0.35) * 18).applyEuler(orbit.rotation); sat.position.copy(tmp).add(orbit.position);
    rim.intensity = 50 + Math.sin(t) * 15;

    composer.render();
  }
  if (reduced) { for (let i = 0; i < TRAIL; i++) step(0.05, 3 + i * 0.05); addEventListener("resize", () => step(0, 4)); }
  else frame();
  requestAnimationFrame(() => canvas.classList.add("ready"));
}
