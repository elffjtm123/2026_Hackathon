// A row of short facts, each in its own span so the layout separates them (never a joined string).
export function MetaLine({items, className = ''}: {items: (string | false | null | undefined)[]; className?: string}) {
  return <p className={`meta-line ${className}`.trim()}>{items.filter(Boolean).map((item, index) => <span key={index}>{item}</span>)}</p>;
}
