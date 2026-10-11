package com.sheepliu712.callaudio

import android.Manifest
import android.app.Activity
import android.app.Application
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioDeviceCallback
import android.media.AudioDeviceInfo
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioFocusRequest
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.NoiseSuppressor
import android.os.Bundle
import android.os.Build
import android.util.Base64
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import expo.modules.kotlin.Promise
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong

private const val CAPTURE_RATE = 16_000
private const val PLAYBACK_RATE = 24_000
private const val CHANNELS = 1
private const val MAX_CAPTURE_BUFFER_BYTES = CAPTURE_RATE * 2 * 3
private const val MAX_PLAYBACK_BUFFER_BYTES = PLAYBACK_RATE * 2 * 4
private const val MAX_CAPTURE_IN_FLIGHT = 30

class CallAudioModule : Module(), Application.ActivityLifecycleCallbacks {
  private val captureRunning = AtomicBoolean(false)
  private val playbackRunning = AtomicBoolean(false)
  private val generation = AtomicLong(0)
  private val sessionGeneration = AtomicLong(0)
  private val workerOwnership = WorkerOwnership()
  @Volatile private var sessionTerminationFailed = false
  private val captureSequence = AtomicLong(0)
  private val streamGenerations = ConcurrentHashMap<StreamKey, Long>()
  private val tombstonedStreams = ConcurrentHashMap.newKeySet<StreamKey>()
  private val queue = PlaybackQueue(MAX_PLAYBACK_BUFFER_BYTES)
  private val playbackState = PlaybackState(queue)
  private var captureThread: Thread? = null
  private var playbackThread: Thread? = null
  private var sessionReady = false
  private var audioRecord: AudioRecord? = null
  private var audioTrack: AudioTrack? = null
  private var echoCanceler: AcousticEchoCanceler? = null
  private var noiseSuppressor: NoiseSuppressor? = null
  private var aecStatus: Pair<Boolean, String?> = false to "aec_not_initialized"
  private var noiseSuppressorStatus: Pair<Boolean, String?> = false to "noise_suppressor_not_initialized"
  private var audioFocusRequest: AudioFocusRequest? = null
  private var legacyAudioFocusListener: AudioManager.OnAudioFocusChangeListener? = null
  private var audioFocusGranted = false
  private var originalAudioMode: Int? = null
  private var routeCallback: AudioDeviceCallback? = null
  private val playbackCommandLock = java.lang.Object()
  private val playbackCommands = ArrayDeque<PlaybackCommand>()
  private var stopOperations = StopOperationRegistry<Promise>()
  private val captureInFlight = ConcurrentHashMap.newKeySet<Long>()
  private var resumedActivities = 0
  private var lifecycleRegistered = false

  override fun definition() = ModuleDefinition {
    Name("CallAudio")
    Events(
      "onCapturedAudio",
      "onPlaybackCompleted",
      "onPlaybackStopped",
      "onAudioFailure",
      "onLifecycle",
      "onRouteChanged",
    )

    AsyncFunction("getCapability") { probeCapability() }
    AsyncFunction("startSession") { startSession() }
    AsyncFunction("stopSession") { closeSession() }
    AsyncFunction("startCapture") { startCapture() }
    AsyncFunction("stopCapture") { stopCapture() }
    AsyncFunction("acknowledgeCapturedAudio") { deviceSequence: Long, eventSessionGeneration: Long ->
      if (eventSessionGeneration == sessionGeneration.get()) captureInFlight.remove(deviceSequence)
    }
    AsyncFunction("enqueuePlayback") {
        responseId: String,
        streamId: Int,
        payloadBase64: String,
        isFinal: Boolean,
      ->
      enqueuePlayback(responseId, streamId, payloadBase64, isFinal)
    }
    AsyncFunction("stopPlayback") { responseId: String?, streamId: Int?, promise: Promise ->
      stopPlayback(responseId, streamId, promise)
    }
    AsyncFunction("tombstone") { responseId: String, streamId: Int, promise: Promise ->
      stopPlayback(responseId, streamId, promise)
    }

    OnDestroy { closeSession() }
  }

  private fun startSession(): Map<String, Any?> {
    if (sessionTerminationFailed || !workerOwnership.canStart()) {
      return capability(false, "session_termination_failed")
    }
    if (sessionReady) return capability(true, null)
    val currentSessionGeneration = sessionGeneration.incrementAndGet()
    resetSessionState()
    try {
      val context = requireContext()
      if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
        return capability(false, "permission_denied")
      }
      val captureInitializationError = initializeCaptureDevice()
      if (captureInitializationError != null) throw SessionInitializationException(captureInitializationError)
      registerLifecycle(context)
      val manager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
      if (originalAudioMode == null) originalAudioMode = manager.mode
      manager.mode = AudioManager.MODE_IN_COMMUNICATION
      val focusError = requestAudioFocus(manager, currentSessionGeneration)
      if (focusError != null) throw SessionInitializationException(focusError)
      registerRouteCallback(manager, currentSessionGeneration)
      startPlayback()
    } catch (error: Exception) {
      val rollbackSucceeded = rollbackSessionInitialization()
      val code = when (error) {
        is SessionInitializationException -> error.code
        is SecurityException -> "permission_denied"
        else -> "session_initialization_failed"
      }
      return capability(false, if (rollbackSucceeded) code else "session_termination_failed")
    }
    sessionReady = true
    return capability(true, null)
  }

  private fun probeCapability(): Map<String, Any?> {
    if (sessionTerminationFailed) return capability(false, "session_termination_failed")
    val context = requireContext()
    if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
      return capability(false, "permission_denied")
    }
    if (sessionReady) return capability(true, null)
    val captureMin = AudioRecord.getMinBufferSize(
      CAPTURE_RATE,
      AudioFormat.CHANNEL_IN_MONO,
      AudioFormat.ENCODING_PCM_16BIT,
    )
    val playbackMin = AudioTrack.getMinBufferSize(
      PLAYBACK_RATE,
      AudioFormat.CHANNEL_OUT_MONO,
      AudioFormat.ENCODING_PCM_16BIT,
    )
    if (captureMin <= 0 || playbackMin <= 0) return capability(false, "required_format_unavailable")
    return capability(false, "not_initialized")
  }

  private fun startCapture(): Map<String, Any?> {
    if (sessionTerminationFailed) return capability(false, "session_termination_failed")
    val context = requireContext()
    if (!sessionReady) return capability(false, "session_not_initialized")
    if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
      return capability(false, "permission_denied")
    }
    if (captureRunning.get()) return capability(true, null)
    if (audioRecord == null) {
      val captureInitializationError = initializeCaptureDevice()
      if (captureInitializationError != null) {
        releaseCapture()
        return capability(false, captureInitializationError)
      }
    }

    val record = audioRecord ?: return capability(false, "capture_initialization_failed")
    try {
      record.startRecording()
    } catch (_: IllegalStateException) {
      releaseCapture()
      return capability(false, "capture_start_failed")
    } catch (_: SecurityException) {
      releaseCapture()
      return capability(false, "permission_denied")
    }
    if (record.recordingState != AudioRecord.RECORDSTATE_RECORDING) {
      releaseCapture()
      return capability(false, "capture_start_failed")
    }
    captureRunning.set(true)
    val eventSessionGeneration = sessionGeneration.get()
    captureThread = Thread(
      { captureLoop(record, eventSessionGeneration) },
      "CallAudioCapture-$eventSessionGeneration",
    ).apply { start() }
    return capability(true, null)
  }

  private fun initializeCaptureDevice(): String? {
    val minBytes = AudioRecord.getMinBufferSize(
      CAPTURE_RATE,
      AudioFormat.CHANNEL_IN_MONO,
      AudioFormat.ENCODING_PCM_16BIT,
    )
    if (minBytes <= 0 || minBytes > MAX_CAPTURE_BUFFER_BYTES) return "capture_format_unavailable"
    val record = try {
      AudioRecord(
        MediaRecorder.AudioSource.VOICE_COMMUNICATION,
        CAPTURE_RATE,
        AudioFormat.CHANNEL_IN_MONO,
        AudioFormat.ENCODING_PCM_16BIT,
        minOf(MAX_CAPTURE_BUFFER_BYTES, maxOf(minBytes * 2, 3200)),
      )
    } catch (_: IllegalArgumentException) {
      return "capture_initialization_failed"
    } catch (_: SecurityException) {
      return "permission_denied"
    }
    if (record.state != AudioRecord.STATE_INITIALIZED || record.sampleRate != CAPTURE_RATE) {
      record.release()
      return "capture_initialization_failed"
    }
    audioRecord = record
    aecStatus = enableAec(record.audioSessionId)
    noiseSuppressorStatus = enableNoiseSuppressor(record.audioSessionId)
    return when {
      !aecStatus.first -> aecStatus.second ?: "aec_initialization_failed"
      !noiseSuppressorStatus.first -> noiseSuppressorStatus.second ?: "noise_suppressor_initialization_failed"
      else -> null
    }
  }

  private fun captureLoop(record: AudioRecord, eventSessionGeneration: Long) {
    val buffer = ByteArray(3200)
    while (captureRunning.get()) {
      val read = record.read(buffer, 0, buffer.size, AudioRecord.READ_BLOCKING)
      if (read > 0) {
        val deviceSequence = captureSequence.incrementAndGet()
        if (captureInFlight.size >= MAX_CAPTURE_IN_FLIGHT) {
          failure("capture_bridge_backpressure", "capture", eventSessionGeneration)
          captureRunning.set(false)
          break
        }
        captureInFlight.add(deviceSequence)
        sendEvent(
          "onCapturedAudio",
          mapOf(
            "deviceSequence" to deviceSequence,
            "sessionGeneration" to eventSessionGeneration,
            "payloadBase64" to Base64.encodeToString(buffer, 0, read, Base64.NO_WRAP),
            "format" to format(CAPTURE_RATE),
          ),
        )
      } else if (read < 0 && captureRunning.get()) {
        failure("capture_read_failed", "capture", eventSessionGeneration)
        captureRunning.set(false)
      }
    }
  }

  private fun stopCapture() {
    captureRunning.set(false)
    try {
      audioRecord?.stop()
    } catch (_: RuntimeException) {
      // The worker stop/join result below remains authoritative.
    }
    captureThread?.interrupt()
    val thread = captureThread
    thread?.join(250)
    if (thread?.isAlive == true) {
      markTerminationFailed("capture_stop_timeout", sessionGeneration.get())
      return
    }
    captureThread = null
    releaseCapture()
  }

  private fun releaseCapture() {
    echoCanceler?.release()
    echoCanceler = null
    noiseSuppressor?.release()
    noiseSuppressor = null
    aecStatus = false to "aec_not_initialized"
    noiseSuppressorStatus = false to "noise_suppressor_not_initialized"
    audioRecord?.release()
    audioRecord = null
  }

  private fun startPlayback() {
    if (sessionTerminationFailed) throw IllegalStateException("session_termination_failed")
    if (playbackRunning.get()) return
    val minBytes = AudioTrack.getMinBufferSize(
      PLAYBACK_RATE,
      AudioFormat.CHANNEL_OUT_MONO,
      AudioFormat.ENCODING_PCM_16BIT,
    )
    if (minBytes <= 0) throw IllegalStateException("playback_format_unavailable")
    val track = AudioTrack.Builder()
      .setAudioAttributes(
        AudioAttributes.Builder()
          .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
          .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
          .build(),
      )
      .setAudioFormat(
        AudioFormat.Builder()
          .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
          .setSampleRate(PLAYBACK_RATE)
          .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
          .build(),
      )
      .setBufferSizeInBytes(maxOf(minBytes * 2, 4800))
      .setTransferMode(AudioTrack.MODE_STREAM)
      .build()
    if (track.state != AudioTrack.STATE_INITIALIZED || track.sampleRate != PLAYBACK_RATE) {
      track.release()
      throw IllegalStateException("playback_initialization_failed")
    }
    audioTrack = track
    track.play()
    playbackRunning.set(true)
    val eventSessionGeneration = sessionGeneration.get()
    playbackThread = Thread(
      { playbackLoop(track, eventSessionGeneration) },
      "CallAudioPlayback-$eventSessionGeneration",
    ).apply { start() }
  }

  private fun enqueuePlayback(
    responseId: String,
    streamId: Int,
    payloadBase64: String,
    isFinal: Boolean,
  ): Long {
    check(!sessionTerminationFailed) { "session_termination_failed" }
    check(sessionReady) { "session_not_initialized" }
    val payload = try {
      Base64.decode(payloadBase64, Base64.DEFAULT)
    } catch (_: IllegalArgumentException) {
      throw IllegalArgumentException("invalid_base64")
    }
    require(payload.isNotEmpty() && payload.size % 2 == 0) { "invalid_pcm_payload" }
    val key = StreamKey(responseId, streamId)
    check(!tombstonedStreams.contains(key)) { "playback_stream_tombstoned" }
    val currentGeneration = streamGenerations.computeIfAbsent(key) { generation.incrementAndGet() }
    check(queue.offer(PlaybackChunk(key, currentGeneration, payload, isFinal))) {
      "playback_buffer_full"
    }
    return currentGeneration
  }

  private fun playbackLoop(track: AudioTrack, eventSessionGeneration: Long) {
    val accounting = PlaybackLoopAccounting(track.playbackHeadPosition.toLong() and 0xffffffffL)
    val commandProcessor = PlaybackCommandProcessor(playbackState, accounting)
    while (playbackRunning.get() || hasPlaybackCommands()) {
      val command = synchronized(playbackCommandLock) {
        if (playbackCommands.isEmpty()) null else playbackCommands.removeFirst()
      }
      if (command != null) {
        val outcome = commandProcessor.stop(
          command.keys,
          track.playbackHeadPosition.toLong() and 0xffffffffL,
        )
        if (outcome.activeStopped) {
          track.pause()
          track.flush()
          if (playbackRunning.get()) track.play()
          accounting.applyStop(true, track.playbackHeadPosition.toLong() and 0xffffffffL)
        }
        outcome.stoppedKeys.forEach { emitStoppedReceipt(it, command.generation, eventSessionGeneration) }
        stopOperations.complete(outcome.stoppedKeys).forEach { it.resolve(null) }
      }

      val active = playbackState.chooseActive()
      val chunk = if (active != null && accounting.finalTarget == null) queue.pollFor(active) else null
      if (chunk == null) {
        Thread.sleep(5)
      }
      if (chunk != null && isCurrent(chunk)) {
        var offset = 0
        while (offset < chunk.payload.size && playbackRunning.get() && isCurrent(chunk)) {
          val writeBytes = minOf(960, chunk.payload.size - offset)
          val written = track.write(chunk.payload, offset, writeBytes, AudioTrack.WRITE_BLOCKING)
          if (written <= 0) {
            failure("playback_write_failed", "playback", eventSessionGeneration)
            break
          }
          offset += written
          accounting.recordSubmitted(written / 2L)
        }
        if (offset == chunk.payload.size && chunk.isFinal && isCurrent(chunk)) {
          accounting.markFinal(chunk)
        }
      }

      val currentHead = track.playbackHeadPosition.toLong() and 0xffffffffL
      accounting.observeHead(currentHead)
      accounting.finalTarget?.first?.let { finalChunk ->
        if (!isCurrent(finalChunk)) accounting.discardStaleFinal()
        else accounting.takeConsumedFinal()?.let { consumedFinal ->
          completion(consumedFinal, eventSessionGeneration)
          playbackState.complete(finalChunk.key)
          accounting.complete(track.playbackHeadPosition.toLong() and 0xffffffffL)
        }
      }
    }
  }

  private fun completion(chunk: PlaybackChunk, eventSessionGeneration: Long) {
    sendEvent(
      "onPlaybackCompleted",
      mapOf(
        "responseId" to chunk.key.responseId,
        "streamId" to chunk.key.streamId,
        "generation" to chunk.generation,
        "sessionGeneration" to eventSessionGeneration,
      ),
    )
  }

  private fun stopPlayback(responseId: String?, streamId: Int?, promise: Promise) {
    if (sessionTerminationFailed) {
      promise.reject("ERR_CALL_AUDIO_TERMINATION_FAILED", "session_termination_failed", null)
      return
    }
    val requestedKeys = if (responseId != null && streamId != null) {
      listOf(StreamKey(responseId, streamId))
    } else {
      streamGenerations.keys.toList()
    }
    val registration = stopOperations.register(requestedKeys, promise)
    if (registration.resolveImmediately) {
      promise.resolve(null)
      return
    }
    val keys = registration.newlyPendingKeys
    if (keys.isEmpty()) return
    if (playbackThread?.isAlive != true) {
      stopOperations.cancelRegistration(promise)
      promise.reject("ERR_CALL_AUDIO_PLAYBACK_UNAVAILABLE", "playback_worker_unavailable", null)
      return
    }
    val stoppedGeneration = generation.incrementAndGet()
    keys.forEach {
      tombstonedStreams.add(it)
      streamGenerations[it] = stoppedGeneration
    }
    synchronized(playbackCommandLock) {
      playbackCommands.addLast(PlaybackCommand(keys, stoppedGeneration))
    }
    queue.wake()
  }

  private fun isCurrent(chunk: PlaybackChunk): Boolean = streamGenerations[chunk.key] == chunk.generation

  private fun hasPlaybackCommands(): Boolean = synchronized(playbackCommandLock) {
    playbackCommands.isNotEmpty()
  }

  private fun emitStoppedReceipt(key: StreamKey, stoppedGeneration: Long, eventSessionGeneration: Long) = sendEvent(
    "onPlaybackStopped",
    mapOf(
      "responseId" to key.responseId,
      "streamId" to key.streamId,
      "generation" to stoppedGeneration,
      "sessionGeneration" to eventSessionGeneration,
    ),
  )

  private fun closeSession() {
    stopCapture()
    if (captureThread?.isAlive == true) {
      cleanupSessionSideEffects()
      throw IllegalStateException("session_termination_failed")
    }
    playbackRunning.set(false)
    queue.clear()
    queue.wake()
    val thread = playbackThread
    thread?.join(250)
    if (thread?.isAlive == true) {
      markTerminationFailed("playback_stop_timeout", sessionGeneration.get())
      cleanupSessionSideEffects()
      throw IllegalStateException("session_termination_failed")
    }
    playbackThread = null
    try {
      audioTrack?.stop()
    } catch (_: RuntimeException) {
      // Track is released only after its worker has terminated.
    }
    audioTrack?.release()
    audioTrack = null
    cleanupSessionSideEffects()
    sessionReady = false
    check(stopOperations.isIdle()) { "playback_stop_operations_pending" }
    resetSessionState()
  }

  private fun capability(
    available: Boolean,
    reason: String?,
  ): Map<String, Any?> = mapOf(
    "available" to available,
    "reason" to reason,
    "captureFormat" to if (available) format(CAPTURE_RATE) else null,
    "playbackFormat" to if (available) format(PLAYBACK_RATE) else null,
    "aec" to mapOf(
      "available" to AcousticEchoCanceler.isAvailable(),
      "enabled" to aecStatus.first,
      "error" to aecStatus.second,
    ),
    "noiseSuppressor" to mapOf(
      "available" to NoiseSuppressor.isAvailable(),
      "enabled" to noiseSuppressorStatus.first,
      "error" to noiseSuppressorStatus.second,
    ),
    "audioFocus" to mapOf(
      "granted" to audioFocusGranted,
      "error" to if (audioFocusGranted) null else "audio_focus_not_granted",
    ),
    "sessionGeneration" to sessionGeneration.get(),
  )

  private fun enableAec(audioSessionId: Int): Pair<Boolean, String?> {
    if (!AcousticEchoCanceler.isAvailable()) return false to "aec_unavailable"
    val effect = AcousticEchoCanceler.create(audioSessionId)
      ?: return false to "aec_create_failed"
    echoCanceler = effect
    val result = effect.setEnabled(true)
    return if (result == 0 && effect.enabled) true to null else false to "aec_enable_failed"
  }

  private fun enableNoiseSuppressor(audioSessionId: Int): Pair<Boolean, String?> {
    if (!NoiseSuppressor.isAvailable()) return false to "noise_suppressor_unavailable"
    val effect = NoiseSuppressor.create(audioSessionId) ?: return false to "noise_suppressor_create_failed"
    noiseSuppressor = effect
    val result = effect.setEnabled(true)
    return if (result == 0 && effect.enabled) true to null else false to "noise_suppressor_enable_failed"
  }

  private fun requestAudioFocus(manager: AudioManager, eventSessionGeneration: Long): String? {
    val listener = AudioManager.OnAudioFocusChangeListener { change ->
      if (change < 0) {
        failure("audio_focus_lost", "session", eventSessionGeneration)
      }
    }
    legacyAudioFocusListener = listener
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
      @Suppress("DEPRECATION")
      val result = manager.requestAudioFocus(
        listener,
        AudioManager.STREAM_VOICE_CALL,
        AudioManager.AUDIOFOCUS_GAIN_TRANSIENT,
      )
      audioFocusGranted = result == AudioManager.AUDIOFOCUS_REQUEST_GRANTED
      return if (audioFocusGranted) null else "audio_focus_denied"
    }
    val request = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_EXCLUSIVE)
      .setAudioAttributes(
        AudioAttributes.Builder()
          .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
          .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
          .build(),
      )
      .setOnAudioFocusChangeListener(listener)
      .build()
    audioFocusRequest = request
    audioFocusGranted = manager.requestAudioFocus(request) == AudioManager.AUDIOFOCUS_REQUEST_GRANTED
    return if (audioFocusGranted) null else "audio_focus_denied"
  }

  private fun abandonAudioFocus() {
    val context = appContext.reactContext
    if (context == null) {
      audioFocusRequest = null
      legacyAudioFocusListener = null
      audioFocusGranted = false
      return
    }
    val manager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
    val request = audioFocusRequest
    val listener = legacyAudioFocusListener
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && request != null) {
      manager.abandonAudioFocusRequest(request)
    } else if (listener != null) {
      @Suppress("DEPRECATION")
      manager.abandonAudioFocus(listener)
    }
    audioFocusRequest = null
    legacyAudioFocusListener = null
    audioFocusGranted = false
  }

  private fun rollbackSessionInitialization(): Boolean {
    playbackRunning.set(false)
    queue.wake()
    val thread = playbackThread
    thread?.join(250)
    if (thread?.isAlive == true) {
      markTerminationFailed("playback_stop_timeout", sessionGeneration.get())
      releaseCapture()
      cleanupSessionSideEffects()
      return false
    }
    playbackThread = null
    try {
      audioTrack?.stop()
    } catch (_: RuntimeException) {
      // Track is released only after its worker has terminated.
    }
    audioTrack?.release()
    audioTrack = null
    releaseCapture()
    cleanupSessionSideEffects()
    sessionReady = false
    return true
  }

  private fun markTerminationFailed(code: String, eventSessionGeneration: Long) {
    sessionTerminationFailed = true
    workerOwnership.markStopResult(stopped = false)
    sessionReady = false
    synchronized(playbackCommandLock) { playbackCommands.clear() }
    stopOperations.fail().forEach {
      it.reject("ERR_CALL_AUDIO_TERMINATION_FAILED", "session_termination_failed", null)
    }
    failure(code, "session", eventSessionGeneration)
  }

  private fun cleanupSessionSideEffects() {
    try {
      unregisterRouteCallback()
    } catch (_: RuntimeException) {
      routeCallback = null
    }
    try {
      abandonAudioFocus()
    } catch (_: RuntimeException) {
      audioFocusRequest = null
      legacyAudioFocusListener = null
      audioFocusGranted = false
    }
    try {
      restoreAudioMode()
    } catch (_: RuntimeException) {
      originalAudioMode = null
    }
    try {
      unregisterLifecycle()
    } catch (_: RuntimeException) {
      lifecycleRegistered = false
    }
  }

  private fun resetSessionState() {
    streamGenerations.clear()
    tombstonedStreams.clear()
    captureInFlight.clear()
    playbackState.reset()
    synchronized(playbackCommandLock) { playbackCommands.clear() }
    stopOperations = StopOperationRegistry()
    generation.set(0)
    captureSequence.set(0)
  }

  private fun format(sampleRate: Int): Map<String, Any> = mapOf(
    "encoding" to "pcm_s16le",
    "sampleRateHz" to sampleRate,
    "channels" to CHANNELS,
  )

  private fun failure(code: String, operation: String, eventSessionGeneration: Long) {
    sendEvent("onAudioFailure", mapOf(
      "code" to code,
      "operation" to operation,
      "sessionGeneration" to eventSessionGeneration,
    ))
  }

  private fun requireContext(): Context =
    appContext.reactContext ?: throw IllegalStateException("react_context_unavailable")

  private fun registerLifecycle(context: Context) {
    if (lifecycleRegistered) return
    (context.applicationContext as Application).registerActivityLifecycleCallbacks(this)
    lifecycleRegistered = true
  }

  private fun unregisterLifecycle() {
    if (!lifecycleRegistered) return
    val context = appContext.reactContext ?: return
    (context.applicationContext as Application).unregisterActivityLifecycleCallbacks(this)
    lifecycleRegistered = false
  }

  private fun registerRouteCallback(manager: AudioManager, eventSessionGeneration: Long) {
    if (routeCallback != null) return
    routeCallback = object : AudioDeviceCallback() {
        override fun onAudioDevicesAdded(addedDevices: Array<out AudioDeviceInfo>) = emitRoutes(manager, eventSessionGeneration)
        override fun onAudioDevicesRemoved(removedDevices: Array<out AudioDeviceInfo>) = emitRoutes(manager, eventSessionGeneration)
      }
    manager.registerAudioDeviceCallback(routeCallback, null)
    emitRoutes(manager, eventSessionGeneration)
  }

  private fun unregisterRouteCallback() {
    val callback = routeCallback ?: return
    val context = appContext.reactContext ?: return
    (context.getSystemService(Context.AUDIO_SERVICE) as AudioManager).unregisterAudioDeviceCallback(callback)
    routeCallback = null
  }

  private fun emitRoutes(manager: AudioManager, eventSessionGeneration: Long) {
    val outputs = manager.getDevices(AudioManager.GET_DEVICES_OUTPUTS).map { deviceType(it.type) }
    sendEvent("onRouteChanged", mapOf("outputs" to outputs, "sessionGeneration" to eventSessionGeneration))
  }

  private fun deviceType(type: Int): String = when (type) {
    AudioDeviceInfo.TYPE_BLUETOOTH_A2DP -> "bluetooth_a2dp"
    AudioDeviceInfo.TYPE_BLUETOOTH_SCO -> "bluetooth_sco"
    AudioDeviceInfo.TYPE_WIRED_HEADPHONES, AudioDeviceInfo.TYPE_WIRED_HEADSET -> "wired_headset"
    AudioDeviceInfo.TYPE_BUILTIN_EARPIECE -> "earpiece"
    AudioDeviceInfo.TYPE_BUILTIN_SPEAKER -> "speaker"
    else -> "other"
  }

  private fun restoreAudioMode() {
    val context = appContext.reactContext ?: return
    val previous = originalAudioMode ?: return
    (context.getSystemService(Context.AUDIO_SERVICE) as AudioManager).mode = previous
    originalAudioMode = null
  }

  override fun onActivityResumed(activity: Activity) { resumedActivities += 1 }
  override fun onActivityPaused(activity: Activity) {
    resumedActivities = maxOf(0, resumedActivities - 1)
    if (resumedActivities == 0) sendEvent("onLifecycle", mapOf(
      "state" to "background",
      "sessionGeneration" to sessionGeneration.get(),
    ))
  }
  override fun onActivityCreated(activity: Activity, state: Bundle?) = Unit
  override fun onActivityStarted(activity: Activity) = Unit
  override fun onActivityStopped(activity: Activity) = Unit
  override fun onActivitySaveInstanceState(activity: Activity, state: Bundle) = Unit
  override fun onActivityDestroyed(activity: Activity) = Unit
}

private data class PlaybackCommand(
  val keys: List<StreamKey>,
  val generation: Long,
)

private class SessionInitializationException(val code: String) : Exception(code)
