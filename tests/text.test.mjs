import test from 'node:test';
import assert from 'node:assert/strict';
import {splitText} from '../frontend/text.mjs';
test('splits long bilingual prose without losing or reordering words', () => {
  const text = ('English sentences contain quoted “words.” Português também possui acentuação e números 12,527/2011.\n\n').repeat(20);
  const parts = splitText(text);
  assert.ok(parts.length > 1);
  assert.ok(parts.every(part => part.length <= 350));
  assert.equal(parts.join(' '), text.trim().replace(/\s+/gu,' '));
});
test('empty and short input', () => {
  assert.deepEqual(splitText(' \n '), []);
  assert.deepEqual(splitText('Hello world!'), ['Hello world!']);
});
