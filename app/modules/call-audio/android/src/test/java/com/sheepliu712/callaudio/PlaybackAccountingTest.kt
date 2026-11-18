package com.sheepliu712.callaudio

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PlaybackAccountingTest {
  @Test
  fun unsignedDeltaHandlesPlaybackHeadRollover() {
    assertEquals(5L, PlaybackAccounting.unsignedDelta(0xffff_fffeL, 3L))
  }

  @Test
  fun boundedQueueRejectsOverflowAndReleasesCapacity() {
    val queue = PlaybackQueue(4)
    val key = StreamKey("response", 1)
    assertTrue(queue.offer(PlaybackChunk(key, 1, byteArrayOf(1, 2), false)))
    assertFalse(queue.offer(PlaybackChunk(key, 1, byteArrayOf(3, 4, 5), false)))
    assertEquals(2, queue.pollFor(key)?.payload?.size)
    assertTrue(queue.offer(PlaybackChunk(key, 1, byteArrayOf(3, 4, 5), true)))
  }

  @Test
  fun removeDropsOnlyMatchingStream() {
    val queue = PlaybackQueue(8)
    val removed = StreamKey("removed", 1)
    val kept = StreamKey("kept", 2)
    queue.offer(PlaybackChunk(removed, 1, byteArrayOf(1, 2), true))
    queue.offer(PlaybackChunk(kept, 1, byteArrayOf(3, 4), true))

    queue.remove(removed)

    assertEquals(kept, queue.pollFor(kept)?.key)
    assertNull(queue.pollFor(removed))
  }

  @Test
  fun stoppingQueuedStreamDoesNotDisturbActiveStream() {
    val queue = PlaybackQueue(8)
    val state = PlaybackState(queue)
    val active = StreamKey("active", 1)
    val queued = StreamKey("queued", 2)
    queue.offer(PlaybackChunk(active, 1, byteArrayOf(1, 2), false))
    queue.offer(PlaybackChunk(queued, 2, byteArrayOf(3, 4), true))
    assertEquals(active, state.chooseActive())

    assertFalse(state.stop(queued))

    assertEquals(active, state.chooseActive())
    assertEquals(active, queue.pollFor(active)?.key)
  }

  @Test
  fun stoppingActiveStreamAllowsUnrelatedQueueToResume() {
    val queue = PlaybackQueue(8)
    val state = PlaybackState(queue)
    val active = StreamKey("active", 1)
    val queued = StreamKey("queued", 2)
    queue.offer(PlaybackChunk(active, 1, byteArrayOf(1, 2), false))
    queue.offer(PlaybackChunk(queued, 2, byteArrayOf(3, 4), true))
    assertEquals(active, state.chooseActive())

    assertTrue(state.stop(active))

    assertEquals(queued, state.chooseActive())
  }

  @Test
  fun stoppingQueuedStreamPreservesSubmittedActiveFinalAccounting() {
    val queue = PlaybackQueue(8)
    val state = PlaybackState(queue)
    val active = StreamKey("active", 1)
    val queued = StreamKey("queued", 2)
    val activeFinal = PlaybackChunk(active, 1, byteArrayOf(1, 2, 3, 4), true)
    val accounting = PlaybackLoopAccounting(initialHead = 10)
    val processor = PlaybackCommandProcessor(state, accounting)
    queue.offer(activeFinal)
    queue.offer(PlaybackChunk(queued, 2, byteArrayOf(5, 6), true))
    assertEquals(active, state.chooseActive())
    assertEquals(activeFinal, queue.pollFor(active))
    accounting.recordSubmitted(2)
    accounting.markFinal(activeFinal)

    val firstStop = processor.stop(listOf(queued), currentHead = 11)
    val duplicateStop = processor.stop(listOf(queued), currentHead = 11)

    assertFalse(firstStop.activeStopped)
    assertEquals(listOf(queued), firstStop.stoppedKeys)
    assertTrue(duplicateStop.stoppedKeys.isEmpty())
    accounting.observeHead(11)
    assertNull(accounting.takeConsumedFinal())
    accounting.observeHead(12)
    assertEquals(activeFinal, accounting.takeConsumedFinal())
    accounting.observeHead(13)
    assertNull(accounting.takeConsumedFinal())
  }

  @Test
  fun duplicateAndOverlappingStopsSharePhysicalCompletion() {
    val registry = StopOperationRegistry<String>()
    val active = StreamKey("active", 1)
    val queued = StreamKey("queued", 2)

    assertEquals(listOf(active), registry.register(listOf(active), "first").newlyPendingKeys)
    assertTrue(registry.register(listOf(active), "duplicate").newlyPendingKeys.isEmpty())
    assertEquals(
      listOf(queued),
      registry.register(listOf(active, queued), "global").newlyPendingKeys,
    )

    assertTrue(registry.complete(listOf(active)).containsAll(listOf("first", "duplicate")))
    assertEquals(listOf("global"), registry.complete(listOf(queued)))
    assertTrue(registry.register(listOf(active), "completed").resolveImmediately)
    assertTrue(registry.isIdle())
  }

  @Test
  fun timeoutRejectsEveryPendingWaiterAndLateCompletionSettlesNothing() {
    val registry = StopOperationRegistry<String>()
    val active = StreamKey("active", 1)
    registry.register(listOf(active), "first")
    registry.register(listOf(active), "duplicate")

    assertTrue(registry.fail().containsAll(listOf("first", "duplicate")))
    assertTrue(registry.complete(listOf(active)).isEmpty())
    assertTrue(registry.fail().isEmpty())
    assertTrue(registry.isIdle())
  }

  @Test
  fun nonFinalUnderrunEmitsOneIdleEdgeWithoutCompletingStream() {
    val gate = PlaybackVisualIdleGate()
    gate.onSubmitted()

    assertTrue(gate.shouldEmitIdle(false, playedFrames = 4, submittedFrames = 4, finalPending = false))
    assertFalse(gate.shouldEmitIdle(false, playedFrames = 4, submittedFrames = 4, finalPending = false))
    assertFalse(gate.shouldEmitIdle(true, playedFrames = 4, submittedFrames = 4, finalPending = false))
  }

  @Test
  fun finalPendingAndQueuedAudioDoNotEmitUnderrunIdle() {
    val gate = PlaybackVisualIdleGate()
    gate.onSubmitted()

    assertFalse(gate.shouldEmitIdle(false, playedFrames = 4, submittedFrames = 4, finalPending = true))
    assertFalse(gate.shouldEmitIdle(true, playedFrames = 4, submittedFrames = 4, finalPending = false))
  }

  @Test
  fun laterSubmissionRearmsVisualIdleAfterUnderrun() {
    val gate = PlaybackVisualIdleGate()
    gate.onSubmitted()
    assertTrue(gate.shouldEmitIdle(false, 4, 4, false))

    gate.onSubmitted()
    assertTrue(gate.shouldEmitIdle(false, 8, 8, false))
  }

  @Test
  fun playbackRmsUsesConsumedWindowAndClearsAtUnderrun() {
    val accounting = PlaybackLoopAccounting(initialHead = 0)
    accounting.recordSubmittedPcm(byteArrayOf(0, 64, 0, 64, 0, 0, 0, 0), 0, 8)
    accounting.observeHead(2)
    assertEquals(0.5, accounting.rmsAtPlayedFrames(2), 0.0001)
    accounting.observeHead(3)
    assertEquals(0.0, accounting.rmsAtPlayedFrames(1), 0.0001)
    accounting.observeHead(4)
    assertEquals(0.0, accounting.rmsAtPlayedFrames(2), 0.0001)
  }

  @Test
  fun longChunkRmsFollowsSilenceAndSoundAcrossWriteBoundaries() {
    val pcm = ByteArray(16384)
    for (index in 0 until 8192 step 2) pcm[index + 1] = 64
    val accounting = PlaybackLoopAccounting(0)
    for (offset in pcm.indices step 960) {
      accounting.recordSubmittedPcm(pcm, offset, minOf(960, pcm.size - offset))
    }
    accounting.observeHead(480)
    assertEquals(0.5, accounting.rmsAtPlayedFrames(64), 0.0001)
    accounting.observeHead(4200)
    assertEquals(0.0, accounting.rmsAtPlayedFrames(64), 0.0001)
    accounting.applyStop(true, 0)
    accounting.recordSubmittedPcm(byteArrayOf(0, 32, 0, 32, 0, 0), 0, 6)
    accounting.observeHead(2)
    assertEquals(0.25, accounting.rmsAtPlayedFrames(64), 0.0001)
  }

  @Test
  fun trailingWindowCrossesPcmChunksWithoutIncludingFutureSamples() {
    val accounting = PlaybackLoopAccounting(0)
    accounting.recordSubmittedPcm(byteArrayOf(0, 64, 0, 64), 0, 4)
    accounting.recordSubmittedPcm(byteArrayOf(0, 0, 0, 0), 0, 4)
    accounting.observeHead(3)
    assertEquals(kotlin.math.sqrt(0.125), accounting.rmsAtPlayedFrames(2), 0.0001)
  }
}
