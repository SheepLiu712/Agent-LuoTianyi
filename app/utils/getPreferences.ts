import { server_config } from '../config';
import { addDebugTrace } from './debug_trace';

export interface UserPreferences {
  relationship: string;
  speaking_style: string;
  '#sym:personality_text'?: string;
  personality_traits?: string[];
  custom_context: string;
}

/** 从服务端拉取用户的偏好设置。 */
export async function getPreferences(
  username: string,
  token: string,
): Promise<UserPreferences | null> {
  try {
    const response = await fetch(`${server_config.BASE_URL}/preference/get`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, token }),
    });
    if (!response.ok) {
      addDebugTrace('preferences', 'fetch failed', { status: response.statusText });
      return null;
    }
    const data = await response.json();
    return (data.preferences || data) as UserPreferences;
  } catch (error) {
    addDebugTrace('preferences', 'fetch error', { error: String(error) });
    return null;
  }
}

/** 将偏好设置覆盖保存到服务端。 */
export async function overwritePreferences(
  username: string,
  token: string,
  preferences: UserPreferences,
): Promise<boolean> {
  try {
    const response = await fetch(`${server_config.BASE_URL}/preference/overwrite`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, token, preferences }),
    });
    if (!response.ok) {
      addDebugTrace('preferences', 'overwrite failed', { status: response.statusText });
      return false;
    }
    addDebugTrace('preferences', 'overwrite success');
    return true;
  } catch (error) {
    addDebugTrace('preferences', 'overwrite error', { error: String(error) });
    return false;
  }
}
