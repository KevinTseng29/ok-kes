"""The version-4 format's reversible xorshift32 byte mask.

This is obfuscation, not encryption. Words are emitted little endian, starting
with the first state update, and the mask includes the three-byte file header.
"""

_SEED = 0x870FCD0A


def transform(data: bytes) -> bytes:
    """Apply the same transform to encode or decode an entire wire message."""
    state = _SEED
    result = bytearray(len(data))
    for offset in range(0, len(data), 4):
        state ^= (state << 13) & 0xFFFFFFFF
        state ^= state >> 17
        state ^= (state << 5) & 0xFFFFFFFF
        word = state.to_bytes(4, "little")
        for index in range(min(4, len(data) - offset)):
            result[offset + index] = data[offset + index] ^ word[index]
    return bytes(result)
