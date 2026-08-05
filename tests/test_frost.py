import itertools
import pytest

from seedsigner.helpers import frost
from seedsigner.helpers.frost import (
    InvalidFrostBackupException,
    MismatchedFrostBackupsException,
)


# Official test vectors, from the draft BIP and the frostsnap reference implementation.
# Each entry is (share_index, 25 words).

SHARES_1_OF_1 = [
    (1, "ABSURD AMOUNT DOCTOR ACOUSTIC AVOID LETTER ADVICE CAGE ABSURD AMOUNT DOCTOR ACOUSTIC AVOID LETTER ADVICE CAGE ABSURD AMOUNT DOCTOR ACOUSTIC AVOID LETTER ADVICE CURTAIN SOON"),
]
SECRET_1_OF_1 = "01" * 32

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

# SHARES_2_OF_3[0] with the final word changed from MOBILE to ABANDON.
CORRUPTED_WORDS = SHARES_2_OF_3[0][1].rsplit(" ", 1)[0] + " ABANDON"


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


    @pytest.mark.parametrize("index", [0, -1, 2**32])
    def test_rejects_out_of_range_index(self, index):
        with pytest.raises(InvalidFrostBackupException, match="out of range"):
            frost.decode_backup(index, SHARES_2_OF_3[0][1].split())



class TestRecoverSecret:
    def test_1_of_1(self):
        assert recover(SHARES_1_OF_1) == SECRET_1_OF_1


    def test_2_of_3_every_subset(self):
        for subset in itertools.combinations(SHARES_2_OF_3, 2):
            assert recover(list(subset)) == SECRET_2_OF_3


    def test_3_of_5_every_subset(self):
        for subset in itertools.combinations(SHARES_3_OF_5, 3):
            assert recover(list(subset)) == SECRET_3_OF_5


    def test_detects_backups_from_different_keys(self):
        """Individually valid backups that belong to different keys must be rejected."""
        mixed = [SHARES_2_OF_3[0], SHARES_3_OF_5[1]]
        with pytest.raises(MismatchedFrostBackupsException, match="Polynomial checksum"):
            recover(mixed)


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
