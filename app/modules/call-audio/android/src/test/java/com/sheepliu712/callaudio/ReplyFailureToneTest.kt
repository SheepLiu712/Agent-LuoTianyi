package com.sheepliu712.callaudio

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ReplyFailureToneTest {
  @Test
  fun `cue is bounded non-silent 24 kHz mono pcm`() {
    val pcm = ReplyFailureTone.pcm24kMono()

    assertEquals(24_000 * 215 / 1_000 * 2, pcm.size)
    assertEquals(0, pcm.size % 2)
    assertTrue(pcm.any { it.toInt() != 0 })
  }

  @Test
  fun `cue amplitude is bounded and fades at both ends`() {
    val samples = ReplyFailureTone.pcm24kMono().toSamples()
    val peak = samples.maxOf { kotlin.math.abs(it.toInt()) }

    assertTrue(peak in 5_000..5_500)
    assertEquals(0, samples.first().toInt())
    assertTrue(kotlin.math.abs(samples[20].toInt()) < kotlin.math.abs(samples[120].toInt()))
    assertEquals(0, samples.last().toInt())
    assertTrue(kotlin.math.abs(samples[samples.lastIndex - 20].toInt()) < peak)
  }

  @Test
  fun `local identity cannot be mistaken for a server playback stream`() {
    val local = ReplyFailureToneIdentity.create(7)

    assertTrue(ReplyFailureToneIdentity.matches(local))
    assertFalse(ReplyFailureToneIdentity.matches(StreamKey("response-7", 7)))
    assertFalse(ReplyFailureToneIdentity.matches(StreamKey(local.responseId, 7)))
  }

  private fun ByteArray.toSamples(): List<Short> = indices
    .step(2)
    .map { index -> (((this[index + 1].toInt() and 0xff) shl 8) or (this[index].toInt() and 0xff)).toShort() }
}
