# Voice cache fixture

`voice-cache.m4a` is generated one-second silence, mono 16 kHz AAC in an M4A container, without external source audio:

```sh
ffmpeg -f lavfi -i anullsrc=r=16000:cl=mono -t 1 -c:a aac -b:a 32k voice-cache.m4a
```

The cache tests append a valid ISO BMFF `free` box to make each sample exactly 1 MiB. The byte-backed filesystem double preserves these contents across manager recreation and reports their actual byte lengths. Codec/device decoding is outside these tests; Android playback still needs manual validation.
