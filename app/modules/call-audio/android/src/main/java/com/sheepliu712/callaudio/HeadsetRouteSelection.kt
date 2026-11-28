package com.sheepliu712.callaudio

internal data class RouteDevice(val id: Int, val address: String, val classicBluetooth: Boolean)

internal object HeadsetRouteSelection {
  fun <T> refreshSnapshot(previous: T?, routed: T?, isHeadset: (T) -> Boolean): T? =
    if (routed == null) previous else routed.takeIf(isHeadset)

  fun select(media: RouteDevice, candidates: List<RouteDevice>): Int {
    candidates.singleOrNull { it.id == media.id }?.let { return it.id }
    if (media.address.isNotBlank() && media.address != "00:00:00:00:00:00") {
      candidates.singleOrNull { it.address.equals(media.address, ignoreCase = true) }?.let { return it.id }
    }
    // 部分厂商为 SCO 暴露占位地址。仅有一个经典蓝牙通信端点时可唯一确定。
    if (media.classicBluetooth) {
      candidates.filter { it.classicBluetooth }.singleOrNull()?.let {
        if (it.address.isBlank() || it.address == "00:00:00:00:00:00" || media.address.isBlank()) return it.id
      }
    }
    error("headset_route_unresolved")
  }

  fun ready(target: Int, outputs: List<Int>): Boolean = outputs.isNotEmpty() && outputs.all { it == target }
}
