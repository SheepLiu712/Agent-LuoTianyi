import { server_config } from '../config';

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
      token,
    });
    const url = `${server_config.BASE_URL}/affection/info?${params.toString()}`;
    const response = await fetch(url, { method: 'GET' });
    if (!response.ok) {
      console.error('获取好感度信息失败:', response.statusText);
      return null;
    }
    const data = await response.json();
    return data as AffectionInfo;
  } catch (error) {
    console.error('获取好感度信息失败:', error);
    return null;
  }
}
