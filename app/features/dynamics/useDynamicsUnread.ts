import { useCallback, useEffect, useRef, useState } from 'react';
import type { AccountSession } from '../account/credentials';
import { getDynamicUnreadStatus, markDynamicsRead } from './dynamics';
import { addDebugTrace } from '../../utils/debug_trace';

const read = { hasUnread: false, count: 0 };

export function useDynamicsUnread(session: AccountSession) {
  const [status, setStatus] = useState(read);
  const version = useRef(0);
  const activeSession = useRef<AccountSession | null>(session);
  const refresh = useCallback(async () => {
    const request = ++version.current;
    try {
      const latest = await getDynamicUnreadStatus(session.username, session.token);
      if (request === version.current && activeSession.current === session) {
        setStatus({ hasUnread: latest.has_unread, count: latest.unread_count });
      }
    } catch (error) {
      addDebugTrace('dynamics', 'unread fetch failed', { error: String(error) });
    }
  }, [session]);
  const markRead = useCallback(async () => {
    try {
      const result = await markDynamicsRead(session.username, session.token);
      if (result.ok && activeSession.current === session) {
        version.current++;
        setStatus(read);
      }
    } catch (error) {
      addDebugTrace('dynamics', 'mark read failed', { error: String(error) });
    }
  }, [session]);
  useEffect(() => {
    activeSession.current = session;
    setStatus(read);
    void refresh();
    const timer = setInterval(refresh, 30_000);
    return () => { activeSession.current = null; clearInterval(timer); };
  }, [refresh, session]);
  return { ...status, refresh, markRead };
}
