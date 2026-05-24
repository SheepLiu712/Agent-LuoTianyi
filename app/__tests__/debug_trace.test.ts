/**
 * debug_trace 单元测试
 * 测试环形缓冲区、订阅/取消订阅、清空等功能。
 */
import { addDebugTrace, clearDebugTrace, getDebugTraceSnapshot, subscribeDebugTrace } from '../utils/debug_trace';

beforeEach(() => {
  clearDebugTrace();
});

describe('addDebugTrace', () => {
  it('should add an entry with correct fields', () => {
    addDebugTrace('test', 'hello', { key: 'value' });

    const snapshot = getDebugTraceSnapshot();
    expect(snapshot).toHaveLength(1);
    expect(snapshot[0].scope).toBe('test');
    expect(snapshot[0].message).toBe('hello');
    expect(snapshot[0].detail).toBe('{"key":"value"}');
    expect(typeof snapshot[0].ts).toBe('number');
    expect(snapshot[0].id).toBe(1);
  });

  it('should handle undefined detail', () => {
    addDebugTrace('scope', 'msg');
    const snapshot = getDebugTraceSnapshot();
    expect(snapshot[0].detail).toBeUndefined();
  });

  it('should handle string detail directly', () => {
    addDebugTrace('scope', 'msg', 'raw string');
    expect(getDebugTraceSnapshot()[0].detail).toBe('raw string');
  });

  it('should increment id sequentially', () => {
    addDebugTrace('a', '1');
    addDebugTrace('b', '2');
    addDebugTrace('c', '3');

    const snapshot = getDebugTraceSnapshot();
    expect(snapshot[2].id - snapshot[1].id).toBe(1);
    expect(snapshot[1].id - snapshot[0].id).toBe(1);
  });
});

describe('ring buffer', () => {
  it('should keep at most MAX_ENTRIES (200) entries', () => {
    for (let i = 0; i < 250; i++) {
      addDebugTrace('stress', `entry-${i}`);
    }

    const snapshot = getDebugTraceSnapshot();
    expect(snapshot).toHaveLength(200);
    // 最早的条目应被丢弃
    expect(snapshot[0].message).toBe('entry-50');
    expect(snapshot[199].message).toBe('entry-249');
  });
});

describe('subscribeDebugTrace', () => {
  it('should receive snapshot on subscribe', () => {
    addDebugTrace('pre', 'existing');

    const listener = jest.fn();
    const unsubscribe = subscribeDebugTrace(listener);

    expect(listener).toHaveBeenCalledTimes(1);
    const snapshot = listener.mock.calls[0][0];
    expect(snapshot).toHaveLength(1);
    expect(snapshot[0].message).toBe('existing');

    unsubscribe();
  });

  it('should notify listener on new entries', () => {
    const listener = jest.fn();
    subscribeDebugTrace(listener);
    listener.mockClear(); // 清除初始快照

    addDebugTrace('live', 'new msg');

    expect(listener).toHaveBeenCalledTimes(1);
    const entries = listener.mock.calls[0][0];
    expect(entries).toHaveLength(1);
    expect(entries[0].message).toBe('new msg');
  });

  it('should stop notifying after unsubscribe', () => {
    const listener = jest.fn();
    const unsubscribe = subscribeDebugTrace(listener);
    listener.mockClear();

    unsubscribe();
    addDebugTrace('after', 'unsubscribed');

    // 不应该再有新通知
    expect(listener).not.toHaveBeenCalled();
  });

  it('should support multiple listeners', () => {
    const l1 = jest.fn();
    const l2 = jest.fn();
    subscribeDebugTrace(l1);
    subscribeDebugTrace(l2);
    l1.mockClear();
    l2.mockClear();

    addDebugTrace('multi', 'broadcast');

    expect(l1).toHaveBeenCalled();
    expect(l2).toHaveBeenCalled();
  });
});

describe('clearDebugTrace', () => {
  it('should clear all entries and notify listeners', () => {
    addDebugTrace('a', '1');
    addDebugTrace('b', '2');

    const listener = jest.fn();
    subscribeDebugTrace(listener);
    listener.mockClear();

    clearDebugTrace();

    expect(getDebugTraceSnapshot()).toHaveLength(0);
    expect(listener).toHaveBeenCalledWith([]);
  });
});
