import { server_config } from '../config';
import { addDebugTrace } from './debug_trace';

export interface DynamicPost {
  id: string;
  author_type: 'user' | 'agent' | 'system' | string;
  author_id: string;
  author_name: string;
  owner_user_id: string | null;
  visibility: 'private' | 'global' | string;
  content: string;
  image_refs: unknown[];
  source_type: string;
  source_id: string | null;
  allow_comment: boolean;
  memory_policy: string | null;
  memory_status: string | null;
  memory_error: string | null;
  reply_status: string | null;
  reply_error: string | null;
  status: string;
  created_at: string | null;
  updated_at: string | null;
  comment_count: number;
  cursor: string;
}

export interface DynamicComment {
  id: string;
  dynamic_id: string;
  author_type: 'user' | 'agent' | 'system' | string;
  author_id: string;
  author_name: string;
  owner_user_id: string | null;
  parent_comment_id: string | null;
  content: string;
  memory_policy: string | null;
  memory_status: string | null;
  memory_error: string | null;
  reply_status: string | null;
  reply_error: string | null;
  status: string;
  created_at: string | null;
  updated_at: string | null;
  cursor: string;
}

export interface DynamicListResponse {
  items: DynamicPost[];
  has_more: boolean;
  next_cursor: string | null;
}

export interface DynamicCommentListResponse {
  items: DynamicComment[];
  has_more: boolean;
  next_cursor: string | null;
}

export interface DynamicUnreadStatus {
  has_unread: boolean;
  unread_count: number;
  unread_dynamic_count: number;
  unread_comment_count: number;
  last_read_dynamic_at: string | null;
  last_read_comment_at: string | null;
}

function buildQuery(params: Record<string, string | number | undefined | null>) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') {
      continue;
    }
    query.append(key, String(value));
  }
  return query.toString();
}

async function parseJsonOrThrow(response: Response) {
  if (response.ok) {
    return response.json();
  }

  let detail = response.statusText || '请求失败';
  try {
    const data = await response.json();
    if (typeof data?.detail === 'string' && data.detail) {
      detail = data.detail;
    }
  } catch {
    // ignore JSON parse errors and keep status text
  }
  throw new Error(detail);
}

export async function getDynamics(
  username: string,
  token: string,
  limit = 20,
  cursor?: string | null,
): Promise<DynamicListResponse> {
  const query = buildQuery({ username, token, limit, cursor: cursor || undefined });
  const url = `${server_config.BASE_URL}/dynamics?${query}`;
  addDebugTrace('dynamics', 'fetch list', { limit, hasCursor: Boolean(cursor) });
  const response = await fetch(url, {
    method: 'GET',
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
  return parseJsonOrThrow(response) as Promise<DynamicListResponse>;
}

export async function createDynamic(
  username: string,
  token: string,
  content: string,
): Promise<DynamicPost> {
  addDebugTrace('dynamics', 'create post', { textLength: content.length });
  const response = await fetch(`${server_config.BASE_URL}/dynamics`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, token, content }),
  });
  const data = await parseJsonOrThrow(response);
  return data.item as DynamicPost;
}

export async function getDynamicComments(
  username: string,
  token: string,
  dynamicId: string,
  limit = 50,
  cursor?: string | null,
): Promise<DynamicCommentListResponse> {
  const query = buildQuery({ username, token, limit, cursor: cursor || undefined });
  addDebugTrace('dynamics', 'fetch comments', { dynamicId, hasCursor: Boolean(cursor) });
  const response = await fetch(`${server_config.BASE_URL}/dynamics/${encodeURIComponent(dynamicId)}/comments?${query}`, {
    method: 'GET',
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
  return parseJsonOrThrow(response) as Promise<DynamicCommentListResponse>;
}

export async function createDynamicComment(
  username: string,
  token: string,
  dynamicId: string,
  content: string,
  parentCommentId?: string | null,
): Promise<DynamicComment> {
  addDebugTrace('dynamics', 'create comment', { dynamicId, textLength: content.length });
  const response = await fetch(`${server_config.BASE_URL}/dynamics/${encodeURIComponent(dynamicId)}/comments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      username,
      token,
      content,
      parent_comment_id: parentCommentId || null,
    }),
  });
  const data = await parseJsonOrThrow(response);
  return data.item as DynamicComment;
}

export async function getDynamicUnreadStatus(
  username: string,
  token: string,
): Promise<DynamicUnreadStatus> {
  const query = buildQuery({ username, token });
  const response = await fetch(`${server_config.BASE_URL}/dynamics/unread?${query}`, {
    method: 'GET',
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
  return parseJsonOrThrow(response) as Promise<DynamicUnreadStatus>;
}

export async function markDynamicsRead(
  username: string,
  token: string,
): Promise<{ ok: boolean; last_read_dynamic_at: string | null; last_read_comment_at: string | null }> {
  addDebugTrace('dynamics', 'mark read');
  const response = await fetch(`${server_config.BASE_URL}/dynamics/read`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, token }),
  });
  return parseJsonOrThrow(response) as Promise<{ ok: boolean; last_read_dynamic_at: string | null; last_read_comment_at: string | null }>;
}
