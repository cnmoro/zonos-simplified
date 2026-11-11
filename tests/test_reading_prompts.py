"""Validate the user-visible reading catalogue, without model/browser dependencies."""
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]


class ReadingCatalogue(unittest.TestCase):
    def test_twenty_distinct_natural_paragraphs_in_each_supported_language(self):
        catalogue=json.loads((ROOT/'frontend/reading-prompts.json').read_text())
        ids=set()
        for language in ['pt_br','en_us']:
            rows=catalogue['languages'][language]
            self.assertGreaterEqual(len(rows),20)
            self.assertEqual(len({row['text'] for row in rows}),len(rows))
            for row in rows:
                self.assertTrue(row['title'].strip())
                self.assertNotIn(row['id'],ids)
                ids.add(row['id'])
                self.assertGreaterEqual(len(row['text'].split()),25)
                self.assertLessEqual(len(row['text'].split()),65)
                self.assertTrue(row['text'].endswith(('.', '?', '!')))


if __name__=='__main__': unittest.main()
