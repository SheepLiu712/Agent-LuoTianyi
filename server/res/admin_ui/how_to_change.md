# 如何修改管理员控制台前端
管理员前端源码在：
页面和交互：[server/res/admin_ui/src/main.tsx](src/main.tsx)
样式：[server/res/admin_ui/src/styles.css](src/styles.css)
前端构建配置：[server/res/admin_ui/vite.config.ts](vite.config.ts)
不要直接修改 admin_static，它是构建生成目录。

构建步骤：
```powershell
cd server\res\admin_ui
npm install        # 只有依赖未安装时执行
npm run build
```
