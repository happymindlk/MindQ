export type MarkdownBlock =
  | { kind: 'heading'; level: 1 | 2 | 3; text: string }
  | { kind: 'ul'; items: string[] }
  | { kind: 'ol'; items: string[] }
  | { kind: 'p'; lines: string[] };

export type InlineToken =
  | { kind: 'text'; value: string }
  | { kind: 'strong'; value: string }
  | { kind: 'em'; value: string }
  | { kind: 'code'; value: string };

const INLINE_PATTERN = /(\*\*[^*]+\*\*|\*[^*]+\*|_[^_]+_|`[^`]+`)/g;

/**
 * Tokenize inline emphasis and code spans.
 *
 * @param text - One line of Markdown.
 * @returns Inline tokens in order.
 */
export function tokenizeInline(text: string): InlineToken[] {
  return text
    .split(INLINE_PATTERN)
    .filter((part) => part !== '')
    .map((part): InlineToken => {
      if (part.length > 4 && part.startsWith('**') && part.endsWith('**')) {
        return { kind: 'strong', value: part.slice(2, -2) };
      }
      if (part.length > 2 && part.startsWith('`') && part.endsWith('`')) {
        return { kind: 'code', value: part.slice(1, -1) };
      }
      if (
        part.length > 2 &&
        ((part.startsWith('*') && part.endsWith('*')) || (part.startsWith('_') && part.endsWith('_')))
      ) {
        return { kind: 'em', value: part.slice(1, -1) };
      }
      return { kind: 'text', value: part };
    });
}

/**
 * Parse the supported Markdown subset (headings, lists, paragraphs) into blocks.
 *
 * @param source - Raw Markdown.
 * @returns Ordered block list.
 */
export function parseMarkdownBlocks(source: string): MarkdownBlock[] {
  const blocks: MarkdownBlock[] = [];
  const state: { paragraph: string[]; list: { kind: 'ul' | 'ol'; items: string[] } | null } = {
    paragraph: [],
    list: null,
  };

  const flushParagraph = () => {
    if (state.paragraph.length) blocks.push({ kind: 'p', lines: state.paragraph });
    state.paragraph = [];
  };
  const flushList = () => {
    if (state.list) blocks.push(state.list);
    state.list = null;
  };

  for (const raw of source.replace(/\r\n?/g, '\n').split('\n')) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }
    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    if (heading?.[1] && heading[2] !== undefined) {
      flushParagraph();
      flushList();
      blocks.push({ kind: 'heading', level: heading[1].length as 1 | 2 | 3, text: heading[2] });
      continue;
    }
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line);
    const ordered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    const itemKind: 'ul' | 'ol' | null = bullet ? 'ul' : ordered ? 'ol' : null;
    const itemText = bullet?.[1] ?? ordered?.[1];
    if (itemKind && itemText !== undefined) {
      flushParagraph();
      if (state.list && state.list.kind === itemKind) {
        state.list.items.push(itemText);
      } else {
        flushList();
        state.list = { kind: itemKind, items: [itemText] };
      }
      continue;
    }
    flushList();
    state.paragraph.push(line);
  }
  flushParagraph();
  flushList();
  return blocks;
}
