# AAC-LC validation fixture

`aac-lc.m4a` is copied byte-for-byte from `app/__tests__/fixtures/voice-cache.m4a`.
It contains real AAC-LC media (approximately 1.064 seconds), not only synthetic metadata.
Tests replace only the same-length ftyp payload to cover Android mp42/isom branding;
media bytes and chunk offsets remain unchanged. This is an Android-shaped sample,
not a recording captured on an Android device. Device acceptance remains in #252.
