import Icon from './Icon.jsx'

/** Strip the scheme and any www. so a source chip reads as a masthead. */
function label(source) {
  if (source.title) return source.title
  try {
    return new URL(source.url).hostname.replace(/^www\./, '')
  } catch {
    return source.url
  }
}

/** Where an answer's web results came from, as the mockup's pill row. */
export default function SourceChips({ sources }) {
  return (
    <footer className="border-t border-outline-variant pt-6">
      <p className="font-label-caps text-label-caps text-on-surface-variant mb-4 uppercase tracking-wider">
        Sources &amp; Inspiration
      </p>
      <div className="flex flex-wrap gap-4">
        {sources.map((source) => (
          <a
            key={source.url}
            href={source.url}
            target="_blank"
            rel="noreferrer noopener"
            className="flex items-center gap-2 px-3 py-1.5 bg-surface-container-low rounded-full hover:bg-surface-container transition-colors border border-outline-variant/20"
          >
            <span className="font-label-caps text-label-caps uppercase">{label(source)}</span>
            <Icon name="open_in_new" className="text-[16px]" />
          </a>
        ))}
      </div>
    </footer>
  )
}
