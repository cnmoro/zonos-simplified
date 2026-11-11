// Reconstruct cosine-to-selected-mean from the full-precision Gram matrix.
// Raw arithmetic mean, equal coefficient per sample, matching the native API.
export function selectedSimilarities(matrix, norms, selected) {
  if (!selected.length) return norms.map(() => null);
  let squared = 0;
  for (const a of selected) for (const b of selected) squared += matrix[a][b] * norms[a] * norms[b];
  if (!Number.isFinite(squared) || squared <= 1e-20) return norms.map(() => null);
  const denominator = Math.sqrt(squared);
  return norms.map((_, i) => Math.max(-1, Math.min(1,
    selected.reduce((sum, j) => sum + matrix[i][j] * norms[j], 0) / denominator)));
}
