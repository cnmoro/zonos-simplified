import {test} from 'node:test';
import assert from 'node:assert/strict';
import {selectedSimilarities} from '../frontend/reference-math.mjs';
const matrix = [[1,0,-1],[0,1,0],[-1,0,1]], norms = [2,1,2];
test('selected mean uses raw embedding magnitudes, not normalized means', () => {
  const scores = selectedSimilarities(matrix, norms, [0,1]);
  assert.ok(Math.abs(scores[0] - 2 / Math.sqrt(5)) < 1e-12);
  assert.ok(Math.abs(scores[1] - 1 / Math.sqrt(5)) < 1e-12);
  assert.ok(Math.abs(scores[2] + 2 / Math.sqrt(5)) < 1e-12);
});
test('unselected reference does not contribute to the selected mean', () => {
  assert.deepEqual(selectedSimilarities(matrix,norms,[1]), [0,1,0]);
  assert.deepEqual(selectedSimilarities(matrix,norms,[0]), [1,0,-1]);
});
test('empty and cancelling selections have no defined cosine', () => {
  assert.deepEqual(selectedSimilarities(matrix,norms,[]), [null,null,null]);
  assert.deepEqual(selectedSimilarities(matrix,norms,[0,2]), [null,null,null]);
});
