import { Crosshair, Sparkles, Zap, Mail } from 'lucide-react'

interface AuthHeroProps {
  title?: string
  subtitle?: string
}

export default function AuthHero({
  title = "Hunt your next 100 leads — automatically.",
  subtitle = "AI-powered outbound prospecting across 12+ free sources, fully on autopilot.",
}: AuthHeroProps) {
  return (
    <div className="relative hidden md:flex md:w-1/2 lg:w-3/5 flex-col justify-between p-12 overflow-hidden text-white">
      {/* Gradient background */}
      <div className="absolute inset-0 bg-gradient-brand" />
      {/* Floating blobs for depth */}
      <div className="absolute top-10 right-10 w-72 h-72 rounded-full bg-white/10 blur-3xl pointer-events-none" />
      <div className="absolute -bottom-20 -left-20 w-96 h-96 rounded-full bg-fuchsia-300/20 blur-3xl pointer-events-none" />
      <div className="absolute top-1/2 left-1/3 w-48 h-48 rounded-full bg-cyan-300/15 blur-2xl pointer-events-none" />

      {/* Logo top-left */}
      <div className="relative z-10 flex items-center gap-2.5">
        <div className="w-9 h-9 bg-white/20 backdrop-blur-sm rounded-lg flex items-center justify-center">
          <Crosshair className="w-5 h-5 text-white" />
        </div>
        <span className="font-bold text-xl">LeadHunt</span>
      </div>

      {/* Hero copy */}
      <div className="relative z-10 max-w-md">
        <h1 className="text-4xl lg:text-5xl font-bold leading-tight mb-4">
          {title}
        </h1>
        <p className="text-lg text-white/85 mb-10">{subtitle}</p>

        <ul className="space-y-4">
          <Feature icon={Zap} title="100+ leads / day per strategy"
            body="From HackerNews, YC, Reddit, RemoteOK + 8 more — fresh every hour." />
          <Feature icon={Mail} title="60%+ with verified emails"
            body="Layered enrichment: source text → company site → WHOIS → pattern match." />
          <Feature icon={Sparkles} title="Personalized outreach drafts"
            body="Groq-generated cold emails that reference what each lead actually said." />
        </ul>
      </div>

      {/* Footer stats */}
      <div className="relative z-10 flex items-center gap-6 text-sm text-white/70">
        <span>✨ Free forever (zero paid services)</span>
        <span>·</span>
        <span>🚀 Deploys on Railway + Vercel</span>
      </div>
    </div>
  )
}

function Feature({ icon: Icon, title, body }: { icon: React.ElementType; title: string; body: string }) {
  return (
    <li className="flex items-start gap-3">
      <div className="w-9 h-9 bg-white/20 backdrop-blur-sm rounded-lg flex items-center justify-center shrink-0">
        <Icon className="w-4 h-4 text-white" />
      </div>
      <div>
        <div className="font-semibold">{title}</div>
        <div className="text-sm text-white/75">{body}</div>
      </div>
    </li>
  )
}
