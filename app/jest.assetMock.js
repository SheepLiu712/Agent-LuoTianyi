// Jest 静态资源 mock：config/index.ts 会 require 图片资源，
// ts-jest 无法解析二进制文件，映射为字符串桩（React Native 项目标准做法）。
module.exports = 'asset-stub';
