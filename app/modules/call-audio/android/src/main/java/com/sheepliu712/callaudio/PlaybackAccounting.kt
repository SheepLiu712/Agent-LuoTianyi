package com.sheepliu712.callaudio

internal object PlaybackAccounting {
  private const val UINT32_MODULUS = 1L shl 32

  fun unsignedDelta(previous: Long, current: Long): Long {
    require(previous in 0 until UINT32_MODULUS)
    require(current in 0 until UINT32_MODULUS)
    return if (current >= previous) current - previous else UINT32_MODULUS - previous + current
  }
}

internal class PlaybackQueue(private val capacityBytes: Int) {
  private val entries = ArrayDeque<PlaybackChunk>()
  private var bytes = 0

  @Synchronized
  fun offer(chunk: PlaybackChunk): Boolean {
    if (chunk.payload.size > capacityBytes - bytes) return false
    entries.addLast(chunk)
    bytes += chunk.payload.size
    (this as java.lang.Object).notifyAll()
    return true
  }

  @Synchronized
  fun nextStream(): StreamKey? = entries.firstOrNull()?.key

  @Synchronized
  fun pollFor(identity: StreamKey): PlaybackChunk? {
    val index = entries.indexOfFirst { it.key == identity }
    if (index < 0) return null
    val chunk = entries.removeAt(index)
    bytes -= chunk.payload.size
    return chunk
  }

  @Synchronized
  fun contains(identity: StreamKey): Boolean = entries.any { it.key == identity }

  @Synchronized
  fun remove(identity: StreamKey) {
    val retained = entries.filterNot { it.key == identity }
    entries.clear()
    entries.addAll(retained)
    bytes = retained.sumOf { it.payload.size }
  }

  @Synchronized
  fun clear() {
    entries.clear()
    bytes = 0
    (this as java.lang.Object).notifyAll()
  }

  @Synchronized
  fun wake() {
    (this as java.lang.Object).notifyAll()
  }
}

internal class PlaybackState(private val queue: PlaybackQueue) {
  var active: StreamKey? = null
    private set

  fun chooseActive(): StreamKey? {
    if (active == null) active = queue.nextStream()
    return active
  }

  fun complete(identity: StreamKey) {
    if (active == identity) active = null
  }

  fun stop(identity: StreamKey): Boolean {
    queue.remove(identity)
    val wasActive = active == identity
    if (wasActive) active = null
    return wasActive
  }

  fun reset() {
    active = null
    queue.clear()
  }
}

/** Mutable playback-head accounting used directly by the AudioTrack worker. */
internal class PlaybackLoopAccounting(initialHead: Long) {
  var previousHead = initialHead
    private set
  var playedFrames = 0L
    private set
  var submittedFrames = 0L
    private set
  var finalTarget: Pair<PlaybackChunk, Long>? = null
    private set

  fun recordSubmitted(frames: Long) {
    submittedFrames += frames
  }

  fun markFinal(chunk: PlaybackChunk) {
    finalTarget = chunk to submittedFrames
  }

  fun recordPlaybackHead(currentHead: Long): PlaybackChunk? {
    playedFrames += PlaybackAccounting.unsignedDelta(previousHead, currentHead)
    previousHead = currentHead
    val target = finalTarget ?: return null
    if (playedFrames < target.second) return null
    finalTarget = null
    return target.first
  }

  fun observeHead(currentHead: Long) {
    playedFrames += PlaybackAccounting.unsignedDelta(previousHead, currentHead)
    previousHead = currentHead
  }

  fun takeConsumedFinal(): PlaybackChunk? {
    val target = finalTarget ?: return null
    if (playedFrames < target.second) return null
    finalTarget = null
    return target.first
  }

  fun discardStaleFinal() {
    finalTarget = null
  }

  fun applyStop(activeStopped: Boolean, currentHead: Long) {
    if (!activeStopped) return
    reset(currentHead)
  }

  fun complete(currentHead: Long) {
    reset(currentHead)
  }

  private fun reset(currentHead: Long) {
    previousHead = currentHead
    playedFrames = 0L
    submittedFrames = 0L
    finalTarget = null
  }
}

internal data class PlaybackStopOutcome(
  val activeStopped: Boolean,
  val stoppedKeys: List<StreamKey>,
)

internal class PlaybackCommandProcessor(
  private val playbackState: PlaybackState,
  private val accounting: PlaybackLoopAccounting,
) {
  private val receipted = mutableSetOf<StreamKey>()

  fun stop(keys: List<StreamKey>, currentHead: Long): PlaybackStopOutcome {
    var activeStopped = false
    val newlyStopped = keys.filter { receipted.add(it) }
    newlyStopped.forEach { activeStopped = playbackState.stop(it) || activeStopped }
    accounting.applyStop(activeStopped, currentHead)
    return PlaybackStopOutcome(activeStopped, newlyStopped)
  }
}

internal class WorkerOwnership {
  private var failed = false

  fun markStopResult(stopped: Boolean) {
    if (!stopped) failed = true
  }

  fun canStart(): Boolean = !failed

  fun accepts(eventGeneration: Long, currentGeneration: Long): Boolean =
    !failed && eventGeneration == currentGeneration
}

internal data class StopRegistration(
  val newlyPendingKeys: List<StreamKey>,
  val resolveImmediately: Boolean,
)

/** Owns logical stop requests independently from physical stopped receipts. */
internal class StopOperationRegistry<W> {
  private data class Request<W>(val waiter: W, val remaining: MutableSet<StreamKey>)

  private val pendingByKey = mutableMapOf<StreamKey, MutableSet<Long>>()
  private val completedKeys = mutableSetOf<StreamKey>()
  private val requests = mutableMapOf<Long, Request<W>>()
  private var nextRequestId = 1L
  private var failed = false

  @Synchronized
  fun register(keys: List<StreamKey>, waiter: W): StopRegistration {
    if (failed) return StopRegistration(emptyList(), false)
    val remaining = keys.toSet().filterNotTo(mutableSetOf()) { completedKeys.contains(it) }
    if (remaining.isEmpty()) return StopRegistration(emptyList(), true)
    val requestId = nextRequestId++
    requests[requestId] = Request(waiter, remaining)
    val newlyPending = mutableListOf<StreamKey>()
    remaining.forEach { key ->
      val requestIds = pendingByKey[key]
      if (requestIds == null) {
        pendingByKey[key] = mutableSetOf(requestId)
        newlyPending.add(key)
      } else {
        requestIds.add(requestId)
      }
    }
    return StopRegistration(newlyPending, false)
  }

  @Synchronized
  fun cancelRegistration(waiter: W) {
    val requestIds = requests.filterValues { it.waiter == waiter }.keys
    requestIds.forEach { requestId ->
      val request = requests.remove(requestId) ?: return@forEach
      request.remaining.forEach remainingLoop@{ key ->
        val ids = pendingByKey[key] ?: return@remainingLoop
        ids.remove(requestId)
        if (ids.isEmpty()) pendingByKey.remove(key)
      }
    }
  }

  @Synchronized
  fun complete(keys: List<StreamKey>): List<W> {
    if (failed) return emptyList()
    val settled = mutableListOf<W>()
    keys.forEach { key ->
      if (!completedKeys.add(key)) return@forEach
      val requestIds = pendingByKey.remove(key).orEmpty()
      requestIds.forEach { requestId ->
        val request = requests[requestId] ?: return@forEach
        request.remaining.remove(key)
        if (request.remaining.isEmpty()) {
          requests.remove(requestId)
          settled.add(request.waiter)
        }
      }
    }
    return settled
  }

  @Synchronized
  fun fail(): List<W> {
    if (failed) return emptyList()
    failed = true
    val waiters = requests.values.map { it.waiter }
    requests.clear()
    pendingByKey.clear()
    return waiters
  }

  @Synchronized
  fun isIdle(): Boolean = requests.isEmpty() && pendingByKey.isEmpty()
}

internal data class StreamKey(val responseId: String, val streamId: Int)

internal data class PlaybackChunk(
  val key: StreamKey,
  val generation: Long,
  val payload: ByteArray,
  val isFinal: Boolean,
)
