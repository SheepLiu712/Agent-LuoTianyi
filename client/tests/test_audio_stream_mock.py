
import io
import wave
import struct
import numpy as np
import soundfile as sf
import logging

# Mock PyAudio
class MockStream:
    def __init__(self, rate, channels, format):
        self.rate = rate
        self.channels = channels
        self.format = format
        self.data_written = b""

    def write(self, data):
        self.data_written += data
    
    def get_output_latency(self):
        return 0.1
    
    def stop_stream(self): pass
    def close(self): pass

class MockPyAudio:
    def __init__(self):
        self.paInt16 = 8
        self.paInt24 = 4 # Fake constants
        self.paInt32 = 2
        self.paFloat32 = 1

    def open(self, format, channels, rate, output):
        print(f"Opening stream: Rate={rate}, Channels={channels}, Format={format}")
        return MockStream(rate, channels, format)
    
    def terminate(self): pass

# Copied from audio_processor.py and modified imports
logger = logging.getLogger("test")
logging.basicConfig(level=logging.INFO)

class AudioPlayerStream:
    def __init__(self):
        self.p = MockPyAudio()
        self.has_pyaudio = True
            
        self.stream = None
        self.header_parsed = False
        self.samplerate = 0
        self.channels = 0
        self.subtype = None 

    def append_buffer(self, data: bytes):
        if not self.has_pyaudio:
            return

        if not self.header_parsed:
            try:
                # Try to force read despite incomplete file?
                # soundfile might warn but work if header is intact
                with sf.SoundFile(io.BytesIO(data)) as f:
                    self.samplerate = f.samplerate
                    self.channels = f.channels
                    self.subtype = f.subtype
                    
                    initial_audio = f.read(dtype='int16')
                    
                    format_pyaudio = 8 # paInt16
                    
                    self.stream = self.p.open(format=format_pyaudio,
                                              channels=self.channels,
                                              rate=self.samplerate,
                                              output=True)
                    
                    raw_bytes = initial_audio.tobytes()
                    self.stream.write(raw_bytes)
                    self.header_parsed = True
            except Exception as e:
                logger.error(f"Failed to parse header from first chunk: {e}")
                pass
        else:
            self.stream.write(data)

    def close(self):
        pass

def create_test_wav():
    # Create a 1 second sine wave at 44100Hz, Stereo
    sample_rate = 44100
    duration = 1.0
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    # 440Hz sine wave
    signal = 0.5 * np.sin(2 * np.pi * 440 * t)
    # Stereo: Same signal on both channels
    signal_stereo = np.column_stack((signal, signal))
    
    # Save to Bytes
    buf = io.BytesIO()
    sf.write(buf, signal_stereo, sample_rate, format='WAV', subtype='PCM_16')
    return buf.getvalue()

def test_stream():
    wav_bytes = create_test_wav()
    print(f"Total WAV size: {len(wav_bytes)}")
    
    # Split into two chunks
    # WAV Header is usually 44 bytes.
    # Let's split at 100 bytes (header + a little data)
    chunk1 = wav_bytes[:100]
    chunk2 = wav_bytes[100:]
    
    player = AudioPlayerStream()
    print("Sending Chunk 1...")
    player.append_buffer(chunk1)
    
    print("Sending Chunk 2...")
    player.append_buffer(chunk2)
    
    if player.stream is None:
        print("Stream NOT created!")
        return

    total_written = len(player.stream.data_written)
    print(f"Total data written to stream: {total_written}")
    
    # Calculate expected data size
    # 1 sec * 44100 samples/sec * 2 channels * 2 bytes/sample = 176400 bytes
    expected = 44100 * 2 * 2
    print(f"Expected raw PCM data size: {expected}")
    
    print(f"Difference: {total_written - expected}")

if __name__ == "__main__":
    test_stream()
