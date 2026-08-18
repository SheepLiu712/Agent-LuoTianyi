import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

type DashboardSummary = {
  window_days: number;
  llm: Record<string, number>;
  pipeline: Record<string, LatencySummary>;
  logs: Record<string, number>;
  recent_logs: LogEvent[];
  slow_spans: PipelineSpan[];
};

type LatencySummary = {
  count: number;
  avg_ms: number;
  p50_ms: number;
  p90_ms: number;
  p99_ms: number;
  max_ms: number;
};

type LlmSummary = {
  window_type: 'days' | 'recent';
  window_days?: number;
  recent_limit?: number;
  totals: Record<string, number>;
  by_module: Array<Record<string, string | number | null>>;
  time_buckets: Array<Record<string, string | number>>;
  daily: Array<Record<string, string | number>>;
};

type AdminAuthStatus = {
  configured: boolean;
  setup_required: boolean;
};

type RuntimeStatus = {
  state: string;
  running: boolean;
  busy?: boolean;
  last_error?: string | null;
  last_started_at?: string | null;
  last_stopped_at?: string | null;
  validation?: RuntimeValidation | null;
};

type RuntimeValidation = {
  ok: boolean;
  core_ok: boolean;
  items: ValidationItem[];
  world_disabled: ValidationItem[];
};

type ValidationItem = {
  scope: string;
  name: string;
  status: string;
  severity: string;
  message: string;
};

type SecretInfo = {
  configured: boolean;
  source?: string | null;
  masked: string;
  required?: boolean;
  referenced?: boolean;
  category?: 'required' | 'llm_api_key' | 'custom' | string;
};

type SecretStatus = Record<string, SecretInfo>;

type QQMusicCredentialStatus = {
  state: 'idle' | 'running' | 'success' | 'failed';
  running: boolean;
  message: string;
  started_at?: string | null;
  finished_at?: string | null;
  success?: boolean | null;
  credential_file?: string | null;
  legacy_file?: string | null;
  qr_file?: string | null;
};

type LlmInterfaceConfig = {
  api_type?: string;
  model?: string;
  api_key?: string;
  base_url?: string;
  can_enable_thinking?: boolean;
  can_use_json?: boolean;
  default_params?: Record<string, unknown>;
  [key: string]: unknown;
};

type ModuleBinding = {
  path: string;
  kind: 'llm' | 'vlm';
  interface_name: string;
  prompt_name?: string;
  enable_thinking?: boolean;
  use_json?: boolean;
  params?: Record<string, unknown>;
  params_text?: string;
};

type LlmConfigInfo = {
  available_llms: Record<string, LlmInterfaceConfig>;
  available_vlms: Record<string, LlmInterfaceConfig>;
  module_bindings: ModuleBinding[];
};

type LlmCall = {
  id: number;
  ts: string;
  trace_id?: string;
  user_id?: string;
  module_name: string;
  interface_name?: string;
  model_name?: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  latency_ms: number;
  success: number;
  error_type?: string;
  error_message?: string;
  metadata?: Record<string, unknown>;
};

type PipelineSpan = {
  id: number;
  trace_id: string;
  user_id?: string;
  topic_id?: string;
  span_name: string;
  start_ts: string;
  duration_ms: number;
  status: string;
  metadata?: Record<string, unknown>;
};

type LogEvent = {
  id: number;
  ts: string;
  level: string;
  logger_name: string;
  message: string;
  traceback?: string;
};

type TraceSummary = {
  trace_id: string;
  user_id?: string;
  topic_id?: string;
  start_ts?: string;
  end_ts?: string;
  duration_ms: number;
  span_count: number;
  total_span_ms: number;
  max_span_ms: number;
  llm_call_count: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  total_llm_latency_ms: number;
  failed_llm_calls: number;
};

type TraceDetail = {
  summary: TraceSummary;
  spans: PipelineSpan[];
  llm_calls: LlmCall[];
};

type MemoryTraceSummary = {
  window_days: number;
  totals: Record<string, number>;
  by_type: Array<Record<string, string | number | null>>;
};

type MemoryTraceEvent = {
  id: number;
  ts: string;
  trace_id?: string;
  user_id?: string;
  topic_id?: string;
  event_type: string;
  item_type: string;
  command_text?: string;
  content_text?: string;
  source_context?: string;
  result?: Record<string, unknown>;
  duration_ms: number;
  annotation_required: boolean;
  annotation_label?: string;
  annotation_notes?: string;
  annotation_updated_at?: string;
  metadata?: Record<string, unknown>;
};

type DynamicAdminPost = {
  id: string;
  author_type: string;
  author_id: string;
  author_name: string;
  owner_user_id?: string | null;
  visibility: string;
  content: string;
  image_refs?: unknown[];
  source_type: string;
  source_id?: string | null;
  allow_comment: boolean;
  memory_policy?: string | null;
  memory_status?: string | null;
  memory_error?: string | null;
  reply_status?: string | null;
  reply_error?: string | null;
  status: string;
  created_at?: string | null;
  updated_at?: string | null;
  comment_count?: number;
  cursor?: string;
};

type DynamicAdminComment = {
  id: string;
  dynamic_id: string;
  author_type: string;
  author_id: string;
  author_name: string;
  owner_user_id?: string | null;
  parent_comment_id?: string | null;
  content: string;
  memory_policy?: string | null;
  memory_status?: string | null;
  memory_error?: string | null;
  reply_status?: string | null;
  reply_error?: string | null;
  status: string;
  created_at?: string | null;
  updated_at?: string | null;
  cursor?: string;
};

type MemoryTraceTab = {
  id: string;
  label: string;
  eventTypes: string[];
  description: string;
  contextLabel: string;
  commandLabel: string;
  contentLabel: string;
  resultLabel: string;
  labels: Array<{ label: string; text: string }>;
};

type Page = 'dashboard' | 'llm' | 'pipeline' | 'traces' | 'memory' | 'dynamics' | 'invite_codes' | 'config' | 'logs';

type LlmStatsTab = {
  id: 'seven_days' | 'one_day' | 'recent';
  label: string;
  subtitle: string;
  url: string;
  metricTitle: string;
  tokenDetail: string;
  showTimeBuckets: boolean;
};

type LocalActionStatus = {
  tone: 'info' | 'success' | 'error';
  message: string;
};

type LlmChartMetric = {
  id: 'call_count' | 'total_tokens' | 'avg_total_tokens' | 'avg_prompt_tokens' | 'avg_completion_tokens' | 'avg_latency_ms' | 'failed_calls';
  label: string;
  field: string;
  format: 'number' | 'ms';
};

const llmStatsTabs: LlmStatsTab[] = [
  {
    id: 'seven_days',
    label: '7日平均',
    subtitle: '最近 7 日 LLM 调用量、Token 与耗时',
    url: '/admin/api/llm/summary?days=7&bucket_hours=2',
    metricTitle: '7 日调用',
    tokenDetail: '7 日累计',
    showTimeBuckets: true,
  },
  {
    id: 'one_day',
    label: '1日平均',
    subtitle: '最近 24 小时 LLM 调用量、Token 与耗时',
    url: '/admin/api/llm/summary?days=1&bucket_hours=2',
    metricTitle: '1 日调用',
    tokenDetail: '1 日累计',
    showTimeBuckets: true,
  },
  {
    id: 'recent',
    label: '最近平均',
    subtitle: '最近 50 次 LLM 调用的平均表现',
    url: '/admin/api/llm/summary?recent_limit=50',
    metricTitle: '最近调用',
    tokenDetail: '最近 50 次累计',
    showTimeBuckets: false,
  },
];

const llmChartMetrics: LlmChartMetric[] = [
  { id: 'call_count', label: '调用次数', field: 'call_count', format: 'number' },
  { id: 'total_tokens', label: 'Token 数', field: 'total_tokens', format: 'number' },
  { id: 'avg_total_tokens', label: '平均 Token', field: 'avg_total_tokens', format: 'number' },
  { id: 'avg_prompt_tokens', label: '平均 Prompt', field: 'avg_prompt_tokens', format: 'number' },
  { id: 'avg_completion_tokens', label: '平均 Completion', field: 'avg_completion_tokens', format: 'number' },
  { id: 'avg_latency_ms', label: '平均耗时', field: 'avg_latency_ms', format: 'ms' },
  { id: 'failed_calls', label: '失败次数', field: 'failed_calls', format: 'number' },
];

const memoryTraceTabs: MemoryTraceTab[] = [
  {
    id: 'memory_command',
    label: '记忆检索命令',
    eventTypes: ['memory_command'],
    description: '查看 TopicExtractor 在什么上下文下生成了哪些记忆检索 query。重点判断 query 是否覆盖当前会话需要的长期信息。',
    contextLabel: '输入上下文',
    commandLabel: '检索 query',
    contentLabel: '话题摘要',
    resultLabel: '调试信息',
    labels: [
      { label: 'good_query', text: '好查询' },
      { label: 'too_broad', text: '过宽' },
      { label: 'too_narrow', text: '过窄' },
      { label: 'missing_query', text: '漏查' },
    ],
  },
  {
    id: 'memory_recall',
    label: '记忆召回',
    eventTypes: ['memory_recall'],
    description: '查看每条 query 召回了哪条记忆、相似度和来源。重点判断这条记忆对本轮回复是否有帮助。',
    contextLabel: '话题上下文',
    commandLabel: '检索 query',
    contentLabel: '召回记忆',
    resultLabel: '召回元数据',
    labels: [
      { label: 'useful', text: '有用' },
      { label: 'not_useful', text: '无用' },
      { label: 'wrong_memory', text: '错召回' },
      { label: 'no_hit_should_hit', text: '应召未召' },
    ],
  },
  {
    id: 'memory_write',
    label: '记忆写入',
    eventTypes: ['memory_write', 'memory_write_extraction'],
    description: '查看当前对话被抽取成了哪些候选记忆，以及最终写入/跳过状态。重点判断新记忆是否值得长期保存。',
    contextLabel: '写入依据',
    commandLabel: '抽取命令',
    contentLabel: '候选/写入记忆',
    resultLabel: '写入状态',
    labels: [
      { label: 'reasonable', text: '合理' },
      { label: 'unreasonable', text: '不合理' },
      { label: 'too_trivial', text: '太琐碎' },
      { label: 'should_merge', text: '应合并' },
    ],
  },
  {
    id: 'user_profile_update',
    label: '用户画像',
    eventTypes: ['user_profile_update'],
    description: '查看长期上下文如何更新用户画像。重点判断画像是否准确、稳定，是否把短期状态误写成长期特征。',
    contextLabel: '画像依据',
    commandLabel: '更新意图',
    contentLabel: '新用户画像',
    resultLabel: '旧/新画像',
    labels: [
      { label: 'accurate', text: '准确' },
      { label: 'inaccurate', text: '不准确' },
      { label: 'overfit', text: '过拟合' },
      { label: 'missed_update', text: '漏更新' },
    ],
  },
  {
    id: 'fact_command',
    label: '事实命令',
    eventTypes: ['fact_command', 'fact_result'],
    description: '查看模型生成的事实检索命令和确定性事实结果。事实结果本身不要求标注，重点标注命令是否应该检索。',
    contextLabel: '输入上下文',
    commandLabel: '事实命令',
    contentLabel: '事实结果/话题',
    resultLabel: '结果元数据',
    labels: [
      { label: 'needed', text: '需要' },
      { label: 'unneeded', text: '多余' },
      { label: 'wrong_target', text: '目标错误' },
      { label: 'missing_fact', text: '漏事实' },
    ],
  },
  {
    id: 'sing_command',
    label: '唱歌尝试',
    eventTypes: ['sing_command', 'sing_result'],
    description: '查看模型识别出的唱歌尝试和确定性选段结果。选段不要求标注，重点判断唱歌意图识别是否正确。',
    contextLabel: '输入上下文',
    commandLabel: '唱歌尝试',
    contentLabel: '选歌/选段结果',
    resultLabel: '规划元数据',
    labels: [
      { label: 'correct_intent', text: '意图正确' },
      { label: 'wrong_intent', text: '意图错误' },
      { label: 'wrong_song', text: '歌名错误' },
      { label: 'missed_sing', text: '漏识别' },
    ],
  },
];

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { credentials: 'same-origin' });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

async function postJson<T>(url: string, payload: unknown): Promise<T> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

async function putJson<T>(url: string, payload: unknown): Promise<T> {
  const response = await fetch(url, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

function formatMs(value?: number) {
  if (value === undefined || Number.isNaN(value)) {
    return '-';
  }
  if (value >= 1000) {
    return `${(value / 1000).toFixed(2)}s`;
  }
  return `${value.toFixed(0)}ms`;
}

function formatNumber(value?: number) {
  return Number(value || 0).toLocaleString('zh-CN');
}

const shanghaiDateTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});

function formatShanghaiTime(value?: string | null) {
  if (!value) {
    return '-';
  }
  const normalized = /[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return shanghaiDateTimeFormatter.format(date).replace(/\//g, '-');
}

function currentShanghaiTimeText() {
  return shanghaiDateTimeFormatter.format(new Date()).replace(/\//g, '-');
}

function formatQQCredentialStatus(status?: QQMusicCredentialStatus | null) {
  if (!status) {
    return '尚未刷新';
  }
  const timestamp = formatShanghaiTime(status.finished_at || status.started_at);
  const title =
    status.running ? '正在更新' :
    status.success ? '更新成功' :
    status.state === 'failed' ? '更新失败' :
    '尚未刷新';
  const lines = [`${title} · ${timestamp}`];
  if (status.message) {
    lines.push(status.message);
  }
  if (status.running) {
    lines.push('请扫描下方二维码完成 QQ 音乐登录。');
  }
  return lines.join('\n');
}

function formatSecretCategory(secret: SecretInfo) {
  if (secret.required) {
    return '必需';
  }
  if (secret.referenced) {
    return 'LLM API Key';
  }
  return '自定义';
}

function formatChartValue(value: number, metric: LlmChartMetric) {
  return metric.format === 'ms' ? formatMs(value) : formatNumber(value);
}

function AdminGate() {
  const [status, setStatus] = useState<AdminAuthStatus | null>(null);
  const [authenticated, setAuthenticated] = useState(false);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    try {
      const nextStatus = await fetchJson<AdminAuthStatus>('/admin/api/admin-auth/status');
      setStatus(nextStatus);
      if (nextStatus.configured) {
        try {
          await fetchJson<RuntimeStatus>('/admin/api/runtime/status');
          setAuthenticated(true);
        } catch {
          setAuthenticated(false);
        }
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  if (loading) {
    return <div className="auth-shell"><div className="auth-panel">加载中...</div></div>;
  }
  if (!status?.configured) {
    return <AdminSetupPage onReady={refresh} />;
  }
  if (!authenticated) {
    return <AdminLoginPage onReady={() => setAuthenticated(true)} />;
  }
  return <App onLogout={() => setAuthenticated(false)} />;
}

function AdminSetupPage({ onReady }: { onReady: () => void }) {
  const [setupToken, setSetupToken] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    try {
      await postJson('/admin/api/admin-auth/setup', { setup_token: setupToken, password });
      setError(null);
      onReady();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="auth-shell">
      <div className="auth-panel">
        <h1>初始化控制台</h1>
        <p>输入服务器本地生成的 setup token，并设置管理员密码。</p>
        {error && <div className="status error">{error}</div>}
        <input value={setupToken} onChange={(event) => setSetupToken(event.target.value)} placeholder="Setup token" />
        <input value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Admin password" type="password" />
        <button onClick={submit}>完成初始化</button>
      </div>
    </div>
  );
}

function AdminLoginPage({ onReady }: { onReady: () => void }) {
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    try {
      await postJson('/admin/api/admin-auth/login', { password });
      setError(null);
      onReady();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="auth-shell">
      <div className="auth-panel">
        <h1>控制台登录</h1>
        <p>需要管理员密码才能访问服务端配置和监控数据。</p>
        {error && <div className="status error">{error}</div>}
        <input value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Admin password" type="password" onKeyDown={(event) => event.key === 'Enter' && void submit()} />
        <button onClick={submit}>登录</button>
      </div>
    </div>
  );
}

function App({ onLogout }: { onLogout: () => void }) {
  const [page, setPage] = useState<Page>('dashboard');

  async function logout() {
    await postJson('/admin/api/admin-auth/logout', {});
    onLogout();
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-title">AgentLuo</div>
          <div className="brand-subtitle">Server Console</div>
        </div>
        <nav className="nav">
          <button className={page === 'dashboard' ? 'active' : ''} onClick={() => setPage('dashboard')}>首页</button>
          <button className={page === 'llm' ? 'active' : ''} onClick={() => setPage('llm')}>LLM 统计</button>
          <button className={page === 'pipeline' ? 'active' : ''} onClick={() => setPage('pipeline')}>链路耗时</button>
          <button className={page === 'traces' ? 'active' : ''} onClick={() => setPage('traces')}>链路追踪</button>
          <button className={page === 'memory' ? 'active' : ''} onClick={() => setPage('memory')}>记忆追踪</button>
          <button className={page === 'dynamics' ? 'active' : ''} onClick={() => setPage('dynamics')}>动态管理</button>
          <button className={page === 'config' ? 'active' : ''} onClick={() => setPage('config')}>服务配置</button>
          <button className={page === 'invite_codes' ? 'active' : ''} onClick={() => setPage('invite_codes')}>邀请码管理</button>
          <button className={page === 'logs' ? 'active' : ''} onClick={() => setPage('logs')}>异常日志</button>
          <button onClick={logout}>退出登录</button>
        </nav>
      </aside>
      <main className="content">
        {page === 'dashboard' && <DashboardPage />}
        {page === 'llm' && <LlmPage />}
        {page === 'pipeline' && <PipelinePage />}
        {page === 'traces' && <TracePage />}
        {page === 'memory' && <MemoryTracePage />}
        {page === 'dynamics' && <DynamicsPage />}
        {page === 'invite_codes' && <InviteCodesPage />}
        {page === 'config' && <ConfigPage />}
        {page === 'logs' && <LogsPage />}
      </main>
    </div>
  );
}

function usePolling<T>(url: string | null, intervalMs = 10000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);
    async function load() {
      if (!url) {
        setLoading(false);
        setData(null);
        return;
      }
      try {
        const next = await fetchJson<T>(url);
        if (!cancelled) {
          setData(next);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    void load();
    const timer = window.setInterval(load, intervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [url, intervalMs]);

  return { data, error, loading };
}

function usePostPolling<T>(url: string | null, payload: unknown, intervalMs = 10000, refreshKey = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const payloadJson = JSON.stringify(payload);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    async function load() {
      if (!url) {
        setLoading(false);
        setData(null);
        return;
      }
      try {
        const next = await postJson<T>(url, JSON.parse(payloadJson));
        if (!cancelled) {
          setData(next);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    void load();
    const timer = window.setInterval(load, intervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [url, payloadJson, intervalMs, refreshKey]);

  return { data, error, loading };
}

function PageHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
      <div className="refresh-note">自动刷新</div>
    </header>
  );
}

function DashboardPage() {
  const { data, error, loading } = usePolling<DashboardSummary>('/admin/api/dashboard?days=1');
  const slowSpans = data?.slow_spans || [];
  const recentLogs = data?.recent_logs || [];

  return (
    <>
      <PageHeader title="首页" subtitle="今日服务端调用量、延迟和异常概览" />
      <StatusBar loading={loading} error={error} />
      <section className="metric-grid">
        <MetricCard title="LLM 调用" value={formatNumber(data?.llm?.call_count)} detail={`${formatNumber(data?.llm?.total_tokens)} tokens`} />
        <MetricCard title="LLM 平均耗时" value={formatMs(data?.llm?.avg_latency_ms)} detail={`${formatNumber(data?.llm?.failed_calls)} failed`} />
        <MetricCard title="Warnings" value={formatNumber(data?.logs?.warning_count)} detail="最近 24 小时" tone="warning" />
        <MetricCard title="Errors" value={formatNumber(data?.logs?.error_count)} detail="最近 24 小时" tone="danger" />
      </section>
      <section className="two-column">
        <Panel title="慢 Span">
          <SpanTable rows={slowSpans} compact />
        </Panel>
        <Panel title="最近异常">
          <LogTable rows={recentLogs} compact />
        </Panel>
      </section>
    </>
  );
}

function LlmPage() {
  const [activeTabId, setActiveTabId] = useState<LlmStatsTab['id']>('seven_days');
  const activeTab = llmStatsTabs.find((tab) => tab.id === activeTabId) || llmStatsTabs[0];
  const { data, error, loading } = usePolling<LlmSummary>(activeTab.url);
  return (
    <>
      <PageHeader title="LLM 统计" subtitle={activeTab.subtitle} />
      <div className="sub-tabs">
        {llmStatsTabs.map((tab) => (
          <button
            key={tab.id}
            className={tab.id === activeTabId ? 'active' : ''}
            onClick={() => setActiveTabId(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <StatusBar loading={loading} error={error} />
      <section className="metric-grid">
        <MetricCard title={activeTab.metricTitle} value={formatNumber(data?.totals?.call_count)} detail={`${formatNumber(data?.totals?.total_tokens)} tokens`} />
        <MetricCard title="平均 Token" value={formatNumber(data?.totals?.avg_total_tokens)} detail={`${formatNumber(data?.totals?.avg_prompt_tokens)} prompt / ${formatNumber(data?.totals?.avg_completion_tokens)} completion`} />
        <MetricCard title="Prompt Tokens" value={formatNumber(data?.totals?.prompt_tokens)} detail={activeTab.tokenDetail} />
        <MetricCard title="平均耗时" value={formatMs(data?.totals?.avg_latency_ms)} detail={`${formatNumber(data?.totals?.failed_calls)} failed`} />
      </section>
      <Panel title="模块统计">
        <LlmModuleTable rows={data?.by_module || []} />
      </Panel>
      {activeTab.showTimeBuckets && (
        <Panel title="分时趋势">
          <LlmTimeBucketChart rows={data?.time_buckets || []} />
        </Panel>
      )}
    </>
  );
}

function LlmModuleTable({ rows }: { rows: Array<Record<string, string | number | null>> }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Module</th>
          <th>Interface</th>
          <th>Model</th>
          <th>Calls</th>
          <th>Tokens</th>
          <th>Avg Tokens</th>
          <th>Avg Prompt</th>
          <th>Avg Completion</th>
          <th>Avg</th>
          <th>Failed</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={index}>
            <td>{String(row.module_name || '-')}</td>
            <td>{String(row.interface_name || '-')}</td>
            <td>{String(row.model_name || '-')}</td>
            <td>{formatNumber(Number(row.call_count || 0))}</td>
            <td>{formatNumber(Number(row.total_tokens || 0))}</td>
            <td>{formatNumber(Number(row.avg_total_tokens || 0))}</td>
            <td>{formatNumber(Number(row.avg_prompt_tokens || 0))}</td>
            <td>{formatNumber(Number(row.avg_completion_tokens || 0))}</td>
            <td>{formatMs(Number(row.avg_latency_ms || 0))}</td>
            <td>{formatNumber(Number(row.failed_calls || 0))}</td>
          </tr>
        ))}
        {rows.length === 0 && (
          <tr>
            <td colSpan={10} className="empty-state">暂无 LLM 调用数据</td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

function LlmTimeBucketChart({ rows }: { rows: Array<Record<string, string | number>> }) {
  const [activeMetricId, setActiveMetricId] = useState<LlmChartMetric['id']>('call_count');
  const metric = llmChartMetrics.find((item) => item.id === activeMetricId) || llmChartMetrics[0];
  const values = rows.map((row) => Number(row[metric.field] || 0));
  const maxValue = Math.max(...values, 0);
  const chartWidth = 960;
  const chartHeight = 300;
  const padding = { top: 24, right: 28, bottom: 54, left: 64 };
  const plotWidth = chartWidth - padding.left - padding.right;
  const plotHeight = chartHeight - padding.top - padding.bottom;
  const scaleY = (value: number) => {
    if (maxValue <= 0) {
      return padding.top + plotHeight;
    }
    return padding.top + plotHeight - (value / maxValue) * plotHeight;
  };
  const points = rows.map((row, index) => {
    const x = padding.left + (rows.length <= 1 ? plotWidth / 2 : (index / (rows.length - 1)) * plotWidth);
    const y = scaleY(Number(row[metric.field] || 0));
    return { x, y, row };
  });
  const polylinePoints = points.map((point) => `${point.x},${point.y}`).join(' ');
  const total = values.reduce((sum, value) => sum + value, 0);
  const average = values.length ? total / values.length : 0;

  return (
    <div className="llm-chart-panel">
      <div className="metric-switch">
        {llmChartMetrics.map((item) => (
          <button
            key={item.id}
            className={item.id === activeMetricId ? 'active' : ''}
            onClick={() => setActiveMetricId(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {rows.length === 0 ? (
        <div className="empty-state">暂无时段数据</div>
      ) : (
        <>
          <div className="line-chart-wrap">
            <svg className="line-chart" viewBox={`0 0 ${chartWidth} ${chartHeight}`} role="img" aria-label={`${metric.label}分时趋势`}>
              <line className="chart-axis" x1={padding.left} y1={padding.top} x2={padding.left} y2={padding.top + plotHeight} />
              <line className="chart-axis" x1={padding.left} y1={padding.top + plotHeight} x2={padding.left + plotWidth} y2={padding.top + plotHeight} />
              {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
                const y = padding.top + plotHeight - ratio * plotHeight;
                const value = maxValue * ratio;
                return (
                  <g key={ratio}>
                    <line className="chart-grid-line" x1={padding.left} y1={y} x2={padding.left + plotWidth} y2={y} />
                    <text className="chart-y-label" x={padding.left - 10} y={y + 4} textAnchor="end">
                      {formatChartValue(value, metric)}
                    </text>
                  </g>
                );
              })}
              {polylinePoints && <polyline className="chart-line" points={polylinePoints} />}
              {points.map((point, index) => (
                <g key={String(point.row.bucket_start || index)}>
                  <circle className="chart-point" cx={point.x} cy={point.y} r="4">
                    <title>{`${String(point.row.bucket_label || point.row.bucket_start)}: ${formatChartValue(Number(point.row[metric.field] || 0), metric)}`}</title>
                  </circle>
                  <text className="chart-x-label" x={point.x} y={padding.top + plotHeight + 24} textAnchor="middle">
                    {String(point.row.bucket_start || '').replace(':00', '')}
                  </text>
                </g>
              ))}
            </svg>
          </div>
          <div className="chart-summary">
            <span>峰值 {formatChartValue(maxValue, metric)}</span>
            <span>平均 {formatChartValue(average, metric)}</span>
          </div>
        </>
      )}
    </div>
  );
}

function PipelinePage() {
  const { data, error, loading } = usePolling<Record<string, LatencySummary>>('/admin/api/pipeline/latency?days=7');
  const { data: spans } = usePolling<PipelineSpan[]>('/admin/api/pipeline/spans?limit=100&slow=true');
  const summaryRows = useMemo(() => Object.entries(data || {}), [data]);

  return (
    <>
      <PageHeader title="链路耗时" subtitle="TopicPlanner、TopicReplier 和 TTS 首包延迟" />
      <StatusBar loading={loading} error={error} />
      <Panel title="7 日耗时分布">
        <table>
          <thead>
            <tr>
              <th>Span</th>
              <th>Count</th>
              <th>Avg</th>
              <th>P50</th>
              <th>P90</th>
              <th>P99</th>
              <th>Max</th>
            </tr>
          </thead>
          <tbody>
            {summaryRows.map(([name, row]) => (
              <tr key={name}>
                <td>{name}</td>
                <td>{formatNumber(row.count)}</td>
                <td>{formatMs(row.avg_ms)}</td>
                <td>{formatMs(row.p50_ms)}</td>
                <td>{formatMs(row.p90_ms)}</td>
                <td>{formatMs(row.p99_ms)}</td>
                <td>{formatMs(row.max_ms)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
      <Panel title="慢 Span 明细" className="scroll-panel">
        <SpanTable rows={spans || []} />
      </Panel>
    </>
  );
}

function TracePage() {
  const { data, error, loading } = usePolling<TraceSummary[]>('/admin/api/traces?days=7&limit=200');
  const traces = data || [];
  const [selectedTrace, setSelectedTrace] = useState<string | null>(null);
  const [traceQuery, setTraceQuery] = useState('');
  const visibleTraces = useMemo(() => {
    const query = traceQuery.trim().toLowerCase();
    if (!query) {
      return traces;
    }
    return traces.filter((trace) => trace.trace_id.toLowerCase().includes(query));
  }, [traceQuery, traces]);

  useEffect(() => {
    if (!selectedTrace && traces.length > 0) {
      setSelectedTrace(traces[0].trace_id);
    }
  }, [selectedTrace, traces]);

  function submitTraceSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextTrace = traceQuery.trim();
    if (nextTrace) {
      setSelectedTrace(nextTrace);
    }
  }

  const detailUrl = selectedTrace ? `/admin/api/traces/${encodeURIComponent(selectedTrace)}` : null;
  const { data: detail, error: detailError, loading: detailLoading } = usePolling<TraceDetail>(detailUrl);
  const summary = detail?.summary || traces.find((trace) => trace.trace_id === selectedTrace);

  return (
    <>
      <PageHeader title="链路追踪" subtitle="按 trace_id 汇总同一轮链路的耗时、Span 和 LLM Token" />
      <StatusBar loading={loading} error={error} />
      <section className="trace-layout">
        <Panel title="最近 Trace" className="scroll-panel trace-list-panel">
          <form className="trace-search" onSubmit={submitTraceSearch}>
            <input
              value={traceQuery}
              onChange={(event) => setTraceQuery(event.target.value)}
              placeholder="搜索或输入 trace_id"
            />
            <button type="submit">查看</button>
          </form>
          <table>
            <thead>
              <tr>
                <th>Trace</th>
                <th>Duration</th>
                <th>Spans</th>
                <th>LLM</th>
                <th>Tokens</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {visibleTraces.map((trace) => (
                <tr
                  key={trace.trace_id}
                  className={trace.trace_id === selectedTrace ? 'selected-row' : ''}
                  onClick={() => setSelectedTrace(trace.trace_id)}
                >
                  <td className="mono">{trace.trace_id}</td>
                  <td>{formatMs(trace.duration_ms)}</td>
                  <td>{formatNumber(trace.span_count)}</td>
                  <td>{formatNumber(trace.llm_call_count)}</td>
                  <td>{formatNumber(trace.total_tokens)}</td>
                  <td>{formatShanghaiTime(trace.end_ts || trace.start_ts)}</td>
                </tr>
              ))}
              {visibleTraces.length === 0 && (
                <tr>
                  <td colSpan={6}>没有匹配的 trace</td>
                </tr>
              )}
            </tbody>
          </table>
        </Panel>
        <div>
          <StatusBar loading={detailLoading} error={detailError} />
          <section className="metric-grid trace-metrics">
            <MetricCard title="链路耗时" value={formatMs(summary?.duration_ms)} detail={`${formatNumber(summary?.span_count)} spans`} />
            <MetricCard title="LLM Token" value={formatNumber(summary?.total_tokens)} detail={`${formatNumber(summary?.prompt_tokens)} prompt / ${formatNumber(summary?.completion_tokens)} completion`} />
            <MetricCard title="LLM 耗时和调用" value={formatMs(summary?.total_llm_latency_ms)} detail={`${formatNumber(summary?.llm_call_count)} calls`} />
            <MetricCard title="失败调用" value={formatNumber(summary?.failed_llm_calls)} detail={summary?.topic_id || 'topic_id -'} tone={summary?.failed_llm_calls ? 'danger' : undefined} />
          </section>
          <Panel title="Span 明细">
            <SpanTable rows={detail?.spans || []} />
          </Panel>
          <Panel title="LLM 调用明细">
            <LlmCallTable rows={detail?.llm_calls || []} />
          </Panel>
        </div>
      </section>
    </>
  );
}

function MemoryTracePage() {
  const [traceQuery, setTraceQuery] = useState('');
  const [activeTabId, setActiveTabId] = useState(memoryTraceTabs[0].id);
  const [annotationState, setAnnotationState] = useState('');
  const [refreshNonce, setRefreshNonce] = useState(0);
  const activeTab = memoryTraceTabs.find((tab) => tab.id === activeTabId) || memoryTraceTabs[0];
  const query = new URLSearchParams({
    days: '7',
    limit: '200',
    ...(traceQuery.trim() ? { trace_id: traceQuery.trim() } : {}),
    event_type: activeTab.eventTypes.join(','),
    ...(annotationState ? { annotation_state: annotationState } : {}),
    r: String(refreshNonce),
  });
  const { data: summary, error: summaryError, loading: summaryLoading } = usePolling<MemoryTraceSummary>('/admin/api/memory/summary?days=7');
  const { data, error, loading } = usePolling<MemoryTraceEvent[]>(`/admin/api/memory/events?${query.toString()}`);
  const visibleEvents = useMemo(() => {
    return (data || []).filter((event) => activeTab.eventTypes.includes(event.event_type));
  }, [activeTab, data]);
  const totals = summary?.totals || {};
  const typeRows = useMemo(() => {
    return (summary?.by_type || []).filter((row) => activeTab.eventTypes.includes(String(row.event_type || '')));
  }, [activeTab, summary]);

  async function annotate(eventId: number, label: string, notes?: string) {
    await postJson(`/admin/api/memory/events/${eventId}/annotation`, {
      label,
      notes,
      annotator: 'console',
    });
    setRefreshNonce((value) => value + 1);
  }

  return (
    <>
      <PageHeader title="记忆追踪" subtitle="查看记忆召回、记忆写入、用户画像更新、事实命令和唱歌尝试，并进行人工标注" />
      <StatusBar loading={summaryLoading || loading} error={summaryError || error} />
      <section className="metric-grid">
        <MetricCard title="事件总数" value={formatNumber(totals.event_count)} detail="最近 7 日" />
        <MetricCard title="需要标注" value={formatNumber(totals.annotation_required_count)} detail="召回、写入、画像、命令" />
        <MetricCard title="待标注" value={formatNumber(totals.pending_annotation_count)} detail="当前筛查重点" tone={totals.pending_annotation_count ? 'warning' : undefined} />
        <MetricCard title="已标注" value={formatNumber(totals.annotated_count)} detail="人工反馈样本" />
      </section>
      <Panel title="筛选">
        <div className="memory-tabs">
          {memoryTraceTabs.map((tab) => (
            <button
              key={tab.id}
              className={tab.id === activeTab.id ? 'active' : ''}
              onClick={() => setActiveTabId(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <div className="filter-row memory-filter-row">
          <input value={traceQuery} onChange={(event) => setTraceQuery(event.target.value)} placeholder="trace_id" />
          <select value={annotationState} onChange={(event) => setAnnotationState(event.target.value)}>
            <option value="">全部标注状态</option>
            <option value="pending">待标注</option>
            <option value="annotated">已标注</option>
          </select>
        </div>
      </Panel>
      <section className="two-column">
        <Panel title={activeTab.label}>
          <div className="behavior-note">{activeTab.description}</div>
          <table>
            <thead>
              <tr>
                <th>Event</th>
                <th>Item</th>
                <th>Count</th>
                <th>Pending</th>
                <th>Avg</th>
                <th>Max</th>
              </tr>
            </thead>
            <tbody>
              {typeRows.map((row, index) => (
                <tr key={index}>
                  <td>{String(row.event_type || '-')}</td>
                  <td>{String(row.item_type || '-')}</td>
                  <td>{formatNumber(Number(row.event_count || 0))}</td>
                  <td>{formatNumber(Number(row.pending_annotation_count || 0))}</td>
                  <td>{formatMs(Number(row.avg_duration_ms || 0))}</td>
                  <td>{formatMs(Number(row.max_duration_ms || 0))}</td>
                </tr>
              ))}
              {typeRows.length === 0 && (
                <tr>
                  <td colSpan={6}>暂无该行为的统计</td>
                </tr>
              )}
            </tbody>
          </table>
        </Panel>
        <Panel title={`${activeTab.label}事件`} className="scroll-panel memory-event-panel">
          <div className="memory-event-list">
            {visibleEvents.map((event) => (
              <MemoryEventCard key={event.id} event={event} tab={activeTab} onAnnotate={annotate} />
            ))}
            {visibleEvents.length === 0 && <div className="empty-state">没有匹配的{activeTab.label}事件</div>}
          </div>
        </Panel>
      </section>
    </>
  );
}

function DynamicsPage() {
  const [ownerQuery, setOwnerQuery] = useState('');
  const [authorType, setAuthorType] = useState('');
  const [sourceType, setSourceType] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [createdAfter, setCreatedAfter] = useState('');
  const [createdBefore, setCreatedBefore] = useState('');
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [systemContent, setSystemContent] = useState('');
  const [systemSourceType, setSystemSourceType] = useState('system_notice');
  const [systemSourceId, setSystemSourceId] = useState('');
  const [systemAllowComment, setSystemAllowComment] = useState(false);
  const [systemPublishStatus, setSystemPublishStatus] = useState<LocalActionStatus | null>(null);
  const [systemPublishing, setSystemPublishing] = useState(false);

  const query = useMemo(() => {
    const params = new URLSearchParams({ limit: '100' });
    params.set('_', String(refreshNonce));
    if (ownerQuery.trim()) {
      params.set('owner_user_id', ownerQuery.trim());
    }
    if (authorType) {
      params.set('author_type', authorType);
    }
    if (sourceType) {
      params.set('source_type', sourceType);
    }
    if (statusFilter) {
      params.set('status', statusFilter);
    }
    if (createdAfter) {
      params.set('created_after', createdAfter);
    }
    if (createdBefore) {
      params.set('created_before', createdBefore);
    }
    return params.toString();
  }, [authorType, createdAfter, createdBefore, ownerQuery, refreshNonce, sourceType, statusFilter]);

  const { data, error, loading } = usePolling<{ items: DynamicAdminPost[]; has_more: boolean; next_cursor: string | null }>(
    `/admin/api/dynamics?${query}`,
    15000,
  );
  const rows = data?.items || [];

  const [selectedDynamicId, setSelectedDynamicId] = useState<string | null>(null);

  useEffect(() => {
    if (!rows.length) {
      setSelectedDynamicId(null);
      return;
    }
    if (!selectedDynamicId || !rows.some((row) => row.id === selectedDynamicId)) {
      setSelectedDynamicId(rows[0].id);
    }
  }, [rows, selectedDynamicId]);

  const selected = rows.find((row) => row.id === selectedDynamicId) || null;
  const commentQuery = useMemo(() => {
    if (!selectedDynamicId) {
      return null;
    }
    const params = new URLSearchParams({ limit: '200' });
    if (ownerQuery.trim()) {
      params.set('owner_user_id', ownerQuery.trim());
    }
    if (createdAfter) {
      params.set('created_after', createdAfter);
    }
    if (createdBefore) {
      params.set('created_before', createdBefore);
    }
    return `/admin/api/dynamics/${encodeURIComponent(selectedDynamicId)}/comments?${params.toString()}`;
  }, [createdAfter, createdBefore, ownerQuery, selectedDynamicId]);

  const { data: commentData, error: commentError, loading: commentLoading } = usePolling<{ items: DynamicAdminComment[] }>(
    commentQuery,
    15000,
  );
  const comments = commentData?.items || [];

  const waitingReplyCount = rows.filter((row) => row.reply_status === 'pending').length;
  const waitingMemoryCount = rows.filter((row) => row.memory_status === 'pending').length;
  const failedCount = rows.filter((row) => row.reply_status === 'failed' || row.memory_status === 'failed').length;

  async function publishSystemDynamic() {
    const content = systemContent.trim();
    if (!content) {
      setSystemPublishStatus({ tone: 'error', message: '系统动态内容不能为空' });
      return;
    }
    setSystemPublishing(true);
    setSystemPublishStatus({ tone: 'info', message: '正在发布系统动态...' });
    try {
      const result = await postJson<{ ok: boolean; item: DynamicAdminPost }>('/admin/api/dynamics/system', {
        content,
        source_type: systemSourceType.trim() || 'system_notice',
        source_id: systemSourceId.trim() || null,
        visibility: 'global',
        allow_comment: systemAllowComment,
      });
      setSystemContent('');
      setSystemPublishStatus({
        tone: 'success',
        message: `发布成功 · ${result.item.id}`,
      });
      setAuthorType('');
      setSourceType('');
      setRefreshNonce((value) => value + 1);
    } catch (err) {
      setSystemPublishStatus({
        tone: 'error',
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setSystemPublishing(false);
    }
  }

  return (
    <>
      <PageHeader title="动态管理" subtitle="查看用户动态、天依动态、系统通知，以及评论、回复和记忆处理状态" />
      <StatusBar loading={loading} error={error} />
      <section className="metric-grid">
        <MetricCard title="当前动态" value={formatNumber(rows.length)} detail={data?.has_more ? '当前页前 100 条' : '当前筛选结果'} />
        <MetricCard title="待回复" value={formatNumber(waitingReplyCount)} detail="reply_status = pending" />
        <MetricCard title="待记忆" value={formatNumber(waitingMemoryCount)} detail="memory_status = pending" />
        <MetricCard title="失败项" value={formatNumber(failedCount)} detail="reply/memory failed" tone={failedCount ? 'danger' : undefined} />
      </section>

      <Panel title="发布系统动态">
        <div className="system-dynamic-publisher">
          <textarea
            value={systemContent}
            onChange={(event) => setSystemContent(event.target.value)}
            placeholder="输入要展示给所有用户的系统通知"
            rows={4}
          />
          <div className="system-dynamic-controls">
            <input
              value={systemSourceType}
              onChange={(event) => setSystemSourceType(event.target.value)}
              placeholder="source_type"
            />
            <input
              value={systemSourceId}
              onChange={(event) => setSystemSourceId(event.target.value)}
              placeholder="source_id，可选"
            />
            <label className="checkbox-line">
              <input
                type="checkbox"
                checked={systemAllowComment}
                onChange={(event) => setSystemAllowComment(event.target.checked)}
              />
              允许评论
            </label>
            <button onClick={publishSystemDynamic} disabled={systemPublishing || !systemContent.trim()}>
              {systemPublishing ? '发布中...' : '发布'}
            </button>
          </div>
          {systemPublishStatus && (
            <div className={`inline-status ${systemPublishStatus.tone === 'error' ? 'error' : systemPublishStatus.tone === 'success' ? 'success' : ''}`}>
              {systemPublishStatus.message}
            </div>
          )}
        </div>
      </Panel>

      <Panel title="筛选">
        <div className="filter-row dynamic-filter-row">
          <input value={ownerQuery} onChange={(event) => setOwnerQuery(event.target.value)} placeholder="owner_user_id" />
          <select value={authorType} onChange={(event) => setAuthorType(event.target.value)}>
            <option value="">全部作者</option>
            <option value="user">用户</option>
            <option value="agent">天依</option>
            <option value="system">系统</option>
          </select>
          <select value={sourceType} onChange={(event) => setSourceType(event.target.value)}>
            <option value="">全部来源</option>
            <option value="user_post">用户动态</option>
            <option value="citywalk">城市漫步</option>
            <option value="song_learned">学歌完成</option>
            <option value="system_notice">系统通知</option>
          </select>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="">全部状态</option>
            <option value="published">published</option>
            <option value="hidden">hidden</option>
            <option value="deleted">deleted</option>
          </select>
          <input type="datetime-local" value={createdAfter} onChange={(event) => setCreatedAfter(event.target.value)} />
          <input type="datetime-local" value={createdBefore} onChange={(event) => setCreatedBefore(event.target.value)} />
        </div>
      </Panel>

      <section className="dynamic-layout">
        <Panel title="动态列表" className="scroll-panel dynamic-list-panel">
          <div className="dynamic-card-list">
            {rows.map((row) => (
              <button
                key={row.id}
                className={`dynamic-card ${row.id === selectedDynamicId ? 'active' : ''}`}
                onClick={() => setSelectedDynamicId(row.id)}
              >
                <div className="dynamic-card-head">
                  <div>
                    <strong>{row.author_name}</strong>
                    <span className="pill">{row.author_type}</span>
                    <span className="pill">{row.source_type}</span>
                  </div>
                  <div className="mono">{row.id.slice(0, 8)}</div>
                </div>
                <div className="dynamic-card-meta">
                  <span>{row.created_at || '-'}</span>
                  <span>owner {row.owner_user_id || '-'}</span>
                  <span>{row.visibility}</span>
                </div>
                <div className="dynamic-card-content">{row.content || '-'}</div>
                <div className="dynamic-card-status">
                  <span className={`pill ${row.reply_status === 'failed' ? 'error' : row.reply_status === 'pending' ? 'warning' : 'success'}`}>
                    reply {row.reply_status || '-'}
                  </span>
                  <span className={`pill ${row.memory_status === 'failed' ? 'error' : row.memory_status === 'pending' ? 'warning' : 'success'}`}>
                    memory {row.memory_status || '-'}
                  </span>
                  <span className="pill">{formatNumber(row.comment_count || 0)} comments</span>
                </div>
              </button>
            ))}
            {rows.length === 0 && <div className="empty-state">当前筛选条件下没有动态</div>}
          </div>
        </Panel>

        <div>
          <Panel title="动态详情">
            {selected ? (
              <div className="dynamic-detail-grid">
                <ReadBlock title="内容" value={selected.content} />
                <ReadBlock
                  title="元信息"
                  value={[
                    `id: ${selected.id}`,
                    `author: ${selected.author_name} (${selected.author_type})`,
                    `owner_user_id: ${selected.owner_user_id || '-'}`,
                    `source_type: ${selected.source_type}`,
                    `visibility: ${selected.visibility}`,
                    `allow_comment: ${String(selected.allow_comment)}`,
                    `created_at: ${selected.created_at || '-'}`,
                    `updated_at: ${selected.updated_at || '-'}`,
                  ].join('\n')}
                />
                <ReadBlock
                  title="回复状态"
                  value={[
                    `reply_status: ${selected.reply_status || '-'}`,
                    selected.reply_error ? `reply_error: ${selected.reply_error}` : '',
                  ].filter(Boolean).join('\n') || '-'}
                />
                <ReadBlock
                  title="记忆状态"
                  value={[
                    `memory_policy: ${selected.memory_policy || '-'}`,
                    `memory_status: ${selected.memory_status || '-'}`,
                    selected.memory_error ? `memory_error: ${selected.memory_error}` : '',
                  ].filter(Boolean).join('\n') || '-'}
                />
              </div>
            ) : (
              <div className="empty-state">请选择一条动态</div>
            )}
          </Panel>

          <Panel title={`评论列表 (${formatNumber(comments.length)})`} className="scroll-panel dynamic-comments-panel">
            {commentLoading && <div className="inline-status">评论加载中...</div>}
            {commentError && <div className="inline-status error">评论请求失败：{commentError}</div>}
            {!commentLoading && !commentError && comments.length === 0 && <div className="empty-state">暂无评论</div>}
            <div className="dynamic-comment-list">
              {comments.map((comment) => (
                <article key={comment.id} className="dynamic-comment-card">
                  <div className="dynamic-comment-head">
                    <div>
                      <strong>{comment.author_name}</strong>
                      <span className="pill">{comment.author_type}</span>
                    </div>
                    <div>{comment.created_at || '-'}</div>
                  </div>
                  <div className="dynamic-comment-meta">
                    owner {comment.owner_user_id || '-'} · parent {comment.parent_comment_id || '-'}
                  </div>
                  <div className="dynamic-comment-content">{comment.content}</div>
                  <div className="dynamic-card-status">
                    <span className={`pill ${comment.reply_status === 'failed' ? 'error' : comment.reply_status === 'pending' ? 'warning' : 'success'}`}>
                      reply {comment.reply_status || '-'}
                    </span>
                    <span className={`pill ${comment.memory_status === 'failed' ? 'error' : comment.memory_status === 'pending' ? 'warning' : 'success'}`}>
                      memory {comment.memory_status || '-'}
                    </span>
                  </div>
                  {(comment.reply_error || comment.memory_error) ? (
                    <div className="dynamic-comment-errors">
                      {comment.reply_error && <div>reply_error: {comment.reply_error}</div>}
                      {comment.memory_error && <div>memory_error: {comment.memory_error}</div>}
                    </div>
                  ) : null}
                </article>
              ))}
            </div>
          </Panel>
        </div>
      </section>
    </>
  );
}

type InviteCodeRow = {
  code: string;
  is_used: boolean;
  disabled: boolean;
  created_at?: string | null;
  used_at?: string | null;
  user_id?: string | null;
  username?: string | null;
  nickname?: string | null;
  can_use?: boolean;
};

function InviteCodesPage() {
  const [statusFilter, setStatusFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [genCount, setGenCount] = useState('5');
  const [genCodes, setGenCodes] = useState<string[]>([]);
  const [genStatus, setGenStatus] = useState<LocalActionStatus | null>(null);
  const [genBusy, setGenBusy] = useState(false);

  const queryPayload = useMemo(() => ({
    limit: 500,
    status: statusFilter || null,
    search: searchQuery.trim() || null,
  }), [searchQuery, statusFilter]);

  const { data, error, loading } = usePostPolling<{ items: InviteCodeRow[]; total: number }>(
    '/admin/api/invite-codes/query',
    queryPayload,
    10000,
    refreshNonce,
  );
  const rows = data?.items || [];

  const canUse = (row: InviteCodeRow) => row.can_use ?? (!row.is_used && !row.disabled);
  const unusedCount = rows.filter((row) => !row.is_used).length;
  const availableCount = rows.filter(canUse).length;
  const usedCount = rows.filter((row) => row.is_used).length;
  const disabledCount = rows.filter((row) => row.disabled).length;

  async function generateCodes() {
    const count = Number.parseInt(genCount, 10);
    if (!Number.isFinite(count) || count < 1 || count > 100) {
      setGenCodes([]);
      setGenStatus({ tone: 'error', message: '生成数量需在 1-100 之间' });
      return;
    }
    setGenBusy(true);
    setGenCodes([]);
    setGenStatus({ tone: 'info', message: '正在生成...' });
    try {
      const result = await postJson<{ ok: boolean; codes: string[] }>('/admin/api/invite-codes/generate', { count });
      setGenCodes(result.codes);
      setGenStatus({ tone: 'success', message: `已生成 ${result.codes.length} 个邀请码` });
      setRefreshNonce((value) => value + 1);
    } catch (err) {
      setGenStatus({ tone: 'error', message: err instanceof Error ? err.message : String(err) });
    } finally {
      setGenBusy(false);
    }
  }

  async function copyCode(code: string) {
    try {
      await navigator.clipboard.writeText(code);
      setGenStatus({ tone: 'success', message: `已复制 ${code}` });
    } catch {
      setGenStatus({ tone: 'error', message: '复制失败，请手动复制' });
    }
  }

  async function setCodeDisabled(row: InviteCodeRow, disabled: boolean) {
    try {
      await postJson<{ ok: boolean; message: string }>(
        '/admin/api/invite-codes/set-disabled',
        { code: row.code, disabled },
      );
      setRefreshNonce((value) => value + 1);
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    }
  }

  async function deleteCode(row: InviteCodeRow) {
    if (!window.confirm(`确定删除邀请码 ${row.code} 吗？`)) {
      return;
    }
    try {
      await postJson<{ ok: boolean; message: string }>('/admin/api/invite-codes/delete', { code: row.code });
      setRefreshNonce((value) => value + 1);
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <>
      <PageHeader title="邀请码管理" subtitle="查看使用情况、批量生成并启用或禁用邀请码" />
      <StatusBar loading={loading} error={error} />
      <section className="metric-grid">
        <MetricCard title="当前列表" value={formatNumber(rows.length)} detail={data?.total !== undefined ? `共 ${formatNumber(data.total)} 条` : '当前页'} />
        <MetricCard title="未使用" value={formatNumber(unusedCount)} detail="尚未绑定用户" />
        <MetricCard title="可使用" value={formatNumber(availableCount)} detail="可用于注册" />
        <MetricCard title="已使用" value={formatNumber(usedCount)} detail="已绑定用户" />
        <MetricCard title="已禁用" value={formatNumber(disabledCount)} detail="不可注册" tone={disabledCount ? 'warning' : undefined} />
      </section>

      <Panel title="生成邀请码">
        <div className="system-dynamic-publisher">
          <div className="system-dynamic-controls">
            <input
              type="number"
              min={1}
              max={100}
              value={genCount}
              onChange={(event) => setGenCount(event.target.value)}
              placeholder="生成数量"
            />
            <button onClick={generateCodes} disabled={genBusy}>
              {genBusy ? '生成中...' : '生成'}
            </button>
          </div>
          {genStatus && (
            <div className={`inline-status ${genStatus.tone === 'error' ? 'error' : genStatus.tone === 'success' ? 'success' : ''}`}>
              {genStatus.message}
            </div>
          )}
          {genCodes.length > 0 && (
            <div className="invite-code-result">
              {genCodes.map((code) => (
                <button key={code} className="mono invite-code-copy" onClick={() => copyCode(code)} title="点击复制">
                  {code}
                </button>
              ))}
            </div>
          )}
        </div>
      </Panel>

      <Panel title="筛选">
        <div className="filter-row">
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="">全部状态</option>
            <option value="unused">可使用</option>
            <option value="used">已使用</option>
            <option value="disabled">已禁用</option>
          </select>
          <input value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="按邀请码搜索" />
        </div>
      </Panel>

      <Panel title="邀请码列表">
        <div className="invite-code-table-scroll">
          <table>
            <thead>
              <tr>
                <th>邀请码</th>
                <th>使用状态</th>
                <th>可使用</th>
                <th>创建时间</th>
                <th>使用时间</th>
                <th>使用者</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.code}>
                  <td className="mono">{row.code}</td>
                  <td>
                    <span className={`pill ${row.is_used ? 'warning' : 'success'}`}>
                      {row.is_used ? '已使用' : '未使用'}
                    </span>
                  </td>
                  <td>
                    <span className={`pill ${canUse(row) ? 'success' : 'error'}`}>
                      {canUse(row) ? '可以' : '不可以'}
                    </span>
                  </td>
                  <td>{row.created_at || '-'}</td>
                  <td>{row.used_at || '-'}</td>
                  <td>{row.username ? `${row.username}${row.nickname ? `（${row.nickname}）` : ''}` : row.user_id || '-'}</td>
                  <td>
                    <div className="row-actions">
                      <button onClick={() => setCodeDisabled(row, !row.disabled)}>
                        {row.disabled ? '启用' : '禁用'}
                      </button>
                      <button onClick={() => deleteCode(row)} disabled={row.is_used || row.disabled}>
                        删除
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={7}>当前筛选条件下没有邀请码</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}

function ConfigPage() {
  const { data: runtime, error: runtimeError, loading: runtimeLoading } = usePolling<RuntimeStatus>('/admin/api/runtime/status', 5000);
  const [secretRefreshNonce, setSecretRefreshNonce] = useState(0);
  const { data: secrets, error: secretError, loading: secretLoading } = usePolling<SecretStatus>(`/admin/api/secrets/status?nonce=${secretRefreshNonce}`, 10000);
  const { data: validation, error: validationError, loading: validationLoading } = usePolling<RuntimeValidation>('/admin/api/config/validation', 10000);
  const { data: qqCredentialStatus, error: qqCredentialError, loading: qqCredentialLoading } = usePolling<QQMusicCredentialStatus>('/admin/api/qq-music/credential/status', 3000);
  const [llmDraft, setLlmDraft] = useState<LlmConfigInfo | null>(null);
  const [llmLoading, setLlmLoading] = useState(true);
  const [secretUpdates, setSecretUpdates] = useState<Record<string, string>>({});
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [runtimeOverride, setRuntimeOverride] = useState<RuntimeStatus | null>(null);
  const [qqCredentialOverride, setQqCredentialOverride] = useState<QQMusicCredentialStatus | null>(null);
  const [qrImageNonce, setQrImageNonce] = useState(0);
  const [llmApplyStatus, setLlmApplyStatus] = useState<LocalActionStatus | null>(null);
  const [llmApplying, setLlmApplying] = useState(false);
  const [newSecretKey, setNewSecretKey] = useState('');
  const [newSecretValue, setNewSecretValue] = useState('');

  async function loadLlmConfig() {
    setLlmLoading(true);
    try {
      setLlmDraft(await fetchJson<LlmConfigInfo>('/admin/api/llm/config'));
      setActionError(null);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setLlmLoading(false);
    }
  }

  useEffect(() => {
    void loadLlmConfig();
  }, []);

  useEffect(() => {
    if (!runtime || !runtimeOverride) {
      return;
    }
    const overrideState = runtimeOverride.state;
    const runtimeState = runtime.state;
    const actualStateCaughtUp =
      (!['starting', 'stopping'].includes(overrideState) && runtimeState === overrideState) ||
      (overrideState === 'starting' && ['starting', 'running', 'blocked', 'failed'].includes(runtimeState)) ||
      (overrideState === 'stopping' && ['stopping', 'stopped', 'starting', 'failed'].includes(runtimeState));
    if (actualStateCaughtUp) {
      setRuntimeOverride(null);
      if (actionMessage?.startsWith('Runtime ')) {
        setActionMessage(null);
      }
    }
  }, [runtime?.state, runtimeOverride?.state, actionMessage]);

  useEffect(() => {
    const runtimeSettled = runtime && !runtime.busy && !['starting', 'stopping'].includes(runtime.state);
    if (!runtimeOverride && runtimeSettled && actionMessage?.startsWith('Runtime ')) {
      setActionMessage(null);
    }
  }, [runtime?.state, runtime?.busy, runtimeOverride, actionMessage]);

  useEffect(() => {
    if (!qqCredentialStatus || !qqCredentialOverride) {
      return;
    }
    if (qqCredentialStatus.started_at === qqCredentialOverride.started_at) {
      setQqCredentialOverride(null);
    }
  }, [qqCredentialStatus?.state, qqCredentialStatus?.started_at, qqCredentialOverride?.started_at]);

  useEffect(() => {
    const activeStatus = qqCredentialOverride || qqCredentialStatus;
    if (!activeStatus?.running) {
      return;
    }
    setQrImageNonce(Date.now());
    const timer = window.setInterval(() => setQrImageNonce(Date.now()), 2000);
    return () => window.clearInterval(timer);
  }, [qqCredentialOverride?.running, qqCredentialStatus?.running, qqCredentialOverride?.started_at, qqCredentialStatus?.started_at]);

  async function runtimeAction(action: 'start' | 'stop' | 'restart') {
    const pendingState = action === 'stop' || (action === 'restart' && runtime?.running) ? 'stopping' : 'starting';
    const pendingMessage =
      action === 'start' ? 'Runtime 启动中...' : action === 'stop' ? 'Runtime 停止中...' : 'Runtime 重启中...';
    const pendingStatus: RuntimeStatus = {
      ...(runtime || {
        state: 'stopped',
        running: false,
        last_error: null,
        last_started_at: null,
        last_stopped_at: null,
        validation: null,
      }),
      state: pendingState,
      busy: true,
    };
    try {
      setRuntimeOverride(pendingStatus);
      setActionMessage(pendingMessage);
      const nextStatus = await postJson<RuntimeStatus>(`/admin/api/runtime/${action}`, {});
      setRuntimeOverride(nextStatus);
      const isTransition = nextStatus.busy || ['starting', 'stopping'].includes(nextStatus.state);
      setActionMessage(isTransition ? pendingMessage : `Runtime 当前状态：${nextStatus.state}`);
      setActionError(null);
    } catch (err) {
      setRuntimeOverride(null);
      setActionMessage(null);
      setActionError(err instanceof Error ? err.message : String(err));
    }
  }

  async function saveSecrets() {
    try {
      await putJson('/admin/api/secrets', secretUpdates);
      setSecretUpdates({});
      setSecretRefreshNonce(Date.now());
      setActionError(null);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    }
  }

  async function addSecret() {
    const key = newSecretKey.trim();
    if (!/^[A-Z_][A-Z0-9_]*$/.test(key)) {
      setActionError('新增 Secret 名称必须是合法环境变量名，例如 QWEN_API_KEY');
      return;
    }
    if (!newSecretValue) {
      setActionError('新增 Secret 的值不能为空');
      return;
    }
    try {
      await putJson('/admin/api/secrets', { [key]: newSecretValue });
      setNewSecretKey('');
      setNewSecretValue('');
      setSecretRefreshNonce(Date.now());
      setActionError(null);
      setActionMessage(`已保存 ${key}`);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    }
  }

  async function deleteSecret(key: string) {
    const info = secrets?.[key];
    if (info?.required) {
      setActionError(`${key} 是必需项，不能删除`);
      return;
    }
    if (!window.confirm(`删除 ${key}？`)) {
      return;
    }
    try {
      await putJson('/admin/api/secrets', { [key]: null });
      setSecretUpdates((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
      setSecretRefreshNonce(Date.now());
      setActionError(null);
      setActionMessage(`已删除 ${key}`);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    }
  }

  async function refreshQQMusicCredential() {
    const startedAt = new Date().toISOString();
    setQqCredentialOverride({
      state: 'running',
      running: true,
      message: `正在更新 QQ 音乐凭证，操作时间 ${currentShanghaiTimeText()}`,
      started_at: startedAt,
      finished_at: null,
      success: null,
      credential_file: null,
      legacy_file: null,
      qr_file: null,
    });
    try {
      const nextStatus = await postJson<QQMusicCredentialStatus>('/admin/api/qq-music/credential/refresh', {});
      setQqCredentialOverride(nextStatus);
      setActionError(null);
    } catch (err) {
      setQqCredentialOverride(null);
      setActionError(err instanceof Error ? err.message : String(err));
    }
  }

  async function applyLlmConfig() {
    if (!llmDraft) {
      return;
    }
    setLlmApplying(true);
    setLlmApplyStatus({ tone: 'info', message: '正在写入配置并校验，必要时会重启 runtime...' });
    try {
      const result = await postJson<{ ok: boolean; validation: RuntimeValidation; runtime: RuntimeStatus; written: boolean; restarted: boolean }>('/admin/api/llm/config/apply', llmDraft);
      if (!result.ok) {
        const errors = result.validation.items.filter((item) => item.status === 'error' && item.scope !== 'world');
        const message = `配置未写入：${errors[0]?.message || '核心配置校验失败'}`;
        setActionError(message);
        setLlmApplyStatus({ tone: 'error', message });
        setActionMessage(null);
        return;
      }
      const message = result.restarted ? '配置已写入，runtime 已重启' : '配置已写入，runtime 当前未启动';
      setActionError(null);
      setActionMessage(message);
      setLlmApplyStatus({ tone: 'success', message });
      await loadLlmConfig();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setActionError(message);
      setLlmApplyStatus({ tone: 'error', message: `配置写入失败：${message}` });
    } finally {
      setLlmApplying(false);
    }
  }

  const validationItems = validation?.items || runtime?.validation?.items || [];
  const worldDisabled = validation?.world_disabled || runtime?.validation?.world_disabled || [];
  const effectiveRuntime = runtimeOverride || runtime;
  const effectiveQQCredentialStatus = qqCredentialOverride || qqCredentialStatus;
  const secretEntries = Object.entries(secrets || {});
  const runtimeState = effectiveRuntime?.state || '-';
  const runtimeBusy = Boolean(effectiveRuntime?.busy || ['starting', 'stopping'].includes(runtimeState));
  const runtimeDetail = runtimeBusy ? '状态切换中' : effectiveRuntime?.running ? '业务运行中' : '业务未启动';
  const qqCredentialRunning = Boolean(effectiveQQCredentialStatus?.running);
  const qqQrUrl = qqCredentialRunning ? `/admin/api/qq-music/credential/qr?ts=${encodeURIComponent(effectiveQQCredentialStatus?.started_at || '')}&nonce=${qrImageNonce}` : null;

  return (
    <>
      <PageHeader title="服务配置" subtitle="运行时启停、环境变量、资源和 LLM/VLM 配置检查" />
      <StatusBar loading={runtimeLoading || secretLoading || validationLoading || qqCredentialLoading || llmLoading} error={runtimeError || secretError || validationError || qqCredentialError || actionError} />
      {actionMessage && <div className="status">{actionMessage}</div>}
      <section className="metric-grid">
        <MetricCard title="Runtime" value={runtimeState} detail={runtimeDetail} />
        <MetricCard title="核心配置" value={validation?.core_ok ? 'OK' : 'BLOCKED'} detail={`${validationItems.filter((item) => item.status === 'error' && item.scope !== 'world').length} errors`} tone={validation?.core_ok ? undefined : 'danger'} />
        <MetricCard title="World 降级" value={formatNumber(worldDisabled.length)} detail="可选任务禁用数" tone={worldDisabled.length ? 'warning' : undefined} />
        <MetricCard title="Secrets" value={formatNumber(Object.values(secrets || {}).filter((item) => item.configured).length)} detail="已配置项" />
      </section>
      <Panel title="运行时控制">
        <div className="action-row">
          <button disabled={runtimeBusy} onClick={() => void runtimeAction('start')}>启动</button>
          <button disabled={runtimeBusy} onClick={() => void runtimeAction('restart')}>重启</button>
          <button disabled={runtimeBusy} onClick={() => void runtimeAction('stop')}>停止</button>
        </div>
        {runtime?.last_error && <pre className="error-block">{runtime.last_error}</pre>}
      </Panel>
      <Panel title="环境变量 / Secrets">
        <div className="secret-list">
          {secretEntries.map(([key, value]) => (
            <div className="secret-row" key={key}>
              <div>
                <strong>{key}</strong>
                <span>{formatSecretCategory(value)} · {value.configured ? `${value.source || '-'} · ${value.masked}` : '未配置'}</span>
              </div>
              <input
                value={secretUpdates[key] || ''}
                onChange={(event) => setSecretUpdates((prev) => ({ ...prev, [key]: event.target.value }))}
                placeholder="留空则不修改"
                type="password"
              />
              <button className="danger-button" disabled={Boolean(value.required)} onClick={() => void deleteSecret(key)}>删除</button>
            </div>
          ))}
        </div>
        <div className="secret-add-row">
          <input value={newSecretKey} onChange={(event) => setNewSecretKey(event.target.value.toUpperCase())} placeholder="NEW_LLM_API_KEY" />
          <input value={newSecretValue} onChange={(event) => setNewSecretValue(event.target.value)} placeholder="API key" type="password" />
          <button onClick={() => void addSecret()}>新增 LLM API Key</button>
        </div>
        <div className="action-row">
          <button onClick={() => void saveSecrets()}>保存 Secrets</button>
        </div>
      </Panel>
      <Panel title="QQ 音乐凭证">
        <div className="qq-credential-row">
          <button disabled={qqCredentialRunning} onClick={() => void refreshQQMusicCredential()}>刷新 QQ 音乐凭证</button>
          <textarea readOnly value={formatQQCredentialStatus(effectiveQQCredentialStatus)} />
        </div>
        {qqQrUrl && (
          <div className="qq-credential-qr-wrap">
            <img className="qq-credential-qr" src={qqQrUrl} alt="QQ 音乐登录二维码" />
          </div>
        )}
      </Panel>
      <Panel title="LLM Interfaces">
        <LlmInterfacesDraftEditor draft={llmDraft} onChange={setLlmDraft} />
      </Panel>
      <Panel title="LLMModule / VLMModule 绑定">
        <LlmModuleBindingDraftEditor
          draft={llmDraft}
          onChange={setLlmDraft}
          onApply={() => void applyLlmConfig()}
          onReload={() => void loadLlmConfig()}
          applyStatus={llmApplyStatus}
          applying={llmApplying}
        />
      </Panel>
      <Panel title="配置检查">
        <ValidationTable rows={validationItems} />
      </Panel>
    </>
  );
}

function LlmInterfacesDraftEditor({
  draft,
  onChange,
}: {
  draft: LlmConfigInfo | null;
  onChange: (draft: LlmConfigInfo) => void;
}) {
  if (!draft) {
    return <div className="empty-state">暂无 LLM 配置</div>;
  }
  const currentDraft = draft;

  function updateInterfaces(kind: 'available_llms' | 'available_vlms', next: Record<string, LlmInterfaceConfig>) {
    onChange({ ...currentDraft, [kind]: next });
  }

  return (
    <div className="llm-config-editor">
      <InterfaceEditor title="LLM Interfaces" kind="available_llms" rows={currentDraft.available_llms} onChange={updateInterfaces} />
      <InterfaceEditor title="VLM Interfaces" kind="available_vlms" rows={currentDraft.available_vlms} onChange={updateInterfaces} />
    </div>
  );
}

function LlmModuleBindingDraftEditor({
  draft,
  onChange,
  onApply,
  onReload,
  applyStatus,
  applying,
}: {
  draft: LlmConfigInfo | null;
  onChange: (draft: LlmConfigInfo) => void;
  onApply: () => void;
  onReload: () => void;
  applyStatus: LocalActionStatus | null;
  applying: boolean;
}) {
  if (!draft) {
    return <div className="empty-state">暂无模块绑定</div>;
  }
  const currentDraft = draft;
  const llmNames = Object.keys(currentDraft.available_llms);
  const vlmNames = Object.keys(currentDraft.available_vlms);

  function updateBindings(next: ModuleBinding[]) {
    onChange({ ...currentDraft, module_bindings: next });
  }

  return (
    <div className="llm-config-editor">
      <ModuleBindingEditor bindings={currentDraft.module_bindings} llmNames={llmNames} vlmNames={vlmNames} onChange={updateBindings} />
      <div className="action-row">
        <button disabled={applying} onClick={onApply}>{applying ? '修改中...' : '修改'}</button>
        <button className="secondary-button" disabled={applying} onClick={onReload}>放弃草稿</button>
      </div>
      {applyStatus && <div className={`inline-status ${applyStatus.tone}`}>{applyStatus.message}</div>}
    </div>
  );
}

function InterfaceEditor({
  title,
  kind,
  rows,
  onChange,
}: {
  title: string;
  kind: 'available_llms' | 'available_vlms';
  rows: Record<string, LlmInterfaceConfig>;
  onChange: (kind: 'available_llms' | 'available_vlms', next: Record<string, LlmInterfaceConfig>) => void;
}) {
  function updateName(oldName: string, newName: string) {
    const trimmed = newName.trim();
    if (!trimmed || trimmed === oldName) {
      return;
    }
    const next = { ...rows };
    next[trimmed] = next[oldName];
    delete next[oldName];
    onChange(kind, next);
  }

  function updateField(name: string, field: string, value: unknown) {
    onChange(kind, { ...rows, [name]: { ...rows[name], [field]: value } });
  }

  function updateDefaultParams(name: string, value: string) {
    try {
      updateField(name, 'default_params', value.trim() ? JSON.parse(value) : {});
    } catch {
      updateField(name, 'default_params_text', value);
    }
  }

  function addInterface() {
    let index = Object.keys(rows).length + 1;
    let name = `${kind === 'available_llms' ? 'llm' : 'vlm'}_${index}`;
    while (rows[name]) {
      index += 1;
      name = `${kind === 'available_llms' ? 'llm' : 'vlm'}_${index}`;
    }
    onChange(kind, {
      ...rows,
      [name]: {
        api_type: 'openai',
        model: '',
        api_key: '',
        base_url: '',
        can_enable_thinking: false,
        can_use_json: false,
        default_params: {},
      },
    });
  }

  function removeInterface(name: string) {
    const next = { ...rows };
    delete next[name];
    onChange(kind, next);
  }

  return (
    <div className="interface-editor">
      <div className="editor-head">
        <h3>{title}</h3>
        <button onClick={addInterface}>新增</button>
      </div>
      {Object.entries(rows).map(([name, item]) => (
        <div className="interface-card" key={name}>
          <input className="interface-name-input" defaultValue={name} onBlur={(event) => updateName(name, event.target.value)} />
          <input className="interface-type-input" value={String(item.api_type || '')} onChange={(event) => updateField(name, 'api_type', event.target.value)} placeholder="api_type" />
          <input className="interface-model-input" value={String(item.model || '')} onChange={(event) => updateField(name, 'model', event.target.value)} placeholder="model" />
          <input className="interface-key-input" value={String(item.api_key || '')} onChange={(event) => updateField(name, 'api_key', event.target.value)} placeholder="$API_KEY" />
          <input className="interface-url-input" value={String(item.base_url || '')} onChange={(event) => updateField(name, 'base_url', event.target.value)} placeholder="base_url" />
          <div className="interface-flags">
            <label><input type="checkbox" checked={Boolean(item.can_enable_thinking)} onChange={(event) => updateField(name, 'can_enable_thinking', event.target.checked)} /> thinking</label>
            <label><input type="checkbox" checked={Boolean(item.can_use_json)} onChange={(event) => updateField(name, 'can_use_json', event.target.checked)} /> json</label>
          </div>
          <textarea
            value={String(item.default_params_text || JSON.stringify(item.default_params || {}, null, 2))}
            onChange={(event) => updateDefaultParams(name, event.target.value)}
            placeholder="default_params JSON"
          />
          <button className="danger-button" onClick={() => removeInterface(name)}>删除</button>
        </div>
      ))}
      {Object.keys(rows).length === 0 && <div className="empty-state">暂无配置</div>}
    </div>
  );
}

function ModuleBindingEditor({
  bindings,
  llmNames,
  vlmNames,
  onChange,
}: {
  bindings: ModuleBinding[];
  llmNames: string[];
  vlmNames: string[];
  onChange: (bindings: ModuleBinding[]) => void;
}) {
  function updateBinding(index: number, patch: Partial<ModuleBinding>) {
    onChange(bindings.map((binding, current) => current === index ? { ...binding, ...patch } : binding));
  }

  function updateParams(index: number, value: string) {
    try {
      updateBinding(index, { params: value.trim() ? JSON.parse(value) : {}, params_text: undefined });
    } catch {
      updateBinding(index, { params_text: value });
    }
  }

  return (
    <div className="module-binding-editor">
      <h3>LLMModule / VLMModule 绑定</h3>
      <div className="module-binding-table">
      <table>
        <thead>
          <tr>
            <th>Kind</th>
            <th>Module Path</th>
            <th>Prompt</th>
            <th>Interface</th>
            <th>Thinking</th>
            <th>JSON</th>
            <th>Params</th>
          </tr>
        </thead>
        <tbody>
          {bindings.map((binding, index) => {
            const names = binding.kind === 'llm' ? llmNames : vlmNames;
            const options = names.includes(binding.interface_name) ? names : [binding.interface_name, ...names].filter(Boolean);
            return (
              <tr key={`${binding.kind}-${binding.path}`}>
                <td className="module-kind-cell">{binding.kind.toUpperCase()}</td>
                <td className="mono module-path-cell">{binding.path}</td>
                <td className="module-prompt-cell">{binding.prompt_name || '-'}</td>
                <td>
                  <select value={binding.interface_name} onChange={(event) => updateBinding(index, { interface_name: event.target.value })}>
                    {options.map((name) => <option key={name} value={name}>{name}</option>)}
                  </select>
                </td>
                <td className="module-check-cell">
                  <input
                    type="checkbox"
                    checked={Boolean(binding.enable_thinking)}
                    onChange={(event) => updateBinding(index, { enable_thinking: event.target.checked })}
                  />
                </td>
                <td className="module-check-cell">
                  <input
                    type="checkbox"
                    checked={Boolean(binding.use_json)}
                    onChange={(event) => updateBinding(index, { use_json: event.target.checked })}
                  />
                </td>
                <td className="module-params-cell">
                  <textarea
                    className={binding.params_text !== undefined ? 'json-invalid' : undefined}
                    value={binding.params_text ?? JSON.stringify(binding.params || {}, null, 2)}
                    onChange={(event) => updateParams(index, event.target.value)}
                    placeholder='{"temperature": 0.7}'
                  />
                </td>
              </tr>
            );
          })}
          {bindings.length === 0 && (
            <tr>
              <td colSpan={7} className="empty-state">暂无模块绑定</td>
            </tr>
          )}
        </tbody>
      </table>
      </div>
    </div>
  );
}

function ValidationTable({ rows }: { rows: ValidationItem[] }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Scope</th>
          <th>Name</th>
          <th>Status</th>
          <th>Message</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={`${row.name}-${index}`}>
            <td>{row.scope}</td>
            <td>{row.name}</td>
            <td><span className={`pill ${row.status === 'ok' ? 'success' : row.status === 'disabled' ? 'warning' : 'error'}`}>{row.status}</span></td>
            <td>{row.message}</td>
          </tr>
        ))}
        {rows.length === 0 && (
          <tr>
            <td colSpan={4} className="empty-state">暂无检查结果</td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

function LogsPage() {
  const { data, error, loading } = usePolling<LogEvent[]>('/admin/api/logs?limit=200&min_level=WARNING');
  return (
    <>
      <PageHeader title="异常日志" subtitle="Warning/Error/Critical 事件集中查看" />
      <StatusBar loading={loading} error={error} />
      <Panel title="日志列表">
        <LogTable rows={data || []} />
      </Panel>
    </>
  );
}

function StatusBar({ loading, error }: { loading: boolean; error: string | null }) {
  if (loading) {
    return <div className="status">加载中...</div>;
  }
  if (error) {
    return <div className="status error">请求失败：{error}</div>;
  }
  return null;
}

function MetricCard({ title, value, detail, tone }: { title: string; value: string; detail: string; tone?: 'warning' | 'danger' }) {
  return (
    <div className={`metric-card ${tone || ''}`}>
      <div className="metric-title">{title}</div>
      <div className="metric-value">{value}</div>
      <div className="metric-detail">{detail}</div>
    </div>
  );
}

function Panel({ title, children, className }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={`panel ${className || ''}`}>
      <h2>{title}</h2>
      <div className="panel-content">{children}</div>
    </section>
  );
}

function SpanTable({ rows, compact = false }: { rows: PipelineSpan[]; compact?: boolean }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Span</th>
          <th>Duration</th>
          {!compact && <th>Trace</th>}
          <th>Status</th>
          {!compact && <th>Time</th>}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.id}>
            <td>{row.span_name}</td>
            <td>{formatMs(row.duration_ms)}</td>
            {!compact && <td className="mono">{row.trace_id}</td>}
            <td><span className={`pill ${row.status}`}>{row.status}</span></td>
            {!compact && <td>{formatShanghaiTime(row.start_ts)}</td>}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function LlmCallTable({ rows }: { rows: LlmCall[] }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Module</th>
          <th>Model</th>
          <th>Latency</th>
          <th>Total</th>
          <th>Prompt</th>
          <th>Completion</th>
          <th>Status</th>
          <th>Time</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.id}>
            <td>{row.module_name}</td>
            <td>{row.model_name || '-'}</td>
            <td>{formatMs(row.latency_ms)}</td>
            <td>{formatNumber(row.total_tokens)}</td>
            <td>{formatNumber(row.prompt_tokens)}</td>
            <td>{formatNumber(row.completion_tokens)}</td>
            <td><span className={`pill ${row.success ? 'success' : 'error'}`}>{row.success ? 'success' : 'error'}</span></td>
            <td>{formatShanghaiTime(row.ts)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function MemoryEventCard({
  event,
  tab,
  onAnnotate,
}: {
  event: MemoryTraceEvent;
  tab: MemoryTraceTab;
  onAnnotate: (eventId: number, label: string, notes?: string) => Promise<void>;
}) {
  const [notes, setNotes] = useState(event.annotation_notes || '');
  const [saving, setSaving] = useState(false);
  const resultText = event.result ? JSON.stringify(event.result, null, 2) : '';

  async function submit(label: string) {
    setSaving(true);
    try {
      await onAnnotate(event.id, label, notes);
    } finally {
      setSaving(false);
    }
  }

  return (
    <article className="memory-event-card">
      <div className="memory-event-head">
        <div>
          <span className="mono">#{event.id}</span>
          <span className="pill">{event.event_type}</span>
          <span className="pill">{event.item_type}</span>
          {event.annotation_required && !event.annotation_label && <span className="pill warning">pending</span>}
          {event.annotation_label && <span className="pill success">{event.annotation_label}</span>}
        </div>
        <div className="mono">{event.trace_id || '-'}</div>
      </div>
      <div className="memory-event-grid">
        <ReadBlock title={tab.contextLabel} value={event.source_context} />
        <ReadBlock title={tab.commandLabel} value={event.command_text} />
        <ReadBlock title={tab.contentLabel} value={event.content_text} />
        <ReadBlock title={tab.resultLabel} value={resultText} />
      </div>
      {event.annotation_required ? (
        <div className="annotation-row">
          <input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="标注意见" />
          {tab.labels.map((label) => (
            <button key={label.label} disabled={saving} onClick={() => submit(label.label)}>{label.text}</button>
          ))}
        </div>
      ) : (
        <div className="memory-event-meta">该事件是确定性结果，仅记录，不要求标注。</div>
      )}
      <div className="memory-event-meta">
        {formatShanghaiTime(event.ts)} · {formatMs(event.duration_ms)} · topic {event.topic_id || '-'}
      </div>
    </article>
  );
}

function ReadBlock({ title, value }: { title: string; value?: string }) {
  return (
    <div className="read-block">
      <div className="read-block-title">{title}</div>
      <pre>{value || '-'}</pre>
    </div>
  );
}

function LogTable({ rows, compact = false }: { rows: LogEvent[]; compact?: boolean }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Level</th>
          <th>Logger</th>
          <th>Message</th>
          {!compact && <th>Time</th>}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.id}>
            <td><span className={`pill ${row.level.toLowerCase()}`}>{row.level}</span></td>
            <td>{row.logger_name}</td>
            <td>{row.message}</td>
            {!compact && <td>{formatShanghaiTime(row.ts)}</td>}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

createRoot(document.getElementById('root')!).render(<AdminGate />);
