"""Bounded raw DEFLATE compression used by version 4 preset codes.

The complete preset dictionary was extracted from the client's codec module.
Encoding keeps using self-contained streams for compatibility with other tools.
"""
from __future__ import annotations

import zlib

from .errors import InvalidCodeError

# Three adjacent dictionary fragments in game/build_preset_codec.js.
# Provenance and cross-checks: docs/dictionary.md, research/samples/client_dictionary.json.
_DICTIONARY = (
    b"TALENT_REPLICATIONTALENT_CATEGORY_UNIQUECATEGORY_ENCOUNTERCATEGORY_PUBLICCATEGORY_NONE"
    b"rsp1_c_rsp2_c_rsp3_c_rsp4_c_rsp5_c_add_r_sparklbk_c_pot_c_assault_"
    b"card_c__srt1_srt2_srt3_srt4_uni1_uni2_uni3_uni4_rsp1_rsp2_rsp3_rsp4_rsp5_lbk_pot_eps_col_col2"
)


def compress(payload: bytes) -> bytes:
    """Return a valid raw DEFLATE stream without external dictionary matches."""
    compressor = zlib.compressobj(level=9, wbits=-15)
    return compressor.compress(payload) + compressor.flush()


def _inflate(data: bytes, dictionary: bytes, limit: int) -> bytes:
    decompressor = zlib.decompressobj(wbits=-15, zdict=dictionary)
    try:
        result = decompressor.decompress(data, limit + 1)
    except zlib.error as exc:
        raise InvalidCodeError("Invalid DEFLATE stream or unsupported dictionary reference") from exc
    if len(result) > limit or decompressor.unconsumed_tail:
        raise InvalidCodeError("Decoded deck exceeds the configured size limit")
    if not decompressor.eof:
        raise InvalidCodeError("Truncated DEFLATE stream")
    if decompressor.unused_data:
        raise InvalidCodeError("Unexpected bytes after the DEFLATE stream")
    return result


def decompress(data: bytes, *, max_output: int = 1_048_576) -> bytes:
    """Inflate one bounded stream using the client-extracted BP4 dictionary."""
    if not isinstance(max_output, int) or isinstance(max_output, bool) or max_output < 0:
        raise ValueError("max_output must be a non-negative integer")
    return _inflate(data, _DICTIONARY, max_output)
