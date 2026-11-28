package com.sheepliu712.callaudio

import org.junit.Assert.*
import org.junit.Test

class PlaybackRouteAwaiterTest {
  private class QueuedSpeech {
    val key = StreamKey("reply", 1)
    val queue = PlaybackQueue(1024)
    val state = PlaybackState(queue)
    val accounting = PlaybackLoopAccounting(0)
    val processor = PlaybackCommandProcessor(state, accounting)
    val stops = StopOperationRegistry<String>()
    val pending = ArrayDeque<List<StreamKey>>()
    val settled = mutableListOf<String>()
    val receipts = mutableListOf<StreamKey>()

    init {
      check(queue.offer(PlaybackChunk(key, 1, byteArrayOf(1, 0), true)))
    }

    fun requestStop() {
      pending.add(stops.register(listOf(key), "stop").newlyPendingKeys)
    }

    fun processStop() {
      if (pending.isEmpty()) return
      val outcome = processor.stop(pending.removeFirst(), 0)
      assertFalse("尚未写入语音，不应声称停止了正在播放的音轨", outcome.activeStopped)
      receipts.addAll(outcome.stoppedKeys)
      settled.addAll(stops.complete(outcome.stoppedKeys))
    }

    fun assertStoppedWithoutPlayback() {
      assertEquals(listOf("stop"), settled)
      assertEquals(listOf(key), receipts)
      assertTrue(stops.isIdle())
      assertFalse(queue.hasFor(key))
      assertEquals(0L, accounting.submittedFrames)
      assertEquals(0L, accounting.playedFrames)
      assertNull(accounting.takeConsumedFinal())
    }
  }

  @Test fun `stops queued speech while the headset route is still waiting`() {
    val speech = QueuedSpeech()
    var probes = 0
    val ready = PlaybackRouteAwaiter.await({ true }, speech::processStop) {
      when (probes++) {
        0 -> { speech.requestStop(); RouteProbeResult.WAITING }
        else -> { speech.assertStoppedWithoutPlayback(); RouteProbeResult.READY }
      }
    }
    assertTrue(ready)
    speech.assertStoppedWithoutPlayback()
  }

  @Test fun `cancelling route confirmation settles a queued stop before returning`() {
    val speech = QueuedSpeech()
    var running = true
    val ready = PlaybackRouteAwaiter.await({ running }, speech::processStop) {
      speech.requestStop()
      running = false
      RouteProbeResult.WAITING
    }
    assertFalse(ready)
    speech.assertStoppedWithoutPlayback()
  }

  @Test fun `failed route confirmation does not report speech consumed`() {
    val speech = QueuedSpeech()
    speech.requestStop()
    assertFalse(PlaybackRouteAwaiter.await({ true }, speech::processStop) { RouteProbeResult.FAILED })
    speech.assertStoppedWithoutPlayback()
  }
}
