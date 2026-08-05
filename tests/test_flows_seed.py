from typing import Callable
from unittest.mock import patch
import pytest

# Must import test base before the Controller
from base import BaseTest, FlowTest, FlowStep
from base import FlowTestInvalidButtonDataSelectionException

from seedsigner.controller import Controller
from seedsigner.gui.screens.screen import RET_CODE__BACK_BUTTON, ButtonOption
from seedsigner.models.settings import Settings, SettingsConstants
from seedsigner.models.seed import ElectrumSeed, FrostSeed, Seed
from seedsigner.views.view import MainMenuView, OptionDisabledView, View, NetworkMismatchErrorView
from seedsigner.views import seed_views, scan_views, settings_views


def load_seed_into_decoder(view: scan_views.ScanView):
    view.decoder.add_data("0000" * 11 + "0003")



class TestSeedFlows(FlowTest):

    def test_scan_seedqr_flow(self):
        """
            Selecting "Scan" from the MainMenuView and scanning a SeedQR should enter the
            Finalize Seed flow and end at the SeedOptionsView.
        """
        self.run_sequence([
            FlowStep(MainMenuView, button_data_selection=MainMenuView.SCAN),
            FlowStep(scan_views.ScanView, before_run=load_seed_into_decoder),  # simulate read SeedQR; ret val is ignored
            FlowStep(seed_views.SeedFinalizeView, button_data_selection=seed_views.SeedFinalizeView.FINALIZE),
            FlowStep(seed_views.SeedOptionsView),
        ])


    def test_passphrase_entry_flow(self):
        """
        Opting to add a BIP-39 passphrase on the Finalize Seed screen should enter the
        passphrase entry / review flow and end at the SeedOptionsView. 
        """
        self.run_sequence([
            FlowStep(MainMenuView, button_data_selection=MainMenuView.SCAN),
            FlowStep(scan_views.ScanView, before_run=load_seed_into_decoder),  # simulate read SeedQR; ret val is ignored
            FlowStep(seed_views.SeedFinalizeView, button_data_selection=seed_views.SeedFinalizeView.PASSPHRASE),
            FlowStep(seed_views.SeedAddPassphraseView, screen_return_value=dict(passphrase="muhpassphrase", is_back_button=True)),
            FlowStep(seed_views.SeedAddPassphraseExitDialogView, button_data_selection=seed_views.SeedAddPassphraseExitDialogView.DISCARD),
            FlowStep(seed_views.SeedFinalizeView, button_data_selection=seed_views.SeedFinalizeView.PASSPHRASE),
            FlowStep(seed_views.SeedAddPassphraseView, screen_return_value=dict(passphrase="muhpassphrase", is_back_button=True)),
            FlowStep(seed_views.SeedAddPassphraseExitDialogView, button_data_selection=seed_views.SeedAddPassphraseExitDialogView.EDIT),
            FlowStep(seed_views.SeedAddPassphraseView, screen_return_value=dict(passphrase="muhpassphrase")),
            FlowStep(seed_views.SeedReviewPassphraseView, button_data_selection=seed_views.SeedReviewPassphraseView.EDIT),
            FlowStep(seed_views.SeedAddPassphraseView, screen_return_value=dict(passphrase="muhpassphrase")),
            FlowStep(seed_views.SeedReviewPassphraseView, button_data_selection=seed_views.SeedReviewPassphraseView.DONE),
            FlowStep(seed_views.SeedOptionsView),
        ])


    def test_mnemonic_entry_flow(self):
        """
            Manually entering a mnemonic should land at the Finalize Seed flow and end at
            the SeedOptionsView.
        """
        def test_with_mnemonic(mnemonic):
            sequence = [
                FlowStep(MainMenuView, button_data_selection=MainMenuView.SEEDS),
                FlowStep(seed_views.SeedsMenuView, is_redirect=True),  # When no seeds are loaded it auto-redirects to LoadSeedView
                FlowStep(seed_views.LoadSeedView, button_data_selection=seed_views.LoadSeedView.TYPE_12WORD if len(mnemonic) == 12 else seed_views.LoadSeedView.TYPE_24WORD),
            ]

            # Now add each manual word entry step
            for word in mnemonic:
                sequence.append(
                    FlowStep(seed_views.SeedMnemonicEntryView, screen_return_value=word)
                )
            
            # With the mnemonic completely entered, we land on the SeedFinalizeView
            sequence += [
                FlowStep(seed_views.SeedFinalizeView, button_data_selection=seed_views.SeedFinalizeView.FINALIZE),
                FlowStep(seed_views.SeedOptionsView),
            ]

            self.run_sequence(sequence)

        # Test data from iancoleman.io; 12- and 24-word mnemonic
        test_with_mnemonic("tone flat shed cool census soul paddle boy flight fantasy stem social".split())

        BaseTest.reset_controller()

        test_with_mnemonic("cotton artefact spy mind wing there echo steak child oak awful host despair online bicycle divorce middle firm diamond rare execute chimney almost hollow".split())


    def test_invalid_mnemonic(self):
        """ Should be able to go back and edit or discard an invalid mnemonic """
        # Test data from iancoleman.io
        mnemonic = "blush twice taste dawn feed second opinion lazy thumb play neglect impact".split()
        sequence = [
            FlowStep(MainMenuView, button_data_selection=MainMenuView.SEEDS),
            FlowStep(seed_views.SeedsMenuView, is_redirect=True),  # When no seeds are loaded it auto-redirects to LoadSeedView
            FlowStep(seed_views.LoadSeedView, button_data_selection=seed_views.LoadSeedView.TYPE_12WORD if len(mnemonic) == 12 else seed_views.LoadSeedView.TYPE_24WORD),
        ]
        for word in mnemonic[:-1]:
            sequence.append(FlowStep(seed_views.SeedMnemonicEntryView, screen_return_value=word))

        sequence += [
            FlowStep(seed_views.SeedMnemonicEntryView, screen_return_value="zoo"),  # But finish with an INVALID checksum word
            FlowStep(seed_views.SeedMnemonicInvalidView, button_data_selection=seed_views.SeedMnemonicInvalidView.EDIT),
        ]

        # Restarts from first word
        for word in mnemonic[:-1]:
            sequence.append(FlowStep(seed_views.SeedMnemonicEntryView, screen_return_value=word))

        sequence += [
            FlowStep(seed_views.SeedMnemonicEntryView, screen_return_value="zebra"),  # provide yet another invalid checksum word
            FlowStep(seed_views.SeedMnemonicInvalidView, button_data_selection=seed_views.SeedMnemonicInvalidView.DISCARD),
            FlowStep(MainMenuView),
        ]

        self.run_sequence(sequence)


    def test_electrum_mnemonic_entry_flow(self):
        """
            Manually entering an Electrum mnemonic should land at the Finalize Seed flow and end at
            the SeedOptionsView.

            Most BIP-39 mnemonics should generate an error if entered as Electrum seeds.
        """
        def test_with_mnemonic(mnemonic: list[str], custom_extension: str = None, expects_electrum_seed_is_valid: bool = True):
            settings = Settings.get_instance()
            settings.set_value(SettingsConstants.SETTING__ELECTRUM_SEEDS, SettingsConstants.OPTION__ENABLED)

            sequence = [
                FlowStep(MainMenuView, button_data_selection=MainMenuView.SEEDS),
                FlowStep(seed_views.SeedsMenuView, is_redirect=True),  # When no seeds are loaded it auto-redirects to LoadSeedView
                FlowStep(seed_views.LoadSeedView, button_data_selection=seed_views.LoadSeedView.TYPE_ELECTRUM),
                FlowStep(seed_views.SeedElectrumMnemonicStartView),  # Warning screen; no relevant button data selection.
            ]

            # Now add each manual word entry step
            for word in mnemonic:
                sequence.append(
                    FlowStep(seed_views.SeedMnemonicEntryView, screen_return_value=word)
                )

            if expects_electrum_seed_is_valid:
                # With the mnemonic completely entered, we land on the SeedFinalizeView
                if custom_extension:
                    sequence += [
                        FlowStep(seed_views.SeedFinalizeView, screen_return_value=1),  # The passphrase / custom extension button is dynamic so there's no constant to refer to here
                        FlowStep(seed_views.SeedAddPassphraseView, screen_return_value=dict(passphrase=custom_extension)),  # This is a one-off oddity where the Screen returns dict instead of int | str
                        FlowStep(seed_views.SeedReviewPassphraseView, button_data_selection=seed_views.SeedReviewPassphraseView.DONE),
                        FlowStep(seed_views.SeedOptionsView),
                    ]
                else:
                    sequence += [
                        FlowStep(seed_views.SeedFinalizeView, button_data_selection=seed_views.SeedFinalizeView.FINALIZE),
                        FlowStep(seed_views.SeedOptionsView),
                    ]

            else:
                # Or we bomb out if the mnemonic is invalid for Electrum
                sequence.append(FlowStep(seed_views.SeedMnemonicInvalidView, button_data_selection=seed_views.SeedMnemonicInvalidView.DISCARD))

            self.run_sequence(sequence)

            BaseTest.reset_controller()


        # Test seeds generated by Electrum v4.5.5
        test_with_mnemonic("bomb congress scorpion mutual word stamp tongue valid permit salmon yellow spy".split())
        test_with_mnemonic("morning pretty hobby click extend color wait joke define sausage boost salmon".split())
        test_with_mnemonic("basket print toy noodle betray weird filter ticket insect copy force machine".split())
        test_with_mnemonic("basket print toy noodle betray weird filter ticket insect copy force machine".split(), custom_extension="test")
        test_with_mnemonic("basket print toy noodle betray weird filter ticket insect copy force machine".split(), custom_extension="monkey fling orange coin good")

        # Most BIP-39 seeds should fail; test seed generated by bitcoiner.guide
        test_with_mnemonic("pioneer divide volcano art victory family grow novel mandate bicycle senior adjust".split(), expects_electrum_seed_is_valid=False)


    def test_export_xpub_standard_flow(self):
        """
            Selecting "Export XPUB" from the SeedOptionsView should enter the Export XPUB flow and end at the MainMenuView
        """
        def flowtest_standard_xpub(sig_tuple, script_tuple, xpub_qr_tuple):
            if sig_tuple[0] == SettingsConstants.SINGLE_SIG:
                sig_selection = seed_views.SeedExportXpubSigTypeView.SINGLE_SIG
            else:
                sig_selection = seed_views.SeedExportXpubSigTypeView.MULTISIG
            self.run_sequence(
                initial_destination_view_args=dict(seed=seed),
                sequence=[
                    FlowStep(seed_views.SeedOptionsView, button_data_selection=seed_views.SeedOptionsView.EXPORT_XPUB),
                    FlowStep(seed_views.SeedExportXpubSigTypeView, button_data_selection=sig_selection),
                    FlowStep(seed_views.SeedExportXpubScriptTypeView, button_data_selection=ButtonOption(script_tuple[1], return_data=script_tuple[0])),
                    FlowStep(seed_views.SeedExportXpubQRFormatView, button_data_selection=ButtonOption(xpub_qr_tuple[1], return_data=xpub_qr_tuple[0])),
                    FlowStep(seed_views.SeedExportXpubWarningView, screen_return_value=0),
                    FlowStep(seed_views.SeedExportXpubDetailsView, screen_return_value=0),
                    FlowStep(seed_views.SeedExportXpubQRDisplayView, screen_return_value=0),
                    FlowStep(MainMenuView),
                ]
        )
            
        # Load a finalized Seed into the Controller
        seed = Seed(mnemonic="blush twice taste dawn feed second opinion lazy thumb play neglect impact".split())
        self.controller.storage.set_pending_seed(seed)
        self.controller.storage.finalize_pending_seed()

        # these are lists of (constant_value, display_name) tuples
        sig_types: list[tuple[str, str]] = SettingsConstants.ALL_SIG_TYPES
        script_types: list[tuple[str, str]] = SettingsConstants.ALL_SCRIPT_TYPES
        xpub_qr_formats: list[tuple[str, str]] = SettingsConstants.ALL_XPUB_QR_FORMATS

        # enable non-defaults so they're available in views
        self.settings.set_value(SettingsConstants.SETTING__SIG_TYPES, [x for x,y in sig_types])
        self.settings.set_value(SettingsConstants.SETTING__SCRIPT_TYPES, [x for x,y in script_types])
        self.settings.set_value(SettingsConstants.SETTING__XPUB_QR_FORMAT, [x for x,y in xpub_qr_formats])

        # exhaustively test flows thru standard sig_types, script_types, and xpub_qr_formats
        for sig_tuple in sig_types:
            for script_tuple in script_types:
                for xpub_qr_tuple in xpub_qr_formats:
                    # skip custom derivation
                    if script_tuple[0] == SettingsConstants.CUSTOM_DERIVATION:
                        continue 
                    # skip multisig taproot
                    elif sig_tuple[0] == SettingsConstants.MULTISIG and script_tuple[0] == SettingsConstants.TAPROOT:
                        continue
                    else:
                        print('\n\ntest_standard_xpubs(%s, %s, %s)' % (sig_tuple, script_tuple, xpub_qr_tuple))
                        flowtest_standard_xpub(sig_tuple, script_tuple, xpub_qr_tuple)


    def test_export_xpub_disabled_not_available_flow(self):
        """
            If sig_type/script_type/xpub_qr_format disabled, then these options are not available
        """
        # Load a finalized Seed into the Controller
        seed = Seed(mnemonic="blush twice taste dawn feed second opinion lazy thumb play neglect impact".split())
        self.controller.storage.set_pending_seed(seed)
        self.controller.storage.finalize_pending_seed()

        # these are lists of (constant_value, display_name) tuples
        sig_types: list[tuple[str, str]] = SettingsConstants.ALL_SIG_TYPES
        script_types: list[tuple[str, str]] = SettingsConstants.ALL_SCRIPT_TYPES
        xpub_qr_formats: list[tuple[str, str]] = SettingsConstants.ALL_XPUB_QR_FORMATS

        # these are the disabled types that we will be testing
        disabled_sig = SettingsConstants.MULTISIG
        disabled_script = SettingsConstants.TAPROOT
        disabled_xpub_qr_format = SettingsConstants.XPUB_QR_FORMAT__SPECTER_LEGACY

        # enable all but our target disabled type
        self.settings.set_value(SettingsConstants.SETTING__SIG_TYPES, [x for x,y in sig_types if x!=disabled_sig])
        self.settings.set_value(SettingsConstants.SETTING__SCRIPT_TYPES, [x for x,y in script_types if x!=disabled_script])
        self.settings.set_value(SettingsConstants.SETTING__XPUB_QR_FORMAT, [x for x,y in xpub_qr_formats if x!=disabled_xpub_qr_format])

        # If multisig isn't an option, then the sig type selection is skipped altogether
        self.run_sequence(
            initial_destination_view_args=dict(seed=seed),
            sequence=[
                FlowStep(seed_views.SeedOptionsView, button_data_selection=seed_views.SeedOptionsView.EXPORT_XPUB),
                FlowStep(seed_views.SeedExportXpubSigTypeView, is_redirect=True),
                FlowStep(seed_views.SeedExportXpubScriptTypeView),
            ]
        )

        # test that taproot is not an option via exception raised when choice is taproot
        with pytest.raises(FlowTestInvalidButtonDataSelectionException) as e:
            self.run_sequence(
                initial_destination_view_args=dict(seed=seed),
                sequence=[
                    FlowStep(seed_views.SeedOptionsView, button_data_selection=seed_views.SeedOptionsView.EXPORT_XPUB),
                    FlowStep(seed_views.SeedExportXpubSigTypeView, is_redirect=True),
                    FlowStep(seed_views.SeedExportXpubScriptTypeView, button_data_selection=disabled_script),
                ]
            )

        # test that nunchuk is not an option via exception raised when choice is nunchuk
        with pytest.raises(FlowTestInvalidButtonDataSelectionException) as e:
            self.run_sequence(
                initial_destination_view_args=dict(seed=seed),
                sequence=[
                    FlowStep(seed_views.SeedOptionsView, button_data_selection=seed_views.SeedOptionsView.EXPORT_XPUB),
                    FlowStep(seed_views.SeedExportXpubSigTypeView, is_redirect=True),
                    FlowStep(seed_views.SeedExportXpubScriptTypeView, screen_return_value=0),
                    FlowStep(seed_views.SeedExportXpubQRFormatView, button_data_selection=disabled_xpub_qr_format),
                ]
            )


    def test_export_xpub_custom_derivation_flow(self):
        """
            Export XPUB flow for custom derivation finishes at MainMenuView
        """
        # Load a finalized Seed into the Controller
        seed = Seed(mnemonic="blush twice taste dawn feed second opinion lazy thumb play neglect impact".split())
        self.controller.storage.set_pending_seed(seed)
        self.controller.storage.finalize_pending_seed()

        # enable custom derivation script_type setting (plus at least one more for a choice)
        self.settings.set_value(SettingsConstants.SETTING__SCRIPT_TYPES, [
            SettingsConstants.NATIVE_SEGWIT, 
            SettingsConstants.NESTED_SEGWIT,
            SettingsConstants.CUSTOM_DERIVATION
        ])

        # Ensure that all xpub_qr_formats are enabled
        self.settings.set_value(SettingsConstants.SETTING__XPUB_QR_FORMAT, [x for x, y in SettingsConstants.ALL_XPUB_QR_FORMATS])

        # Set up button_data selections
        sig_type = seed_views.SeedExportXpubSigTypeView.SINGLE_SIG

        custom_derivation = SettingsConstants.CUSTOM_DERIVATION
        script_type = ButtonOption(self.settings.get_multiselect_value_display_names(SettingsConstants.SETTING__SCRIPT_TYPES)[2], return_data=custom_derivation)

        specter_legacy = SettingsConstants.XPUB_QR_FORMAT__SPECTER_LEGACY
        assert SettingsConstants.ALL_XPUB_QR_FORMATS[2][0] == specter_legacy
        xpub_qr_format = ButtonOption(self.settings.get_multiselect_value_display_names(SettingsConstants.SETTING__XPUB_QR_FORMAT)[2], return_data=specter_legacy)

        self.run_sequence(
            initial_destination_view_args=dict(seed=seed),
            sequence=[
                FlowStep(seed_views.SeedOptionsView, button_data_selection=seed_views.SeedOptionsView.EXPORT_XPUB),
                FlowStep(seed_views.SeedExportXpubSigTypeView, button_data_selection=sig_type),
                FlowStep(seed_views.SeedExportXpubScriptTypeView, button_data_selection=script_type),
                FlowStep(seed_views.SeedExportXpubCustomDerivationView, screen_return_value="m/0'/0'"),
                FlowStep(seed_views.SeedExportXpubQRFormatView, button_data_selection=xpub_qr_format),
                FlowStep(seed_views.SeedExportXpubWarningView, screen_return_value=0),
                FlowStep(seed_views.SeedExportXpubDetailsView, screen_return_value=0),
                FlowStep(seed_views.SeedExportXpubQRDisplayView, screen_return_value=0),
                FlowStep(MainMenuView),
            ]
        )


    def test_export_xpub_skip_non_option_flow(self):
        """
            Export XPUB flows w/o user choices when no other options for sig_types, script_types, and/or xpub_qr_formats
        """
        # Load a finalized Seed into the Controller
        seed = Seed(mnemonic="blush twice taste dawn feed second opinion lazy thumb play neglect impact".split())
        self.controller.storage.set_pending_seed(seed)
        self.controller.storage.finalize_pending_seed()

        # exclusively set only one choice for each of sig_types, script_types and xpub_qr_formats
        self.settings.update({
            SettingsConstants.SETTING__SIG_TYPES: SettingsConstants.MULTISIG,
            SettingsConstants.SETTING__SCRIPT_TYPES: SettingsConstants.NESTED_SEGWIT,
            SettingsConstants.SETTING__XPUB_QR_FORMAT: SettingsConstants.XPUB_QR_FORMAT__UR_CRYPTO_ACCOUNT,
        })

        self.run_sequence(
            initial_destination_view_args=dict(seed=seed),
            sequence=[
                FlowStep(seed_views.SeedOptionsView, button_data_selection=seed_views.SeedOptionsView.EXPORT_XPUB),
                FlowStep(seed_views.SeedExportXpubSigTypeView, is_redirect=True),
                FlowStep(seed_views.SeedExportXpubScriptTypeView, is_redirect=True),
                FlowStep(seed_views.SeedExportXpubQRFormatView, is_redirect=True),
                FlowStep(seed_views.SeedExportXpubWarningView, screen_return_value=0),
                FlowStep(seed_views.SeedExportXpubDetailsView, screen_return_value=0),
                FlowStep(seed_views.SeedExportXpubQRDisplayView, screen_return_value=0),
                FlowStep(MainMenuView),
            ]
        )


    def test_export_xpub_electrum_seed_flow(self):
        """
            Electrum seeds should skip script type selection
        """            
        # Load a finalized Seed into the Controller
        self.controller.storage.init_pending_mnemonic(num_words=12, is_electrum=True)
        seed = ElectrumSeed(mnemonic="regular reject rare profit once math fringe chase until ketchup century escape".split())
        self.controller.storage.set_pending_seed(seed)
        self.controller.storage.finalize_pending_seed()

        # Make sure all options are enabled
        self.settings.set_value(SettingsConstants.SETTING__SIG_TYPES, [x for x,y in SettingsConstants.ALL_SIG_TYPES])
        self.settings.set_value(SettingsConstants.SETTING__SCRIPT_TYPES, [x for x,y in SettingsConstants.ALL_SCRIPT_TYPES])
        self.settings.set_value(SettingsConstants.SETTING__XPUB_QR_FORMAT, [x for x,y in SettingsConstants.ALL_XPUB_QR_FORMATS])

        self.run_sequence(
            initial_destination_view_args=dict(seed=seed),
            sequence=[
                FlowStep(seed_views.SeedOptionsView, button_data_selection=seed_views.SeedOptionsView.EXPORT_XPUB),
                FlowStep(seed_views.SeedExportXpubSigTypeView, button_data_selection=seed_views.SeedExportXpubSigTypeView.SINGLE_SIG),

                # Skips past the script type options via redirect
                FlowStep(seed_views.SeedExportXpubScriptTypeView, is_redirect=True),
                FlowStep(seed_views.SeedExportXpubQRFormatView, button_data_selection=ButtonOption(self.settings.get_multiselect_value_display_names(SettingsConstants.SETTING__XPUB_QR_FORMAT)[0], return_data=SettingsConstants.ALL_XPUB_QR_FORMATS[0][0])),
                FlowStep(seed_views.SeedExportXpubWarningView, screen_return_value=0),
                FlowStep(seed_views.SeedExportXpubDetailsView, screen_return_value=0),
                FlowStep(seed_views.SeedExportXpubQRDisplayView, screen_return_value=0),
                FlowStep(MainMenuView),
            ]
        )


    def test_discard_seed_flow(self):
        """
            Selecting "Discard Seed" from the SeedOptionsView should enter the Discard Seed flow and 
            remove the in-memory seed from the Controller.
        """
        # Load a finalized Seed into the Controller
        seed = Seed(mnemonic="blush twice taste dawn feed second opinion lazy thumb play neglect impact".split())
        self.controller.storage.set_pending_seed(seed)
        self.controller.storage.finalize_pending_seed()

        self.run_sequence(
            initial_destination_view_args=dict(seed=seed),
            sequence=[
                FlowStep(seed_views.SeedOptionsView, button_data_selection=seed_views.SeedOptionsView.DISCARD),
                FlowStep(seed_views.SeedDiscardView, button_data_selection=seed_views.SeedDiscardView.DISCARD),
                FlowStep(MainMenuView, button_data_selection=MainMenuView.SEEDS),
                FlowStep(seed_views.SeedsMenuView, is_redirect=True),  # When no seeds are loaded it auto-redirects to LoadSeedView
                FlowStep(seed_views.LoadSeedView),
            ]
        )


    @patch("seedsigner.gui.screens.seed_screens.SeedTranscribeSeedQRZoomedInScreen", autospec=True)
    def test_transcribe_seedqr_and_verify(self, mock_zoomed_in_screen: Callable):
        """
        """
        # Load a finalized Seed into the Controller
        mnemonic = ["abandon"] * 11 + ["about"]
        self.controller.storage.set_pending_seed(Seed(mnemonic=mnemonic))
        self.controller.storage.finalize_pending_seed()

        def load_wrong_seed_into_decoder(view: View):
            view.decoder.add_data("0138" * 24)

        def load_completely_wrong_qr_type_into_decoder(view: View):
            view.decoder.add_data("I like cheese")

        def load_recognized_qr_type_isnot_seed_into_decoder(view: View):
            view.decoder.add_data("UR:CRYPTO-PSBT/HKADHEJOJKIDJYZMADAEGMAOAEAEAEADHHGLEYKGBDSBKEMTSARLVYSGIABEDELFSKWLLUDKLYESJOFDLPJPFXSOHHWZTYWEAEAEAEAEAEZCZMZMZMADBKBZJEDEHEAEAEAECMAEBBVEPFDWDMBBGSPFZTKIMYCLKPSOBDDTRDWTWPYKGAQDKNAEAEGWADAAECLTTKAXWSWTUTSNLAAEAEAEPKCTBSHGISSSRETIVEWSGYNEPTHTESNSWMLBTARYEMHTBTBTLNWSBKJLMKYNFGHLAXJYBBTTIDHKDICHAMLEHHDSRKATGDLYSBIYHNHDNEWPJKZSZMDKVETYNSGOCXKNDNBEOLFSRSNSGHAEAELAADAEAELAAEAEAELAAEADADCTKSBZJEDEHEAEAEAECMAEBBVEPFDWDMBBGSPFZTKIMYCLKPSOBDDTRDWTWPYKGAADAXAAADAEAEAECPAMAODSFTLDTYFRECSKVWYLKNBANNKKZCRTHYJTPSHLHNHKNBPDCLCFDMSOLPDKFXLFQZCSOLFSRSNSGHAEAELAADAEAELAAEAEAELAAEAEAEAEAEAEAEAEAECPAOAODSFTLDTYFRECSKVWYLKNBANNKKZCRTHYJTPSHLHNHKNBPDCLCFDMSOLPDKFXLFQZCSOLFSRSNSGHAEAELAADAEAELAAEAEAELAAEAEAEAEAEAEAEAEAELGMKFZCW")        

        def load_right_seed_into_decoder(view: View):
            view.decoder.add_data("0000" * 11 + "0003")

        self.run_sequence([
            FlowStep(MainMenuView, button_data_selection=MainMenuView.SEEDS),
            FlowStep(seed_views.SeedsMenuView, screen_return_value=0),
            FlowStep(seed_views.SeedOptionsView, button_data_selection=seed_views.SeedOptionsView.BACKUP),
            FlowStep(seed_views.SeedBackupView, button_data_selection=seed_views.SeedBackupView.EXPORT_SEEDQR),
            FlowStep(seed_views.SeedTranscribeSeedQRFormatView, button_data_selection=seed_views.SeedTranscribeSeedQRFormatView.STANDARD_12),
            FlowStep(seed_views.SeedTranscribeSeedQRWarningView),
            FlowStep(seed_views.SeedTranscribeSeedQRWholeQRView),
            FlowStep(seed_views.SeedTranscribeSeedQRZoomedInView),
            FlowStep(seed_views.SeedTranscribeSeedQRConfirmQRPromptView, button_data_selection=seed_views.SeedTranscribeSeedQRConfirmQRPromptView.SCAN),

            # Intentionally "scan" the wrong SeedQR
            FlowStep(seed_views.SeedTranscribeSeedQRConfirmScanView, before_run=load_wrong_seed_into_decoder),
            FlowStep(seed_views.SeedTranscribeSeedQRConfirmWrongSeedView),
            FlowStep(seed_views.SeedTranscribeSeedQRZoomedInView),

            # Intentionally scan QR data that makes no sense for this flow
            FlowStep(seed_views.SeedTranscribeSeedQRConfirmQRPromptView, button_data_selection=seed_views.SeedTranscribeSeedQRConfirmQRPromptView.SCAN),
            FlowStep(seed_views.SeedTranscribeSeedQRConfirmScanView, before_run=load_completely_wrong_qr_type_into_decoder),
            FlowStep(seed_views.SeedTranscribeSeedQRConfirmInvalidQRView),
            FlowStep(seed_views.SeedTranscribeSeedQRZoomedInView),

            # Intentionally scan QR data that makes no sense for this flow because is another QR recognized but is not a SeedQR (e.g., bitcoin address, psbt)
            FlowStep(seed_views.SeedTranscribeSeedQRConfirmQRPromptView, button_data_selection=seed_views.SeedTranscribeSeedQRConfirmQRPromptView.SCAN),
            FlowStep(seed_views.SeedTranscribeSeedQRConfirmScanView, before_run=load_recognized_qr_type_isnot_seed_into_decoder),
            FlowStep(seed_views.SeedTranscribeSeedQRConfirmInvalidQRView),
            FlowStep(seed_views.SeedTranscribeSeedQRZoomedInView),
            
            # Now scan the correct SeedQR
            FlowStep(seed_views.SeedTranscribeSeedQRConfirmQRPromptView, button_data_selection=seed_views.SeedTranscribeSeedQRConfirmQRPromptView.SCAN),
            FlowStep(seed_views.SeedTranscribeSeedQRConfirmScanView, before_run=load_right_seed_into_decoder),
            FlowStep(seed_views.SeedTranscribeSeedQRConfirmSuccessView),
            FlowStep(seed_views.SeedOptionsView),
        ])

    def test_transcribe_seedqr_screensaver_startable_status(self):
        """
            The controller should return False for screensaver startable status when SeedTranscribeSeedQRZoomedInView
            is active.
        """
        # Load a finalized Seed into the Controller
        mnemonic = ["abandon"] * 11 + ["about"]
        seed = Seed(mnemonic=mnemonic)
        self.controller.storage.set_pending_seed(seed)
        self.controller.storage.finalize_pending_seed()

        self.run_sequence(
            initial_destination_view_args={'num_modules': 21, 'seed': seed, 'seedqr_format': 'seed__seedqr'},
            sequence=[
                FlowStep(seed_views.SeedTranscribeSeedQRWholeQRView),
                FlowStep(seed_views.SeedTranscribeSeedQRZoomedInView, is_redirect=True),  # Live interactive screens are a bit weird; not sure why `is_redirect` is necessary here
        ])

        assert self.controller.is_screensaver_start_allowed == False



class TestSeedEntryBackFlows(FlowTest):
    """
    Tests for every BACK exit scenario from SeedMnemonicEntryView and related views.
    
    A naive BackStackView swap can leave resume_main_flow dangling, causing
    auto-redirects on stale flow state. These tests verify that BACK navigation
    returns to the correct parent view AND that no flow state leaks.
    """

    def test_back_from_seed_entry_first_word(self):
        """
        Pressing BACK on the first word of mnemonic entry should return to
        the View that initiated the mnemonic entry process.
        """
        for seed_type in [seed_views.LoadSeedView.TYPE_12WORD, seed_views.LoadSeedView.TYPE_24WORD]:
            self.run_sequence([
                FlowStep(MainMenuView, button_data_selection=MainMenuView.SEEDS),
                FlowStep(seed_views.SeedsMenuView, is_redirect=True),  # No seeds loaded; auto-redirects to LoadSeedView
                FlowStep(seed_views.LoadSeedView, button_data_selection=seed_type),
                FlowStep(seed_views.SeedMnemonicEntryView, screen_return_value=RET_CODE__BACK_BUTTON),
                FlowStep(seed_views.LoadSeedView),  # Should land here, NOT MainMenuView
            ])
            BaseTest.reset_controller()


    def test_back_from_seed_entry_mid_word(self):
        """
        Pressing BACK from a middle word (eg. word #2) should return to the
        previous SeedMnemonicEntryView (eg. word #1) via the back stack.
        """
        self.run_sequence([
            FlowStep(MainMenuView, button_data_selection=MainMenuView.SEEDS),
            FlowStep(seed_views.SeedsMenuView, is_redirect=True),
            FlowStep(seed_views.LoadSeedView, button_data_selection=seed_views.LoadSeedView.TYPE_12WORD),
            FlowStep(seed_views.SeedMnemonicEntryView, screen_return_value="abandon"),  # word #1
            FlowStep(seed_views.SeedMnemonicEntryView, screen_return_value=RET_CODE__BACK_BUTTON),  # BACK from word #2
            FlowStep(seed_views.SeedMnemonicEntryView),  # Returns to word #1
        ])

        # Verify we're back on word #1: word at index 0 should still be set
        # from the previous entry, while word at index 1 should be unset.
        assert self.controller.storage.get_pending_mnemonic_word(0) == "abandon"
        assert self.controller.storage.get_pending_mnemonic_word(1) is None


    def test_back_from_seed_entry_via_seed_select(self):
        """
        Backing out of mnemonic entry during an active flow must preserve
        `resume_main_flow` so the user remains within that flow.
        """
        from seedsigner.controller import Controller
        from seedsigner.models.settings import SettingsConstants

        self.settings.set_value(SettingsConstants.SETTING__MESSAGE_SIGNING, SettingsConstants.OPTION__ENABLED)

        def load_signmessage_into_decoder(view):
            view.decoder.add_data("signmessage m/84h/0h/0h/0/0 ascii:test message")

        self.run_sequence([
            FlowStep(MainMenuView, button_data_selection=MainMenuView.SCAN),
            FlowStep(scan_views.ScanView, before_run=load_signmessage_into_decoder),
            FlowStep(seed_views.SeedSignMessageStartView, is_redirect=True),
            FlowStep(seed_views.SeedSelectSeedView, button_data_selection=seed_views.SeedSelectSeedView.TYPE_12WORD),
            FlowStep(seed_views.SeedMnemonicEntryView, screen_return_value=RET_CODE__BACK_BUTTON),  # BACK on first word
            FlowStep(seed_views.SeedSelectSeedView),  # Should return here, in the sign message flow
        ])

        # Verify resume_main_flow is still set — user is still in the sign message flow
        assert self.controller.resume_main_flow == Controller.FLOW__SIGN_MESSAGE




class TestMessageSigningFlows(FlowTest):
    MAINNET_DERIVATION_PATH = "m/84h/0h/0h/0/0"
    TESTNET_DERIVATION_PATH = "m/84h/1h/0h/0/0"
    CUSTOM_DERIVATION_PATH = "m/99h/0/0"
    SHORT_MESSAGE = "I attest that I control this bitcoin address blah blah blah"
    NO_WHITESPACE_MESSAGE = """{"height":841407,"lightning_bolt12":"lno1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}"""
    MULTIPAGE_MESSAGE = """Chancellor on brink of second bailout for banks

        Billions may be needed as lending squeeze tightens

        Alistair Darling has been forced to consider a second bailout for banks as the lending drought worsens.

        The Chancellor will decide within weeks whether to pump billions more into the economy as evidence mounts that the £37 billion part-nationalisation last year has failed to keep credit flowing. Options include cash injections, offering banks cheaper state guarantees to raise money privately or buying up “toxic assets”, The Times has learnt."""


    def load_seed_into_decoder(self, view: scan_views.ScanView):
        view.decoder.add_data("0000" * 11 + "0003")


    def load_signmessage_into_decoder(self, view:View, derivation_path: str, message: str):
        view.decoder.add_data(f"signmessage {derivation_path} ascii:{message}")


    def load_short_message_into_decoder(self, view: View):
        self.load_signmessage_into_decoder(view, self.MAINNET_DERIVATION_PATH, self.SHORT_MESSAGE)


    def load_testnet_message_into_decoder(self, view: View):
        self.load_signmessage_into_decoder(view, self.TESTNET_DERIVATION_PATH, self.SHORT_MESSAGE)


    def load_multipage_message_into_decoder(self, view: View):
        self.load_signmessage_into_decoder(view, self.MAINNET_DERIVATION_PATH, self.MULTIPAGE_MESSAGE)


    def load_no_whitespace_message_into_decoder(self, view: View):
        self.load_signmessage_into_decoder(view, self.MAINNET_DERIVATION_PATH, self.NO_WHITESPACE_MESSAGE)


    def load_custom_derivation_into_decoder(self, view: View):
        self.load_signmessage_into_decoder(view, self.CUSTOM_DERIVATION_PATH, self.SHORT_MESSAGE)


    def inject_mesage_as_paged_message(self, view: View):
        # Because the Screen won't actually run, we have to do the Screen's work here
        from seedsigner.gui.components import reflow_text_into_pages, GUIConstants
        paged = reflow_text_into_pages(
            text=self.controller.sign_message_data["message"],
            width=240 - 2*GUIConstants.EDGE_PADDING,
            height=240 - GUIConstants.TOP_NAV_HEIGHT - 3*GUIConstants.EDGE_PADDING - GUIConstants.BUTTON_HEIGHT,
        )
        self.controller.sign_message_data["paged_message"] = paged


    def test_sign_message_flow(self):
        """
        Should scan a `signmessage` QR and complete the message review, address review,
        and signing flow.
        """
        # Ensure message signing is enabled
        self.settings.set_value(SettingsConstants.SETTING__MESSAGE_SIGNING, SettingsConstants.OPTION__ENABLED)

        # Scenario 1: Load the mesage first, then the seed
        self.run_sequence([
            FlowStep(MainMenuView, button_data_selection=MainMenuView.SCAN),
            FlowStep(scan_views.ScanView, before_run=self.load_short_message_into_decoder),  # simulate read message QR; ret val is ignored
            FlowStep(seed_views.SeedSignMessageStartView, is_redirect=True),
            FlowStep(seed_views.SeedSelectSeedView, button_data_selection=seed_views.SeedSelectSeedView.SCAN_SEED),
            FlowStep(scan_views.ScanView, before_run=self.load_seed_into_decoder),  # simulate read SeedQR; ret val is ignored
            FlowStep(seed_views.SeedFinalizeView, button_data_selection=seed_views.SeedFinalizeView.FINALIZE),
            FlowStep(seed_views.SeedOptionsView, is_redirect=True),
            FlowStep(seed_views.SeedSignMessageConfirmMessageView, before_run=self.inject_mesage_as_paged_message, screen_return_value=0),
            FlowStep(seed_views.SeedSignMessageConfirmAddressView, screen_return_value=0),
            FlowStep(seed_views.SeedSignMessageSignedMessageQRView, screen_return_value=0),
            FlowStep(MainMenuView),
        ])

        # Scenario 2: Scan the seed first, then select Sign Message
        self.controller.discard_seed(self.controller.storage.seeds[0])
        self.run_sequence([
            FlowStep(MainMenuView, button_data_selection=MainMenuView.SCAN),
            FlowStep(scan_views.ScanView, before_run=self.load_seed_into_decoder),  # simulate read SeedQR; ret val is ignored
            FlowStep(seed_views.SeedFinalizeView, button_data_selection=seed_views.SeedFinalizeView.FINALIZE),
            FlowStep(seed_views.SeedOptionsView, button_data_selection=seed_views.SeedOptionsView.SIGN_MESSAGE),
            FlowStep(scan_views.ScanView, before_run=self.load_short_message_into_decoder),  # simulate read message QR; ret val is ignored
            FlowStep(seed_views.SeedSignMessageStartView, is_redirect=True),
            FlowStep(seed_views.SeedSignMessageConfirmMessageView, before_run=self.inject_mesage_as_paged_message, screen_return_value=0),
            FlowStep(seed_views.SeedSignMessageConfirmAddressView, screen_return_value=0),
            FlowStep(seed_views.SeedSignMessageSignedMessageQRView, screen_return_value=0),
            FlowStep(MainMenuView),
        ])

        # Scenario 3: Load a long, multipage message
        self.run_sequence([
            FlowStep(MainMenuView, button_data_selection=MainMenuView.SCAN),
            FlowStep(scan_views.ScanView, before_run=self.load_multipage_message_into_decoder),  # simulate read message QR; ret val is ignored
            FlowStep(seed_views.SeedSignMessageStartView, is_redirect=True),
            FlowStep(seed_views.SeedSelectSeedView, button_data_selection=seed_views.SeedSelectSeedView.SCAN_SEED),
            FlowStep(scan_views.ScanView, before_run=self.load_seed_into_decoder),  # simulate read SeedQR; ret val is ignored
            FlowStep(seed_views.SeedFinalizeView, button_data_selection=seed_views.SeedFinalizeView.FINALIZE),
            FlowStep(seed_views.SeedOptionsView, is_redirect=True),
            FlowStep(seed_views.SeedSignMessageConfirmMessageView, before_run=self.inject_mesage_as_paged_message, screen_return_value=0),  # page 1/5
            FlowStep(seed_views.SeedSignMessageConfirmMessageView, screen_return_value=0),  # page 2/5
            FlowStep(seed_views.SeedSignMessageConfirmMessageView, screen_return_value=0),  # page 3/5
            FlowStep(seed_views.SeedSignMessageConfirmMessageView, screen_return_value=0),  # page 4/5
            FlowStep(seed_views.SeedSignMessageConfirmMessageView, screen_return_value=0),  # page 5/5

            # Arrive at the address confirmation, then go backwards to re-review the paged message
            FlowStep(seed_views.SeedSignMessageConfirmAddressView, screen_return_value=RET_CODE__BACK_BUTTON),  # then back to page 5/5
            FlowStep(seed_views.SeedSignMessageConfirmMessageView, screen_return_value=RET_CODE__BACK_BUTTON),  # back to page 4/5
            FlowStep(seed_views.SeedSignMessageConfirmMessageView, screen_return_value=RET_CODE__BACK_BUTTON),  # back to page 3/5
            FlowStep(seed_views.SeedSignMessageConfirmMessageView, screen_return_value=RET_CODE__BACK_BUTTON),  # back to page 2/5
            FlowStep(seed_views.SeedSignMessageConfirmMessageView, screen_return_value=RET_CODE__BACK_BUTTON),  # back to page 1/5

            # Now proceed forward again to the end
            FlowStep(seed_views.SeedSignMessageConfirmMessageView, screen_return_value=0),  # page 1/5
            FlowStep(seed_views.SeedSignMessageConfirmMessageView, screen_return_value=0),  # page 2/5
            FlowStep(seed_views.SeedSignMessageConfirmMessageView, screen_return_value=0),  # page 3/5
            FlowStep(seed_views.SeedSignMessageConfirmMessageView, screen_return_value=0),  # page 4/5
            FlowStep(seed_views.SeedSignMessageConfirmMessageView, screen_return_value=0),  # page 5/5
            FlowStep(seed_views.SeedSignMessageConfirmAddressView, screen_return_value=0),
            FlowStep(seed_views.SeedSignMessageSignedMessageQRView, screen_return_value=0),
            FlowStep(MainMenuView),
        ])

        # Scenario 4: Load a long message without whitespace
        self.controller.discard_seed(self.controller.storage.seeds[0])
        self.run_sequence([
            FlowStep(MainMenuView, button_data_selection=MainMenuView.SCAN),
            FlowStep(scan_views.ScanView, before_run=self.load_seed_into_decoder),  # simulate read SeedQR; ret val is ignored
            FlowStep(seed_views.SeedFinalizeView, button_data_selection=seed_views.SeedFinalizeView.FINALIZE),
            FlowStep(seed_views.SeedOptionsView, button_data_selection=seed_views.SeedOptionsView.SIGN_MESSAGE),
            FlowStep(scan_views.ScanView, before_run=self.load_no_whitespace_message_into_decoder),  # simulate read message QR; ret val is ignored
            FlowStep(seed_views.SeedSignMessageStartView, is_redirect=True),
            FlowStep(seed_views.SeedSignMessageConfirmMessageView, before_run=self.inject_mesage_as_paged_message, screen_return_value=0),
            FlowStep(seed_views.SeedSignMessageConfirmAddressView, screen_return_value=0),
            FlowStep(seed_views.SeedSignMessageSignedMessageQRView, screen_return_value=0),
            FlowStep(MainMenuView),
        ])


    def test_sign_message_network_mismatch_flow(self):
        """
        Should redirect to NetworkMismatchErrorView if a message's derivation path network doesn't match the current network.

        The error view should then forward to the Network Settings update View.
        """
        # Ensure message signing is enabled
        self.settings.set_value(SettingsConstants.SETTING__MESSAGE_SIGNING, SettingsConstants.OPTION__ENABLED)

        def expect_network_mismatch_error(load_message: Callable):
            self.run_sequence([
                FlowStep(MainMenuView, button_data_selection=MainMenuView.SCAN),
                FlowStep(scan_views.ScanView, before_run=load_message),  # simulate read message QR; ret val is ignored
                FlowStep(seed_views.SeedSignMessageStartView, is_redirect=True),
                FlowStep(NetworkMismatchErrorView),
                FlowStep(settings_views.SettingsEntryUpdateSelectionView),
            ])

        # MAINNET settings vs TESTNET derivation path with the message
        self.settings.set_value(SettingsConstants.SETTING__NETWORK, SettingsConstants.MAINNET)
        expect_network_mismatch_error(self.load_testnet_message_into_decoder)

        # TESTNET settings vs MAINNET derivation path with the message
        self.settings.set_value(SettingsConstants.SETTING__NETWORK, SettingsConstants.TESTNET)
        expect_network_mismatch_error(self.load_short_message_into_decoder)

        # REGTEST settings vs MAINNET derivation path with the message
        self.settings.set_value(SettingsConstants.SETTING__NETWORK, SettingsConstants.REGTEST)
        expect_network_mismatch_error(self.load_short_message_into_decoder)


    def test_sign_message_option_disabled(self):
        """
        Should redirect to OptionDisabledView if a `signmessage` QR is scanned with
        message signing disabled.

        Should offer the option to route directly to enable that settings or return to
        MainMenuView.
        """
        # Ensure message signing is disabled
        self.settings.set_value(SettingsConstants.SETTING__MESSAGE_SIGNING, SettingsConstants.OPTION__DISABLED)

        sequence = [
            FlowStep(MainMenuView, button_data_selection=MainMenuView.SCAN),
            FlowStep(scan_views.ScanView, before_run=self.load_short_message_into_decoder),  # simulate read message QR; ret val is ignored
            FlowStep(seed_views.SeedSignMessageStartView, is_redirect=True),
        ]

        # First test routing to update the setting
        self.run_sequence(
            sequence + [
                FlowStep(OptionDisabledView, button_data_selection=OptionDisabledView.UPDATE_SETTING),
                FlowStep(settings_views.SettingsEntryUpdateSelectionView),
            ]
        )

        # Now test exiting to Main Menu
        self.run_sequence(
            sequence + [
                FlowStep(OptionDisabledView, button_data_selection=OptionDisabledView.DONE),
                FlowStep(MainMenuView),
            ]
        )


    def test_sign_message_invalid_qr_flow(self):
        """
        Should clear `Controller.resume_main_flow` and redirect to ErrorView if an
        invalid signmessage QR is scanned.

        The error view should then forward to MainMenuView.
        """
        # Ensure message signing is enabled
        self.settings.set_value(SettingsConstants.SETTING__MESSAGE_SIGNING, SettingsConstants.OPTION__ENABLED)

        def load_invalid_signmessage_qr(view: scan_views.ScanView):
            view.decoder.add_data("this text will not make sense to the decoder")

        self.run_sequence([
            FlowStep(MainMenuView, button_data_selection=MainMenuView.SCAN),
            FlowStep(scan_views.ScanView, before_run=self.load_seed_into_decoder),  # simulate read SeedQR; ret val is ignored
            FlowStep(seed_views.SeedFinalizeView, button_data_selection=seed_views.SeedFinalizeView.FINALIZE),
            FlowStep(seed_views.SeedOptionsView, button_data_selection=seed_views.SeedOptionsView.SIGN_MESSAGE),
            FlowStep(scan_views.ScanView, before_run=load_invalid_signmessage_qr),  # simulate read message QR; ret val is ignored
            FlowStep(scan_views.ScanInvalidQRTypeView),
            FlowStep(MainMenuView),
        ])

        assert self.controller.resume_main_flow is None


    def test_sign_message_unsupported_derivation_flow(self):
        """
        Should redirect to NotYetImplementedView if a message's derivation path isn't yet supported
        """
        # Ensure message signing is enabled
        self.settings.set_value(SettingsConstants.SETTING__MESSAGE_SIGNING, SettingsConstants.OPTION__ENABLED)

        def expect_unsupported_derivation(load_message: Callable):
            self.run_sequence([
                FlowStep(MainMenuView, button_data_selection=MainMenuView.SCAN),
                FlowStep(scan_views.ScanView, before_run=self.load_seed_into_decoder),  # simulate read SeedQR; ret val is ignored
                FlowStep(seed_views.SeedFinalizeView, button_data_selection=seed_views.SeedFinalizeView.FINALIZE),
                FlowStep(seed_views.SeedOptionsView, button_data_selection=seed_views.SeedOptionsView.SIGN_MESSAGE),
                FlowStep(scan_views.ScanView, before_run=load_message),  # simulate read message QR; ret val is ignored
                FlowStep(seed_views.SeedSignMessageStartView, is_redirect=True),
                FlowStep(seed_views.NotYetImplementedView),
                FlowStep(MainMenuView),
            ])

        self.settings.set_value(SettingsConstants.SETTING__NETWORK, SettingsConstants.MAINNET)
        expect_unsupported_derivation(self.load_custom_derivation_into_decoder)





class TestFrostFlows(FlowTest):
    """
        Restoring a wallet from FROST key backups.

        Vectors are the official ones; see tests/test_frost.py.
    """
    SHARES_2_OF_3 = [
        (1, "MUTUAL JEANS SNAP STING BLESS JOURNEY MORAL BREAD ROOM LIMIT DOSE GRAVITY SORT DELIVER OUTDOOR RIPPLE DONKEY BLOUSE PLAY CART CENTURY MAXIMUM MAKE LOCAL MOBILE"),
        (2, "CASH TRASH FOIL PREFER BUTTER IDEA BRAVE BITTER ITEM WINK DRIFT SMILE TOMATO LUNCH OPTION HERO THREE ENGINE BLESS MANAGE HORSE JAR ADVICE SHERIFF BUSINESS"),
        (3, "REGION FINISH TRAVEL LAUNDRY CHEAP HAIR PLUNGE BANANA CRACK INTEREST DURING COTTON PHONE DISAGREE CRUNCH AIRPORT CANCEL FOLD LAUNDRY PONY LOBSTER LENS MAMMAL CLOTH FINGER"),
    ]
    FINGERPRINT_2_OF_3 = "79b00088"

    # The same wallet backed up as key #0, which carries the whole secret on its own.
    WHOLE_WALLET_BACKUP = (0, "ABSURD AMOUNT DOCTOR ACOUSTIC AVOID LETTER ADVICE CAGE ABSURD AMOUNT DOCTOR ACOUSTIC AVOID LETTER ADVICE CAGE ABSURD AMOUNT DOCTOR ACOUSTIC AVOID LETTER ADVICE CHECK WIDTH")

    SHARE_3_OF_5_NUM_2 = (2, "SUGAR GENERAL PARK VOYAGE CREEK FLY MOTOR ALWAYS WAVE SUNNY WARRIOR DIAMOND WAVE SUNSET ANY LEFT LIGHT FLOAT VAULT GENUINE ELBOW TENNIS BECOME TABLE CLAIM")


    def enable_frost(self):
        Settings.get_instance().set_value(SettingsConstants.SETTING__FROST_BACKUPS, SettingsConstants.OPTION__ENABLED)


    def entry_steps(self) -> list[FlowStep]:
        """Navigate from the main menu to the threshold prompt."""
        return [
            FlowStep(MainMenuView, button_data_selection=MainMenuView.SEEDS),
            FlowStep(seed_views.SeedsMenuView, is_redirect=True),  # auto-redirects when no seeds are loaded
            FlowStep(seed_views.LoadSeedView, button_data_selection=seed_views.LoadSeedView.TYPE_FROST),
            FlowStep(seed_views.SeedFrostStartView),  # warning screen; no relevant button data selection
        ]


    def backup_steps(self, share) -> list[FlowStep]:
        """Enter one backup: its number, then its 25 words."""
        index, words = share
        steps = [FlowStep(seed_views.SeedFrostShareIndexView, screen_return_value=str(index))]
        for word in words.lower().split():
            steps.append(FlowStep(seed_views.SeedFrostWordEntryView, screen_return_value=word))
        return steps


    def test_restore_flow(self):
        """Entering `threshold` valid backups should restore the key and load it."""
        self.enable_frost()

        sequence = self.entry_steps()
        sequence.append(FlowStep(seed_views.SeedFrostSelectThresholdView, screen_return_value="2"))
        for share in self.SHARES_2_OF_3[:2]:
            sequence += self.backup_steps(share)
        sequence += [
            FlowStep(seed_views.SeedFinalizeView, button_data_selection=seed_views.SeedFinalizeView.FINALIZE),
            FlowStep(seed_views.SeedOptionsView),
        ]

        self.run_sequence(sequence)

        seed = self.controller.storage.seeds[0]
        assert isinstance(seed, FrostSeed)
        assert seed.get_fingerprint() == self.FINGERPRINT_2_OF_3


    def test_any_threshold_subset_restores_the_same_key(self):
        """Any 2 of the 3 backups must restore the same key."""
        for shares in [self.SHARES_2_OF_3[:2], self.SHARES_2_OF_3[1:], [self.SHARES_2_OF_3[0], self.SHARES_2_OF_3[2]]]:
            BaseTest.reset_controller()
            self.enable_frost()

            sequence = self.entry_steps()
            sequence.append(FlowStep(seed_views.SeedFrostSelectThresholdView, screen_return_value="2"))
            for share in shares:
                sequence += self.backup_steps(share)
            sequence += [
                FlowStep(seed_views.SeedFinalizeView, button_data_selection=seed_views.SeedFinalizeView.FINALIZE),
                FlowStep(seed_views.SeedOptionsView),
            ]
            self.run_sequence(sequence)

            # reset_controller() replaced the singleton, so re-fetch rather than using
            # the instance captured in setup_method().
            assert Controller.get_instance().storage.seeds[0].get_fingerprint() == self.FINGERPRINT_2_OF_3


    def test_option_is_hidden_when_disabled(self):
        """The menu entry must not appear unless the setting is enabled."""
        with pytest.raises(FlowTestInvalidButtonDataSelectionException):
            self.run_sequence([
                FlowStep(MainMenuView, button_data_selection=MainMenuView.SEEDS),
                FlowStep(seed_views.SeedsMenuView, is_redirect=True),
                FlowStep(seed_views.LoadSeedView, button_data_selection=seed_views.LoadSeedView.TYPE_FROST),
            ])


    @pytest.mark.parametrize("threshold", ["0", "9"])
    def test_invalid_threshold(self, threshold):
        self.enable_frost()

        self.run_sequence(
            self.entry_steps() + [
                FlowStep(seed_views.SeedFrostSelectThresholdView, screen_return_value=threshold),
                FlowStep(seed_views.SeedFrostInvalidThresholdView, button_data_selection=seed_views.SeedFrostInvalidThresholdView.TRY_AGAIN),
                FlowStep(seed_views.SeedFrostSelectThresholdView, screen_return_value=RET_CODE__BACK_BUTTON),
                FlowStep(seed_views.LoadSeedView),
            ]
        )


    def test_restore_whole_wallet_backup(self):
        """Key #0 carries the whole secret, so one of them restores the wallet on its own."""
        self.enable_frost()

        sequence = self.entry_steps()
        sequence.append(FlowStep(seed_views.SeedFrostSelectThresholdView, screen_return_value="1"))
        sequence += self.backup_steps(self.WHOLE_WALLET_BACKUP)
        sequence += [
            FlowStep(seed_views.SeedFinalizeView, button_data_selection=seed_views.SeedFinalizeView.FINALIZE),
            FlowStep(seed_views.SeedOptionsView),
        ]

        self.run_sequence(sequence)

        seed = self.controller.storage.seeds[0]
        assert isinstance(seed, FrostSeed)
        assert seed.get_fingerprint() == self.FINGERPRINT_2_OF_3


    def test_whole_wallet_backup_not_mixed_with_shares(self):
        """Key #0 is a whole wallet, so it must be rejected when more keys are expected."""
        self.enable_frost()

        self.run_sequence(
            self.entry_steps() + [
                FlowStep(seed_views.SeedFrostSelectThresholdView, screen_return_value="2"),
                FlowStep(seed_views.SeedFrostShareIndexView, screen_return_value="0"),
                FlowStep(seed_views.SeedFrostInvalidShareIndexView, button_data_selection=seed_views.SeedFrostInvalidShareIndexView.TRY_AGAIN),
                FlowStep(seed_views.SeedFrostShareIndexView),
            ]
        )


    def test_duplicate_share_index(self):
        """The same key number can't be used twice."""
        self.enable_frost()

        sequence = self.entry_steps()
        sequence.append(FlowStep(seed_views.SeedFrostSelectThresholdView, screen_return_value="2"))
        sequence += self.backup_steps(self.SHARES_2_OF_3[0])
        sequence += [
            FlowStep(seed_views.SeedFrostShareIndexView, screen_return_value="1"),  # already used
            FlowStep(seed_views.SeedFrostInvalidShareIndexView, button_data_selection=seed_views.SeedFrostInvalidShareIndexView.TRY_AGAIN),
            FlowStep(seed_views.SeedFrostShareIndexView),
        ]

        self.run_sequence(sequence)


    def test_words_checksum_failure(self):
        """A mistyped word must be caught as soon as that backup is complete."""
        self.enable_frost()

        index, words = self.SHARES_2_OF_3[0]
        corrupted = words.lower().split()
        corrupted[-1] = "abandon"

        sequence = self.entry_steps()
        sequence += [
            FlowStep(seed_views.SeedFrostSelectThresholdView, screen_return_value="2"),
            FlowStep(seed_views.SeedFrostShareIndexView, screen_return_value=str(index)),
        ]
        for word in corrupted:
            sequence.append(FlowStep(seed_views.SeedFrostWordEntryView, screen_return_value=word))
        sequence += [
            FlowStep(seed_views.SeedFrostInvalidBackupView, button_data_selection=seed_views.SeedFrostInvalidBackupView.DISCARD),
            FlowStep(MainMenuView),
        ]

        self.run_sequence(sequence)

        assert self.controller.frost_data is None
        assert len(self.controller.storage.seeds) == 0


    def test_words_checksum_failure_can_be_edited(self):
        """After a checksum failure, "Review & edit" returns to that backup's number."""
        self.enable_frost()

        index, words = self.SHARES_2_OF_3[0]
        corrupted = words.lower().split()
        corrupted[-1] = "abandon"

        sequence = self.entry_steps()
        sequence += [
            FlowStep(seed_views.SeedFrostSelectThresholdView, screen_return_value="2"),
            FlowStep(seed_views.SeedFrostShareIndexView, screen_return_value=str(index)),
        ]
        for word in corrupted:
            sequence.append(FlowStep(seed_views.SeedFrostWordEntryView, screen_return_value=word))
        sequence += [
            FlowStep(seed_views.SeedFrostInvalidBackupView, button_data_selection=seed_views.SeedFrostInvalidBackupView.EDIT),
            FlowStep(seed_views.SeedFrostShareIndexView),
        ]

        self.run_sequence(sequence)


    def test_backups_from_different_keys(self):
        """
        Two individually-valid backups that belong to different wallets must be caught by
        the polynomial checksum.
        """
        self.enable_frost()

        sequence = self.entry_steps()
        sequence.append(FlowStep(seed_views.SeedFrostSelectThresholdView, screen_return_value="2"))
        sequence += self.backup_steps(self.SHARES_2_OF_3[0])
        sequence += self.backup_steps(self.SHARE_3_OF_5_NUM_2)
        sequence += [
            FlowStep(seed_views.SeedFrostMismatchedBackupsView, button_data_selection=seed_views.SeedFrostMismatchedBackupsView.DISCARD),
            FlowStep(MainMenuView),
        ]

        self.run_sequence(sequence)

        assert self.controller.frost_data is None
        assert len(self.controller.storage.seeds) == 0


    def test_back_from_threshold_returns_to_load_seed_menu(self):
        """The intro warning forwards past itself, so back must not re-show it."""
        self.enable_frost()

        self.run_sequence(
            self.entry_steps() + [
                FlowStep(seed_views.SeedFrostSelectThresholdView, screen_return_value=RET_CODE__BACK_BUTTON),
                FlowStep(seed_views.LoadSeedView),
            ]
        )

        assert self.controller.frost_data is None


    def test_back_through_word_entry(self):
        """Backing out of word 1 returns to the backup number prompt."""
        self.enable_frost()

        index, words = self.SHARES_2_OF_3[0]
        first_two = words.lower().split()[:2]

        self.run_sequence(
            self.entry_steps() + [
                FlowStep(seed_views.SeedFrostSelectThresholdView, screen_return_value="2"),
                FlowStep(seed_views.SeedFrostShareIndexView, screen_return_value=str(index)),
                FlowStep(seed_views.SeedFrostWordEntryView, screen_return_value=first_two[0]),
                FlowStep(seed_views.SeedFrostWordEntryView, screen_return_value=first_two[1]),
                FlowStep(seed_views.SeedFrostWordEntryView, screen_return_value=RET_CODE__BACK_BUTTON),  # back to word 2
                FlowStep(seed_views.SeedFrostWordEntryView, screen_return_value=RET_CODE__BACK_BUTTON),  # back to word 1
                FlowStep(seed_views.SeedFrostWordEntryView, screen_return_value=RET_CODE__BACK_BUTTON),  # back to the number
                FlowStep(seed_views.SeedFrostShareIndexView),
            ]
        )


    def restore_steps(self) -> list[FlowStep]:
        """Full sequence up to (but not including) SeedFinalizeView."""
        sequence = self.entry_steps()
        sequence.append(FlowStep(seed_views.SeedFrostSelectThresholdView, screen_return_value="2"))
        for share in self.SHARES_2_OF_3[:2]:
            sequence += self.backup_steps(share)
        return sequence


    def test_passphrase_option_is_hidden(self):
        """
        A restored FROST key has no mnemonic to salt, so the BIP-39 passphrase button must
        be absent even though the setting is enabled.
        """
        self.enable_frost()
        self.settings.set_value(SettingsConstants.SETTING__PASSPHRASE, SettingsConstants.OPTION__ENABLED)

        sequence = self.restore_steps()
        sequence.append(FlowStep(seed_views.SeedFinalizeView, button_data_selection=seed_views.SeedFinalizeView.PASSPHRASE))

        with pytest.raises(FlowTestInvalidButtonDataSelectionException):
            self.run_sequence(sequence)


    def test_backup_option_is_hidden(self):
        """There are no words to transcribe, so "Backup seed" must be absent."""
        self.enable_frost()

        sequence = self.restore_steps()
        sequence += [
            FlowStep(seed_views.SeedFinalizeView, button_data_selection=seed_views.SeedFinalizeView.FINALIZE),
            FlowStep(seed_views.SeedOptionsView, button_data_selection=seed_views.SeedOptionsView.BACKUP),
        ]

        with pytest.raises(FlowTestInvalidButtonDataSelectionException):
            self.run_sequence(sequence)
