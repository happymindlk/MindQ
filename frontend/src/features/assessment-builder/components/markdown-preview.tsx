import { Fragment, memo } from 'react';
import type { ReactNode } from 'react';
import { parseMarkdownBlocks, tokenizeInline } from '../lib/markdown';

/*
 * Prompts are admin-authored but candidate-facing, so Markdown is rendered as
 * React nodes (never innerHTML) to be XSS-proof by construction.
 */

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  return tokenizeInline(text).map((token, i) => {
    const key = `${keyPrefix}-${i}`;
    switch (token.kind) {
      case 'strong':
        return <strong key={key} className="font-semibold">{token.value}</strong>;
      case 'em':
        return <em key={key}>{token.value}</em>;
      case 'code':
        return (
          <code key={key} className="rounded bg-slate-800/80 px-1 py-0.5 font-mono text-[0.9em]">
            {token.value}
          </code>
        );
      case 'text':
        return <Fragment key={key}>{token.value}</Fragment>;
    }
  });
}

const HEADING_CLASS: Record<1 | 2 | 3, string> = {
  1: 'text-lg font-semibold',
  2: 'text-base font-semibold',
  3: 'text-sm font-semibold uppercase tracking-wide',
};

export const MarkdownText = memo(function MarkdownText({
  source,
  className = '',
}: {
  source: string;
  className?: string;
}) {
  const blocks = parseMarkdownBlocks(source);
  return (
    <div className={`space-y-2 leading-relaxed ${className}`}>
      {blocks.map((block, i) => {
        const key = `b${i}`;
        switch (block.kind) {
          case 'heading': {
            const Tag = `h${block.level + 2}` as 'h3' | 'h4' | 'h5';
            return (
              <Tag key={key} className={HEADING_CLASS[block.level]}>
                {renderInline(block.text, key)}
              </Tag>
            );
          }
          case 'ul':
            return (
              <ul key={key} className="list-disc space-y-1 pl-5">
                {block.items.map((item, j) => (
                  <li key={j}>{renderInline(item, `${key}-${j}`)}</li>
                ))}
              </ul>
            );
          case 'ol':
            return (
              <ol key={key} className="list-decimal space-y-1 pl-5">
                {block.items.map((item, j) => (
                  <li key={j}>{renderInline(item, `${key}-${j}`)}</li>
                ))}
              </ol>
            );
          case 'p':
            return (
              <p key={key}>
                {block.lines.map((line, j) => (
                  <Fragment key={j}>
                    {j > 0 && <br />}
                    {renderInline(line, `${key}-${j}`)}
                  </Fragment>
                ))}
              </p>
            );
        }
      })}
    </div>
  );
});
