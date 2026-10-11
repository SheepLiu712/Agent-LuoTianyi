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
    assertNull(accounting.recordPlaybackHead(11))
    assertEquals(activeFinal, accounting.recordPlaybackHead(12))
    assertNull(accounting.recordPlaybackHead(13))
  }

  @Test
  fun timedOutWorkerBlocksRestartAndCannotBecomeNewGeneration() {
    val ownership = WorkerOwnership()
    ownership.markStopResult(stopped = false)

    assertFalse(ownership.canStart())
    assertFalse(ownership.accepts(eventGeneration = 1, currentGeneration = 2))
    assertFalse(ownership.accepts(eventGeneration = 2, currentGeneration = 2))
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
}
