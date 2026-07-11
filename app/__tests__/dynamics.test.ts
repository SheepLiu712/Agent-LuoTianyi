import {
  createDynamic,
  createDynamicComment,
  getDynamicComments,
  getDynamics,
  getDynamicUnreadStatus,
  markDynamicsRead,
} from '../utils/dynamics';

jest.mock('../config', () => ({
  server_config: {
    BASE_URL: 'http://example.test',
  },
}));

jest.mock('../utils/debug_trace', () => ({
  addDebugTrace: jest.fn(),
}));

describe('dynamics api helpers', () => {
  const mockFetch = jest.fn();

  beforeEach(() => {
    mockFetch.mockReset();
    global.fetch = mockFetch as unknown as typeof fetch;
  });

  it('getDynamics should send auth header and paging query', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        items: [{ id: 'post-1' }],
        has_more: true,
        next_cursor: 'cursor-1',
      }),
    });

    const result = await getDynamics('alice', 'token-123', 20, 'cursor-1');

    expect(mockFetch).toHaveBeenCalledWith(
      'http://example.test/dynamics?username=alice&token=token-123&limit=20&cursor=cursor-1',
      {
        method: 'GET',
        headers: {
          Authorization: 'Bearer token-123',
        },
      },
    );
    expect(result.items[0].id).toBe('post-1');
    expect(result.has_more).toBe(true);
    expect(result.next_cursor).toBe('cursor-1');
  });

  it('createDynamic should post json payload and return created item', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        item: {
          id: 'post-2',
          content: 'hello dynamic',
        },
      }),
    });

    const result = await createDynamic('alice', 'token-123', 'hello dynamic');

    expect(mockFetch).toHaveBeenCalledWith('http://example.test/dynamics', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: 'alice',
        token: 'token-123',
        content: 'hello dynamic',
      }),
    });
    expect(result.id).toBe('post-2');
  });

  it('getDynamicComments should include auth header and encoded dynamic id', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        items: [{ id: 'comment-1' }],
        has_more: false,
        next_cursor: null,
      }),
    });

    const result = await getDynamicComments('alice', 'token-123', 'dynamic/1', 50, null);

    expect(mockFetch).toHaveBeenCalledWith(
      'http://example.test/dynamics/dynamic%2F1/comments?username=alice&token=token-123&limit=50',
      {
        method: 'GET',
        headers: {
          Authorization: 'Bearer token-123',
        },
      },
    );
    expect(result.items[0].id).toBe('comment-1');
  });

  it('createDynamicComment should surface detail message on failure', async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      statusText: 'Bad Request',
      json: async () => ({
        detail: '评论创建失败',
      }),
    });

    await expect(
      createDynamicComment('alice', 'token-123', 'post-3', 'bad comment'),
    ).rejects.toThrow('评论创建失败');
  });

  it('getDynamicUnreadStatus should request unread endpoint', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        has_unread: true,
        unread_count: 2,
        unread_dynamic_count: 1,
        unread_comment_count: 1,
        last_read_dynamic_at: null,
        last_read_comment_at: null,
      }),
    });

    const result = await getDynamicUnreadStatus('alice', 'token-123');

    expect(mockFetch).toHaveBeenCalledWith(
      'http://example.test/dynamics/unread?username=alice&token=token-123',
      {
        method: 'GET',
        headers: {
          Authorization: 'Bearer token-123',
        },
      },
    );
    expect(result.unread_count).toBe(2);
  });

  it('markDynamicsRead should post read marker payload', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        last_read_dynamic_at: '2026-07-05 11:00:00',
        last_read_comment_at: '2026-07-05 11:00:00',
      }),
    });

    const result = await markDynamicsRead('alice', 'token-123');

    expect(mockFetch).toHaveBeenCalledWith('http://example.test/dynamics/read', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: 'alice',
        token: 'token-123',
      }),
    });
    expect(result.ok).toBe(true);
  });
});
