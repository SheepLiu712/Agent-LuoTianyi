import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import React from 'react';
import { useDynamicsUnread } from '../features/dynamics/useDynamicsUnread';
import { getDynamicUnreadStatus, markDynamicsRead, type DynamicUnreadStatus } from '../features/dynamics/dynamics';
import type { AccountSession } from '../features/account/credentials';

jest.mock('../features/dynamics/dynamics', () => ({ getDynamicUnreadStatus: jest.fn(), markDynamicsRead: jest.fn() }));

it('旧的查询不会在读完动态或换账号后点亮红点', async () => {
  const replies: ((result: DynamicUnreadStatus) => void)[] = [];
  jest.mocked(getDynamicUnreadStatus).mockImplementation(() => new Promise(resolve => replies.push(resolve)));
  jest.mocked(markDynamicsRead).mockResolvedValue({ ok: true, last_read_dynamic_at: null, last_read_comment_at: null });
  const unread = { has_unread: true, unread_count: 3, unread_dynamic_count: 2, unread_comment_count: 1, last_read_dynamic_at: null, last_read_comment_at: null };
  const alice = { username: 'alice', token: 'a', serverUrl: 'https://test' };
  const bob = { ...alice, username: 'bob', token: 'b' };
  let state!: ReturnType<typeof useDynamicsUnread>;
  let root!: ReactTestRenderer;
  function Probe({ session }: { session: AccountSession }) { state = useDynamicsUnread(session); return null; }
  act(() => { root = create(<Probe session={alice} />); });
  await act(async () => { replies.shift()!(unread); });
  expect(state.count).toBe(3);
  act(() => { void state.refresh(); });
  await act(async () => { await state.markRead(); });
  await act(async () => { replies.shift()!(unread); });
  expect(state.hasUnread).toBe(false);
  act(() => { void state.refresh(); });
  act(() => root.update(<Probe session={bob} />));
  await act(async () => { replies.shift()!(unread); });
  expect(state.hasUnread).toBe(false);
  await act(async () => { replies.shift()!({ ...unread, unread_count: 1 }); });
  expect(state.count).toBe(1);
  act(() => root.unmount());
});
