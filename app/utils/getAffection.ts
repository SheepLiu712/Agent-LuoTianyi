import { server_config } from '../config';
import { addDebugTrace } from './debug_trace';

export interface AffectionInfo {
  score: number;
  level_cn: string;
  level_en: string;
  today_net: number;
  next_level_cn?: string;
  next_level_en?: string;
  next_level_remaining?: number;
}

export async function getAffectionInfo(
  username: string,
  token: string,
): Promise<AffectionInfo | null> {
  try {
    const params = new URLSearchParams({
      username,
    });
    const url = `${server_config.BASE_URL}/affection/info?${params.toString()}`;
    const response = await fetch(url, {
      method: 'GET',
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });
    if (!response.ok) {
      addDebugTrace('affection', 'fetch failed', { status: response.statusText });
      return null;
    }
    const data = await response.json();
    return data as AffectionInfo;
  } catch (error) {
    addDebugTrace('affection', 'fetch error', { error: String(error) });
    return null;
  }
}
