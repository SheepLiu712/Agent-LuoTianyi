import { AvatarSync, emptyAvatars, normalizeAvatarServer, type AvatarSnapshot } from '../features/avatars/avatar_sync';

const alice = { username: 'alice', token: 'message-a', serverUrl: 'https://a.test' };
const image = 'data:image/png;base64,bG9jYWw=';
const normalized = 'data:image/png;base64,bm9ybWFsaXplZA==';
const response = (snapshot: AvatarSnapshot) => ({ ok: true, status: 200, json: async () => snapshot }) as Response;
const unchanged = (token?: string) => ({ ok: false, status: 304, headers: new Headers(token ? { 'X-Avatar-Token': token } : {}) }) as Response;
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; };
function storage() {
  const values = new Map<string, string>();
  return { values, getItem: async (key: string) => values.get(key) ?? null,
    setItem: async (key: string, value: string) => { values.set(key, value); } };
}
function observe(sync: AvatarSync) {
  let value = emptyAvatars;
  sync.subscribe(next => { value = next; });
  return () => value;
}

it('离线保存与恢复默认会持久保留，恢复网络只推送双方 pending（PUT快照即完成检查）', async () => {
  const disk = storage();
  let online = false;
  let remote: AvatarSnapshot = { revision: '1', user: null, agent: image, sync_token: 'avatar-a' };
  const network = jest.fn(async (_url: string | URL | Request, options?: RequestInit) => {
    if (!online) throw new Error('offline');
    if (options?.method === 'PUT') {
      const side = String(_url).includes('/user?') ? 'user' : 'agent';
      remote = { ...remote, revision: String(Number(remote.revision) + 1), [side]: JSON.parse(String(options.body)).image === null ? null : normalized };
      return response(remote);
    }
    return (options?.headers as Record<string, string>)['If-None-Match'] === remote.revision ? unchanged() : response(remote);
  });
  const first = new AvatarSync(alice, disk, network);
  await first.start();
  await first.save('user', image);
  await first.save('agent', null);
  first.dispose();
  const restored = new AvatarSync(alice, disk, network);
  const state = observe(restored);
  await restored.start();
  expect(state()).toMatchObject({ user: image, agent: null, pending: true });
  expect(state().error).toContain('同步失败');
  online = true;
  network.mockClear();
  await restored.retry();
  expect(network.mock.calls.map(([, options]) => options?.method)).toEqual(['PUT', 'PUT']);
  expect(JSON.parse(String(network.mock.calls[1][1]?.body))).toEqual({ image: null });
  expect(state()).toMatchObject({ user: normalized, agent: null, pending: false, error: null });
  await restored.sync();
  expect(state().user).toBe(normalized);
  restored.dispose();
});

it('换服首次上传已知双方（含默认null），规范化同一地址后重进只读取服务端', async () => {
  const disk = storage();
  const atA = new AvatarSync(alice, disk, jest.fn(async () => response({ revision: 'a', user: null, agent: image })));
  await atA.start(); atA.dispose();
  const requests: { url: string; options?: RequestInit }[] = [];
  let remote: AvatarSnapshot = { revision: 'b', user: null, agent: image };
  const network = jest.fn(async (url: string | URL | Request, options?: RequestInit) => {
    requests.push({ url: String(url), options });
    if (options?.method === 'PUT') remote = { ...remote,
      [String(url).includes('/user?') ? 'user' : 'agent']: JSON.parse(String(options.body)).image };
    return response(remote);
  });
  const atB = new AvatarSync({ ...alice, serverUrl: 'https://B.test:443/base/' }, disk, network);
  await atB.start(); atB.dispose();
  expect(requests.map(request => request.options?.method)).toEqual(['PUT', 'PUT']);
  expect(JSON.parse(String(requests[0].options?.body))).toEqual({ image: null });
  expect(requests[0].url).toBe('https://b.test/base/avatars/user?username=alice');
  requests.length = 0;
  const again = new AvatarSync({ ...alice, serverUrl: 'https://b.test/base' }, disk, network);
  await again.start();
  expect(requests.map(request => request.options?.method)).toEqual(['GET']);
  expect((requests[0].options?.headers as Record<string, string>)['If-None-Match']).toBeUndefined();
  await again.save('agent', normalized);
  again.dispose();
  expect(normalizeAvatarServer('https://B.test:443/base///')).toBe('https://b.test/base');
  requests.length = 0;
  const backToA = new AvatarSync(alice, disk, network);
  await backToA.start(); backToA.dispose();
  expect(requests.map(request => request.options?.method)).toEqual(['PUT', 'PUT']);
  expect(JSON.parse(String(requests[1].options?.body))).toEqual({ image: normalized });
});

it('查询和上传途中新修改立即生效，旧snapshot不会盖掉任一边待上传修改', async () => {
  const disk = storage();
  let remote: AvatarSnapshot = { revision: '1', user: null, agent: null };
  const network = jest.fn(async (url: string | URL | Request, options?: RequestInit) => {
    if (options?.method === 'PUT') {
      const side = String(url).includes('/user?') ? 'user' : 'agent';
      remote = { ...remote, revision: String(Number(remote.revision) + 1), [side]: JSON.parse(String(options.body)).image };
    }
    return response(remote);
  });
  const sync = new AvatarSync(alice, disk, network);
  const state = observe(sync);
  await sync.start();
  const oldGet = deferred<Response>();
  network.mockImplementationOnce(() => oldGet.promise);
  const polling = sync.sync();
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  const saveDuringGet = sync.save('user', image);
  oldGet.resolve(response({ revision: '2', user: normalized, agent: null }));
  await Promise.all([polling, saveDuringGet]);
  expect(state().user).toBe(image);
  const oldPut = deferred<Response>();
  network.mockImplementationOnce(() => oldPut.promise);
  const uploading = sync.sync();
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  const saveUser = sync.save('user', normalized);
  const saveAgent = sync.save('agent', image);
  oldPut.resolve(response({ revision: '3', user: 'old-result', agent: 'old-agent' }));
  network.mockImplementation(async (url, options) => response({ revision: '4', user: normalized,
    agent: String(url).includes('/agent?') || options?.method === 'GET' ? image : null }));
  await Promise.all([uploading, saveUser, saveAgent]);
  expect(state()).toMatchObject({ user: normalized, agent: image, pending: false });
  sync.dispose();
});

it('换账号后迟到响应不写入磁盘，也不影响新账号的本地头像', async () => {
  const disk = storage();
  const late = deferred<Response>();
  const firstNetwork = jest.fn(async () => response({ revision: '1', user: image, agent: null }));
  const old = new AvatarSync(alice, disk, firstNetwork);
  await old.start();
  const before = disk.values.get('avatars:alice');
  firstNetwork.mockImplementation(() => late.promise);
  const polling = old.sync();
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  old.dispose();
  const bobNetwork = jest.fn<Promise<Response>, [string | URL | Request, RequestInit?]>(async () => response({ revision: 'bob', user: null, agent: normalized }));
  const bob = new AvatarSync({ ...alice, username: 'bob', token: 'message-b' }, disk, bobNetwork);
  const state = observe(bob);
  await bob.start();
  late.resolve(response({ revision: 'late', user: 'alice-late', agent: image }));
  await polling;
  expect(disk.values.get('avatars:alice')).toBe(before);
  expect(state()).toMatchObject({ user: null, agent: normalized });
  expect(bobNetwork.mock.calls[0][1]?.method).toBe('GET');
  bob.dispose();
});

it('头像专用令牌按服务器保存并优先使用，401仅回退当前message_token一次', async () => {
  const disk = storage(); const tokens = storage();
  const network = jest.fn<Promise<Response>, [string | URL | Request, RequestInit?]>();
  network.mockResolvedValue(response({ revision: '1', user: null, agent: null, sync_token: 'avatar-only' }));
  const first = new AvatarSync(alice, disk, network, tokens);
  await first.start(); first.dispose();
  const next = new AvatarSync(alice, disk, network, tokens);
  await next.start();
  expect((network.mock.calls[1][1]?.headers as Record<string, string>).Authorization).toBe('Bearer avatar-only');
  network.mockClear();
  network.mockResolvedValueOnce({ ok: false, status: 401 } as Response).mockResolvedValueOnce(response({ revision: '2', user: image, agent: null, sync_token: 'new-avatar' }));
  await next.sync();
  expect(network.mock.calls.map(([, options]) => (options?.headers as Record<string, string>).Authorization)).toEqual(['Bearer avatar-only', 'Bearer message-a']);
  expect(tokens.values.get('avatars:alice:https://a.test')).toBe('new-avatar');
  expect(disk.values.get('avatars:alice')).not.toContain('new-avatar');
  next.dispose();
});


it('同步请求合并；前台只在距上次成功检查五分钟后主动拉取', async () => {
  jest.useFakeTimers();
  jest.setSystemTime(new Date('2026-01-01T00:00:00Z'));
  const disk = storage();
  const first = deferred<Response>();
  const network = jest.fn<Promise<Response>, [string | URL | Request, RequestInit?]>()
    .mockImplementationOnce(() => first.promise)
    .mockResolvedValue(unchanged());
  const sync = new AvatarSync(alice, disk, network);
  const starting = sync.start();
  for (let i = 0; i < 10; i++) await Promise.resolve();
  const editorCheck = sync.check();
  expect(network).toHaveBeenCalledTimes(1);
  first.resolve(response({ revision: '1', user: null, agent: null }));
  await Promise.all([starting, editorCheck]);
  await sync.setForeground(false);
  jest.advanceTimersByTime(4 * 60 * 1000);
  await sync.setForeground(true);
  expect(network).toHaveBeenCalledTimes(1);
  await sync.setForeground(false);
  jest.advanceTimersByTime(60 * 1000);
  await sync.setForeground(true);
  expect(network).toHaveBeenCalledTimes(2);
  expect(network.mock.calls[1][1]?.method).toBe('GET');
  sync.dispose();
  jest.useRealTimers();
});

it('pending上传失败仅前台退避10s/30s/120s三次，后台暂停且重新前台立即恢复', async () => {
  jest.useFakeTimers();
  const disk = storage();
  const network = jest.fn<Promise<Response>, [string | URL | Request, RequestInit?]>()
    .mockResolvedValueOnce(response({ revision: '1', user: null, agent: null }))
    .mockRejectedValue(new Error('offline'));
  const sync = new AvatarSync(alice, disk, network);
  await sync.start();
  await sync.save('user', image);
  expect(network).toHaveBeenCalledTimes(2);
  await jest.advanceTimersByTimeAsync(9_999);
  expect(network).toHaveBeenCalledTimes(2);
  await sync.setForeground(false);
  await jest.advanceTimersByTimeAsync(60_000);
  expect(network).toHaveBeenCalledTimes(2);
  await sync.setForeground(true);
  expect(network).toHaveBeenCalledTimes(3);
  await jest.advanceTimersByTimeAsync(10_000);
  expect(network).toHaveBeenCalledTimes(4);
  await jest.advanceTimersByTimeAsync(30_000);
  expect(network).toHaveBeenCalledTimes(5);
  await jest.advanceTimersByTimeAsync(120_000);
  expect(network).toHaveBeenCalledTimes(6);
  await jest.advanceTimersByTimeAsync(300_000);
  expect(network).toHaveBeenCalledTimes(6);
  sync.dispose();
  jest.useRealTimers();
});

it('无pending的GET失败不定时重试，手动检查可立即恢复', async () => {
  jest.useFakeTimers();
  const disk = storage();
  const network = jest.fn<Promise<Response>, [string | URL | Request, RequestInit?]>()
    .mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValue(response({ revision: '2', user: null, agent: null }));
  const sync = new AvatarSync(alice, disk, network);
  await sync.start();
  await jest.advanceTimersByTimeAsync(10 * 60_000);
  expect(network).toHaveBeenCalledTimes(1);
  await sync.check();
  expect(network).toHaveBeenCalledTimes(2);
  expect(network.mock.calls[1][1]?.method).toBe('GET');
  sync.dispose();
  jest.useRealTimers();
});


it('后台完成当前请求后不再续发pending写入，回前台后继续', async () => {
  jest.useFakeTimers();
  const disk = storage();
  let remote: AvatarSnapshot = { revision: '1', user: null, agent: null };
  const delayedPut = deferred<Response>();
  const network = jest.fn(async (url: string | URL | Request, options?: RequestInit) => {
    if (options?.method === 'PUT') {
      const side = String(url).includes('/user?') ? 'user' : 'agent';
      remote = { ...remote, revision: String(Number(remote.revision) + 1), [side]: JSON.parse(String(options.body)).image };
      return response(remote);
    }
    return response(remote);
  });
  const sync = new AvatarSync(alice, disk, network);
  const state = observe(sync);
  await sync.start();
  network.mockImplementationOnce(async (url, options) => {
    expect(options?.method).toBe('PUT');
    const side = String(url).includes('/user?') ? 'user' : 'agent';
    remote = { ...remote, revision: '2', [side]: JSON.parse(String(options?.body)).image };
    return delayedPut.promise;
  });
  const saveUser = sync.save('user', image);
  for (let i = 0; i < 10; i++) await Promise.resolve();
  const saveAgent = sync.save('agent', normalized);
  await sync.setForeground(false);
  delayedPut.resolve(response(remote));
  await Promise.all([saveUser, saveAgent]);
  expect(network.mock.calls.map(([, options]) => options?.method)).toEqual(['GET', 'PUT']);
  expect(state()).toMatchObject({ pending: true });
  await sync.setForeground(true);
  expect(network.mock.calls.map(([, options]) => options?.method)).toEqual(['GET', 'PUT', 'PUT']);
  expect(state()).toMatchObject({ pending: false, agent: normalized });
  sync.dispose();
  jest.useRealTimers();
});


it('后台启动或保存不发请求，回前台后立即上传pending', async () => {
  const disk = storage();
  const network = jest.fn<Promise<Response>, [string | URL | Request, RequestInit?]>(async () =>
    response({ revision: '1', user: image, agent: null }));
  const sync = new AvatarSync(alice, disk, network);
  await sync.setForeground(false);
  await sync.start();
  await sync.save('user', image);
  expect(network).not.toHaveBeenCalled();
  await sync.setForeground(true);
  expect(network.mock.calls.map(([, options]) => options?.method)).toEqual(['PUT']);
  sync.dispose();
});
