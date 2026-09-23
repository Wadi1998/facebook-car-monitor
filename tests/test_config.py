import unittest
from unittest.mock import patch

import config


class TestIsRunOnce(unittest.TestCase):
    def test_false_by_default(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(config.is_run_once())

    def test_true_when_run_once_env_var_set(self):
        with patch.dict("os.environ", {"RUN_ONCE": "true"}, clear=True):
            self.assertTrue(config.is_run_once())

    def test_true_when_run_once_is_1(self):
        with patch.dict("os.environ", {"RUN_ONCE": "1"}, clear=True):
            self.assertTrue(config.is_run_once())

    def test_false_when_run_once_is_explicitly_false(self):
        with patch.dict("os.environ", {"RUN_ONCE": "false"}, clear=True):
            self.assertFalse(config.is_run_once())

    def test_true_when_github_actions_env_var_present(self):
        # GitHub Actions sets this automatically on every run - main.py must
        # switch to a single cycle without any extra configuration needed.
        with patch.dict("os.environ", {"GITHUB_ACTIONS": "true"}, clear=True):
            self.assertTrue(config.is_run_once())

    def test_true_when_both_set(self):
        with patch.dict("os.environ", {"RUN_ONCE": "true", "GITHUB_ACTIONS": "true"}, clear=True):
            self.assertTrue(config.is_run_once())


if __name__ == "__main__":
    unittest.main()
