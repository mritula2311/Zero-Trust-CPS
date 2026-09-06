"""Regression coverage for the audit_repository_evidence.py credential scanner gap:
a credential-sensitive value shorter than the broad-scan noise floor must still be
flagged when it exactly reuses a known public identifier. All values here are
synthetic fixtures, never a real credential."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from audit_repository_evidence import (
    PLAUSIBLE_SECRET_MIN_LEN,
    collect_credential_assignments,
    derive_public_identifiers,
    find_reused_identifiers,
    is_placeholder,
    select_scan_values,
)


def write(tmp, name, content):
    path = Path(tmp) / name
    path.write_text(content, encoding="utf-8")
    return path


class TestCredentialScannerRegression(unittest.TestCase):
    def test_short_value_reusing_public_identifier_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "device_secrets.py",
                         'WIFI_PASSWORD = "syn9x"\n')  # 5 chars, below the noise floor
            self.assertLess(len("syn9x"), PLAUSIBLE_SECRET_MIN_LEN)
            assignments = collect_credential_assignments([path])
            matches = find_reused_identifiers(assignments, identifiers={"syn9x", "unrelated-org"})
            self.assertIn("device_secrets.py:WIFI_PASSWORD", matches)

    def test_short_value_not_matching_any_identifier_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "device_secrets.py",
                         'WIFI_PASSWORD = "syn9x"\n')
            assignments = collect_credential_assignments([path])
            matches = find_reused_identifiers(assignments, identifiers={"totally-different-name"})
            self.assertEqual(matches, [])

    def test_scan_values_include_short_reused_identifier_regardless_of_length(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "device_secrets.py",
                         'WIFI_PASSWORD = "syn9x"\n')
            assignments = collect_credential_assignments([path])
            reused = find_reused_identifiers(assignments, identifiers={"syn9x"})
            values = select_scan_values(assignments, reused)
            self.assertIn("syn9x", values)

    def test_scan_values_exclude_short_non_reused_secret(self):
        # A short value that is NOT a reused public identifier stays below the
        # noise floor and is excluded from the broad substring scan -- lowering
        # the floor globally is exactly what the review asked us not to do.
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "device_secrets.py",
                         'WIFI_PASSWORD = "ab12"\n')
            assignments = collect_credential_assignments([path])
            reused = find_reused_identifiers(assignments, identifiers={"some-other-identifier"})
            values = select_scan_values(assignments, reused)
            self.assertNotIn("ab12", values)

    def test_long_plausible_secret_is_still_scanned_without_identifier_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "secrets_local.py",
                         'MQTT_GATEWAY_PASSWORD = "SyntheticLongPassphrase123"\n')
            assignments = collect_credential_assignments([path])
            reused = find_reused_identifiers(assignments, identifiers={"unrelated"})
            self.assertEqual(reused, [])
            values = select_scan_values(assignments, reused)
            self.assertIn("SyntheticLongPassphrase123", values)

    def test_known_placeholders_are_never_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "device_secrets.py",
                         'WIFI_PASSWORD = "CHANGE-ME-generate-your-own"\n'
                         'DEVICE_SECRET = "YOUR_DEVICE_SECRET"\n'
                         'MQTT_PASSWORD = "REPLACE_WITH_MQTT_PASSWORD"\n')
            assignments = collect_credential_assignments([path])
            for _, _, value in assignments:
                self.assertTrue(is_placeholder(value))
            reused = find_reused_identifiers(assignments, identifiers={"CHANGE-ME-generate-your-own"})
            self.assertEqual(reused, [])
            values = select_scan_values(assignments, reused)
            self.assertEqual(values, set())

    def test_dict_valued_secret_fields_are_labelled_per_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "secrets_local.py",
                         'DEVICE_SECRETS = {"node-a": "shortid", "node-b": "CHANGE-ME"}\n')
            assignments = collect_credential_assignments([path])
            labels = {label for _, label, _ in assignments}
            self.assertIn("DEVICE_SECRETS[node-a]", labels)
            reused = find_reused_identifiers(assignments, identifiers={"shortid"})
            self.assertIn("secrets_local.py:DEVICE_SECRETS[node-a]", reused)

    def test_derive_public_identifiers_reads_repository_slug_from_prd(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "PRD.md",
                  "| **Repository** | `github.com/synthetic-owner/synthetic-repo` |\n")
            identifiers = derive_public_identifiers(Path(tmp), extra=())
            self.assertIn("synthetic-owner", identifiers)
            self.assertIn("synthetic-repo", identifiers)

    def test_token_and_key_field_names_are_recognized_as_sensitive(self):
        # The scanner must not only look at PASSWORD/SECRET; hmac_key, api_key
        # and token-named fields are credential-sensitive too.
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "secrets_local.py",
                         'HMAC_KEY = "synhk"\n'
                         'API_TOKEN = "syntok"\n'
                         'PRIVATE_KEY_ID = "synpk"\n')
            assignments = collect_credential_assignments([path])
            labels = {label for _, label, _ in assignments}
            self.assertEqual(labels, {"HMAC_KEY", "API_TOKEN", "PRIVATE_KEY_ID"})
            reused = find_reused_identifiers(assignments, identifiers={"synhk", "syntok", "synpk"})
            self.assertEqual(set(reused),
                              {"secrets_local.py:HMAC_KEY", "secrets_local.py:API_TOKEN",
                               "secrets_local.py:PRIVATE_KEY_ID"})

    def test_additional_placeholder_forms_are_never_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "device_secrets.py",
                         'WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"\n'
                         'MQTT_PASSWORD = "CHANGE_ME"\n'
                         'DEVICE_SECRET = "EXAMPLE_PASSWORD"\n'
                         'API_TOKEN = "TEST_ONLY"\n')
            assignments = collect_credential_assignments([path])
            for _, _, value in assignments:
                self.assertTrue(is_placeholder(value), f"{value!r} should be a recognized placeholder")
            reused = find_reused_identifiers(assignments, identifiers={
                "YOUR_WIFI_PASSWORD", "CHANGE_ME", "EXAMPLE_PASSWORD", "TEST_ONLY"})
            self.assertEqual(reused, [])
            values = select_scan_values(assignments, reused)
            self.assertEqual(values, set())

    def test_safe_synthetic_values_pass_clean(self):
        # A long, non-placeholder, non-reused value must scan clean: inspected
        # (present in select_scan_values) but not flagged as identifier reuse.
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "secrets_local.py",
                         'MQTT_GATEWAY_PASSWORD = "Sy9thXk3ticSafeValue7Q"\n')
            assignments = collect_credential_assignments([path])
            reused = find_reused_identifiers(assignments, identifiers={"unrelated-public-name"})
            self.assertEqual(reused, [])
            values = select_scan_values(assignments, reused)
            self.assertIn("Sy9thXk3ticSafeValue7Q", values)


if __name__ == "__main__":
    unittest.main()
