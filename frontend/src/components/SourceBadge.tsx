const SOURCE_COLORS: Record<string, { bg: string; text: string; label: string }> = {
  github:        { bg: '#24292e', text: '#fff', label: 'GitHub' },
  producthunt:   { bg: '#da552f', text: '#fff', label: 'PH' },
  ycombinator:   { bg: '#f26625', text: '#fff', label: 'YC' },
  hackernews:    { bg: '#ff6600', text: '#fff', label: 'HN' },
  reddit:        { bg: '#ff4500', text: '#fff', label: 'Reddit' },
  indeed:        { bg: '#003a9b', text: '#fff', label: 'Indeed' },
  wellfound:     { bg: '#000000', text: '#fff', label: 'Wellfound' },
  google_cse:    { bg: '#4285f4', text: '#fff', label: 'Google' },
  whois:         { bg: '#6b7280', text: '#fff', label: 'WHOIS' },
  bing:          { bg: '#0078d4', text: '#fff', label: 'Bing' },
  companies_house: { bg: '#1d4ed8', text: '#fff', label: 'CH' },
  remoteok:      { bg: '#ff4742', text: '#fff', label: 'RemoteOK' },
}

function getDiscoveredColor() {
  return { bg: '#8b5cf6', text: '#fff', label: '✦' }
}

export default function SourceBadge({ source }: { source: string }) {
  const isDiscovered = source.startsWith('discovered:')
  const config = isDiscovered
    ? { ...getDiscoveredColor(), label: source.replace('discovered:', '').slice(0, 12) }
    : SOURCE_COLORS[source] || { bg: '#6b7280', text: '#fff', label: source.slice(0, 8) }

  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
      style={{ backgroundColor: config.bg, color: config.text }}
      title={source}
    >
      {config.label}
    </span>
  )
}
