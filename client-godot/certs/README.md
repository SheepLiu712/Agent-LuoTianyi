# CA 信任源

`ca-bundle.pem` 是 Godot 客户端唯一的 TLS 信任源。`project.godot` 通过
`network/tls/certificate_bundle_override` 指向该文件，因此账号、历史、图片、
WebSocket 与连通性探测的 HTTPS 请求都使用这份证书包，不再读取 Windows
当前用户根证书库或引擎内置 CA 包。

这样做的原因：Godot 4 在 Windows 上默认使用当前用户 ROOT 存储。该存储陈旧、
缺少服务端证书链所依赖的根（例如 `Sectigo Public Server Authentication Root R46`）
时，登录会在 TLS 阶段失败并报 `-9984 (MBEDTLS_ERR_X509_CERT_VERIFY_FAILED)`，
重启、换网络或重装客户端都无效。

## 当前快照

- 来源：<https://curl.se/ca/cacert.pem>（Mozilla CA 包）
- 快照日期：2026-11-16
- 证书数量：118
- SHA-256：`427c064216761a1e72a8b30f0d954d08cb6e4435a82091fb865afd20c8497285`
- 锁记录：`dependencies.lock.json` 的 `ca_bundle`

## 刷新步骤

1. 下载 `https://curl.se/ca/cacert.pem` 覆盖本目录的 `ca-bundle.pem`，保持 LF 换行。
2. 确认文件包含 `Sectigo Public Server Authentication Root R46`，且证书数不少于 100。
3. 更新 `dependencies.lock.json` 中 `ca_bundle.snapshot_date` 与 `ca_bundle.sha256`。
4. 运行 `godot --headless --path client-godot --script res://tests/test_tls_trust.gd`。
5. 对目标服务器做一次联网冒烟：`/auth/public_key` 应返回 200，日志不应出现
   `TLS handshake error: -9984`。

## 日志判读

运行日志的 `system_tls_trust` 事件会记录 `trust_source`、`bundle_present`、
`bundle_loaded`、`bundle_cert_count`、`bundle_has_r46` 与 `bundle_sha256`。
诊断包中该事件为 `bundle_override` 且 `bundle_loaded=true` 时，说明请求没有使用
Windows 根库；此时再出现 `MBEDTLS_ERR_X509_CERT_VERIFY_FAILED`，应检查本 CA 包
是否过期、服务端证书链是否完整、主机名与系统时间是否正确，而不是执行系统根证书同步。

## 边界

- 覆盖设置生效后，系统根库与引擎内置包不再参与校验；文件缺失或损坏会让所有
  HTTPS 请求失败，因此必须同时通过信任测试和导出打包检查。
- 不要用 `TLSOptions.client_unsafe()` 绕过校验。
- 需要信任新的根证书时按上述步骤刷新，而不是回退到系统根库。
