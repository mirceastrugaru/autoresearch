import ReactMarkdown from 'react-markdown'

export function Md({ children, className = '' }: { children: string; className?: string }) {
  return (
    <div className={className}>
      <ReactMarkdown
        components={{
          p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
          strong: ({ children }) => <b className="font-semibold">{children}</b>,
          em: ({ children }) => <em>{children}</em>,
          ul: ({ children }) => <ul className="list-disc pl-4 mb-2">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal pl-4 mb-2">{children}</ol>,
          li: ({ children }) => <li className="mb-0.5">{children}</li>,
          h1: ({ children }) => <h1 className="text-lg font-semibold mb-2 mt-3 first:mt-0">{children}</h1>,
          h2: ({ children }) => <h2 className="text-base font-semibold mb-1.5 mt-2.5 first:mt-0">{children}</h2>,
          h3: ({ children }) => <h3 className="text-sm font-semibold mb-1 mt-2 first:mt-0">{children}</h3>,
          code: ({ children }) => <code className="mono bg-surface-2 px-1 py-0.5 rounded text-[12px]">{children}</code>,
          blockquote: ({ children }) => <blockquote className="border-l-2 border-border-strong pl-3 text-text-2 my-2">{children}</blockquote>,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
