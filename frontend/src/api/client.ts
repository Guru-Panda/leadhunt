import axios from 'axios'

const BASE = import.meta.env.VITE_API_URL || '/api'
const DEMO = new URLSearchParams(window.location.search).get('demo') === 'true'

const DEMO_RESPONSES: Record<string, unknown> = {
  '/strategies': [],
  '/leads': [],
  '/monitor/sync-runs': [],
  '/monitor/discovered-sources': [],
  '/analytics': {
    total_leads: 247, verified_email_pct: 61.5, contacted_pct: 12.1, avg_intent_score: 0.63,
    leads_by_day: [
      {date:'2025-05-18',count:6},{date:'2025-05-19',count:14},{date:'2025-05-20',count:22},
      {date:'2025-05-21',count:18},{date:'2025-05-22',count:31},{date:'2025-05-23',count:28},{date:'2025-05-24',count:11},
    ],
    leads_by_source: [
      {source:'github',count:89},{source:'hackernews',count:54},{source:'producthunt',count:43},
      {source:'reddit',count:31},{source:'discovered:Indie Hackers',count:30},
    ],
    leads_by_score_bucket: [
      {bucket:'0.0-0.3',count:12},{bucket:'0.3-0.5',count:45},{bucket:'0.5-0.7',count:98},
      {bucket:'0.7-0.9',count:72},{bucket:'0.9-1.0',count:20},
    ],
  },
}

export const api = axios.create({
  baseURL: BASE,
  headers: { 'Content-Type': 'application/json' },
})

if (DEMO) {
  api.interceptors.request.use((config) => {
    const path = config.url || ''
    const match = Object.keys(DEMO_RESPONSES).find((k) => path.startsWith(k))
    if (match !== undefined) {
      config.adapter = () =>
        Promise.resolve({ data: DEMO_RESPONSES[match], status: 200, statusText: 'OK', headers: {}, config })
    }
    return config
  })
}

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const original = error.config
    if (error.response?.status === 401 && !original._retry) {
      original._retry = true
      const refresh = localStorage.getItem('refresh_token')
      if (refresh) {
        try {
          const { data } = await axios.post(`${BASE}/auth/refresh`, { refresh_token: refresh })
          localStorage.setItem('access_token', data.access_token)
          localStorage.setItem('refresh_token', data.refresh_token)
          original.headers.Authorization = `Bearer ${data.access_token}`
          return api(original)
        } catch {
          localStorage.clear()
          window.location.href = '/login'
        }
      } else {
        localStorage.clear()
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  }
)
