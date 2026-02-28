import * as FileSystem from 'expo-file-system/legacy';
import { ChatMessage } from '../components/ChatBubbles';
import { server_config } from '../config';

export interface HistoryResponse {
    messages: ChatMessage[];
    startIndex: number;
}

export interface ImageResponse {
    success: boolean;
    error?: string;
    newClientPath?: string; // 确定的新的缓存路径，实际上是URI，包含了文件协议头
}

export async function getHistory(username: string, token: string, count: number, end_index: number): Promise<HistoryResponse> {
    try {
        const params = new URLSearchParams({
            username: username,
            token: token,
            count: count.toString(),
            end_index: end_index.toString()
        });
        const url = `${server_config.BASE_URL}/history?${params.toString()}`;
        const response = await fetch(url, {
            method: 'GET',
            headers: { 'Content-Type': 'application/json' },
        });
        const data = await response.json();
        if (!response.ok) {
            console.error('获取历史记录失败:', data.detail || '未知错误');
            return {
                messages: [], 
                startIndex: 0,
            };
        }

        // 尝试把history中的消息转换为ChatMessage格式
        
        const messages: ChatMessage[] = data.history.map((msg: any) => ({
            uuid: msg.uuid || "unknown_id",
            content: msg.content,
            isUser: msg.source === 'user',
            type: msg.type,
            timestamp: msg.timestamp,
        }));
        return {
            messages: messages,
            startIndex: data.start_index,
        };
        
    } catch (error) {
        console.error('获取历史记录失败:', error);
        return {
            messages: [],
            startIndex: 0,
        };
    }
}

export async function getImage(username: string, token: string, message_id: string): Promise<ImageResponse> {
    try {
        const response = await fetch(`${server_config.BASE_URL}/get_image`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                username: username,
                token,
                uuid: message_id,
            }),
        });

        if (!response.ok) {
            let errorMessage = '获取图片失败';
            try {
                const errorData = await response.json();
                errorMessage = errorData.detail || errorMessage;
            } catch {
                // ignore json parse error and fallback to status text
                errorMessage = response.statusText || errorMessage;
            }
            return {
                success: false,
                error: errorMessage,
            };
        }

        const blob = await response.blob();
        const contentType = (response.headers.get('content-type') || 'image/jpeg').split(';')[0].trim();

        const base64Data: string = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onloadend = () => {
                const result = reader.result;
                if (typeof result !== 'string') {
                    reject(new Error('图片转换失败'));
                    return;
                }
                const base64 = result.split(',')[1];
                if (!base64) {
                    reject(new Error('图片数据为空'));
                    return;
                }
                resolve(base64);
            };
            reader.onerror = () => reject(new Error('读取图片失败'));
            reader.readAsDataURL(blob);
        });

        const extensionMap: Record<string, string> = {
            'image/jpeg': 'jpg',
            'image/jpg': 'jpg',
            'image/png': 'png',
            'image/webp': 'webp',
            'image/gif': 'gif',
            'image/bmp': 'bmp',
            'image/heic': 'heic',
        };
        const ext = extensionMap[contentType] || 'jpg';

        const baseDir = `${FileSystem.documentDirectory}image_cache`;
        await FileSystem.makeDirectoryAsync(baseDir, { intermediates: true });

        const newClientPath = `${baseDir}/${message_id}.${ext}`; // 事实上，它是个URI，包含了文件协议头，但python客户端用的是path，我们就管他叫路径吧
        await FileSystem.writeAsStringAsync(newClientPath, base64Data, {
            encoding: FileSystem.EncodingType.Base64,
        });


        return {
            success: true,
            newClientPath,
        };
    } catch (error) {
        console.error('获取图片失败:', error);
        return {
            success: false,
            error: error instanceof Error ? error.message : '获取图片失败',
        };
    }
}
export async function updateImagePath(username: string, token: string, message_id: string, newClientPath: string): Promise<boolean> {
    try {
        const response = await fetch(`${server_config.BASE_URL}/update_image_client_path`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                username: username,
                token : token,
                uuid: message_id,
                image_client_path: newClientPath,
            }),
        });
        if (!response.ok) {
            console.error('更新图片路径失败:', response.statusText);
            return false;
        }
        return true;
    } catch(error) {
        console.error('更新图片路径失败:', error);
        return false;
    }
}