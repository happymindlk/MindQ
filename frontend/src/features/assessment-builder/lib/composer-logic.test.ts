import { describe, expect, it } from 'vitest';
import { SEQUENCE_DROP_ID, insertAt, libraryDragId, moveItem, resolveDragEnd } from './composer-logic';

const cart = ['a', 'b', 'c'];

describe('resolveDragEnd', () => {
  it('reorders sequence items', () => {
    expect(resolveDragEnd(cart, 'a', 'c')).toEqual({ kind: 'reorder', ids: ['b', 'c', 'a'] });
    expect(resolveDragEnd(cart, 'c', 'a')).toEqual({ kind: 'reorder', ids: ['c', 'a', 'b'] });
  });

  it('inserts a library card before the item it is dropped on', () => {
    expect(resolveDragEnd(cart, libraryDragId('x'), 'b')).toEqual({ kind: 'add', moduleId: 'x', index: 1 });
  });

  it('appends a library card dropped on the empty sequence area', () => {
    expect(resolveDragEnd([], libraryDragId('x'), SEQUENCE_DROP_ID)).toEqual({ kind: 'add', moduleId: 'x', index: 0 });
  });

  it.each([
    ['dropped outside', 'a', null],
    ['dropped on itself', 'b', 'b'],
    ['library card already in cart', libraryDragId('a'), 'b'],
    ['library card dropped on an unknown target', libraryDragId('x'), 'elsewhere'],
  ])('no-ops when %s', (_label, active, over) => {
    expect(resolveDragEnd(cart, active, over)).toBeNull();
  });
});

describe('array helpers', () => {
  it('moveItem does not mutate', () => {
    const source = ['a', 'b', 'c'];
    expect(moveItem(source, 0, 2)).toEqual(['b', 'c', 'a']);
    expect(source).toEqual(['a', 'b', 'c']);
  });

  it('insertAt clamps and ignores duplicates', () => {
    expect(insertAt(cart, 'x', 99)).toEqual(['a', 'b', 'c', 'x']);
    expect(insertAt(cart, 'b', 0)).toEqual(cart);
  });
});
