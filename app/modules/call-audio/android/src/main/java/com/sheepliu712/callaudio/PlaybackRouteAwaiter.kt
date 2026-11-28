package com.sheepliu712.callaudio

internal enum class RouteProbeResult { WAITING, READY, FAILED }

/** Route confirmation must not prevent callers from stopping queued speech. */
internal object PlaybackRouteAwaiter {
  fun await(running: () -> Boolean, processStop: () -> Unit, probe: () -> RouteProbeResult): Boolean {
    while (running()) {
      processStop()
      when (probe()) {
        RouteProbeResult.READY -> return true
        RouteProbeResult.FAILED -> return false
        RouteProbeResult.WAITING -> Unit
      }
    }
    // Cancellation can race with a stop queued during the last probe.
    processStop()
    return false
  }
}
