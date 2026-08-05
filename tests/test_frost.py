import itertools
import pytest

from seedsigner.helpers import frost
from seedsigner.helpers.frost import (
    InvalidFrostBackupException,
    MismatchedFrostBackupsException,
)
from seedsigner.models.seed import FrostSeed, InvalidSeedException
from seedsigner.models.settings_definition import SettingsConstants


# Official test vectors, from the draft BIP and the frostsnap reference implementation.
# Each entry is (share_index, 25 words).

SHARES_1_OF_1 = [
    (1, "ABSURD AMOUNT DOCTOR ACOUSTIC AVOID LETTER ADVICE CAGE ABSURD AMOUNT DOCTOR ACOUSTIC AVOID LETTER ADVICE CAGE ABSURD AMOUNT DOCTOR ACOUSTIC AVOID LETTER ADVICE CURTAIN SOON"),
]
SECRET_1_OF_1 = "01" * 32

# The same secret backed up as key #0, which carries the whole secret rather than a share.
WHOLE_WALLET_BACKUP = (0, "ABSURD AMOUNT DOCTOR ACOUSTIC AVOID LETTER ADVICE CAGE ABSURD AMOUNT DOCTOR ACOUSTIC AVOID LETTER ADVICE CAGE ABSURD AMOUNT DOCTOR ACOUSTIC AVOID LETTER ADVICE CHECK WIDTH")

# WHOLE_WALLET_BACKUP with every bit of its polynomial checksum flipped, re-checksummed so it
# decodes cleanly and only fails once recombined.
WHOLE_WALLET_BACKUP_BAD_POLY = (0, "ABSURD AMOUNT DOCTOR ACOUSTIC AVOID LETTER ADVICE CAGE ABSURD AMOUNT DOCTOR ACOUSTIC AVOID LETTER ADVICE CAGE ABSURD AMOUNT DOCTOR ACOUSTIC AVOID LETTER ADVICE DECLINE SILK")

SHARES_2_OF_3 = [
    (1, "MUTUAL JEANS SNAP STING BLESS JOURNEY MORAL BREAD ROOM LIMIT DOSE GRAVITY SORT DELIVER OUTDOOR RIPPLE DONKEY BLOUSE PLAY CART CENTURY MAXIMUM MAKE LOCAL MOBILE"),
    (2, "CASH TRASH FOIL PREFER BUTTER IDEA BRAVE BITTER ITEM WINK DRIFT SMILE TOMATO LUNCH OPTION HERO THREE ENGINE BLESS MANAGE HORSE JAR ADVICE SHERIFF BUSINESS"),
    (3, "REGION FINISH TRAVEL LAUNDRY CHEAP HAIR PLUNGE BANANA CRACK INTEREST DURING COTTON PHONE DISAGREE CRUNCH AIRPORT CANCEL FOLD LAUNDRY PONY LOBSTER LENS MAMMAL CLOTH FINGER"),
]
SECRET_2_OF_3 = "01" * 32

SHARES_3_OF_5 = [
    (1, "DUTCH GLAD TORCH EXACT PROGRAM GRASS CLUB SCRAP MUSCLE TUITION TISSUE CLERK SEA SUMMER SHIP VERY FREQUENT DIAL SYRUP MAMMAL SIMILAR MISERY PLAY RING ARM"),
    (2, "SUGAR GENERAL PARK VOYAGE CREEK FLY MOTOR ALWAYS WAVE SUNNY WARRIOR DIAMOND WAVE SUNSET ANY LEFT LIGHT FLOAT VAULT GENUINE ELBOW TENNIS BECOME TABLE CLAIM"),
    (3, "ORANGE HAMMER UNFOLD REFUSE IMMUNE FAVORITE POET MEDIA CARRY SEGMENT PULL BRUSH DAMAGE ADDRESS FILE PORTION UNFOLD BLAST ACCOUNT NATION TELL BELT DENY ABILITY FOOD"),
    (4, "MIRACLE KETCHUP SLIM MAZE GUESS FEBRUARY IDLE ENDORSE BARELY POLAR AGAIN SIBLING CLARIFY SHELL EAGER FISCAL DISTANCE FEW ABOVE SURE FRAME ENFORCE BUTTER MORNING ZOO"),
    (5, "PUMPKIN NEUTRAL DESTROY INSTALL BEHAVE FOLD UNDER EAST SHORT MAGNET WORLD DEVICE SPECIAL BUYER STONE MILLION JUNIOR BEAN UPON CRYSTAL SCENE LEARN SEARCH GALAXY SUMMER"),
]
SECRET_3_OF_5 = "deadbeef" * 8

# Only A_1 and A_2 carry fingerprint bits, so A_3 here is never ground.
SHARES_4_OF_4 = [
    (1, "CAT WITNESS MARINE SAVE SHOCK DEVELOP CHAOS DEVELOP SMOOTH SELECT RUG FATIGUE CITIZEN OBSCURE DINOSAUR ROOF ACTOR ALCOHOL SCREEN DEMAND PATH DOLPHIN FATIGUE INSECT FORCE"),
    (2, "ARTWORK REUNION SECOND TURKEY COMMON CONNECT EQUIP HOTEL AFFORD CLOCK SHRIMP OCTOBER OBJECT SHIELD JEALOUS OBVIOUS ARMOR BURDEN HABIT SHIP EYE WORTH TOP OBJECT BEGIN"),
    (3, "TRULY REPAIR WHEAT BRIDGE CANYON STUMBLE DRAMA EDGE GORILLA GROUP MANAGE ORANGE RACCOON VOICE BITTER MARKET ISSUE JOURNEY DELIVER TURN MEDAL MAN SPIRIT WEIRD REFORM"),
    (4, "TOMATO HELP WEAR TUNNEL HEAD CRUISE SPAWN CUSTOM PRETTY NEITHER TONE CLOG RELIEF ELSE QUARTER LEND ROBOT OBVIOUS BUS REGION DILEMMA SUCCESS CARRY INJECT BOARD"),
]
SECRET_4_OF_4 = "02" * 32

# SHARES_2_OF_3[0] with the final word changed from MOBILE to ABANDON.
CORRUPTED_WORDS = SHARES_2_OF_3[0][1].rsplit(" ", 1)[0] + " ABANDON"

# SHARES_2_OF_3[0] with every bit of its polynomial checksum flipped, re-checksummed so it
# decodes cleanly and only fails once recombined.
SHARE_BAD_POLY = (1, "MUTUAL JEANS SNAP STING BLESS JOURNEY MORAL BREAD ROOM LIMIT DOSE GRAVITY SORT DELIVER OUTDOOR RIPPLE DONKEY BLOUSE PLAY CART CENTURY MAXIMUM MAKE ORIGINAL IMPULSE")

# Encodes the group order itself, with a valid words checksum.
SCALAR_OUT_OF_RANGE = (1, "ZOO ZOO ZOO ZOO ZOO ZOO ZOO ZOO ZOO ZOO ZOO WORD PRIORITY HOVER ONE TROUBLE PARENT TARGET VIRUS RUG SNACK BRASS AGREE CACTUS MIRACLE")

# A 2-of-2 that was never ground: every checksum passes, but the fingerprint does not.
NO_FINGERPRINT = [
    (1, "ALPHA DEAL SCRUB ASTHMA IDEA LOGIC BRIGHT THOUGHT ALPHA DEAL SCRUB ASTHMA IDEA LOGIC BRIGHT THOUGHT ALPHA DEAL SCRUB ASTHMA IDEA LOGIC BRIGHT WINDOW BARELY"),
    (2, "ARCH FLAME SECURITY BID RADAR MACHINE CLUB GESTURE ARCH FLAME SECURITY BID RADAR MACHINE CLUB GESTURE ARCH FLAME SECURITY BID RADAR MACHINE CLUB GLOOM INFORM"),
]


def decode(share):
    index, words = share
    scalar, poly = frost.decode_backup(index, words.split())
    return index, scalar, poly


def recover(shares):
    return frost.recover_secret([decode(s) for s in shares]).hex()



class TestDecodeBackup:
    def test_decodes_all_vectors(self):
        for share in SHARES_1_OF_1 + SHARES_2_OF_3 + SHARES_3_OF_5:
            scalar, poly = frost.decode_backup(share[0], share[1].split())
            assert len(scalar) == 32
            assert 0 <= poly <= 0xFF


    def test_is_case_insensitive(self):
        index, words = SHARES_2_OF_3[0]
        assert frost.decode_backup(index, words.split()) == \
               frost.decode_backup(index, words.lower().split())


    def test_rejects_corrupted_word(self):
        """A single wrong word must be caught by the words checksum."""
        with pytest.raises(InvalidFrostBackupException, match="checksum"):
            frost.decode_backup(1, CORRUPTED_WORDS.split())


    def test_rejects_wrong_share_index(self):
        """The index is part of the checksum preimage, so a wrong one is detected."""
        with pytest.raises(InvalidFrostBackupException, match="checksum"):
            frost.decode_backup(2, SHARES_2_OF_3[0][1].split())


    def test_rejects_non_bip39_word(self):
        words = SHARES_2_OF_3[0][1].split()
        words[6] = "notaword"
        with pytest.raises(InvalidFrostBackupException, match="Word #7"):
            frost.decode_backup(1, words)


    def test_rejects_wrong_word_count(self):
        words = SHARES_2_OF_3[0][1].split()
        with pytest.raises(InvalidFrostBackupException, match="25 words"):
            frost.decode_backup(1, words[:24])


    @pytest.mark.parametrize("index", [-1, 2**32])
    def test_rejects_out_of_range_index(self, index):
        with pytest.raises(InvalidFrostBackupException, match="out of range"):
            frost.decode_backup(index, SHARES_2_OF_3[0][1].split())


    def test_accepts_whole_wallet_backup(self):
        """Key #0 carries the whole secret; it is a valid key number, not an error."""
        scalar, _ = frost.decode_backup(WHOLE_WALLET_BACKUP[0], WHOLE_WALLET_BACKUP[1].split())
        assert scalar.hex() == SECRET_1_OF_1


    def test_rejects_scalar_at_group_order(self):
        """A scalar at or above the group order is rejected, never reduced."""
        with pytest.raises(InvalidFrostBackupException, match="group order"):
            decode(SCALAR_OUT_OF_RANGE)



class TestRecoverSecret:
    def test_1_of_1(self):
        assert recover(SHARES_1_OF_1) == SECRET_1_OF_1


    def test_2_of_3_every_subset(self):
        for subset in itertools.combinations(SHARES_2_OF_3, 2):
            assert recover(list(subset)) == SECRET_2_OF_3


    def test_3_of_5_every_subset(self):
        for subset in itertools.combinations(SHARES_3_OF_5, 3):
            assert recover(list(subset)) == SECRET_3_OF_5


    def test_4_of_4(self):
        """A_3 carries no fingerprint bits, so this only passes if the check stops at 36."""
        assert recover(SHARES_4_OF_4) == SECRET_4_OF_4


    def test_detects_backups_from_different_wallets(self):
        """Individually valid backups that belong to different wallets must be rejected."""
        mixed = [SHARES_2_OF_3[0], SHARES_3_OF_5[1]]
        with pytest.raises(MismatchedFrostBackupsException, match="Fingerprint"):
            recover(mixed)


    def test_rejects_set_without_fingerprint(self):
        """Every checksum passes here; only the fingerprint shows these aren't a wallet."""
        with pytest.raises(MismatchedFrostBackupsException, match="Fingerprint"):
            recover(NO_FINGERPRINT)


    def test_detects_bad_poly_checksum(self):
        with pytest.raises(MismatchedFrostBackupsException, match="Polynomial checksum"):
            recover([SHARE_BAD_POLY, SHARES_2_OF_3[1]])


    def test_whole_wallet_backup(self):
        """A lone key #0 recovers the secret once its polynomial checksum verifies."""
        assert recover([WHOLE_WALLET_BACKUP]) == SECRET_1_OF_1


    def test_whole_wallet_backup_with_bad_poly_checksum(self):
        with pytest.raises(MismatchedFrostBackupsException, match="Polynomial checksum"):
            recover([WHOLE_WALLET_BACKUP_BAD_POLY])


    def test_whole_wallet_backup_not_mixed_with_shares(self):
        with pytest.raises(MismatchedFrostBackupsException, match="can't be combined"):
            recover([WHOLE_WALLET_BACKUP, SHARES_2_OF_3[0]])


    def test_rejects_duplicate_index(self):
        with pytest.raises(MismatchedFrostBackupsException, match="Duplicate"):
            recover([SHARES_2_OF_3[0], SHARES_2_OF_3[0]])


    def test_rejects_empty(self):
        with pytest.raises(MismatchedFrostBackupsException):
            frost.recover_secret([])


    def test_too_few_backups_is_rejected(self):
        """
        One backup of a 2-of-3 interpolates a degree-0 polynomial, whose commitment
        won't match the share's polynomial checksum.
        """
        with pytest.raises(MismatchedFrostBackupsException):
            recover([SHARES_2_OF_3[0]])



class TestFrostSeed:
    # The recovered scalar is the BIP-32 master key itself, so this pins the whole
    # chain: recovery -> zero chain code -> xprv.
    GOLDEN_XPRV = ("xprv9s21ZrQH143K24Mfq5zL5MhWK9hUhhGbd45hLXo2Pq2oqzMMo63oStZzF"
                   "93yjHmmfwkTW7jWmaf7X9aF3GP9D3mXSChQcm2zAZG6kerWdMw")

    def test_master_key_matches_spec(self):
        seed = FrostSeed(bytes.fromhex(SECRET_2_OF_3))
        assert seed.get_root().to_base58() == self.GOLDEN_XPRV


    def test_master_key_honors_network(self):
        seed = FrostSeed(bytes.fromhex(SECRET_2_OF_3))
        assert seed.get_root(SettingsConstants.TESTNET).to_base58().startswith("tprv")


    def test_chain_code_is_zero(self):
        """The spec pairs the recovered scalar with an all-zero chain code."""
        assert FrostSeed(bytes.fromhex(SECRET_2_OF_3)).get_root().chain_code == b"\x00" * 32


    def test_derives_spec_addresses(self):
        from seedsigner.helpers import embit_utils

        seed = FrostSeed(bytes.fromhex(SECRET_3_OF_5))
        xpub = seed.get_xpub(seed.derivation_override())
        assert str(xpub) == ("xpub6EQcKg7wXymMV5BfoZUAMcMSH5FewPThRnmd8Yh76L6iUCaiDfPBQ"
                             "LA81You9ouoMm3SKuhwptUoXb1VfihTDLVBJvx2nU6PUJ3Q9DKbMbQ")
        assert embit_utils.get_single_sig_address(xpub, SettingsConstants.TAPROOT, 0, False) == \
            "bc1pae0zyxchyndalaprtrc2yxw6rkpsdc7qguapj2kmzgz737dumtuse04mes"


    def test_recovered_backups_produce_expected_fingerprint(self):
        """End to end: words in, wallet fingerprint out."""
        for shares, expected in [(SHARES_2_OF_3[:2], "79b00088"),
                                 (SHARES_3_OF_5[:3], "66c1d857")]:
            seed = FrostSeed(bytes.fromhex(recover(shares)))
            assert seed.get_fingerprint() == expected


    def test_forces_spec_derivation_and_script_type(self):
        seed = FrostSeed(bytes.fromhex(SECRET_2_OF_3))
        assert seed.script_override == SettingsConstants.TAPROOT
        assert seed.derivation_override(SettingsConstants.SINGLE_SIG) == "m/0/0/0/0"
        assert seed.derivation_override(SettingsConstants.MULTISIG) == "m/0/0/0/0"


    def test_mnemonic_only_features_are_disabled(self):
        seed = FrostSeed(bytes.fromhex(SECRET_2_OF_3))
        assert seed.seedqr_supported is False
        assert seed.bip85_supported is False
        assert seed.passphrase_supported is False
        assert seed.backup_supported is False


    def test_passphrase_is_ignored(self):
        """No mnemonic means nothing to salt; setting one must not alter the key."""
        seed = FrostSeed(bytes.fromhex(SECRET_2_OF_3))
        seed.set_passphrase("anything")
        assert seed.has_passphrase is False
        assert seed.get_root().to_base58() == self.GOLDEN_XPRV


    @pytest.mark.parametrize("bad_secret", [
        b"\x00" * 32,                                   # zero scalar
        b"\xff" * 32,                                   # >= curve order
        b"\x01" * 31,                                   # too short
    ])
    def test_rejects_invalid_scalar(self, bad_secret):
        with pytest.raises(InvalidSeedException):
            FrostSeed(bad_secret)
