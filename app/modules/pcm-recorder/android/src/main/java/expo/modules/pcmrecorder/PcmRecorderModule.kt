package expo.modules.pcmrecorder

import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Base64
import expo.modules.kotlin.exception.CodedException
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import java.util.concurrent.atomic.AtomicBoolean

class PcmRecorderModule : Module() {
  private val stateLock = Any()
  private val running = AtomicBoolean(false)
  private var recorder: AudioRecord? = null
  private var recordingThread: Thread? = null

  override fun definition() = ModuleDefinition {
    Name("PcmRecorder")

    Events("pcmChunk", "recordingError")

    AsyncFunction<Boolean>("start") {
      startRecording()
    }

    AsyncFunction<Boolean>("stop") {
      stopRecording()
    }

    OnDestroy {
      stopRecording()
    }
  }

  private fun startRecording(): Boolean {
    if (running.get()) return true
    stopRecording()

    synchronized(stateLock) {
      if (running.get()) return true

      val minBufferSize = AudioRecord.getMinBufferSize(
        SAMPLE_RATE,
        AudioFormat.CHANNEL_IN_MONO,
        AudioFormat.ENCODING_PCM_16BIT,
      )
      if (minBufferSize <= 0) {
        throw PcmRecorderStartException("Android AudioRecord did not provide a valid buffer size")
      }

      val newRecorder = try {
        AudioRecord(
          MediaRecorder.AudioSource.VOICE_RECOGNITION,
          SAMPLE_RATE,
          AudioFormat.CHANNEL_IN_MONO,
          AudioFormat.ENCODING_PCM_16BIT,
          maxOf(minBufferSize, READ_BUFFER_SIZE),
        )
      } catch (error: Throwable) {
        throw PcmRecorderStartException("Unable to create Android AudioRecord", error)
      }

      if (newRecorder.state != AudioRecord.STATE_INITIALIZED) {
        newRecorder.release()
        throw PcmRecorderStartException("Android AudioRecord failed to initialize")
      }

      try {
        newRecorder.startRecording()
      } catch (error: Throwable) {
        newRecorder.release()
        throw PcmRecorderStartException("Unable to start Android AudioRecord", error)
      }

      recorder = newRecorder
      running.set(true)
      recordingThread = Thread(
        { captureLoop(newRecorder) },
        "PcmRecorder-Capture",
      ).also { it.start() }
    }
    return true
  }

  private fun captureLoop(activeRecorder: AudioRecord) {
    val buffer = ByteArray(READ_BUFFER_SIZE)
    var sequence = 0
    try {
      while (running.get() && recorder === activeRecorder) {
        val count = activeRecorder.read(buffer, 0, buffer.size)
        if (count > 0) {
          sendEvent(
            "pcmChunk",
            mapOf(
              "audio" to Base64.encodeToString(buffer.copyOf(count), Base64.NO_WRAP),
              "seq" to sequence++,
            ),
          )
        } else if (count < 0 && running.get()) {
          sendRecordingError("AudioRecord.read failed with code $count")
          break
        }
      }
    } catch (error: Throwable) {
      if (running.get()) {
        sendRecordingError(error.message ?: "Unexpected PCM capture failure")
      }
    } finally {
      running.set(false)
      synchronized(stateLock) {
        if (recorder === activeRecorder) {
          releaseRecorder(activeRecorder)
          recorder = null
        }
        if (recordingThread === Thread.currentThread()) {
          recordingThread = null
        }
      }
    }
  }

  private fun stopRecording(): Boolean {
    val activeRecorder: AudioRecord?
    val activeThread: Thread?
    synchronized(stateLock) {
      running.set(false)
      activeRecorder = recorder
      activeThread = recordingThread
      try {
        activeRecorder?.stop()
      } catch (_: IllegalStateException) {
        // The capture thread may already have stopped the recorder.
      }
    }

    if (activeThread != null && activeThread !== Thread.currentThread()) {
      try {
        activeThread.join(STOP_JOIN_TIMEOUT_MS)
      } catch (_: InterruptedException) {
        Thread.currentThread().interrupt()
      }
    }

    synchronized(stateLock) {
      if (recorder === activeRecorder) {
        activeRecorder?.release()
        recorder = null
      }
      if (recordingThread === activeThread) {
        recordingThread = null
      }
    }
    return true
  }

  private fun releaseRecorder(activeRecorder: AudioRecord) {
    try {
      if (activeRecorder.recordingState == AudioRecord.RECORDSTATE_RECORDING) {
        activeRecorder.stop()
      }
    } catch (_: IllegalStateException) {
      // Already stopped.
    }
    activeRecorder.release()
  }

  private fun sendRecordingError(message: String) {
    sendEvent(
      "recordingError",
      mapOf(
        "code" to "PCM_CAPTURE_FAILED",
        "message" to message,
      ),
    )
  }

  companion object {
    private const val SAMPLE_RATE = 16_000
    private const val READ_BUFFER_SIZE = 2_048
    private const val STOP_JOIN_TIMEOUT_MS = 500L
  }
}

private class PcmRecorderStartException(
  message: String,
  cause: Throwable? = null,
) : CodedException("PCM_START_FAILED", message, cause)
