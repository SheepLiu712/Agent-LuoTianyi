// 应用配置文件
// 在此处修改服务器地址等全局配置

export const server_config = {
  // 服务器基础URL - 根据实际部署环境修改
  BASE_URL: 'https://www-api.u3493359.nyat.app:11664',
  
  // 可以添加其他配置项
  API_TIMEOUT: 10000, // 10秒超时
  LOAD_HISTORY_COUNT: 20, // 每次加载历史记录的条数
};

export const local_config = {
  // 本地配置项示例
  ERROR_IMAGE: require('../assets/images/error_image.png'),
};

export default server_config;
