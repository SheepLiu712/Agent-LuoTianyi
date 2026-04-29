export interface DebugTraceEntry {
  id: number;
  ts: number;
  scope: string;
  message: string;
  detail?: string;
}

type Listener = (entries: DebugTraceEntry[]) => void;

const MAX_ENTRIES = 200;
const entries: DebugTraceEntry[] = [];
const listeners = new Set<Listener>();
let nextId = 1;

function toDetailText(detail: unknown) {
  if (detail === undefined) {
    return undefined;
  }
  if (typeof detail === 'string') {
    return detail;
  }
  try {
    return JSON.stringify(detail);
  } catch {
    return String(detail);
  }
}

function emitUpdate() {
  const snapshot = [...entries];
  for (const listener of listeners) {
    listener(snapshot);
  }
}

export function addDebugTrace(scope: string, message: string, detail?: unknown) {
  const entry: DebugTraceEntry = {
    id: nextId,
    ts: Date.now(),
    scope,
    message,
    detail: toDetailText(detail),
  };
  nextId += 1;

  entries.push(entry);
  if (entries.length > MAX_ENTRIES) {
    entries.splice(0, entries.length - MAX_ENTRIES);
  }

  if (__DEV__) {
    const line = `[trace][${scope}] ${message}`;
    if (entry.detail) {
      console.log(line, entry.detail);
    } else {
      console.log(line);
    }
  }

  emitUpdate();
}

export function subscribeDebugTrace(listener: Listener) {
  listeners.add(listener);
  listener([...entries]);
  return () => {
    listeners.delete(listener);
  };
}

export function getDebugTraceSnapshot() {
  return [...entries];
}

export function clearDebugTrace() {
  entries.length = 0;
  emitUpdate();
}