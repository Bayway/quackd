/**
 * Drawing the world, straight out of the compiled model.
 *
 * MuJoCo has already parsed the MJCF and every mesh in it, so there is no second copy of
 * the robot here and no STL parser: each geom becomes one three.js mesh built from
 * `model.mesh_vert` and `model.mesh_face`, and every frame copies `data.geom_xpos` and
 * `data.geom_xmat` into its transform. Add a body to the MJCF and it appears; nothing in
 * this file knows what a duck is.
 *
 * MuJoCo is z-up and three.js is y-up. Rather than rotating every geom, the whole scene
 * sits under one group rotated -90 degrees about x, so the arithmetic above stays MuJoCo's.
 */

import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.180.0/build/three.module.js";

const PLANE = 0, SPHERE = 2, CAPSULE = 3, ELLIPSOID = 4, CYLINDER = 5, BOX = 6, MESH = 7;

export class View {
  constructor(canvas, duck) {
    this.canvas = canvas;
    this.duck = duck;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0xbcd2e8);
    this.world = new THREE.Group();
    this.world.rotation.x = -Math.PI / 2; // MuJoCo z-up into three.js y-up
    this.scene.add(this.world);
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x9099a6, 2.0));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(1.5, 3, 2);
    this.scene.add(sun);
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.02, 60);
    this.orbit = { azimuth: 2.3, elevation: 0.42, distance: 1.5 };
    this.mode = "follow";
    this.geoms = [];
    this.build();
    this.bindPointer();
  }

  /** One three.js mesh per MuJoCo geom, sized and coloured from the model. */
  build() {
    const { model } = this.duck;
    for (let g = 0; g < model.ngeom; g++) {
      const type = model.geom_type[g];
      const size = [model.geom_size[g * 3], model.geom_size[g * 3 + 1], model.geom_size[g * 3 + 2]];
      const geometry = this.geometryFor(type, size, model.geom_dataid[g]);
      if (!geometry) continue;
      const rgba = [0, 1, 2, 3].map((i) => model.geom_rgba[g * 4 + i]);
      const material = new THREE.MeshLambertMaterial({
        color: new THREE.Color(rgba[0], rgba[1], rgba[2]),
        transparent: rgba[3] < 1,
        opacity: rgba[3],
      });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.matrixAutoUpdate = false;
      this.world.add(mesh);
      this.geoms.push({ index: g, mesh });
    }
  }

  geometryFor(type, size, dataid) {
    switch (type) {
      case PLANE: {
        const half = size[0] > 0 ? size[0] : 6;
        const plane = new THREE.PlaneGeometry(half * 2, (size[1] > 0 ? size[1] : half) * 2, 1, 1);
        return plane; // already in the xy plane, which is MuJoCo's floor
      }
      case SPHERE: return new THREE.SphereGeometry(size[0], 24, 16);
      case ELLIPSOID: {
        const sphere = new THREE.SphereGeometry(1, 24, 16);
        sphere.scale(size[0], size[1], size[2]);
        return sphere;
      }
      case CAPSULE: return new THREE.CapsuleGeometry(size[0], size[1] * 2, 6, 12);
      case CYLINDER: {
        const cylinder = new THREE.CylinderGeometry(size[0], size[0], size[1] * 2, 20);
        cylinder.rotateX(Math.PI / 2); // three.js cylinders run along y; MuJoCo's along z
        return cylinder;
      }
      case BOX: return new THREE.BoxGeometry(size[0] * 2, size[1] * 2, size[2] * 2);
      case MESH: return this.meshGeometry(dataid);
      default: return null;
    }
  }

  meshGeometry(id) {
    const { model } = this.duck;
    if (id < 0) return null;
    const vertexAt = model.mesh_vertadr[id] * 3;
    const vertexCount = model.mesh_vertnum[id];
    const faceAt = model.mesh_faceadr[id] * 3;
    const faceCount = model.mesh_facenum[id];
    const vertices = new Float32Array(vertexCount * 3);
    for (let i = 0; i < vertexCount * 3; i++) vertices[i] = model.mesh_vert[vertexAt + i];
    const indices = new Uint32Array(faceCount * 3);
    for (let i = 0; i < faceCount * 3; i++) indices[i] = model.mesh_face[faceAt + i];
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(vertices, 3));
    geometry.setIndex(new THREE.BufferAttribute(indices, 1));
    geometry.computeVertexNormals();
    return geometry;
  }

  bindPointer() {
    let dragging = false, lastX = 0, lastY = 0;
    this.canvas.addEventListener("pointerdown", (e) => {
      dragging = true; lastX = e.clientX; lastY = e.clientY; this.canvas.setPointerCapture(e.pointerId);
    });
    this.canvas.addEventListener("pointerup", (e) => {
      dragging = false; this.canvas.releasePointerCapture(e.pointerId);
    });
    this.canvas.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      this.orbit.azimuth -= (e.clientX - lastX) * 0.008;
      this.orbit.elevation = Math.max(-0.2, Math.min(1.4, this.orbit.elevation + (e.clientY - lastY) * 0.006));
      lastX = e.clientX; lastY = e.clientY;
    });
    this.canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      this.orbit.distance = Math.max(0.5, Math.min(6, this.orbit.distance * (1 + Math.sign(e.deltaY) * 0.12)));
    }, { passive: false });
  }

  setMode(mode) { this.mode = mode; }

  frame() {
    const { data } = this.duck;
    for (const { index, mesh } of this.geoms) {
      const p = index * 3, m = index * 9;
      mesh.matrix.set(
        data.geom_xmat[m], data.geom_xmat[m + 1], data.geom_xmat[m + 2], data.geom_xpos[p],
        data.geom_xmat[m + 3], data.geom_xmat[m + 4], data.geom_xmat[m + 5], data.geom_xpos[p + 1],
        data.geom_xmat[m + 6], data.geom_xmat[m + 7], data.geom_xmat[m + 8], data.geom_xpos[p + 2],
        0, 0, 0, 1,
      );
    }
    this.placeCamera();
    const width = this.canvas.clientWidth, height = this.canvas.clientHeight;
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.renderer.setSize(width, height, false);
      this.camera.aspect = width / height;
      this.camera.updateProjectionMatrix();
    }
    this.renderer.render(this.scene, this.camera);
  }

  placeCamera() {
    if (this.mode === "duck") {
      // What the robot's own camera sees. Upstream's camera quaternion is not MuJoCo's
      // viewing convention, so forward is the camera frame's +z, not its -z.
      const head = this.duck.headPose();
      const forward = [
        Math.cos(head.pitch) * Math.cos(head.yaw),
        Math.cos(head.pitch) * Math.sin(head.yaw),
        Math.sin(head.pitch),
      ];
      this.camera.position.set(head.x, head.z, -head.y);
      this.camera.up.set(0, 1, 0);
      this.camera.lookAt(head.x + forward[0], head.z + forward[2], -(head.y + forward[1]));
      if (this.camera.fov !== 90) { this.camera.fov = 90; this.camera.updateProjectionMatrix(); }
      return;
    }
    if (this.camera.fov !== 45) { this.camera.fov = 45; this.camera.updateProjectionMatrix(); }
    const { x, y } = this.duck.pose;
    const { azimuth, elevation, distance } = this.orbit;
    const target = new THREE.Vector3(x, 0.14, -y); // three.js coordinates: y up, -z north
    this.camera.position.set(
      target.x + distance * Math.cos(elevation) * Math.cos(azimuth),
      target.y + distance * Math.sin(elevation),
      target.z + distance * Math.cos(elevation) * Math.sin(azimuth),
    );
    this.camera.up.set(0, 1, 0);
    this.camera.lookAt(target);
  }
}
