const { getDefaultConfig } = require('expo/metro-config');

const config = getDefaultConfig(__dirname);

// 添加 Live2D 相关的资源文件扩展名
config.resolver.assetExts.push(
  'moc3',          // Live2D 模型文件
  'model3',        // Live2D 模型描述文件（部分命名方式）
  'exp3',          // Live2D 表情文件
  'physics3',      // Live2D 物理文件
  'cdi3',          // Live2D CDI 文件
);

module.exports = config;
