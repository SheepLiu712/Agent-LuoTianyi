(function attachAudioStreamPlayer(root, factory) {
  const exports = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = exports;
  }
  if (root) {
    root.createLive2DAudioStreamPlayer = exports.createLive2DAudioStreamPlayer;
  }
})(typeof window !== 'undefined' ? window : globalThis, function audioStreamPlayerFactory() {
  const STREAM_TYPES = new Set(['chat', 'call']);

  function createState() {
    return {
      sampleRate: 44100,
      channels: 1,
      nextStartTime: 0,
      items: new Map(),
      cancelledResponseIds: new Set(),
      checkScheduled: false,
    };
  }

  function createLive2DAudioStreamPlayer(options) {
    const audioContext = options.audioContext;
    const analyser = options.analyser;
    const postMessage = options.postMessage;
    const requestFrame = options.requestFrame || ((callback) => requestAnimationFrame(callback));
    const decodeBase64 = options.decodeBase64 || ((value) => {
      const binary = atob(value);
      const bytes = new Uint8Array(binary.length);
      for (let index = 0; index < binary.length; index += 1) {
        bytes[index] = binary.charCodeAt(index);
      }
      return bytes;
    });
    const states = {
      chat: createState(),
      call: createState(),
    };

    function requireStreamType(value) {
      if (!STREAM_TYPES.has(value)) {
        throw new Error(`Unsupported audio stream_type: ${String(value)}`);
      }
      return value;
    }

    function requireAudioId(packet) {
      if (typeof packet.audio_id !== 'string' || packet.audio_id.length === 0) {
        throw new Error(`${packet.stream_type} audio packet requires audio_id`);
      }
      return packet.audio_id;
    }

    function getOrCreateItem(state, packet) {
      const audioId = requireAudioId(packet);
      let item = state.items.get(audioId);
      if (!item) {
        item = {
          audioId,
          responseId: packet.response_id || null,
          sources: new Set(),
          final: false,
          terminal: null,
          endTime: audioContext.currentTime,
        };
        state.items.set(audioId, item);
      } else if (packet.response_id) {
        item.responseId = packet.response_id;
      }
      return item;
    }

    function hasActiveSources(state) {
      for (const item of state.items.values()) {
        if (item.sources.size > 0) return true;
      }
      return false;
    }

    function resetTimelineIfIdle(state) {
      if (!hasActiveSources(state)) {
        state.nextStartTime = 0;
      }
    }

    function emitFinished(streamType, state, item) {
      if (item.terminal) return;
      item.terminal = 'finished';
      state.items.delete(item.audioId);
      postMessage({
        type: 'audio_finished',
        stream_type: streamType,
        audio_id: item.audioId,
        response_id: item.responseId,
      });
      resetTimelineIfIdle(state);
    }

    function checkFinalItems(streamType) {
      const state = states[streamType];
      state.checkScheduled = false;
      let needsFallback = false;
      for (const item of state.items.values()) {
        if (!item.final || item.terminal) continue;
        if (item.sources.size === 0 || audioContext.currentTime >= item.endTime) {
          emitFinished(streamType, state, item);
        } else {
          needsFallback = true;
        }
      }
      if (needsFallback && !state.checkScheduled) {
        state.checkScheduled = true;
        requestFrame(() => checkFinalItems(streamType));
      }
    }

    function scheduleFinalCheck(streamType) {
      const state = states[streamType];
      checkFinalItems(streamType);
      if (state.checkScheduled) return;
      for (const item of state.items.values()) {
        if (item.final && !item.terminal && item.sources.size > 0) {
          state.checkScheduled = true;
          requestFrame(() => checkFinalItems(streamType));
          return;
        }
      }
    }

    function pcmBufferFromPacket(state, base64Audio) {
      const bytes = decodeBase64(base64Audio);
      let offset = 0;
      if (
        bytes.length >= 44
        && String.fromCharCode(bytes[0], bytes[1], bytes[2], bytes[3]) === 'RIFF'
      ) {
        const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
        state.channels = view.getUint16(22, true);
        state.sampleRate = view.getUint32(24, true);
        let scan = 12;
        while (scan < bytes.length - 8) {
          const id = String.fromCharCode(bytes[scan], bytes[scan + 1], bytes[scan + 2], bytes[scan + 3]);
          const size = view.getUint32(scan + 4, true);
          if (id === 'data') {
            offset = scan + 8;
            break;
          }
          scan += 8 + size;
        }
        if (offset === 0) offset = 44;
      }

      const pcmBytes = bytes.slice(offset);
      const alignedLength = pcmBytes.byteLength - (pcmBytes.byteLength % 2);
      const pcm16 = new Int16Array(
        pcmBytes.buffer,
        pcmBytes.byteOffset,
        alignedLength / Int16Array.BYTES_PER_ELEMENT,
      );
      const numSamples = Math.floor(pcm16.length / state.channels);
      const audioBuffer = audioContext.createBuffer(state.channels, numSamples, state.sampleRate);
      for (let channel = 0; channel < state.channels; channel += 1) {
        const channelData = audioBuffer.getChannelData(channel);
        for (let index = 0; index < numSamples; index += 1) {
          channelData[index] = pcm16[index * state.channels + channel] / 32768.0;
        }
      }
      return audioBuffer;
    }

    async function feed(packet) {
      const streamType = requireStreamType(packet && packet.stream_type);
      if (
        streamType === 'call'
        && packet.response_id
        && states.call.cancelledResponseIds.has(packet.response_id)
      ) {
        return { accepted: false, reason: 'cancelled_response' };
      }
      if (audioContext.state === 'suspended') await audioContext.resume();
      const state = states[streamType];
      const item = getOrCreateItem(state, packet);

      if (packet.audio) {
        const audioBuffer = pcmBufferFromPacket(state, packet.audio);
        const source = audioContext.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(analyser);
        item.sources.add(source);
        source.onended = () => {
          item.sources.delete(source);
          if (item.final && !item.terminal && item.sources.size === 0) {
            emitFinished(streamType, state, item);
          }
          resetTimelineIfIdle(state);
        };

        if (state.nextStartTime < audioContext.currentTime) {
          state.nextStartTime = audioContext.currentTime + 0.05;
        }
        source.start(state.nextStartTime);
        state.nextStartTime += audioBuffer.duration;
        item.endTime = Math.max(item.endTime, state.nextStartTime);
      }

      if (packet.is_final) {
        item.final = true;
        scheduleFinalCheck(streamType);
      }
      return { accepted: true };
    }

    function stop(command) {
      const streamType = requireStreamType(command && command.stream_type);
      const state = states[streamType];
      const requestedAudioIds = new Set(
        Array.isArray(command.audio_ids) ? command.audio_ids.filter(Boolean) : [],
      );
      if (streamType === 'call' && command.response_id) {
        state.cancelledResponseIds.add(command.response_id);
      }

      if (requestedAudioIds.size > 0) {
        for (const audioId of requestedAudioIds) {
          if (!state.items.has(audioId)) {
            state.items.set(audioId, {
              audioId,
              responseId: command.response_id || null,
              sources: new Set(),
              final: false,
              terminal: null,
              endTime: audioContext.currentTime,
            });
          }
        }
      }

      const affectedItems = [...state.items.values()].filter((item) => {
        if (requestedAudioIds.size > 0) return requestedAudioIds.has(item.audioId);
        if (command.response_id) return item.responseId === command.response_id;
        return true;
      });
      for (const item of affectedItems) {
        if (item.terminal) continue;
        item.terminal = 'stopped';
        state.items.delete(item.audioId);
        const sources = [...item.sources];
        item.sources.clear();
        for (const source of sources) {
          try { source.stop(); } catch (_) {}
        }
        postMessage({
          type: 'audio_stopped',
          stream_type: streamType,
          audio_id: item.audioId,
          response_id: item.responseId || command.response_id || null,
          reason: command.reason || 'stopped',
        });
      }
      resetTimelineIfIdle(state);
      return { stopped_audio_ids: affectedItems.map((item) => item.audioId) };
    }

    function isPlaying() {
      return hasActiveSources(states.chat) || hasActiveSources(states.call);
    }

    return { feed, stop, isPlaying };
  }

  return { createLive2DAudioStreamPlayer };
});
