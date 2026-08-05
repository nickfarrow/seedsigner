"""
    FROST threshold backup recovery.

    Implements the backup format specified by the draft BIP "Mnemonic Encoding for
    secp256k1 Secret Keys and Shamir Shares" (Fournier & Farrow), as produced by
    Frostsnap devices.

    A backup is a key number plus 25 BIP-39 words. Unlike BIP-39, the words encode a
    secp256k1 *scalar* directly rather than entropy, which is what allows keys to be
    recombined. There is no BIP-39 checksum anywhere in this scheme; the checksums and
    fingerprint below are its own.

    Key #0 is special: it carries the whole secret rather than a share of it, which is how
    a threshold-1 wallet is backed up. It is recovered on its own and must never be mixed
    with shares.

    Recombining `threshold` backups yields a 32-byte secret that is used directly as a
    BIP-32 master private key with an all-zero chain code (see `FrostSeed`).
"""
import hashlib

from embit import ec
from embit.bip39 import WORDLIST
from typing import List, Tuple


SECP256K1_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141

NUM_WORDS = 25

# The key number is carried alongside the words, not within them. #0 is the whole secret
# rather than a share of it; see `recover_secret()`.
MIN_SHARE_INDEX = 0
MAX_SHARE_INDEX = 2**32 - 1

# Key generation grinds the `frost-v0` fingerprint into the polynomial commitment of every
# wallet with a threshold of 2 or more. Only the first two non-constant coefficients ever
# carry bits, since 18 + 18 reaches the 36-bit total.
FINGERPRINT_TAG = b"frost-v0"
FINGERPRINT_BITS_PER_COEFF = 18
FINGERPRINT_MAX_BITS = 36


class InvalidFrostBackupException(Exception):
    """A single backup is malformed: bad word, wrong length, or failed words checksum."""
    pass


class MismatchedFrostBackupsException(Exception):
    """The backups are individually valid but do not belong to the same wallet."""
    pass



def calc_words_checksum(index: int, scalar_bytes: bytes, poly_checksum: int) -> int:
    """
        The 11-bit checksum occupying the 25th word. Verifiable from a single backup, so
        it catches transcription errors as soon as a backup is entered.

        Note the field widths: the index is hashed as 4 bytes and the polynomial checksum
        as 2 bytes (one leading zero byte, though only 8 bits are significant). These
        differ from `calc_poly_checksum()`, which hashes the index as 32 bytes. The
        inconsistency is in the reference implementation and is flagged as an open
        question in the BIP; implementations must match it exactly, so do not "fix" it.
    """
    digest = hashlib.sha256(
        index.to_bytes(4, "big") + scalar_bytes + poly_checksum.to_bytes(2, "big")
    ).digest()
    return int.from_bytes(digest[0:2], "big") >> 5


def calc_poly_checksum(index: int, scalar_bytes: bytes, poly_commitment: bytes) -> int:
    """
        The 8-bit checksum binding a key to its polynomial commitment. Cannot be
        verified until `threshold` backups are present, but then proves they all came
        from the same wallet.

        The index is hashed as 32 bytes here; see the note in `calc_words_checksum()`.
    """
    digest = hashlib.sha256(
        index.to_bytes(32, "big") + scalar_bytes + poly_commitment
    ).digest()
    return digest[0]


def decode_backup(index: int, words: List[str]) -> Tuple[bytes, int]:
    """
        Decodes one backup's 25 words and verifies its words checksum.

        The 25 words carry 275 bits, packed MSB-first:
            bits   0-255  the secret share scalar, big-endian
            bits 256-263  the polynomial checksum
            bits 264-274  the words checksum (i.e. exactly the 25th word)

        Returns (scalar_bytes, poly_checksum). Raises `InvalidFrostBackupException` if
        the backup can't be decoded or fails its checksum.
    """
    if not MIN_SHARE_INDEX <= index <= MAX_SHARE_INDEX:
        raise InvalidFrostBackupException(f"Key number {index} out of range")

    if len(words) != NUM_WORDS:
        raise InvalidFrostBackupException(f"Expected {NUM_WORDS} words, got {len(words)}")

    # The spec mandates the English BIP-39 wordlist regardless of the user's wordlist
    # language setting; the words encode bits, not language.
    bits = 0
    for i, word in enumerate(words):
        try:
            bits = (bits << 11) | WORDLIST.index(word.lower())
        except ValueError:
            raise InvalidFrostBackupException(f"Word #{i + 1} '{word}' is not a BIP-39 word")

    scalar = bits >> 19
    poly_checksum = (bits >> 11) & 0xFF
    words_checksum = bits & 0x7FF

    # A scalar at or above the group order is rejected outright, never reduced.
    if scalar >= SECP256K1_ORDER:
        raise InvalidFrostBackupException("Scalar is not less than the secp256k1 group order")

    scalar_bytes = scalar.to_bytes(32, "big")

    if calc_words_checksum(index, scalar_bytes, poly_checksum) != words_checksum:
        raise InvalidFrostBackupException("Words checksum failed; likely a transcription error")

    return scalar_bytes, poly_checksum


def _interpolate_polynomial(points: List[Tuple[int, int]]) -> List[int]:
    """
        Lagrange-interpolates the full polynomial through `points`, returning all
        len(points) coefficients mod n, constant term first. The constant term is the
        recovered secret.

        We interpolate every coefficient rather than just evaluating at x=0 because the
        higher coefficients are needed to rebuild the polynomial commitment that the
        polynomial checksum commits to.
    """
    coefficients = [0] * len(points)
    x_values = [x for x, _ in points]

    for x_i, y_i in points:
        # Build the basis polynomial L_i(x) = product over j != i of (x - x_j)/(x_i - x_j)
        basis = [1]
        for x_j in x_values:
            if x_j == x_i:
                continue
            inverse = pow((x_i - x_j) % SECP256K1_ORDER, SECP256K1_ORDER - 2, SECP256K1_ORDER)
            shifted = [0] * (len(basis) + 1)
            for k, coefficient in enumerate(basis):
                shifted[k + 1] = (shifted[k + 1] + coefficient) % SECP256K1_ORDER
                shifted[k] = (shifted[k] - coefficient * x_j) % SECP256K1_ORDER
            basis = [c * inverse % SECP256K1_ORDER for c in shifted]

        for k, coefficient in enumerate(basis):
            coefficients[k] = (coefficients[k] + y_i * coefficient) % SECP256K1_ORDER

    return coefficients


def _polynomial_commitment(coefficients: List[int]) -> bytes:
    """
        The polynomial commitment: each coefficient multiplied by G and serialized
        compressed, constant term first.

        Because we hold the secret coefficients we can map each to a point directly,
        rather than interpolating the share images on the curve as the reference
        implementation does. That keeps this to `ec_pubkey_create`, which embit's
        pure-Python secp256k1 fallback provides; its `ec_pubkey_tweak_mul` and
        `ec_pubkey_combine` are not compiled in, so the curve-interpolation approach
        would not run on that backend.
    """
    try:
        return b"".join(
            ec.PrivateKey(c.to_bytes(32, "big")).get_public_key().sec() for c in coefficients
        )
    except Exception as e:
        # A zero or out-of-range coefficient is astronomically unlikely for genuine
        # backups, so treat it as a mismatch rather than letting it crash the app.
        raise MismatchedFrostBackupsException(repr(e))


def _has_fingerprint(commitment: bytes) -> bool:
    """
        Whether a polynomial commitment carries the `frost-v0` fingerprint.

        A running hash absorbs `len(tag) || tag || A_0`; each further coefficient must then
        drive it to at least `needed` leading zero bits. A threshold-1 commitment has no
        further coefficients and passes trivially, carrying no fingerprint bits.
    """
    coefficients = [commitment[i:i + 33] for i in range(0, len(commitment), 33)]
    absorbed = bytes([len(FINGERPRINT_TAG)]) + FINGERPRINT_TAG + coefficients[0]
    bits = 0

    for coefficient in coefficients[1:]:
        needed = min(FINGERPRINT_BITS_PER_COEFF, FINGERPRINT_MAX_BITS - bits)
        if needed == 0:
            break
        digest = hashlib.sha256(absorbed + coefficient).digest()
        leading_zero_bits = 8 * len(digest) - int.from_bytes(digest, "big").bit_length()
        if leading_zero_bits < needed:
            return False
        absorbed += coefficient
        bits += needed

    return True


def recover_secret(backups: List[Tuple[int, bytes, int]]) -> bytes:
    """
        Recombines decoded backups into the 32-byte master secret.

        `backups` is a list of (index, scalar_bytes, poly_checksum) as returned by
        `decode_backup()`, and must contain exactly `threshold` entries: the threshold
        determines the degree of the polynomial being reconstructed.

        A lone #0 backup carries the secret itself. It needs no special case here —
        interpolating the single point (0, s) yields the constant polynomial [s], whose
        commitment is s*G, which is exactly what its polynomial checksum commits to.

        Raises `MismatchedFrostBackupsException` if the backups do not all belong to the
        same wallet.
    """
    if not backups:
        raise MismatchedFrostBackupsException("No backups provided")

    indexes = [index for index, _, _ in backups]
    if len(set(indexes)) != len(indexes):
        raise MismatchedFrostBackupsException("Duplicate key number")

    if 0 in indexes and len(backups) > 1:
        raise MismatchedFrostBackupsException("Key #0 is the whole secret; it can't be combined with other keys")

    coefficients = _interpolate_polynomial(
        [(index, int.from_bytes(scalar, "big")) for index, scalar, _ in backups]
    )
    commitment = _polynomial_commitment(coefficients)

    if not _has_fingerprint(commitment):
        raise MismatchedFrostBackupsException("Fingerprint check failed; these keys don't form a wallet")

    for index, scalar, poly_checksum in backups:
        if calc_poly_checksum(index, scalar, commitment) != poly_checksum:
            raise MismatchedFrostBackupsException(
                f"Polynomial checksum failed for key #{index}"
            )

    return coefficients[0].to_bytes(32, "big")
