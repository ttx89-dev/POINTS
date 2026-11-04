"""Reed-Solomon (255, 223) codec over GF(256).

RS(255,223): 223 data symbols + 32 parity symbols = 255 codeword.
Corrects up to t=16 symbol errors (any location).

Field: GF(2^8) with primitive polynomial p(x) = x^8 + x^4 + x^3 + x^2 + 1 (0x11D).
Generator: ∏(x - α^j) for j=0..31 (systematic encoding).

Both encoding and decoding use numpy for log/antilog table lookups.
Decoder uses Berlekamp-Massey (error locator) + Chien search (roots) +
Forney algorithm (error values)."""

from __future__ import annotations

import numpy as np

# ── GF(2^8) Tables ────────────────────────────────────────────────

_PRIMITIVE = 0x11D  # x^8 + x^4 + x^3 + x^2 + 1

def _build_gf_tables() -> tuple[np.ndarray, np.ndarray]:
    """Build (log, antilog) tables for GF(2^8) with primitive 0x11D."""
    size = 256
    gf_exp = np.zeros(512, dtype=np.int32)  # double-size for fast mul
    gf_log = np.zeros(size, dtype=np.int32)

    x = 1
    for i in range(255):
        gf_exp[i] = x
        gf_exp[i + 255] = x  # second copy for wrapping
        gf_log[x] = i
        x <<= 1
        if x & 0x100:
            x ^= _PRIMITIVE
    gf_exp[255] = gf_exp[0]  # log(1) = 0, ensures exp[255] = 1
    gf_exp[511] = gf_exp[0]
    return gf_log, gf_exp


GF_LOG, GF_EXP = _build_gf_tables()


def gf_mul(a: int, b: int) -> int:
    """Multiply two GF(2^8) elements."""
    if a == 0 or b == 0:
        return 0
    return GF_EXP[GF_LOG[a] + GF_LOG[b]]


def gf_pow(a: int, n: int) -> int:
    """Raise GF element to integer power n."""
    if a == 0:
        return 0
    log_a = GF_LOG[a]
    result_log = (log_a * n) % 255
    return GF_EXP[result_log]


def gf_poly_eval(poly: list[int], x: int) -> int:
    """Evaluate polynomial at point x (Horner's method).

    Assumes poly[0] is the coefficient of the HIGHEST power of x
    (descending order — convariant with codeword polynomial storage).
    """
    y = poly[0]
    for i in range(1, len(poly)):
        y = gf_mul(y, x) ^ poly[i]
    return y


def gf_poly_eval_natural(poly: list[int], x: int) -> int:
    """Evaluate ascending-order polynomial at point x.

    poly[0] = constant term = coefficient of x^0
    poly[1] = coefficient of x^1
    ...
    poly[m] = coefficient of x^m

    Used for Λ(x), Ω(x), Λ'(x) which are stored ascending.
    """
    y = poly[-1]  # start with highest-degree coefficient
    for i in range(len(poly) - 2, -1, -1):
        y = gf_mul(y, x) ^ poly[i]
    return y


# ── Generator Polynomial ───────────────────────────────────────────

def _rs_generator_poly(n_parity: int) -> list[int]:
    """Build generator polynomial for RS with n_parity check symbols.

    g(x) = ∏_{j=0}^{n_parity-1} (x - α^j)

    Returns coefficients g[0]..g[n_parity], where g[0]=1.
    """
    g: list[int] = [1]  # g(x) = 1
    for j in range(n_parity):
        # multiply by (x - α^j)
        term = [1, GF_EXP[j]]  # (x - α^j) where -α^j = α^j in GF(2)
        # polynomial multiplication
        new_g = [0] * (len(g) + 1)
        for i, gi in enumerate(g):
            new_g[i] ^= gi
            new_g[i + 1] ^= gf_mul(gi, term[1])
        g = new_g
    return g


# ── Encoder ────────────────────────────────────────────────────────

def rs_encode(data: bytes, n_parity: int = 32) -> bytes:
    """Encode ``data`` with RS(n_parity) parity.

    Systematic encoding: data symbols are preserved in output[0:n_data],
    parity appended at output[n_data:n_data+n_parity].

    If len(data) > 255 - n_parity, data is split into blocks.
    """
    n_data = 255 - n_parity
    generator = _rs_generator_poly(n_parity)

    result = bytearray()
    for offset in range(0, len(data), n_data):
        block = data[offset:offset + n_data]
        result.extend(_encode_block(block, generator, n_parity))
    return bytes(result)


def _encode_block(data: bytes, generator: list[int],
                  n_parity: int) -> bytes:
    """Encode one RS block (max 255-n_parity data bytes)."""
    n_data = 255 - n_parity
    padded = bytearray(data.ljust(n_data, b'\x00'))
    # Polynomial division: multiply by x^n_parity, divide by generator
    # Remainder becomes parity symbols
    remainder = [0] * n_parity
    for byte_val in padded:
        feedback = byte_val ^ remainder[0]
        for j in range(n_parity - 1):
            remainder[j] = remainder[j + 1] ^ gf_mul(feedback, generator[j + 1])
        remainder[n_parity - 1] = gf_mul(feedback, generator[n_parity])

    codeword = bytes(padded) + bytes(remainder)
    return codeword


# ── Decoder (Berlekamp-Massey + Chien + Forney) ────────────────────

def rs_decode(codeword: bytes, n_parity: int = 32) -> tuple[bytes, int]:
    """Decode an RS-encoded message, correcting up to n_parity//2 errors.

    Returns ``(data_bytes, errors_corrected)``.

    Raises ``ValueError`` if the codeword is too damaged to decode.
    """
    n_data = 255 - n_parity
    generator = _rs_generator_poly(n_parity)

    result = bytearray()
    total_errors = 0
    for offset in range(0, len(codeword), 255):
        block = codeword[offset:offset + 255]
        # Pad short blocks
        if len(block) < 255:
            block = block.ljust(255, b'\x00')
        data, n_err = _decode_block(bytes(block), generator, n_parity, n_data)
        result.extend(data)
        total_errors += n_err
    return bytes(result), total_errors


def _decode_block(codeword: bytes, generator: list[int],
                  n_parity: int, n_data: int) -> tuple[bytes, int]:
    """Decode one RS block (exactly 255 bytes)."""
    # Step 1: Compute syndromes S_j = codeword(α^j) for j=0..n_parity-1
    syndromes = []
    has_error = False
    for j in range(n_parity):
        s = gf_poly_eval(list(codeword), GF_EXP[j])
        syndromes.append(s)
        if s != 0:
            has_error = True

    if not has_error:
        # No errors detected — strip parity, return data
        return codeword[:n_data], 0

    # Step 2: Berlekamp-Massey — find error locator polynomial Λ(x)
    lam = _berlekamp_massey(syndromes, n_parity)

    # Step 3: Chien search — find roots of Λ(x) (error positions)
    error_positions = _chien_search(lam, 255)

    if len(error_positions) == 0:
        raise ValueError("RS decode: error detected but no roots found")

    # Step 4: Forney algorithm — compute error values
    error_values = _forney(syndromes, lam, error_positions, n_parity)

    # Step 5: Apply corrections
    corrected = bytearray(codeword)
    for pos, val in zip(error_positions, error_values):
        corrected[254 - pos] ^= val

    # Verify: recompute syndromes on corrected codeword
    for j in range(n_parity):
        s = gf_poly_eval(list(corrected), GF_EXP[j])
        if s != 0:
            raise ValueError("RS decode: correction failed (syndromes nonzero)")

    return bytes(corrected[:n_data]), len(error_positions)


def _berlekamp_massey(syndromes: list[int],
                      n_parity: int) -> list[int]:
    """Find error locator polynomial Λ(x) via Berlekamp-Massey.

    Returns Λ coefficients [Λ0, Λ1, ..., Λm] where Λ0 = 1.
    """
    # Initialization
    C = [1]  # current connection polynomial
    B = [1]  # previous connection polynomial
    L = 0    # current degree
    m = 1    # iteration lag
    b = 1    # previous discrepancy

    for r in range(n_parity):
        # Compute discrepancy d = S_r + Σ C_i * S_{r-i}
        d = syndromes[r]
        for i in range(1, L + 1):
            d ^= gf_mul(C[i], syndromes[r - i])

        if d == 0:
            m += 1
        else:
            T = C[:]
            # C(x) = C(x) - d * b^(-1) * x^m * B(x)
            scale = gf_mul(d, GF_EXP[255 - GF_LOG[b]])  # d * b^(-1)
            while len(C) < len(B) + m:
                C.append(0)
            for i in range(len(B)):
                C[i + m] ^= gf_mul(scale, B[i])

            if 2 * L <= r:
                L = r + 1 - L
                B = T
                b = d
                m = 1
            else:
                m += 1

    return C


def _chien_search(lam: list[int], max_pos: int) -> list[int]:
    """Find roots of Λ(x) by evaluating at α^(-i) for i=0..max_pos-1.

    Λ(x) is stored in ascending order (Λ[0] = constant term).
    Uses ``gf_poly_eval_natural`` so that Λ(α^(-i)) = 0 directly indicates
    an error at coefficient c_i in the codeword polynomial.

    Returns list of exponents i where Λ(α^(-i)) = 0.
    Each returned i maps to byte index (254 − i) in the codeword array.
    """
    positions = []
    for i in range(max_pos):
        x = GF_EXP[(255 - i) % 255]  # α^(-i)
        val = gf_poly_eval_natural(lam, x)
        if val == 0:
            positions.append(i)
    return positions


def _forney(syndromes: list[int], lam: list[int],
            error_positions: list[int], n_parity: int) -> list[int]:
    """Compute error values via Forney algorithm.

    Ω(x) = S(x) * Λ(x) mod x^n_parity (error evaluator polynomial)
    e_k = -Ω(α^(-k)) / Λ'(α^(-k))

    Returns list of error values, one per error_position.
    """
    # Compute Ω(x) = S(x) * Λ(x) mod x^n_parity
    # S(x) = Σ S_j x^j for j=0..n_parity-1
    omega = [0] * n_parity
    for i in range(min(len(syndromes), n_parity)):
        for j in range(min(len(lam), n_parity - i)):
            if i + j < n_parity:
                omega[i + j] ^= gf_mul(syndromes[i], lam[j])

    # Compute formal derivative Λ'(x) = Λ1 + 2*Λ2*x + 3*Λ3*x^2 + ...
    # In GF(2^m), only odd-indexed terms survive (2*Λ_i = 0 for even i):
    #   Λ'(x) = Λ1 + Λ3*x^2 + Λ5*x^4 + ...
    # Coefficients are at x^{i-1} where i is odd, so exponents are 0, 2, 4, ...
    # We must keep zero entries for the missing odd powers.
    lam_prime = []
    for i in range(1, len(lam), 2):  # i = 1, 3, 5, ... (Λ_i is coefficient of x^i)
        target = i - 1  # exponent in Λ'(x), always even
        while len(lam_prime) < target:
            lam_prime.append(0)
        assert len(lam_prime) == target  # should be exactly at the gap
        lam_prime.append(lam[i])  # coefficient of x^target

    values = []
    for pos in error_positions:
        x_inv = GF_EXP[(255 - pos) % 255]  # α^(-pos)
        # Evaluate Ω(α^(-pos)) — ascending order
        omega_val = gf_poly_eval_natural(omega, x_inv)
        # Evaluate Λ'(α^(-pos)) — ascending order
        lam_prime_val = gf_poly_eval_natural(lam_prime, x_inv)
        if lam_prime_val == 0:
            raise ValueError(f"Forney: Λ'(α^(-{pos})) = 0, cannot compute error")
        # e_k = -Ω(α^{-k}) / Λ'(α^{-k}) ... Forney with α⁰-root convention
        # Missing factor: α^k (GF_EXP[pos % 255])
        inv = GF_EXP[255 - GF_LOG[lam_prime_val]]
        e = gf_mul(gf_mul(omega_val, inv), GF_EXP[pos % 255])
        values.append(e)

    return values


# ── Convenience ────────────────────────────────────────────────────

def compute_rs_parity_size(content_size: int,
                           n_parity: int = 32) -> int:
    """Compute total parity bytes for RS(255, 255-n_parity) encoding.

    Content is split into (255-n_parity)-byte blocks; each block gets
    n_parity parity bytes appended.
    """
    n_data = 255 - n_parity
    n_blocks = (content_size + n_data - 1) // n_data
    return n_blocks * n_parity


# ── Self-test ──────────────────────────────────────────────────────

def _selftest():
    """Quick smoke test: encode random data, corrupt it, verify decode."""
    import random as rnd
    rnd.seed(42)

    for n_parity in [16, 32, 64]:
        n_data = 255 - n_parity
        t = n_parity // 2  # correctable errors
        data = bytes(rnd.randint(0, 255) for _ in range(n_data))
        codeword = rs_encode(data, n_parity)
        assert len(codeword) == 255, f"Expected 255, got {len(codeword)}"
        assert codeword[:n_data] == data, "Systematic check failed"

        # Corrupt up to t random symbols
        corrupted = bytearray(codeword)
        n_corrupt = rnd.randint(1, max(1, t))
        positions = rnd.sample(range(255), n_corrupt)
        for p in positions:
            corrupted[p] ^= rnd.randint(1, 255)

        decoded, n_err = rs_decode(bytes(corrupted), n_parity)
        assert decoded == data, f"Corruption failed for n_parity={n_parity}: decoded mismatch"
        assert n_err == n_corrupt, f"Error count: expected {n_corrupt}, got {n_err}"

    print(f"RS selftest OK: 3 configurations, random {t}-error bursts")


if __name__ == "__main__":
    _selftest()
