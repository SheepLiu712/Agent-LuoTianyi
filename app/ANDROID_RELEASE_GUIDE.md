# Expo Android 从 Prebuild 到发行构建手册

本文适用于 `Agent-LuoTianyi/app`（Expo SDK 54、React Native 0.81）。目标是让 `android/` 始终作为可再生目录：原生模块、权限和构建定制都来自受版本控制的 Expo 配置，不依赖开发者电脑上某份手改过的 `android/`。

## 1. 先理解哪些文件需要提交

需要提交：

- `app.json`：应用版本、Android `versionCode`、权限和 config plugin；
- `modules/pcm-recorder/`：16-bit、16 kHz、单声道 PCM 本地 Expo Module；
- `plugins/withLive2DAndroidAssets.js`：在 Android 构建前将 `public/` 同步进 APK 的 `assets/public/`；
- `public/`、`assets/`、TypeScript 源码、`package.json` 和 `package-lock.json`。

不提交：

- `android/`、`ios/`：由 Expo Prebuild 生成；
- `node_modules/`、`.expo/` 和构建产物；
- `.android-signing/` 中的 keystore、密码、`key.properties` 等签名秘密。

不要只把 Kotlin 文件强制加入被忽略的 `android/`。`npx expo prebuild --clean` 会重建整个目录，手工注册和手工复制的资源仍会丢失。

## 2. 准备构建环境

安装以下工具：

1. Node.js 和 npm；
2. JDK 17（Expo/React Native Android 构建的稳妥选择）；
3. Android Studio，以及项目所需的 Android SDK、Build Tools 和 Platform Tools；
4. 可用的 `ANDROID_HOME`，并确保 `adb` 可执行；
5. JDK 自带的 `keytool`，以及 Android Build Tools 自带的 `apksigner`。

在 PowerShell 中进入 app 客户端根目录并安装锁定版本的依赖：

```powershell
cd E:\Agent-LuoTianyi\app
npm ci
npx expo-doctor
```

`npm ci` 以 `package-lock.json` 为准，适合干净环境和 CI。日常新增依赖时使用 `npx expo install <包名>`，让 Expo 选择与当前 SDK 兼容的版本。

## 3. 发布前更新版本号

一次 Android 发布至少要维护两个值：

- `expo.version`：用户可见版本，例如 `0.4.0`；
- `expo.android.versionCode`：Google Play/Android 用的单调递增整数，不能复用。

先让 npm 同步 `package.json` 和 `package-lock.json`：

```powershell
npm version 0.4.0 --no-git-tag-version
```

然后在 `app.json` 中把 `expo.version` 改成相同版本，并把 `expo.android.versionCode` 加一。提交前确认三处一致：

```powershell
node -e "const p=require('./package.json'); const l=require('./package-lock.json'); const a=require('./app.json').expo; console.log({package:p.version, lock:l.version, expo:a.version, versionCode:a.android.versionCode})"
```

## 4. 生成干净的 Android 工程

首次构建、原生模块变化、config plugin 变化、Expo SDK 升级，或者怀疑 `android/` 被手改时，执行：

```powershell
npm run prebuild:android:clean
```

该命令等价于：

```powershell
npx expo prebuild --platform android --clean
```

`--clean` 会删除并重建 `android/`。本项目的签名材料放在被忽略的 `app/.android-signing/`，因此不会被清理；同时仍应另做离线备份。密码绝不能提交到 Git。

如果只是同步未变化的配置，可以执行：

```powershell
npm run prebuild:android
```

但发布前建议至少做一次干净 Prebuild，以证明项目不依赖陈旧的生成文件。

## 5. 验证 Prebuild 结果

### 5.1 本地 Expo Module 已自动链接

```powershell
npx expo-modules-autolinking search --platform android --json |
  Select-String -Pattern 'pcm-recorder|PcmRecorderModule'
```

结果应包含：

```text
expo.modules.pcmrecorder.PcmRecorderModule
```

`android/app/src/main/java/.../MainApplication.kt` 不应该再出现 `PcmRecorderPackage()` 的手工注册，也不需要 `PcmRecorderPackage.kt`。

### 5.2 权限来自 app 配置

```powershell
Select-String -Path android\app\src\main\AndroidManifest.xml -Pattern 'RECORD_AUDIO'
```

必须包含 `android.permission.RECORD_AUDIO`。运行时授权仍由通话页面发起；Manifest 声明不能替代运行时授权。

### 5.3 Live2D 资源同步任务已注入

```powershell
Select-String -Path android\app\build.gradle -Pattern 'syncLive2DPublicAssets'
```

该任务在每次 `preBuild` 前把 `app/public/` 同步到构建目录，最终保持 WebView 所需路径：

```text
file:///android_asset/public/live2d/live2d.html
```

因此修改 `public/live2d/live2d.html` 后不需要再手工复制到 `android/app/src/main/assets/`。

## 6. 构建并测试开发版

本地 Expo Module 不能在 Expo Go 中动态出现。首次加入模块或修改 Kotlin 后，必须重新构建原生客户端：

```powershell
npx expo run:android
```

只修改 TypeScript、样式或其他 JS 代码时可以继续使用 Fast Refresh；修改 Kotlin、Manifest、Gradle 或 config plugin 后必须重新 Prebuild/构建。

发布前至少完成以下检查：

```powershell
npx tsc --noEmit
npm run lint
cd android
.\gradlew.bat :app:assembleDebug
cd ..
```

随后在真机上验证麦克风授权、建立电话、连续上传 PCM、挂断、断线重连和 Live2D 音频播放。

## 7. 在本机构建签名发行版

项目只使用本地 Gradle 构建。`withAndroidReleaseSigning` config plugin 会在 Prebuild 时把发行签名配置写入生成的 `android/app/build.gradle`，并覆盖 Expo 默认的 debug 签名。签名值来自同名 Gradle property 或环境变量；缺少任何一项时，release 打包会直接失败，避免误发 debug 签名或未签名产物。

### 7.1 首次发布：创建上传密钥

keystore 只能创建一次。后续同一 Android 应用的所有升级包必须继续使用同一个密钥；丢失密钥和密码可能导致无法更新已经发布的应用。

在 Android 生成目录之外的被忽略目录中创建密钥：

```powershell
$keyDirectory = Join-Path (Get-Location) '.android-signing\release'
New-Item -ItemType Directory -Force -Path $keyDirectory | Out-Null
$keyStore = Join-Path $keyDirectory 'luotianyi-upload-key.p12'

keytool -genkeypair -v `
  -storetype PKCS12 `
  -keystore $keyStore `
  -alias luotianyi-upload `
  -keyalg RSA `
  -keysize 2048 `
  -validity 10000
```

`keytool` 会交互式询问密码和证书信息。PKCS12 通常让私钥密码与 keystore 密码保持一致。创建完成后，应分别离线备份：

- `luotianyi-upload-key.p12`；
- alias（本例为 `luotianyi-upload`）；
- keystore 密码和私钥密码；
- `keytool -list -v` 显示的证书 SHA-256 指纹。

不要把上述文件或密码提交到仓库，也不要只保存在构建电脑上。

### 7.2 准备被忽略的本地签名目录

把当前构建使用的文件放在以下目录：

```text
app/.android-signing/key.properties
app/.android-signing/release/<keystore 文件>
```

`key.properties` 使用 Android Gradle 常见格式：

```properties
storeFile=release/luotianyi-upload-key.p12
storePassword=替换为真实密码
keyAlias=luotianyi-upload
keyPassword=替换为真实密码
```

整个 `.android-signing/` 已加入 `.gitignore`，不会被跟踪。构建脚本会自动读取它；同名环境变量优先级更高，适合 CI 或临时覆盖。

如果不希望密码落盘，也可以不创建 `key.properties`，在当前 PowerShell 会话中注入。下面的写法不会把明文密码写入 PowerShell 历史：

```powershell
$env:MYAPP_UPLOAD_STORE_FILE = (Resolve-Path '.android-signing\release\luotianyi-upload-key.p12').Path
$env:MYAPP_UPLOAD_KEY_ALIAS = 'luotianyi-upload'

$storePassword = Read-Host 'Keystore password' -AsSecureString
$keyPassword = Read-Host 'Private key password' -AsSecureString
$env:MYAPP_UPLOAD_STORE_PASSWORD = (New-Object System.Net.NetworkCredential('', $storePassword)).Password
$env:MYAPP_UPLOAD_KEY_PASSWORD = (New-Object System.Net.NetworkCredential('', $keyPassword)).Password
```

这四个变量只在当前 PowerShell 进程中有效：

```text
MYAPP_UPLOAD_STORE_FILE
MYAPP_UPLOAD_KEY_ALIAS
MYAPP_UPLOAD_STORE_PASSWORD
MYAPP_UPLOAD_KEY_PASSWORD
```

如果使用 `key.properties`，不需要手动设置上述环境变量。不要写入项目的 `android/gradle.properties`，因为 `prebuild --clean` 会删除它。

### 7.3 干净 Prebuild 并构建签名 APK

在 app 根目录执行：

```powershell
cd E:\Agent-LuoTianyi\app
npm run prebuild:android:clean
npm run build:android:release
```

第二条命令调用受版本控制的 `scripts/build-android-release.ps1`，它会：

1. 读取 `.android-signing/key.properties`，并检查四个签名值；
2. 把 keystore 路径转换为绝对路径；
3. 设置 `NODE_ENV=production`；
4. 执行 `android\gradlew.bat :app:assembleRelease`。

签名 APK 输出到：

```text
android/app/build/outputs/apk/release/app-release.apk
```

如果需要 Google Play 使用的 AAB，在已经注入签名变量后执行：

```powershell
cd E:\Agent-LuoTianyi\app\android
$env:NODE_ENV = 'production'
.\gradlew.bat :app:bundleRelease
```

AAB 输出到 `android/app/build/outputs/bundle/release/app-release.aab`。

### 7.4 验证 APK 确实使用发行证书签名

不要只凭 `assembleRelease` 成功就认定签名正确。使用 Android Build Tools 的 `apksigner`：

```powershell
$apk = 'E:\Agent-LuoTianyi\app\android\app\build\outputs\apk\release\app-release.apk'
$buildTools = Get-ChildItem "$env:ANDROID_HOME\build-tools" -Directory |
  Sort-Object Name -Descending |
  Select-Object -First 1

& (Join-Path $buildTools.FullName 'apksigner.bat') verify `
  --verbose `
  --print-certs `
  $apk
```

命令必须成功，并输出 `Verified`。将 `Signer #1 certificate SHA-256 digest` 与创建 keystore 时离线保存的指纹比较；两者必须一致。

## 8. 签名密钥和后续升级规则

- 同一个 Android package（本项目为 `com.sheepliu712.ailuotianyi`）必须持续使用同一签名密钥；
- 每次发布都要增加 `expo.android.versionCode`；
- 不要因为换电脑、重装系统或 `prebuild --clean` 而重新生成 keystore；
- keystore、alias、密码和证书指纹至少保留两份相互独立的离线备份；
- CI 如需构建，应从秘密管理系统临时恢复 keystore 和环境变量，构建结束后立即清理；
- 如果使用 Google Play App Signing，应区分“上传密钥”和由 Google 保管的“应用签名密钥”。

## 9. 验证最终 APK，而不只验证源码

假设 APK 路径为 `$apk`：

```powershell
$apk = 'E:\path\to\release.apk'
jar tf $apk | Select-String -Pattern 'assets/public/live2d/live2d.html'
```

必须能找到：

```text
assets/public/live2d/live2d.html
```

如果本机 Android SDK 提供 `apkanalyzer`，再检查版本和权限：

```powershell
apkanalyzer manifest version-name $apk
apkanalyzer manifest version-code $apk
apkanalyzer manifest permissions $apk | Select-String -Pattern 'RECORD_AUDIO'
```

安装到真机：

```powershell
adb install -r $apk
```

最终验收应在发行 APK 上完成，至少包括：

1. 安装、启动、登录正常；
2. 聊天 WebView 能加载 Live2D；
3. “语音通话”能申请麦克风权限；
4. 原生 `PcmRecorder` 可持续输出 16-bit、16 kHz、mono PCM；
5. Live2D 表情、分段音频播放、打断和挂断正常；
6. APK 内的 Live2D HTML 确实是本次源码版本。

## 10. 常见问题

### `Cannot find native module 'PcmRecorder'`

通常是仍在使用 Expo Go、只刷新了 JS，或没有在新增 Kotlin 后重建原生客户端。执行干净 Prebuild，再执行 `npx expo run:android`。

### `RECORD_AUDIO` 已配置但仍无法录音

Manifest 权限只表示应用可以申请权限。检查用户是否拒绝了运行时授权，以及 Android 系统设置中该应用的麦克风权限。

### 开发环境正常，发行 APK 的 Live2D 是旧版本

先检查 `android/app/build.gradle` 是否包含 `syncLive2DPublicAssets`，再直接检查 APK 的 `assets/public/live2d/live2d.html`。不要通过手工复制修复；如果任务没有生成，重新执行干净 Prebuild。

### `prebuild --clean` 后本地改动消失

这是预期行为。把需要长期保留的原生行为迁移到 `modules/`、`app.json` 或 `plugins/`；不要继续编辑生成目录并把它当作唯一源码。

## 参考资料

- [Expo Prebuild](https://docs.expo.dev/workflow/prebuild/)
- [Expo Modules](https://docs.expo.dev/modules/get-started/)
- [Android：为应用签名](https://developer.android.com/studio/publish/app-signing)
- [Android：从命令行构建应用](https://developer.android.com/build/building-cmdline)
