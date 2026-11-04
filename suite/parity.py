"""XOR-interleaved and Reed-Solomon parity for POINTS glyphs.

Per Point 2: dual-mode parity. XOR recovers any single lost block
(algo_id=1). RS(255,223) corrects up to 16 symbol errors per codeword
(algo_id=2).

Upgrade path: PARITY_ALGO_ID in header selects mode at decode time.
"""

from __future__ import annotations

from . import rs_codec as _rs

# RS(255, 223) — hardcoded per spec (point2_enhanced.md §11.2)
RS_N_PARITY = 32   # 255 - 223
RS_N_DATA = 223     # data symbols per codeword


def compute_parity_size(content_size: int, ratio: int = 15,
                        algo_id: int = 1) -> int:
    """Compute parity block size.

    For XOR (algo_id=1): ``ratio``% of content size.
    For RS (algo_id=2): exact RS parity size = n_blocks × n_parity.
    """
    if algo_id == 2:
        n_blocks = (content_size + RS_N_DATA - 1) // RS_N_DATA
        return n_blocks * RS_N_PARITY
    return max(1, (content_size * ratio) // 100)


def encode_parity(content: bytes, algo_id: int = 1,
                  ratio: int = 15) -> bytes:
    """Generate parity block for content.

    XOR-interleaved (algo_id=1): split content into ``n_blocks`` chunks,
    XOR them into one parity block.

    Reed-Solomon (algo_id=2): RS(255,223)-encode content, return only the
    parity bytes (systematic — data is preserved as-is in the glyph).
    """
    if algo_id == 2:
        if len(content) == 0:
            return bytes(0)
        codeword = _rs.rs_encode(content, RS_N_PARITY)
        # Systematic: codeword = D0|P0|D1|P1|... — extract parity contiguously
        n_blocks = (len(content) + RS_N_DATA - 1) // RS_N_DATA
        parity_bytes = bytearray()
        for i in range(n_blocks):
            block_parity_start = i * 255 + RS_N_DATA
            parity_bytes.extend(
                codeword[block_parity_start:block_parity_start + RS_N_PARITY])
        return bytes(parity_bytes)

    # ── XOR (algo_id=1) ──────────────────────────────────────────────
    if algo_id != 1:
        raise ValueError(f"Unsupported parity algo: {algo_id}")

    parity_size = compute_parity_size(len(content), ratio)
    if len(content) == 0:
        return bytes(parity_size)

    n_blocks = max(2, len(content) // parity_size)
    if n_blocks > len(content):
        n_blocks = len(content)
    block_size = (len(content) + n_blocks - 1) // n_blocks

    # Pad content to multiple of block_size for clean XOR
    padded = content.ljust(n_blocks * block_size, b"\x00")

    # XOR all blocks into parity
    parity = bytearray(block_size)
    for i in range(n_blocks):
        start = i * block_size
        chunk = padded[start:start + block_size]
        for j in range(len(chunk)):
            parity[j] ^= chunk[j]

    # Trim or pad to exact parity_size
    if len(parity) > parity_size:
        parity = parity[:parity_size]
    elif len(parity) < parity_size:
        parity = parity.ljust(parity_size, b"\x00")

    return bytes(parity)


def verify_parity(content: bytes, parity_block: bytes,
                  algo_id: int = 1, ratio: int | None = None) -> bool:
    """Verify parity by recomputing and comparing.

    Pass ``ratio`` for exact reconstruction (avoids rounding error
    from reverse-computing the ratio from block size).

    XOR parity can't detect all errors (unlike CRC), so this is a
    consistency check, not a guarantee. RS verification re-encodes the
    content and compares parity bytes.
    """
    if algo_id == 2:
        computed = encode_parity(content, algo_id)
        return computed == parity_block

    if ratio is None:
        ratio = (len(parity_block) * 100) // max(1, len(content))
    computed = encode_parity(content, algo_id, ratio)
    return computed == parity_block


def decode_and_repair(content: bytes, parity_block: bytes,
                      algo_id: int = 1) -> tuple[bytes, int]:
    """Decode and repair content using parity.

    Returns ``(corrected_content, errors_corrected)``.

    XOR (algo_id=1): parity can only detect, not repair. Returns content
    unchanged with ``errors_corrected=0``.

    Reed-Solomon (algo_id=2): reassembles content + parity into RS
    codewords, runs RS decode, returns corrected content and count of
    symbol errors fixed.
    """
    if algo_id == 2:
        if len(content) == 0:
            return (b"", 0)
        combined = _reassemble_rs_codewords(content, parity_block)
        decoded, errors = _rs.rs_decode(combined, RS_N_PARITY)
        return (decoded[:len(content)], errors)

    # XOR has no repair capability
    return (content, 0)


def _reassemble_rs_codewords(content: bytes,
                              parity_block: bytes) -> bytes:
    """Reassemble content + parity into contiguous RS codewords.

    Each RS codeword is 255 bytes: 223 data + 32 parity.
    Content is split into 223-byte blocks, parity into 32-byte blocks.
    """
    n_blocks = (len(content) + RS_N_DATA - 1) // RS_N_DATA
    expected_parity = n_blocks * RS_N_PARITY

    # Pad parity if short
    pb = parity_block
    if len(pb) < expected_parity:
        pb = pb.ljust(expected_parity, b"\x00")
    elif len(pb) > expected_parity:
        pb = pb[:expected_parity]

    parts = []
    for i in range(n_blocks):
        data_start = i * RS_N_DATA
        data_chunk = content[data_start:data_start + RS_N_DATA]
        parity_start = i * RS_N_PARITY
        parity_chunk = pb[parity_start:parity_start + RS_N_PARITY]
        codeword = data_chunk.ljust(RS_N_DATA, b"\x00") + parity_chunk
        parts.append(codeword)

    return b"".join(parts)
