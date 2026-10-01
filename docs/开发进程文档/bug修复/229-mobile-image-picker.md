# #229 · 0.3.2 版本：手机端部分机型无法发送图片（选择图片接口无法弹出）

| 项 | 值 |
| --- | --- |
| 分支 | `fix/mobile-image-picker` |
| Issue | [#229](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/229) |
| 来源 | 《AgentLuo bug收集》（腾讯文档） |
| 流程 | 普通修复：dev → fix/ → PR → dev |
| 状态 | 计划（首提交占位），实现与验证待进行 |

## 触发条件
部分机型点击「选择图片」：接口不弹出、界面无响应（原生抛错被静默忽略 / 权限路径失败）。

## 被违反的不变量
点击选图在受支持机型上要么弹出选择器，要么给出可见失败提示（不得静默无响应）。

## 根因（详见 #229 调查记录）
- `app/hooks/useChatLogic.ts:273-281`：无权限申请、无 try/catch，原生抛错即未处理 rejection；
- Android 13+ `READ_MEDIA_IMAGES` 无任何声明——系统 Photo Picker 缺失、回退到自家相册的机型弹不出；
- 插件由 prebuild 自动应用（非主因，供核对）。

## 修复点
1. 异常捕获 + 用户可见提示；
2. 按平台条件化权限申请（系统 picker 路径避免无谓弹窗，回退路径才需要媒体权限）；
3. `app.json` 补 `READ_MEDIA_IMAGES` 等声明；显式配置 expo-image-picker 插件（照片用途文案）。

## 改动范围
`app/hooks/useChatLogic.ts`、`app/app.json`。

## 验收标准（拟 · 待人审）
- 受影响机型可弹出选择器并成功发送；
- 权限拒绝 / 原生异常时有明确提示；
- prebuild 产物 manifest 含所需权限声明。

## 验证计划
- `expo prebuild` 产物核对（AndroidManifest）；
- 真机 logcat（区分抛错/空列表）+ 手工回归。

## 待定与前置
- 受影响机型清单（用于真机验证）。
