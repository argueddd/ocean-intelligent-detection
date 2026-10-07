import React, { useEffect, useRef } from "react";
import * as THREE from "three";

const ACCENT = new THREE.Color("#0753d7");
const MAX_LINE_SEGMENTS = 220;

function randomAt(seed) {
  const value = Math.sin(seed * 12.9898 + 78.233) * 43758.5453;
  return value - Math.floor(value);
}

function pointOnPolyline(points, progress) {
  const scaled = Math.min(progress, 0.999999) * (points.length - 1);
  const segment = Math.floor(scaled);
  const local = scaled - segment;
  const start = points[segment];
  const end = points[segment + 1];
  return [
    start[0] + (end[0] - start[0]) * local,
    start[1] + (end[1] - start[1]) * local,
    start[2] + (end[2] - start[2]) * local,
  ];
}

function pointOnTube(start, end, progress, angle, radius) {
  const dx = end[0] - start[0];
  const dy = end[1] - start[1];
  const dz = end[2] - start[2];
  const length = Math.hypot(dx, dy, dz) || 1;
  const tx = dx / length;
  const ty = dy / length;
  const tz = dz / length;
  const planarLength = Math.hypot(tx, ty);
  const nx = planarLength > 0.001 ? -ty / planarLength : 1;
  const ny = planarLength > 0.001 ? tx / planarLength : 0;
  const nz = 0;
  const bx = -tz * ny;
  const by = tz * nx;
  const bz = tx * ny - ty * nx;
  const cosine = Math.cos(angle) * radius;
  const sine = Math.sin(angle) * radius;
  return [
    start[0] + dx * progress + nx * cosine + bx * sine,
    start[1] + dy * progress + ny * cosine + by * sine,
    start[2] + dz * progress + nz * cosine + bz * sine,
  ];
}

function pointOnBox(center, halfSize, randA, randB, randC) {
  const face = Math.floor(randA * 6);
  const a = randB * 2 - 1;
  const b = randC * 2 - 1;
  const [halfWidth, halfHeight, halfDepth] = halfSize;
  const faces = [
    [halfWidth, a * halfHeight, b * halfDepth],
    [-halfWidth, a * halfHeight, b * halfDepth],
    [a * halfWidth, halfHeight, b * halfDepth],
    [a * halfWidth, -halfHeight, b * halfDepth],
    [a * halfWidth, b * halfHeight, halfDepth],
    [a * halfWidth, b * halfHeight, -halfDepth],
  ];
  return [
    center[0] + faces[face][0],
    center[1] + faces[face][1],
    center[2] + faces[face][2],
  ];
}

function pointOnBoxEdge(center, halfSize, edgeIndex, progress) {
  const [halfWidth, halfHeight, halfDepth] = halfSize;
  const signA = edgeIndex % 2 === 0 ? -1 : 1;
  const signB = Math.floor(edgeIndex / 2) % 2 === 0 ? -1 : 1;
  const axis = Math.floor(edgeIndex / 4) % 3;
  if (axis === 0) {
    return [
      center[0] - halfWidth + progress * halfWidth * 2,
      center[1] + signA * halfHeight,
      center[2] + signB * halfDepth,
    ];
  }
  if (axis === 1) {
    return [
      center[0] + signA * halfWidth,
      center[1] - halfHeight + progress * halfHeight * 2,
      center[2] + signB * halfDepth,
    ];
  }
  return [
    center[0] + signA * halfWidth,
    center[1] + signB * halfHeight,
    center[2] - halfDepth + progress * halfDepth * 2,
  ];
}

function pointOnRectangle(centerX, centerY, centerZ, halfWidth, halfDepth, progress) {
  const perimeterProgress = Math.min(progress, 0.999999) * 4;
  const edge = Math.floor(perimeterProgress);
  const local = perimeterProgress - edge;
  if (edge === 0) {
    return [centerX - halfWidth + local * halfWidth * 2, centerY, centerZ - halfDepth];
  }
  if (edge === 1) {
    return [centerX + halfWidth, centerY, centerZ - halfDepth + local * halfDepth * 2];
  }
  if (edge === 2) {
    return [centerX + halfWidth - local * halfWidth * 2, centerY, centerZ + halfDepth];
  }
  return [centerX - halfWidth, centerY, centerZ + halfDepth - local * halfDepth * 2];
}

const CITY_BUILDINGS = [
  [-1.2, -0.72, 0.32, 0.27, 0.62],
  [-0.64, -0.7, 0.28, 0.3, 1.12],
  [0.58, -0.72, 0.36, 0.28, 0.78],
  [1.18, -0.7, 0.26, 0.32, 1.34],
  [-1.18, -0.06, 0.3, 0.28, 1.18],
  [-0.62, -0.04, 0.34, 0.3, 0.7],
  [0.6, -0.02, 0.3, 0.31, 1.48],
  [1.18, -0.02, 0.27, 0.3, 0.92],
  [-1.18, 0.65, 0.3, 0.29, 0.82],
  [-0.62, 0.66, 0.4, 0.28, 1.28],
  [0.6, 0.67, 0.3, 0.3, 0.96],
  [1.18, 0.66, 0.34, 0.27, 1.56],
];

function generateShape(shape, count) {
  const positions = new Float32Array(count * 3);

  for (let index = 0; index < count; index += 1) {
    const offset = index * 3;
    const progress = (index + 0.5) / count;
    const randA = randomAt(index + shape * 1009);
    const randB = randomAt(index * 1.73 + shape * 2027);
    const randC = randomAt(index * 2.41 + shape * 3011);
    let x = 0;
    let y = 0;
    let z = 0;

    if (shape === 0) {
      if (progress < 0.58) {
        y = -1.32 + randB * 2.42;
        const lowerWidth = 0.18 + ((y + 1.32) / 1.12) * 0.9;
        const upperWidth = 1.08 - Math.max(0, y - 0.72) * 0.55;
        const halfWidth = y < -0.2 ? lowerWidth : upperWidth;
        x = (randA * 2 - 1) * halfWidth;
        const normalizedX = x / Math.max(halfWidth, 0.1);
        z = 0.08 + (1 - normalizedX * normalizedX) * 0.19 + (randC - 0.5) * 0.13;
      } else if (progress < 0.78) {
        const shieldOutline = [
          [0, 1.18, 0.27],
          [1.04, 0.87, 0.25],
          [0.98, -0.34, 0.24],
          [0.62, -0.94, 0.22],
          [0, -1.4, 0.2],
          [-0.62, -0.94, 0.22],
          [-0.98, -0.34, 0.24],
          [-1.04, 0.87, 0.25],
          [0, 1.18, 0.27],
        ];
        const rimProgress = (progress - 0.58) / 0.2;
        [x, y, z] = pointOnPolyline(shieldOutline, rimProgress);
        const innerRim = index % 3 === 0 ? 0.82 : 1;
        x = x * innerRim + (randA - 0.5) * 0.035;
        y = y * innerRim + (randB - 0.5) * 0.035;
        z += (randC - 0.5) * 0.05;
      } else if (progress < 0.92) {
        const checkPath = [
          [-0.5, -0.05, 0.36],
          [-0.14, -0.43, 0.38],
          [0.64, 0.47, 0.36],
        ];
        [x, y, z] = pointOnPolyline(
          checkPath,
          (progress - 0.78) / 0.14,
        );
        x += (randA - 0.5) * 0.09;
        y += (randB - 0.5) * 0.09;
        z += (randC - 0.5) * 0.08;
      } else {
        const scanLines = [
          [[-0.67, 0.62, 0.31], [-0.23, 0.62, 0.34]],
          [[0.23, 0.74, 0.34], [0.68, 0.74, 0.3]],
          [[-0.68, -0.68, 0.25], [-0.35, -0.68, 0.31]],
          [[0.35, -0.65, 0.31], [0.66, -0.65, 0.25]],
        ];
        const line = scanLines[index % scanLines.length];
        [x, y, z] = pointOnTube(
          line[0],
          line[1],
          randA,
          randB * Math.PI * 2,
          0.025,
        );
      }
    } else if (shape === 1) {
      const columns = Math.ceil(Math.sqrt(count));
      const gridX = (index % columns) / columns;
      const gridY = Math.floor(index / columns) / columns;
      x = (gridX - 0.5) * 3.1;
      z = (gridY - 0.5) * 3.1;
      y = Math.sin(x * 2.7 + z * 0.7) * 0.3 + Math.cos(z * 2.25) * 0.26;
    } else if (shape === 2) {
      if (progress < 0.58) {
        const side = index % 2 === 0 ? -1 : 1;
        const theta = randC * Math.PI * 2;
        const ringLevels = [-0.82, -0.26, 0.3, 0.86];
        const radiusX = 0.5;
        const radiusZ = 0.36;
        x = side * 0.94 + Math.cos(theta) * radiusX;
        z = Math.sin(theta) * radiusZ;
        if (randA < 0.72) {
          y = ringLevels[Math.floor(randB * ringLevels.length)];
          x += (randA - 0.36) * 0.025;
          z += (randB - 0.5) * 0.025;
        } else if (randA < 0.92) {
          y = -0.82 + randB * 1.68;
        } else {
          const diskRadius = Math.sqrt(randB);
          x = side * 0.94 + Math.cos(theta) * radiusX * diskRadius;
          z = Math.sin(theta) * radiusZ * diskRadius;
          y = 0.86;
        }
      } else if (progress < 0.76) {
        const lane = index % 5;
        const start = [-0.46, -0.58 + lane * 0.29, 0.04];
        const end = [0.46, -0.58 + lane * 0.29, 0.04];
        const bridgeProgress = randA;
        [x, y, z] = pointOnTube(
          start,
          end,
          bridgeProgress,
          randB * Math.PI * 2,
          0.024,
        );
        z += Math.sin(bridgeProgress * Math.PI) * (0.38 + lane * 0.025);
      } else if (progress < 0.92) {
        const localProgress = (progress - 0.76) / 0.16;
        if (index % 3 !== 0) {
          const verificationFrame = [
            [0, 0.63, 0.7],
            [0.48, 0.06, 0.72],
            [0, -0.52, 0.74],
            [-0.48, 0.06, 0.72],
            [0, 0.63, 0.7],
          ];
          [x, y, z] = pointOnPolyline(verificationFrame, localProgress);
        } else {
          const checkPath = [
            [-0.25, 0.04, 0.82],
            [-0.05, -0.17, 0.84],
            [0.3, 0.27, 0.82],
          ];
          [x, y, z] = pointOnPolyline(checkPath, randA);
        }
        x += (randA - 0.5) * 0.04;
        y += (randB - 0.5) * 0.04;
      } else {
        const theta = randA * Math.PI * 2;
        const outer = index % 2 === 0 ? 1 : 0.72;
        x = Math.cos(theta) * 1.62 * outer;
        y = -1.02 + (randB - 0.5) * 0.035;
        z = Math.sin(theta) * 0.62 * outer;
      }
    } else if (shape === 3) {
      if (progress < 0.22) {
        const gridLine = index % 2;
        const lineIndex = Math.floor(index / 2) % 11;
        const linePosition = -1.55 + (lineIndex / 10) * 3.1;
        if (gridLine === 0) {
          x = linePosition;
          z = -1.08 + randA * 2.16;
        } else {
          x = -1.55 + randA * 3.1;
          z = linePosition * 0.7;
        }
        y = -0.82 + (randB - 0.5) * 0.025;
      } else if (progress < 0.79) {
        const building = CITY_BUILDINGS[index % CITY_BUILDINGS.length];
        const [sourceX, sourceZ, sourceWidth, sourceDepth, height] = building;
        const buildingX = sourceX * 0.88;
        const buildingZ = sourceZ * 0.84;
        const halfWidth = sourceWidth * 1.08;
        const halfDepth = sourceDepth * 1.08;
        const center = [buildingX, -0.82 + height / 2, buildingZ];
        const halfSize = [halfWidth, height / 2, halfDepth];
        if (randA < 0.56) {
          const floorCount = Math.max(3, Math.round(height * 5));
          const floor = index % floorCount;
          const floorY = -0.82 + (floor / (floorCount - 1)) * height;
          [x, y, z] = pointOnRectangle(
            buildingX,
            floorY,
            buildingZ,
            halfWidth,
            halfDepth,
            randB,
          );
          x += (randC - 0.5) * 0.014;
          z += (randA - 0.28) * 0.014;
        } else if (randA < 0.78) {
          [x, y, z] = pointOnBoxEdge(
            center,
            halfSize,
            index % 12,
            randB,
          );
          x += (randC - 0.5) * 0.018;
          z += (randA - 0.2) * 0.018;
        } else if (randA < 0.88) {
          x = buildingX + (randB * 2 - 1) * halfWidth;
          y = -0.82 + height;
          z = buildingZ + (randC * 2 - 1) * halfDepth;
        } else {
          [x, y, z] = pointOnBox(
            center,
            halfSize,
            randA,
            randB,
            randC,
          );
        }
      } else if (progress < 0.91) {
        const markerProgress = (progress - 0.79) / 0.12;
        const markerCenter = [0.03, 0.98, 0.52];
        if (markerProgress < 0.64) {
          const theta = (markerProgress / 0.64) * Math.PI * 2;
          x = markerCenter[0] + Math.cos(theta) * 0.22;
          y = markerCenter[1] + Math.sin(theta) * 0.22;
          z = markerCenter[2] + (randA - 0.5) * 0.055;
        } else if (index % 2 === 0) {
          [x, y, z] = pointOnTube(
            [-0.13, 0.82, 0.52],
            [0.03, 0.36, 0.5],
            randA,
            randB * Math.PI * 2,
            0.022,
          );
        } else {
          [x, y, z] = pointOnTube(
            [0.19, 0.82, 0.52],
            [0.03, 0.36, 0.5],
            randA,
            randB * Math.PI * 2,
            0.022,
          );
        }
      } else {
        const theta = randA * Math.PI * 2;
        const ring = index % 3;
        const radiusX = 0.34 + ring * 0.18;
        const radiusZ = 0.2 + ring * 0.11;
        x = 0.03 + Math.cos(theta) * radiusX;
        y = -0.79 + (randB - 0.5) * 0.018;
        z = 0.08 + Math.sin(theta) * radiusZ;
      }
    } else if (shape === 4) {
      if (progress < 0.2) {
        const localProgress = progress / 0.2;
        const phi = Math.acos(1 - 2 * localProgress);
        const theta = Math.PI * (1 + Math.sqrt(5)) * index;
        x = -0.27 + 0.42 * Math.sin(phi) * Math.cos(theta);
        y = 0.85 + 0.5 * Math.cos(phi);
        z = 0.34 * Math.sin(phi) * Math.sin(theta);
      } else if (progress < 0.55) {
        y = -1.16 + randB * 1.5;
        const torsoProgress = (y + 1.16) / 1.5;
        const halfWidth = 0.43 + torsoProgress * 0.43;
        x = -0.25 + (randA * 2 - 1) * halfWidth;
        const normalizedX = (x + 0.25) / halfWidth;
        z = (randC * 2 - 1) * 0.27 * Math.sqrt(Math.max(0, 1 - normalizedX * normalizedX));
      } else if (progress < 0.72) {
        const arm = index % 3;
        if (arm === 0) {
          [x, y, z] = pointOnTube(
            [-0.96, 0.16, 0],
            [-0.9, -0.78, 0.04],
            randA,
            randB * Math.PI * 2,
            0.09,
          );
        } else if (arm === 1) {
          [x, y, z] = pointOnTube(
            [0.48, 0.2, 0.02],
            [0.74, -0.1, 0.12],
            randA,
            randB * Math.PI * 2,
            0.1,
          );
        } else {
          [x, y, z] = pointOnTube(
            [0.74, -0.1, 0.12],
            [0.34, 0.48, 0.19],
            randA,
            randB * Math.PI * 2,
            0.085,
          );
        }
      } else if (progress < 0.87) {
        if (index % 4 !== 0) {
          [x, y, z] = pointOnTube(
            [0.32, 0.36, 0.2],
            [0.48, 0.97, 0.18],
            randA,
            randB * Math.PI * 2,
            0.055,
          );
        } else {
          const phi = Math.acos(1 - 2 * randA);
          const theta = randB * Math.PI * 2;
          x = 0.5 + 0.16 * Math.sin(phi) * Math.cos(theta);
          y = 1.08 + 0.23 * Math.cos(phi);
          z = 0.18 + 0.14 * Math.sin(phi) * Math.sin(theta);
        }
      } else if (progress < 0.94) {
        const hairAngle = Math.PI * (0.08 + randA * 0.84);
        x = -0.27 + Math.cos(hairAngle) * 0.45;
        y = 0.86 + Math.sin(hairAngle) * 0.54;
        z = 0.02 + (randB - 0.5) * 0.32;
      } else {
        const wave = index % 3;
        const angle = -0.88 + randA * 1.76;
        const radius = 0.28 + wave * 0.17;
        x = 0.54 + Math.cos(angle) * radius;
        y = 1.08 + Math.sin(angle) * radius;
        z = 0.2 + (randB - 0.5) * 0.035;
      }
    } else if (shape === 5) {
      if (progress < 0.55) {
        const localProgress = progress / 0.55;
        const phi = Math.acos(1 - 2 * localProgress);
        const theta = Math.PI * (1 + Math.sqrt(5)) * index;
        const radius = 0.96 + randC * 0.12;
        x = radius * Math.sin(phi) * Math.cos(theta);
        y = radius * Math.cos(phi);
        z = radius * Math.sin(phi) * Math.sin(theta);
      } else if (progress < 0.72) {
        const radius = 1.045;
        if (index % 2 === 0) {
          const latitude = -0.82 + ((index % 7) / 6) * 1.64;
          const theta = randA * Math.PI * 2;
          const ringRadius = Math.cos(latitude) * radius;
          x = Math.cos(theta) * ringRadius;
          y = Math.sin(latitude) * radius;
          z = Math.sin(theta) * ringRadius;
        } else {
          const longitude = ((index % 8) / 8) * Math.PI * 2;
          const phi = randA * Math.PI;
          x = Math.sin(phi) * Math.cos(longitude) * radius;
          y = Math.cos(phi) * radius;
          z = Math.sin(phi) * Math.sin(longitude) * radius;
        }
        x += (randB - 0.5) * 0.018;
        y += (randC - 0.5) * 0.018;
      } else if (progress < 0.9) {
        const ring = index % 2;
        const theta = randA * Math.PI * 2;
        const radius = ring === 0 ? 1.5 : 1.34;
        const axisA = Math.cos(theta) * radius;
        const axisB = Math.sin(theta) * radius;
        if (ring === 0) {
          x = axisA;
          y = axisB * 0.48;
          z = axisB * 0.78;
        } else {
          x = axisA * 0.82;
          y = axisB * 0.76;
          z = axisA * 0.43;
        }
        x += (randB - 0.5) * 0.024;
        y += (randC - 0.5) * 0.024;
      } else {
        const satellite = index % 5;
        const satelliteAngle = (satellite / 5) * Math.PI * 2 + 0.24;
        const orbitRadius = 1.5;
        const centerX = Math.cos(satelliteAngle) * orbitRadius;
        const centerY = Math.sin(satelliteAngle) * orbitRadius * 0.48;
        const centerZ = Math.sin(satelliteAngle) * orbitRadius * 0.78;
        const phi = Math.acos(1 - 2 * randA);
        const theta = randB * Math.PI * 2;
        const satelliteRadius = satellite === 0 ? 0.14 : 0.095;
        x = centerX + satelliteRadius * Math.sin(phi) * Math.cos(theta);
        y = centerY + satelliteRadius * Math.cos(phi);
        z = centerZ + satelliteRadius * Math.sin(phi) * Math.sin(theta);
      }
    } else if (shape === 6) {
      const side = index % 2 === 0 ? -1 : 1;
      const pageX = randA;
      x = side * (0.08 + pageX * 1.28);
      y = (randB - 0.5) * 1.72;
      z = Math.sin(pageX * Math.PI) * 0.34 + side * y * 0.045;
    } else if (shape === 7) {
      const heights = [0.72, 1.18, 0.94, 1.72, 1.38];
      const bar = index % heights.length;
      const halfHeight = heights[bar] / 2;
      const halfWidth = 0.18;
      const halfDepth = 0.3;
      const face = Math.floor(randA * 6);
      const a = randB * 2 - 1;
      const b = randC * 2 - 1;
      const faces = [
        [halfWidth, a * halfHeight, b * halfDepth],
        [-halfWidth, a * halfHeight, b * halfDepth],
        [a * halfWidth, halfHeight, b * halfDepth],
        [a * halfWidth, -halfHeight, b * halfDepth],
        [a * halfWidth, b * halfHeight, halfDepth],
        [a * halfWidth, b * halfHeight, -halfDepth],
      ];
      [x, y, z] = faces[face];
      x += (bar - 2) * 0.56;
      y += -0.88 + halfHeight;
    } else if (shape === 8) {
      // Deep-sea research vessel: hull, bridge, mast and a restrained sonar fan.
      if (progress < 0.48) {
        const hullProgress = randA;
        x = -1.44 + hullProgress * 2.94;
        const sternTaper = Math.min(1, 0.72 + hullProgress * 3.5);
        const bowTaper = hullProgress > 0.68
          ? Math.max(0.08, (1 - hullProgress) / 0.32)
          : 1;
        const halfBeam = 0.43 * sternTaper * Math.sqrt(bowTaper);
        const crossSection = randB * Math.PI * 2;
        const depth = (0.3 + Math.sin(hullProgress * Math.PI) * 0.16) * Math.sqrt(bowTaper);
        z = Math.cos(crossSection) * halfBeam * (0.86 + randC * 0.14);
        y = -0.2 + Math.sin(crossSection) * depth;
        if (Math.sin(crossSection) > 0.35) y *= 0.72;
      } else if (progress < 0.57) {
        const side = index % 2 === 0 ? -1 : 1;
        const hullOutline = [
          [-1.42, 0.02, side * 0.3],
          [-1.04, 0.12, side * 0.39],
          [0.82, 0.12, side * 0.39],
          [1.48, -0.02, side * 0.05],
          [1.1, -0.46, side * 0.12],
          [-0.82, -0.58, side * 0.27],
          [-1.42, 0.02, side * 0.3],
        ];
        [x, y, z] = pointOnPolyline(hullOutline, randA);
        x += (randB - 0.5) * 0.025;
        y += (randC - 0.5) * 0.025;
      } else if (progress < 0.71) {
        const upper = index % 3 === 0;
        const center = upper ? [0.08, 0.52, 0] : [-0.24, 0.25, 0];
        const halfSize = upper ? [0.38, 0.16, 0.27] : [0.72, 0.17, 0.33];
        [x, y, z] = pointOnBox(center, halfSize, randA, randB, randC);
      } else if (progress < 0.8) {
        const window = index % 4;
        const centerX = -0.2 + window * 0.18;
        const side = index % 2 === 0 ? -1 : 1;
        const windowOutline = [
          [centerX - 0.065, 0.55, side * 0.285],
          [centerX + 0.065, 0.55, side * 0.285],
          [centerX + 0.055, 0.64, side * 0.285],
          [centerX - 0.055, 0.64, side * 0.285],
          [centerX - 0.065, 0.55, side * 0.285],
        ];
        [x, y, z] = pointOnPolyline(windowOutline, randA);
        z += (randB - 0.5) * 0.012;
      } else if (progress < 0.89) {
        const mastPart = index % 5;
        if (mastPart < 2) {
          [x, y, z] = pointOnTube(
            [-0.08, 0.67, 0],
            [-0.08, 1.18, 0],
            randA,
            randB * Math.PI * 2,
            0.025,
          );
        } else if (mastPart < 4) {
          [x, y, z] = pointOnTube(
            [-0.36, 1.02, 0],
            [0.2, 1.02, 0],
            randA,
            randB * Math.PI * 2,
            0.022,
          );
        } else {
          const angle = randA * Math.PI * 2;
          x = -0.08 + Math.cos(angle) * 0.16;
          y = 1.19 + Math.sin(angle) * 0.09;
          z = (randB - 0.5) * 0.035;
        }
      } else {
        const source = [0.18, -0.5, 0];
        if (index % 4 !== 0) {
          const band = index % 3;
          const angle = -0.82 + randA * 1.64;
          const radius = 0.52 + band * 0.26;
          x = source[0] + Math.sin(angle) * radius;
          y = source[1] - Math.cos(angle) * radius;
          z = (randB - 0.5) * (0.035 + band * 0.018);
        } else {
          const ray = index % 5;
          const angle = -0.74 + (ray / 4) * 1.48;
          const radius = 0.98;
          [x, y, z] = pointOnTube(
            source,
            [
              source[0] + Math.sin(angle) * radius,
              source[1] - Math.cos(angle) * radius,
              0,
            ],
            randA,
            randB * Math.PI * 2,
            0.012,
          );
        }
      }
    } else {
      if (progress < 0.26) {
        const coreProgress = progress / 0.26;
        const phi = Math.acos(1 - 2 * coreProgress);
        const theta = Math.PI * (1 + Math.sqrt(5)) * index;
        const radius = 0.38 + randA * 0.1;
        x = radius * Math.sin(phi) * Math.cos(theta);
        y = radius * Math.cos(phi);
        z = radius * Math.sin(phi) * Math.sin(theta);
      } else {
        const satellite = index % 8;
        const angle = (satellite / 8) * Math.PI * 2;
        const targetX = Math.cos(angle) * 1.5;
        const targetY = Math.sin(angle) * 1.06;
        const targetZ = Math.sin(angle * 2) * 0.5;
        if (randC < 0.62) {
          const distance = randA;
          x = targetX * distance + (randB - 0.5) * 0.06;
          y = targetY * distance + (randC - 0.5) * 0.06;
          z = targetZ * distance + (randB - 0.5) * 0.06;
        } else {
          const theta = Math.PI * 2 * randA;
          const phi = Math.acos(1 - 2 * randB);
          const radius = 0.12 + randC * 0.1;
          x = targetX + radius * Math.sin(phi) * Math.cos(theta);
          y = targetY + radius * Math.cos(phi);
          z = targetZ + radius * Math.sin(phi) * Math.sin(theta);
        }
      }
    }

    positions[offset] = x;
    positions[offset + 1] = y;
    positions[offset + 2] = z;
  }

  return positions;
}

function buildLinePairs(positions, count) {
  const targetSamples = 480;
  const sampleStep = Math.max(1, Math.floor(count / targetSamples));
  const cellSize = 0.44;
  const maxDistanceSquared = 0.72 ** 2;
  const minDistanceSquared = 0.1 ** 2;
  const preferredDistance = 0.27;
  const buckets = new Map();
  const samples = [];

  const getCell = (index) => {
    const offset = index * 3;
    return [
      Math.floor(positions[offset] / cellSize),
      Math.floor(positions[offset + 1] / cellSize),
      Math.floor(positions[offset + 2] / cellSize),
    ];
  };

  for (let index = 0; index < count; index += sampleStep) {
    const cell = getCell(index);
    const key = cell.join(":");
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(index);
    samples.push(index);
  }

  const candidates = [];
  for (const index of samples) {
    const [cellX, cellY, cellZ] = getCell(index);
    const offset = index * 3;
    let nearest = -1;
    let nearestDistance = maxDistanceSquared;

    for (let x = -1; x <= 1; x += 1) {
      for (let y = -1; y <= 1; y += 1) {
        for (let z = -1; z <= 1; z += 1) {
          const nearby = buckets.get(
            `${cellX + x}:${cellY + y}:${cellZ + z}`,
          );
          if (!nearby) continue;

          for (const candidate of nearby) {
            if (candidate === index) continue;
            const candidateOffset = candidate * 3;
            const deltaX = positions[offset] - positions[candidateOffset];
            const deltaY =
              positions[offset + 1] - positions[candidateOffset + 1];
            const deltaZ =
              positions[offset + 2] - positions[candidateOffset + 2];
            const distance =
              deltaX * deltaX + deltaY * deltaY + deltaZ * deltaZ;
            if (
              distance > minDistanceSquared &&
              distance < nearestDistance
            ) {
              nearest = candidate;
              nearestDistance = distance;
            }
          }
        }
      }
    }

    if (nearest >= 0) {
      candidates.push({
        start: Math.min(index, nearest),
        end: Math.max(index, nearest),
        distance: nearestDistance,
      });
    }
  }

  candidates.sort(
    (first, second) =>
      Math.abs(Math.sqrt(first.distance) - preferredDistance) -
      Math.abs(Math.sqrt(second.distance) - preferredDistance),
  );
  const degree = new Uint8Array(count);
  const seen = new Set();
  const pairs = [];

  for (const candidate of candidates) {
    const key = `${candidate.start}:${candidate.end}`;
    if (
      seen.has(key) ||
      degree[candidate.start] >= 2 ||
      degree[candidate.end] >= 2
    ) {
      continue;
    }
    seen.add(key);
    degree[candidate.start] += 1;
    degree[candidate.end] += 1;
    pairs.push([candidate.start, candidate.end]);
    if (pairs.length >= MAX_LINE_SEGMENTS) break;
  }

  return pairs;
}

export default function ParticleStage({ shape, onReady, onError }) {
  const mountRef = useRef(null);
  const shapeRef = useRef(shape);
  const targetRef = useRef(null);

  useEffect(() => {
    shapeRef.current = shape;
  }, [shape]);

  useEffect(() => {
    if (!mountRef.current) return undefined;

    let renderer;
    let animationFrame;
    let disposed = false;

    try {
      const mount = mountRef.current;
      const reducedMotion = window.matchMedia(
        "(prefers-reduced-motion: reduce)",
      ).matches;
      const isCompact = window.innerWidth < 768;
      const count = isCompact ? 3000 : 7600;
      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
      const baseCameraDistance = 5.05;
      camera.position.set(0, 0, baseCameraDistance);

      renderer = new THREE.WebGLRenderer({
        alpha: true,
        antialias: !isCompact,
        powerPreference: "high-performance",
      });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.6));
      renderer.setClearColor(0x000000, 0);
      mount.appendChild(renderer.domElement);

      const geometry = new THREE.BufferGeometry();
      const initial = generateShape(shapeRef.current, count);
      const particleSeeds = new Float32Array(count);
      for (let index = 0; index < count; index += 1) {
        particleSeeds[index] = randomAt(index * 3.17 + 707);
      }
      geometry.setAttribute("position", new THREE.BufferAttribute(initial, 3));
      geometry.setAttribute(
        "aSeed",
        new THREE.BufferAttribute(particleSeeds, 1),
      );
      targetRef.current = initial.slice();

      const material = new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        blending: THREE.NormalBlending,
        uniforms: {
          uTime: { value: 0 },
          uColor: { value: ACCENT },
          uSize: { value: isCompact ? 0.82 : 1 },
        },
        vertexShader: `
          attribute float aSeed;
          uniform float uTime;
          uniform float uSize;
          varying float vNear;
          varying float vSeed;

          void main() {
            vec3 p = position;
            p *= 1.0 + sin(uTime * 0.7 + position.y * 2.5) * 0.012;
            vec4 mvPosition = modelViewMatrix * vec4(p, 1.0);
            float cameraDepth = -mvPosition.z;
            vNear = clamp((6.8 - cameraDepth) / 3.3, 0.0, 1.0);
            vSeed = aSeed;
            float perspectiveSize = mix(0.8, 5.6, vNear);
            gl_PointSize = uSize * perspectiveSize * (0.76 + aSeed * 0.48);
            gl_Position = projectionMatrix * mvPosition;
          }
        `,
        fragmentShader: `
          uniform vec3 uColor;
          varying float vNear;
          varying float vSeed;

          void main() {
            float distanceToCenter = distance(gl_PointCoord, vec2(0.5));
            if (distanceToCenter > 0.5) discard;
            float core = 1.0 - smoothstep(0.08, 0.44, distanceToCenter);
            float halo = 1.0 - smoothstep(0.32, 0.5, distanceToCenter);
            vec3 farColor = vec3(0.36, 0.63, 0.92);
            vec3 color = mix(farColor, uColor, vNear);
            float depthAlpha = mix(0.26, 0.98, vNear);
            float alpha = (core * 0.76 + halo * 0.24) * depthAlpha;
            gl_FragColor = vec4(color, alpha * (0.76 + vSeed * 0.24));
          }
        `,
      });

      const particleObject = new THREE.Points(geometry, material);
      particleObject.rotation.x =
        shapeRef.current === 3 ? -0.68
          : shapeRef.current === 5 ? -0.22
            : shapeRef.current === 8 ? -0.16
              : -0.36;
      particleObject.rotation.y = shapeRef.current === 3 ? -0.46 : shapeRef.current === 8 ? -0.2 : 0;
      scene.add(particleObject);

      const lineGeometry = new THREE.BufferGeometry();
      const linePositions = new Float32Array(MAX_LINE_SEGMENTS * 6);
      const linePosition = new THREE.BufferAttribute(linePositions, 3);
      lineGeometry.setAttribute("position", linePosition);
      const lineMaterial = new THREE.LineBasicMaterial({
        color: 0x1f67c7,
        transparent: true,
        opacity: 0.28,
        depthWrite: false,
      });
      const lineObject = new THREE.LineSegments(lineGeometry, lineMaterial);
      lineObject.frustumCulled = false;
      lineObject.renderOrder = 0;
      particleObject.add(lineObject);

      let linePairs = buildLinePairs(initial, count);
      const syncLinePositions = (source) => {
        for (let segment = 0; segment < linePairs.length; segment += 1) {
          const [start, end] = linePairs[segment];
          const lineOffset = segment * 6;
          const startOffset = start * 3;
          const endOffset = end * 3;
          linePositions[lineOffset] = source[startOffset];
          linePositions[lineOffset + 1] = source[startOffset + 1];
          linePositions[lineOffset + 2] = source[startOffset + 2];
          linePositions[lineOffset + 3] = source[endOffset];
          linePositions[lineOffset + 4] = source[endOffset + 1];
          linePositions[lineOffset + 5] = source[endOffset + 2];
        }
        lineGeometry.setDrawRange(0, linePairs.length * 2);
        linePosition.needsUpdate = true;
      };
      syncLinePositions(initial);

      const dustGeometry = new THREE.BufferGeometry();
      const dustCount = isCompact ? 260 : 700;
      const dustPositions = new Float32Array(dustCount * 3);
      for (let index = 0; index < dustCount; index += 1) {
        dustPositions[index * 3] = (randomAt(index + 200) - 0.5) * 8;
        dustPositions[index * 3 + 1] = (randomAt(index + 600) - 0.5) * 5;
        dustPositions[index * 3 + 2] = (randomAt(index + 900) - 0.5) * 5;
      }
      dustGeometry.setAttribute(
        "position",
        new THREE.BufferAttribute(dustPositions, 3),
      );
      const dustMaterial = new THREE.PointsMaterial({
        color: 0x7aa9df,
        size: 0.014,
        transparent: true,
        opacity: 0.28,
        depthWrite: false,
      });
      const dust = new THREE.Points(dustGeometry, dustMaterial);
      scene.add(dust);

      const pointer = { x: 0, y: 0 };
      const cameraTarget = { x: 0, y: 0 };
      let lastShape = shapeRef.current;
      let morphFramesRemaining = 0;

      const handlePointer = (event) => {
        const rect = mount.getBoundingClientRect();
        pointer.x = ((event.clientX - rect.left) / rect.width - 0.5) * 2;
        pointer.y = ((event.clientY - rect.top) / rect.height - 0.5) * 2;
      };

      const resize = () => {
        const { clientWidth, clientHeight } = mount;
        renderer.setSize(clientWidth, clientHeight, false);
        camera.aspect = clientWidth / Math.max(clientHeight, 1);
        const framingAspect = shapeRef.current === 3 ? 1.17 : 0.88;
        camera.position.z =
          baseCameraDistance *
          Math.max(1, framingAspect / Math.max(camera.aspect, 0.1));
        camera.updateProjectionMatrix();
      };

      const clock = new THREE.Clock();
      let firstFrame = true;
      const animate = () => {
        if (disposed) return;

        if (lastShape !== shapeRef.current) {
          lastShape = shapeRef.current;
          targetRef.current = generateShape(lastShape, count);
          linePairs = buildLinePairs(targetRef.current, count);
          syncLinePositions(geometry.attributes.position.array);
          resize();
          morphFramesRemaining = reducedMotion ? 1 : 150;
        }

        const position = geometry.attributes.position;
        const array = position.array;
        const target = targetRef.current;
        if (morphFramesRemaining > 0) {
          const easing = reducedMotion ? 1 : 0.055;
          for (let index = 0; index < array.length; index += 1) {
            array[index] += (target[index] - array[index]) * easing;
          }
          position.needsUpdate = true;
          syncLinePositions(array);
          morphFramesRemaining -= 1;
        }

        const elapsed = clock.getElapsedTime();
        material.uniforms.uTime.value = elapsed;
        lineMaterial.opacity = reducedMotion
          ? 0.28
          : 0.23 + (Math.sin(elapsed * 0.72) + 1) * 0.05;
        if (!reducedMotion) {
          const isCityModel = lastShape === 3;
          const isKnowledgePlanet = lastShape === 5;
          const isResearchVessel = lastShape === 8;
          const targetRotationX =
            (isCityModel ? -0.68 : isKnowledgePlanet ? -0.22 : isResearchVessel ? -0.16 : -0.36) +
            Math.sin(elapsed * 0.34) * (isCityModel ? 0.035 : isResearchVessel ? 0.025 : 0.06);
          const targetRotationY =
            (isCityModel ? -0.46 : isResearchVessel ? -0.2 : 0) +
            Math.sin(elapsed * 0.24) * (isCityModel ? 0.07 : isResearchVessel ? 0.08 : 0.18);
          particleObject.rotation.x +=
            (targetRotationX - particleObject.rotation.x) * 0.045;
          particleObject.rotation.y +=
            (targetRotationY - particleObject.rotation.y) * 0.045;
          particleObject.rotation.z = Math.sin(elapsed * 0.18) * (isResearchVessel ? 0.012 : 0.025);
          dust.rotation.y -= 0.00022;
          cameraTarget.x = pointer.x * 0.24;
          cameraTarget.y = -pointer.y * 0.16;
          camera.position.x += (cameraTarget.x - camera.position.x) * 0.035;
          camera.position.y += (cameraTarget.y - camera.position.y) * 0.035;
          camera.lookAt(0, 0, 0);
        }

        renderer.render(scene, camera);
        if (firstFrame) {
          firstFrame = false;
          onReady?.();
        }
        animationFrame = window.requestAnimationFrame(animate);
      };

      resize();
      mount.addEventListener("pointermove", handlePointer, { passive: true });
      window.addEventListener("resize", resize, { passive: true });
      animate();

      return () => {
        disposed = true;
        window.cancelAnimationFrame(animationFrame);
        mount.removeEventListener("pointermove", handlePointer);
        window.removeEventListener("resize", resize);
        geometry.dispose();
        material.dispose();
        lineGeometry.dispose();
        lineMaterial.dispose();
        dustGeometry.dispose();
        dustMaterial.dispose();
        renderer.dispose();
        renderer.domElement.remove();
      };
    } catch (error) {
      onError?.(error);
      return undefined;
    }
  }, [onError, onReady]);

  return <div className="particle-stage" ref={mountRef} aria-hidden="true" />;
}
