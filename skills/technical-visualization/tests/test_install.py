"""Installation preserves existing user files and verifies complete copies."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from install_skill import install, inventory


class InstallTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'SKILL.md').write_text('---\nname: technical-visualization\ndescription: test\n---\n')
        (self.source / 'references').mkdir()
        (self.source / 'references' / 'guide.md').write_text('Guide')
        self.dest = self.root / 'installed'

    def test_full_directory_copy_and_check(self):
        install(self.source, self.dest)
        self.assertEqual(inventory(self.source), inventory(self.dest))
        self.assertIn('verified', install(self.source, self.dest, check=True))

    def test_existing_changed_file_is_preserved(self):
        install(self.source, self.dest)
        guide = self.dest / 'references' / 'guide.md'
        guide.write_text('User customization')
        with self.assertRaisesRegex(ValueError, 'different content'):
            install(self.source, self.dest)
        self.assertEqual(guide.read_text(), 'User customization')

    def test_check_does_not_create_directory(self):
        with self.assertRaisesRegex(ValueError, 'Not installed'):
            install(self.source, self.dest, check=True)
        self.assertFalse(self.dest.exists())


if __name__ == '__main__':
    unittest.main()
