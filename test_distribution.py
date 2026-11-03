"""Publication checks that use only generic patterns and synthetic examples."""
import json
from pathlib import Path
import unittest

from client import Profile

ROOT = Path(__file__).resolve().parent


class DistributionTests(unittest.TestCase):
    def test_defaults_are_non_routable_examples(self):
        profile = Profile()
        self.assertTrue(profile.host == 'server.example.invalid', 'Host must be the reserved example hostname')
        self.assertEqual(profile.user, 'monitor')
        self.assertEqual(profile.key, '.ssh/id_ed25519')
        self.assertEqual(profile.root, '/srv/simulations')

    def test_example_matches_defaults(self):
        self.assertTrue((ROOT / 'profile.example.json').is_file(), 'Safe example configuration must exist')
        example = json.loads((ROOT / 'profile.example.json').read_text(encoding='utf-8'))
        self.assertEqual(Profile(**example), Profile())

    def test_build_does_not_bundle_live_configuration(self):
        self.assertTrue((ROOT / 'build_app.ps1').is_file(), 'Portable build script must exist')
        build = (ROOT / 'build_app.ps1').read_text(encoding='utf-8')
        self.assertNotIn("'profile.json'", build)
        self.assertIn('profile.example.json', build)


if __name__ == '__main__':
    unittest.main()
