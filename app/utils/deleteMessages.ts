import { server_config } from '../config';
import { addDebugTrace } from './debug_trace';

export interface DeleteMessagesResponse {
    deleted: number;
    uuids: string[];
}

/**
 * 批量删除对话消息。
 */
export async function deleteMessages(
    username: string,
    token: string,
    uuids: string[]
): Promise<DeleteMessagesResponse> {
    try {
        const response = await fetch(`${server_config.BASE_URL}/delete_messages`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                username,
                token,
                uuids,
            }),
        });
        const data = await response.json();
        if (!response.ok) {
            addDebugTrace('history', 'deleteMessages failed', { detail: data.detail || '未知错误' });
            return { deleted: 0, uuids: [] };
        }
        return {
            deleted: Number(data.deleted || 0),
            uuids: Array.isArray(data.uuids) ? data.uuids : [],
        };
    } catch (error) {
        addDebugTrace('history', 'deleteMessages error', { error: String(error) });
        return { deleted: 0, uuids: [] };
    }
}
