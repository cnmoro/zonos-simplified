import {test} from 'node:test';
import assert from 'node:assert/strict';
import {PCMReader, wavBlob} from '../frontend/audio.mjs';
test('PCM frames survive arbitrary HTTP boundaries and nonfinite values', () => {
  const bytes = new Uint8Array(16), view = new DataView(bytes.buffer);
  [0.5, -0.5, Infinity, 2].forEach((x, i) => view.setFloat32(i * 4, x, true));
  const reader = new PCMReader(), result = [];
  for (let i = 0; i < bytes.length; i += 3) result.push(...reader.push(bytes.slice(i, i + 3)));
  assert.deepEqual(result, [0.5, -0.5, 0, 1]); assert.equal(reader.pending.length, 0);
});
test('download has a correct PCM16 WAV header and sample data', async () => {
  const blob = wavBlob([new Float32Array([0.5, -1]), new Float32Array([1])]);
  const bytes = await blob.arrayBuffer(), view = new DataView(bytes);
  assert.equal(blob.type, 'audio/wav'); assert.equal(bytes.byteLength, 50);
  assert.equal(view.getUint32(24, true), 44100); assert.equal(view.getUint32(40, true), 6);
  assert.equal(view.getInt16(44, true), 16384); assert.equal(view.getInt16(46, true), -32767);
});
