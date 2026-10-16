package com.sheepliu712.callaudio

import kotlin.math.PI
import kotlin.math.sin

internal object ReplyFailureToneIdentity {
  private const val RESPONSE_PREFIX = "__local_reply_failure_tone__"
  private const val STREAM_ID = -1

  fun create(generation: Long): StreamKey = StreamKey("$RESPONSE_PREFIX$generation", STREAM_ID)

  fun matches(key: StreamKey): Boolean = key.responseId.startsWith(RESPONSE_PREFIX) && key.streamId == STREAM_ID
}

/** Original offline cue rendered into the call AudioTrack; no external asset or network is used. */
internal object ReplyFailureTone {
  private const val SAMPLE_RATE = 24_000
  private const val TONE_MILLIS = 90
  private const val GAP_MILLIS = 35
  private const val AMPLITUDE = 5_500

  fun pcm24kMono(): ByteArray {
    val first = tone(520.0, TONE_MILLIS)
    val gap = ByteArray(SAMPLE_RATE * GAP_MILLIS / 1_000 * 2)
    val second = tone(390.0, TONE_MILLIS)
    return first + gap + second
  }

  private fun tone(frequencyHz: Double, durationMillis: Int): ByteArray {
    val sampleCount = SAMPLE_RATE * durationMillis / 1_000
    val output = ByteArray(sampleCount * 2)
    for (index in 0 until sampleCount) {
      val envelope = minOf(index / 120.0, (sampleCount - index - 1) / 120.0, 1.0).coerceAtLeast(0.0)
      val sample = (sin(2.0 * PI * frequencyHz * index / SAMPLE_RATE) * AMPLITUDE * envelope).toInt()
      output[index * 2] = (sample and 0xff).toByte()
      output[index * 2 + 1] = ((sample shr 8) and 0xff).toByte()
    }
    return output
  }
}
