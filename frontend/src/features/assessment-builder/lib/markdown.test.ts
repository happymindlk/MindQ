import { render, screen } from '@testing-library/react';
import { createElement } from 'react';
import { describe, expect, it } from 'vitest';
import { MarkdownText } from '../components/markdown-preview';
import { parseMarkdownBlocks, tokenizeInline } from './markdown';

describe('markdown subset', () => {
  it('parses headings, lists, and paragraphs', () => {
    const blocks = parseMarkdownBlocks('# Title\n\nLine one\nLine two\n\n- a\n- b\n1. x');
    expect(blocks.map((b) => b.kind)).toEqual(['heading', 'p', 'ul', 'ol']);
  });

  it('tokenizes emphasis and code', () => {
    expect(tokenizeInline('a **b** *c* `d`').map((t) => t.kind)).toEqual(['text', 'strong', 'text', 'em', 'text', 'code']);
  });

  it('renders HTML in prompts as inert text', () => {
    const { container } = render(createElement(MarkdownText, { source: '<img src=x onerror=alert(1)> **bold**' }));
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText(/<img src=x onerror=alert\(1\)>/)).toBeInTheDocument();
    expect(screen.getByText('bold').tagName).toBe('STRONG');
  });
});
