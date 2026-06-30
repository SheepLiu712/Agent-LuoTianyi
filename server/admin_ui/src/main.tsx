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
  window_days: number;
  totals: Record<string, number>;
  by_module: Array<Record<string, string | number | null>>;
  daily: Array<Record<string, string | number>>;
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

type Page = 'dashboard' | 'llm' | 'pipeline' | 'logs';

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
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

function App() {
  const [page, setPage] = useState<Page>('dashboard');

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
          <button className={page === 'logs' ? 'active' : ''} onClick={() => setPage('logs')}>异常日志</button>
        </nav>
      </aside>
      <main className="content">
        {page === 'dashboard' && <DashboardPage />}
        {page === 'llm' && <LlmPage />}
        {page === 'pipeline' && <PipelinePage />}
        {page === 'logs' && <LogsPage />}
      </main>
    </div>
  );
}

function usePolling<T>(url: string, intervalMs = 10000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
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
  const { data, error, loading } = usePolling<LlmSummary>('/admin/api/llm/summary?days=7');
  return (
    <>
      <PageHeader title="LLM 统计" subtitle="按模块、接口和天统计调用量、Token 与耗时" />
      <StatusBar loading={loading} error={error} />
      <section className="metric-grid">
        <MetricCard title="7 日调用" value={formatNumber(data?.totals?.call_count)} detail={`${formatNumber(data?.totals?.total_tokens)} tokens`} />
        <MetricCard title="Prompt Tokens" value={formatNumber(data?.totals?.prompt_tokens)} detail="7 日累计" />
        <MetricCard title="Completion Tokens" value={formatNumber(data?.totals?.completion_tokens)} detail="7 日累计" />
        <MetricCard title="平均耗时" value={formatMs(data?.totals?.avg_latency_ms)} detail={`${formatNumber(data?.totals?.failed_calls)} failed`} />
      </section>
      <Panel title="模块统计">
        <table>
          <thead>
            <tr>
              <th>Module</th>
              <th>Interface</th>
              <th>Model</th>
              <th>Calls</th>
              <th>Tokens</th>
              <th>Avg</th>
              <th>Failed</th>
            </tr>
          </thead>
          <tbody>
            {(data?.by_module || []).map((row, index) => (
              <tr key={index}>
                <td>{String(row.module_name || '-')}</td>
                <td>{String(row.interface_name || '-')}</td>
                <td>{String(row.model_name || '-')}</td>
                <td>{formatNumber(Number(row.call_count || 0))}</td>
                <td>{formatNumber(Number(row.total_tokens || 0))}</td>
                <td>{formatMs(Number(row.avg_latency_ms || 0))}</td>
                <td>{formatNumber(Number(row.failed_calls || 0))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </>
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
      <Panel title="慢 Span 明细">
        <SpanTable rows={spans || []} />
      </Panel>
    </>
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

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="panel">
      <h2>{title}</h2>
      {children}
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
            {!compact && <td>{row.start_ts}</td>}
          </tr>
        ))}
      </tbody>
    </table>
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
            {!compact && <td>{row.ts}</td>}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
