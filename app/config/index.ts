// 应用配置文件
// 在此处修改服务器地址等全局配置

import AsyncStorage from '@react-native-async-storage/async-storage';

const CUSTOM_SERVER_URL_KEY = 'custom_server_url';

export const server_config: {
  BASE_URL: string;
  API_TIMEOUT: number;
  LOAD_HISTORY_COUNT: number;
} = {
  // 服务器基础URL - 默认值
  BASE_URL: 'https://www-api.u3493359.nyat.app:11664',
  
  // 可以添加其他配置项
  API_TIMEOUT: 10000, // 10秒超时
  LOAD_HISTORY_COUNT: 20, // 每次加载历史记录的条数
};

/** 从持久化存储加载自定义服务器地址 */
export async function loadSavedServerUrl(): Promise<void> {
  try {
    const savedUrl = await AsyncStorage.getItem(CUSTOM_SERVER_URL_KEY);
    if (savedUrl) {
      server_config.BASE_URL = savedUrl;
      console.log(`Loaded saved server URL: ${savedUrl}`);
    }
  } catch (e) {
    console.warn('Failed to load saved server URL:', e);
  }
}

export const local_config = {
  // 本地配置项示例
  ERROR_IMAGE: require('../assets/images/error_image.png'),
};

export default server_config;
