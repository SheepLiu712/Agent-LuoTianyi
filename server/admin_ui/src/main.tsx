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

type Page = 'dashboard' | 'llm' | 'pipeline' | 'traces' | 'logs';

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
          <button className={page === 'traces' ? 'active' : ''} onClick={() => setPage('traces')}>链路追踪</button>
          <button className={page === 'logs' ? 'active' : ''} onClick={() => setPage('logs')}>异常日志</button>
        </nav>
      </aside>
      <main className="content">
        {page === 'dashboard' && <DashboardPage />}
        {page === 'llm' && <LlmPage />}
        {page === 'pipeline' && <PipelinePage />}
        {page === 'traces' && <TracePage />}
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
        <MetricCard title="平均 Token" value={formatNumber(data?.totals?.avg_total_tokens)} detail={`${formatNumber(data?.totals?.avg_prompt_tokens)} prompt / ${formatNumber(data?.totals?.avg_completion_tokens)} completion`} />
        <MetricCard title="Prompt Tokens" value={formatNumber(data?.totals?.prompt_tokens)} detail="7 日累计" />
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
              <th>Avg Tokens</th>
              <th>Avg Prompt</th>
              <th>Avg Completion</th>
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
                <td>{formatNumber(Number(row.avg_total_tokens || 0))}</td>
                <td>{formatNumber(Number(row.avg_prompt_tokens || 0))}</td>
                <td>{formatNumber(Number(row.avg_completion_tokens || 0))}</td>
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
                  <td>{trace.end_ts || trace.start_ts || '-'}</td>
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
            {!compact && <td>{row.start_ts}</td>}
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
            <td>{row.ts}</td>
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
