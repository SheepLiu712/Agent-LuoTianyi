# Android 本地签名构建

在 `app` 目录执行：

```powershell
npm run build:android:release
```

不要直接运行 `gradlew.bat assembleRelease`。受版本控制的构建脚本会自动：

1. 从被忽略的 `.android-signing/key.properties` 读取签名配置；
2. 将相对 keystore 路径解析为绝对路径；
3. 设置 Expo release 打包要求的 `NODE_ENV=production`；
4. 执行 `:app:assembleRelease`；
5. 生成 `android/app/build/outputs/apk/release/AgentLuoChat-release-v<版本>.apk`。

## 修改版本号和 versionCode

Android 发布版本由以下配置共同决定：

- `package.json` 和 `package-lock.json` 中的 `version`；
- `app.json` 中的 `expo.version`；
- `app.json` 中的 `expo.android.versionCode`。

其中 `version` 是用户看到的版本号，例如 `0.3.3`；`versionCode` 是 Android 用来判断升级顺序的整数。每次发布都必须增大 `versionCode`，已经发布过的数字不能复用，即使版本回滚也不能减小。

例如从 `0.3.2 / versionCode 6` 发布到 `0.3.3 / versionCode 7`：

1. 在 `app` 目录执行以下命令，同步修改 `package.json` 和 `package-lock.json`，但不创建 Git tag：

   ```powershell
   npm version 0.3.3 --no-git-tag-version
   ```

2. 修改 `app.json`：

   ```json
   {
     "expo": {
       "version": "0.3.3",
       "android": {
         "versionCode": 7
       }
     }
   }
   ```

   上述内容只是字段示例，不要覆盖 `app.json` 中的其他配置。

3. 检查三处版本是否一致：

   ```powershell
   node -e "const p=require('./package.json'); const l=require('./package-lock.json'); const a=require('./app.json').expo; console.log({package:p.version, lock:l.version, expo:a.version, versionCode:a.android.versionCode})"
   ```

4. 运行 Prebuild，把 `app.json` 中的版本同步到生成的 `android/app/build.gradle`，然后构建：

   ```powershell
   npm run prebuild:android -- --no-install
   npm run build:android:release
   ```

   首次构建、Expo SDK 或原生配置发生变化、或者怀疑生成目录有旧内容时，将第一条替换为：

   ```powershell
   npm run prebuild:android:clean -- --no-install
   ```

构建脚本会根据 `package.json` 中的版本生成 APK 文件名。以上示例最终生成：

```text
android/app/build/outputs/apk/release/AgentLuoChat-release-v0.3.3.apk
```

本地签名文件结构：

```text
.android-signing/key.properties
.android-signing/release/<keystore 文件>
```

`key.properties` 格式：

```properties
storeFile=release/luotianyi-upload.jks
storePassword=<keystore 密码>
keyAlias=<alias>
keyPassword=<私钥密码>
```

也可以不保存密码文件，改为在当前 PowerShell 进程设置：

```text
MYAPP_UPLOAD_STORE_FILE
MYAPP_UPLOAD_KEY_ALIAS
MYAPP_UPLOAD_STORE_PASSWORD
MYAPP_UPLOAD_KEY_PASSWORD
```

首次构建或原生配置变化后，可先重新生成 Android 工程：

```powershell
npm run prebuild:android:clean
npm run build:android:release
```

签名插件和 Live2D 资源插件会在 Prebuild 后重新注入对应 Gradle 配置。`.android-signing/`、`android/` 和签名密钥均不得提交。
