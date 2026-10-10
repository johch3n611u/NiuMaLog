import { useEffect, useMemo, useState } from 'react'

type Event = { id: string; date: string; project: string; type: string; title: string; summary: string }
type Report = { title?: string; markdown: string; html: string; kind: string; mode: string }

const API = import.meta.env.VITE_WORKLOG_API ?? 'http://127.0.0.1:8000'

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API}${path}`)
  if (!response.ok) throw new Error(await response.text())
  return response.json()
}

function App() {
  const [tab, setTab] = useState<'timeline' | 'daily' | 'weekly' | 'import' | 'settings'>('timeline')
  const [events, setEvents] = useState<Event[]>([])
  const [path, setPath] = useState('')
  const [status, setStatus] = useState('')
  const [report, setReport] = useState<Report | null>(null)
  const [dateValue, setDateValue] = useState(new Date().toISOString().slice(0, 10))
  const [weekValue, setWeekValue] = useState('')
  const [provider, setProvider] = useState('ccswitch')
  const [protocol, setProtocol] = useState('openai')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')

  const projects = useMemo(() => Array.from(new Set(events.map(event => event.project))), [events])

  useEffect(() => { refreshEvents() }, [])

  async function refreshEvents() {
    try { setEvents(await get<Event[]>('/api/events')) } catch (error) { setStatus(String(error)) }
  }

  async function importSources() {
    setStatus('正在读取本地目录…')
    const response = await fetch(`${API}/api/import`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ path }) })
    const data = await response.json()
    setStatus(`扫描 ${data.scanned} 个文件，新增 ${data.imported} 个会话`)
    await refreshEvents()
  }

  async function generate(kind: 'daily' | 'weekly', mode = 'deterministic') {
    setStatus('正在生成…')
    const body = kind === 'daily' ? { date: dateValue, mode, provider } : { week: weekValue, mode, provider }
    const response = await fetch(`${API}/api/reports/${kind}`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) })
    if (!response.ok) { setStatus(await response.text()); return }
    setReport(await response.json())
    setStatus('报告已生成，可以在右侧编辑后复制导出。')
  }

  async function saveKey() {
    const configResponse = await fetch(`${API}/api/settings/provider`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ provider, protocol, base_url: baseUrl, model }) })
    if (!configResponse.ok) { setStatus(await configResponse.text()); return }
    if (apiKey.trim()) {
      const keyResponse = await fetch(`${API}/api/settings/key`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ provider, api_key: apiKey }) })
      if (!keyResponse.ok) { setStatus(await keyResponse.text()); return }
      setApiKey('')
    }
    setStatus('模型接口配置已保存。')
  }

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">W</span><span>Worklog</span></div>
      <p className="eyebrow">工作台</p>
      <nav>{[['timeline', '时间线'], ['daily', '日报'], ['weekly', '周报'], ['import', '导入'], ['settings', 'AI 设置']].map(([key, label]) => <button className={tab === key ? 'nav-item active' : 'nav-item'} onClick={() => setTab(key as typeof tab)} key={key}>{label}</button>)}</nav>
      <div className="sidebar-footer"><span className="dot" />本地模式<br /><small>内容保存在这台设备</small></div>
    </aside>
    <main className="content">
      <header className="topbar"><div><p className="eyebrow">个人记录</p><h1>{tab === 'timeline' ? '时间线' : tab === 'daily' ? '日报' : tab === 'weekly' ? '周报' : tab === 'import' ? '导入对话' : 'AI 设置'}</h1></div><span className="status">{status}</span></header>
      {tab === 'timeline' && <section className="panel"><div className="panel-heading"><div><h2>工作事件</h2><p>按日期和项目回看已经发生的工作。</p></div><button className="button quiet" onClick={refreshEvents}>刷新</button></div><div className="project-row">{projects.map(project => <span className="chip" key={project}>{project}</span>)}</div><div className="timeline">{events.length === 0 ? <Empty text="还没有导入记录" /> : events.map(event => <article className="event" key={event.id}><time>{event.date}</time><div className="event-line"><span className={`event-type ${event.type}`}>{event.type}</span><h3>{event.title}</h3><p>{event.summary}</p><small>{event.project}</small></div></article>)}</div></section>}
      {tab === 'import' && <section className="panel narrow"><h2>导入聊天记录</h2><p>输入包含 Codex 或 Claude 导出文件的目录。原始内容只会写入本地数据库。</p><label>本地目录<input value={path} onChange={event => setPath(event.target.value)} placeholder="/Users/you/Downloads/chats" /></label><button className="button primary" onClick={importSources}>扫描并导入</button></section>}
      {tab === 'settings' && <section className="panel narrow"><h2>外接 AI</h2><p>只有你主动点击 AI 模式时，选中的上下文才会发送给对应服务。CCSwitch 可以作为本地或远程中转，原始内容不会自动上传。</p><label>服务商<select value={provider} onChange={event => { setProvider(event.target.value); if (event.target.value === 'anthropic') setProtocol('anthropic') }}><option value="ccswitch">CCSwitch 中转</option><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option></select></label><label>兼容协议<select value={protocol} onChange={event => setProtocol(event.target.value)}><option value="openai">OpenAI Compatible</option><option value="anthropic">Anthropic Compatible</option></select></label><label>Base URL<input value={baseUrl} onChange={event => setBaseUrl(event.target.value)} placeholder="例如 http://127.0.0.1:8317/v1" /></label><label>模型名<input value={model} onChange={event => setModel(event.target.value)} placeholder="例如 claude-sonnet-4-5 或 gpt-4o-mini" /></label><label>API Key（可选）<input type="password" value={apiKey} onChange={event => setApiKey(event.target.value)} placeholder="CCSwitch 无鉴权时可留空" /></label><button className="button primary" onClick={saveKey}>保存接口配置</button></section>}
      {tab === 'daily' && <ReportPanel kind="daily" value={dateValue} onChange={setDateValue} report={report} onGenerate={() => generate('daily')} onGenerateAI={() => generate('daily', 'ai')} />}
      {tab === 'weekly' && <ReportPanel kind="weekly" value={weekValue} onChange={setWeekValue} report={report} onGenerate={() => generate('weekly')} onGenerateAI={() => generate('weekly', 'ai')} />}
    </main>
  </div>
}

function ReportPanel({ kind, value, onChange, report, onGenerate, onGenerateAI }: { kind: 'daily' | 'weekly'; value: string; onChange: (value: string) => void; report: Report | null; onGenerate: () => void; onGenerateAI: () => void }) {
  const [draft, setDraft] = useState('')
  useEffect(() => setDraft(report?.markdown ?? ''), [report])
  return <section className="report-layout"><div className="panel controls"><h2>{kind === 'daily' ? '生成一份日报' : '生成一份周报'}</h2><p>先用本地规则生成草稿，再按需要调用外部 AI 精炼。</p><label>{kind === 'daily' ? '日期' : 'ISO 周'}<input value={value} onChange={event => onChange(event.target.value)} placeholder={kind === 'daily' ? '2026-10-10' : '2026-W41'} /></label><div className="button-row"><button className="button primary" onClick={onGenerate}>代码模式</button><button className="button" onClick={onGenerateAI}>AI 模式</button></div></div><div className="panel preview"><div className="panel-heading"><div><p className="eyebrow">预览</p><h2>{report?.kind ? `${report.kind === 'daily' ? '日报' : '周报'}草稿` : '尚未生成'}</h2></div><button className="button quiet" onClick={() => navigator.clipboard?.writeText(draft)}>复制 Markdown</button></div><textarea value={draft} readOnly={!report} onChange={event => setDraft(event.target.value)} placeholder="报告会显示在这里，可复制到你的文档工具中。" /></div></section>
}

function Empty({ text }: { text: string }) { return <div className="empty"><div className="empty-icon">—</div><p>{text}</p><small>从左侧“导入”开始</small></div> }

export default App
