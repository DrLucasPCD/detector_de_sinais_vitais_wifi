import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  BrowserEngine,
  BrowserSimulator,
  SerialFrameParser,
} from "../src/rf_sense/static/browser-engine.js";

test("parser aceita vetor dourado fragmentado", async () => {
  const text = await readFile(
    new URL("../protocol/golden/raw-csi-v1-node1-4sc.hex", import.meta.url),
    "utf8",
  );
  const bytes = Uint8Array.from(
    text.trim().split(/\s+/).map((value) => Number.parseInt(value, 16)),
  );
  const parser = new SerialFrameParser();
  assert.equal(parser.push(bytes.slice(0, 9)).length, 0);
  const frames = parser.push(bytes.slice(9));
  assert.equal(frames.length, 1);
  assert.equal(frames[0].nodeId, 1);
  assert.equal(frames[0].sequence, 42);
  assert.deepEqual(frames[0].iq[0], [10, -10]);
});

test("engine do navegador calibra e detecta presença", () => {
  const engine = new BrowserEngine(40, "test");
  const simulator = new BrowserSimulator(() => {});
  let update;
  let timestamp = 100;
  for (let index = 0; index < 40; index += 1) {
    update = engine.process(simulator.frame(timestamp, "empty"));
    timestamp += 0.05;
  }
  assert.equal(update.nodes[0].calibration.valid, true);
  for (let index = 0; index < 300; index += 1) {
    update = engine.process(simulator.frame(timestamp, "still"));
    timestamp += 0.05;
  }
  assert.equal(update.classification.presence, true);
  assert.equal(update.classification.motion_state, "still");
});

test("consenso multissubportadora estima respiração e pulso separadamente", () => {
  const engine = new BrowserEngine(40, "test");
  const simulator = new BrowserSimulator(() => {});
  let update;
  let timestamp = 200;
  for (let index = 0; index < 40; index += 1) {
    update = engine.process(simulator.frame(timestamp, "empty"));
    timestamp += 0.05;
  }
  for (let index = 0; index < 1100; index += 1) {
    update = engine.process(simulator.frame(timestamp, "still"));
    timestamp += 0.05;
  }
  assert.equal(update.vital_signs.breathing.valid, true);
  assert.ok(Math.abs(update.vital_signs.breathing.value_bpm - 15) <= 1);
  assert.equal(update.vital_signs.heart.valid, true);
  assert.ok(Math.abs(update.vital_signs.heart.value_bpm - 72) <= 2);
  assert.ok(update.vital_signs.breathing.traces_used >= 3);
  assert.ok(update.vital_signs.heart.traces_used >= 3);
});
