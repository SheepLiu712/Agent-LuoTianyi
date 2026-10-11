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

- 本机没有真实 Android 设备；按用户授权跳过本机真机测试，交由审查员执行。该项是明确 handoff，不是测试通过，也不作为本地候选发布阻断。
- 真机 16 kHz capture 与 24 kHz playback
- AEC / NoiseSuppressor 实际效果
- AudioFocus 获取与恢复效果
- Bluetooth、有线耳机、听筒、扬声器路由
- enqueue、tombstone、真实 playback head completion 的设备行为
- 设备延迟与 P95
- 真实供应商或付费服务
- 非作者复审与人工验收

历史 Gate 1/2/3 `BLOCKED` 与 Oracle `CHANGES_REQUESTED` 记录继续保留；上述 focused 证据只证明编译、APK、模拟器加载和安全降级范围。

## 审查员真机测试清单

测试候选 APK：

```text
SHA-256: ca8acf965a126d8824620f6659394dfad9d3bd0ee2ad3586ce0c0ce8aa0e2179
package: com.sheepliu712.agentluochat
versionCode: 8
versionName: 0.5.0
```

该 Debug APK 不包含 `assets/index.android.bundle`。测试时需要从与候选源码一致的 App checkout 启动 Metro，并执行 `adb reverse tcp:8081 tcp:8081`；仅观察 Activity 启动不算 JS 或 Native Module 测试通过。

1. **安装与模块加载**
   - 校验 APK SHA-256 后安装，连接 Metro，确认 Expo JSI、Fabric `Running "main"`，且 `requireOptionalNativeModule('CallAudio')` 非空
   - 预期：无 `FATAL EXCEPTION`、`UnsatisfiedLinkError` 或模块缺失
2. **麦克风权限**
   - 先拒绝，再允许 `RECORD_AUDIO`
   - 预期：拒绝时 `permission_denied` 且无设备所有权残留；允许后才尝试初始化
3. **固定音频格式与系统处理**
   - 验证 capture 为 PCM16 / 16 kHz / mono，playback 为 PCM16 / 24 kHz / mono
   - 检查 AEC 与 NoiseSuppressor API 初始化和 enabled 状态；另以实际回声/环境噪声录音判断效果
   - API enabled 只证明初始化，不等于实际效果通过
4. **AudioFocus**
   - 通话中用其他媒体/电话场景抢占焦点，再恢复
   - 预期：首次丢失起固定 3 秒内恢复原 `call_id`；`reacquireAudioFocus` 成功恢复原 session，不创建第二 native owner；超时则 fail-closed
5. **路由与设备切换**
   - 覆盖听筒、扬声器、3.5 mm/USB 有线耳机及蓝牙耳机（设备支持的组合）
   - 预期：遵循系统通信路由、无崩溃、无队列串流或旧 generation 复活；记录每个设备型号和 Android 版本
6. **后台与停止清理**
   - ACTIVE、播放中、采集中分别把 App 切后台并返回
   - 预期：按产品规则结束通话；capture/playback/audio focus/route callback 均释放；无后台录音、worker timeout 或 `session_termination_failed`
7. **播放完成与打断**
   - 播放多 chunk 且 final 的 PCM，观察最后一个 sample 被 AudioTrack 实际消费后才产生 completion
   - 播放中执行 stop/tombstone，并发送迟到 chunk/completion
   - 预期：completion 恰好一次；stop 后迟到事件不恢复旧流；queued stop 不 flush 无关 active 流
8. **时延采样**
   - 分别记录有效用户轮次到首个 CALL PCM、首个 PCM 到设备开始播放、final 入队到实际 completion、用户打断到停止确认
   - 至少记录设备、Android 版本、网络、样本数、P50/P95；不得用模拟器或单样本代替 P95

审查员应提交原始命令、脱敏 logcat、设备矩阵、失败复现步骤和结果摘要。真实 provider/P95 仍是独立未验证范围；离线 fake provider 或设备本地音频 smoke 不能替代它们。
