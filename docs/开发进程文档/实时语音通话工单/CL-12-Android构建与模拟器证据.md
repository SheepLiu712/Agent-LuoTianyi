# CL-12 Android 构建与模拟器证据

> 状态：候选验证证据，不是第四次架构审查、非作者复审或人工验收

## 可复现工具矩阵

- Expo SDK `54.0.36`
- React Native `0.81.5`
- expo-modules-core `3.0.30`
- JDK `17.0.20.1`
- Gradle `8.14.3`
- Android Gradle Plugin `8.11.0`
- Kotlin `2.1.20`
- compileSdk / targetSdk `36`，minSdk `24`
- Build Tools `36.0.0`
- NDK `27.1.12297006`
- CMake `3.22.1`

SDK、Gradle cache、build copy、APK 和 debug keystore 都位于隔离工作区，不进入 Git。代理仅通过构建进程 JVM 参数注入，不写全局配置或仓库配置。

## 模块编译

从任意短路径隔离 App copy 的 `android` 目录执行：

```powershell
$env:ANDROID_HOME='<isolated-android-sdk>'
$env:ANDROID_SDK_ROOT=$env:ANDROID_HOME
$env:GRADLE_USER_HOME='<isolated-gradle-home>'
$env:GRADLE_OPTS='-Dhttp.proxyHost=<host> -Dhttp.proxyPort=<port> -Dhttps.proxyHost=<host> -Dhttps.proxyPort=<port> -Dhttp.nonProxyHosts=localhost -Dhttps.nonProxyHosts=localhost -Dorg.gradle.internal.http.connectionTimeout=30000 -Dorg.gradle.internal.http.socketTimeout=120000'

.\gradlew.bat `
  :agent-luotianyi-call-audio:compileDebugKotlin `
  :agent-luotianyi-call-audio:testDebugUnitTest `
  --no-daemon --console=plain
```

结果：`BUILD SUCCESSFUL`；`PlaybackAccountingTest` 9 tests、0 failures、0 errors、0 skipped。模块 `defaultConfig.versionName` 必须由 package version 显式提供，否则 Expo module Gradle plugin 在配置阶段失败。

## 完整 APK

Windows New Architecture CMake 构建必须控制 source、Gradle transform cache 与 object output 的完整路径。验证使用短隔离 source/cache，并仅在隔离 prebuild 工程的 `app/build.gradle` 传入：

```gradle
externalNativeBuild {
  cmake {
    arguments "-DCMAKE_OBJECT_PATH_MAX=200"
  }
}
```

该参数已真实进入 `CMakeCache.txt`。CMake 为长 source suffix 使用 hash 目录；独立核验的完整 `.o` 最大路径为 241 字符。此前记录的 190 只是不含 build root 的相对 object path，不能作为完整路径值。

```powershell
.\gradlew.bat :app:assembleDebug --no-daemon --console=plain
```

最终 APK：

- SHA-256：`ca8acf965a126d8824620f6659394dfad9d3bd0ee2ad3586ce0c0ce8aa0e2179`
- 大小：`184426340` bytes
- application ID：`com.sheepliu712.agentluochat`
- versionCode `8`、versionName `0.5.0`
- minSdk `24`、targetSdk `36`
- ABI：`arm64-v8a`、`armeabi-v7a`、`x86`、`x86_64`
- APK Signature Scheme v2，Android Debug certificate
- DEX 包含 `com/sheepliu712/callaudio/CallAudioModule` 与 `reacquireAudioFocus`

APK 不包含 `assets/index.android.bundle`。因此单独 `adb shell am start` 只证明原生 Activity 壳启动；必须连接真实 Metro，观察 bundle 与 `Running "main"` 后才可声称 JS 已运行。

## 模拟器加载

隔离设备：Android Emulator `37.2.12`、AOSP ATD API 36 x86_64、WHPX、headless、SwiftShader。APK 安装成功，`adb reverse tcp:8081 tcp:8081` 后，真实 Metro bundle `1289 modules`，设备日志显示：

- Expo AppContext 初始化
- JSI interop 安装
- Fabric `Running "main"`
- `requireOptionalNativeModule('CallAudio')` 返回真实模块

test-only smoke 只存在于隔离 build copy，不进入生产 UI 或 Git。

权限拒绝时 `startSession` 返回 `permission_denied`；ADB 授权后，模拟器返回 `aec_unavailable`，`reacquireAudioFocus` 返回 `session_not_ready`，随后 `stopCapture`、`stopPlayback`、`stopSession` cleanup 成功且无 FATAL。该证据说明模块加载和 fail-closed 行为正确，不说明模拟器或真机上的 AEC、降噪和音频焦点效果。

## 未验证

- 真机 16 kHz capture 与 24 kHz playback
- AEC / NoiseSuppressor 实际效果
- AudioFocus 获取与恢复效果
- Bluetooth、有线耳机、听筒、扬声器路由
- enqueue、tombstone、真实 playback head completion 的设备行为
- 设备延迟与 P95
- 真实供应商或付费服务
- 非作者复审与人工验收

历史 Gate 1/2/3 `BLOCKED` 与 Oracle `CHANGES_REQUESTED` 记录继续保留；上述 focused 证据只证明编译、APK、模拟器加载和安全降级范围。
