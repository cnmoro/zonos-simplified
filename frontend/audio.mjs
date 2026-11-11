export class PCMReader {
  constructor() { this.pending = new Uint8Array(0); }
  push(bytes) {
    const all = new Uint8Array(this.pending.length + bytes.length);
    all.set(this.pending); all.set(bytes, this.pending.length);
    const length = all.length - all.length % 4;
    const view = new DataView(all.buffer);
    const samples = new Float32Array(length / 4);
    for (let i = 0; i < samples.length; i++) {
      const value = view.getFloat32(i * 4, true);
      samples[i] = Number.isFinite(value) ? Math.max(-1, Math.min(1, value)) : 0;
    }
    this.pending = all.slice(length);
    return samples;
  }
}
export function wavBlob(chunks, rate = 44100) {
  const length = chunks.reduce((sum, part) => sum + part.length, 0);
  const bytes = new ArrayBuffer(44 + length * 2), view = new DataView(bytes);
  const str = (offset, value) => [...value].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  str(0, 'RIFF'); view.setUint32(4, 36 + length * 2, true); str(8, 'WAVE');
  str(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, 1, true); view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true); str(36, 'data'); view.setUint32(40, length * 2, true);
  let offset = 44;
  for (const part of chunks) for (const value of part) {
    view.setInt16(offset, Math.round(Math.max(-1, Math.min(1, value)) * 32767), true); offset += 2;
  }
  return new Blob([bytes], {type: 'audio/wav'});
}
