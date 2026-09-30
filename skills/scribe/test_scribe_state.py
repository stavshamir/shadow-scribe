import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import scribe_state


@mock.patch.dict("os.environ", {}, clear=True)
class ScribeStateTest(unittest.TestCase):
    def test_init_scaffolds_the_vault_and_resolve_reads_it_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "vault"
            config = Path(tmp) / "config.json"

            scribe_state.init_vault(root, config)

            self.assertTrue(root.joinpath(".scribe", "state").is_dir())
            self.assertFalse(root.joinpath(".scribe", "state", "archive").exists())
            self.assertFalse(root.joinpath(".scribe", "hooks").exists())
            self.assertTrue(root.joinpath("journal").is_dir())
            self.assertTrue(root.joinpath("tags.yaml").is_file())
            self.assertFalse(root.joinpath("tags.md").exists())
            self.assertEqual(
                scribe_state.resolve_vault(config),
                {"configured": True, "vault": str(root.resolve()), "source": str(config)},
            )

    def test_resolve_reports_an_unconfigured_vault_instead_of_failing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(scribe_state, "enclosing_vault", return_value=None):
                resolved = scribe_state.resolve_vault(Path(tmp) / "config.json")

            self.assertEqual(resolved, {"configured": False, "vault": None, "source": None})

    def test_registry_is_selected_by_its_working_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "vault"
            state = root / ".scribe" / "state"
            state.mkdir(parents=True)
            state.joinpath("2026-07-13-first.json").write_text(json.dumps({
                "version": 1,
                "entry": "journal/2026-07-13-first.md",
                "slug": "first",
                "sessions": {"working-session-a": {"watermark": 0, "label": "A"}},
            }))
            second = state / "2026-07-13-second.json"
            second.write_text(json.dumps({
                "version": 1,
                "entry": "journal/2026-07-13-second.md",
                "slug": "second",
                "sessions": {"working-session-b": {"watermark": 0, "label": "B"}},
            }))
            state.joinpath("corrupt.json").write_text("{not json")

            matches = scribe_state.registries_for_sessions(root, {"working-session-b"})

            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["registry"], str(second))

    def test_init_keeps_an_existing_tag_vocabulary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "vault"
            root.mkdir()
            root.joinpath("tags.yaml").write_text("- aws\n")

            scribe_state.init_vault(root, Path(tmp) / "config.json")

            self.assertEqual(root.joinpath("tags.yaml").read_text(), "- aws\n")


if __name__ == "__main__":
    unittest.main()
