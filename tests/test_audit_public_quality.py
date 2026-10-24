import unittest
from scripts.audit_public_quality import AREA_AS_LAYOUT, public_audit


class AuditTests(unittest.TestCase):
    def test_detects_cross_field_legacy_pattern_without_guessing_amounts(self):
        rows = [
            {'id': 'a', 'name': 'D-roomKasumi', 'address': '北九州市門司区大里本町2',
             'vacancy_count': 3, 'rent_min': None, 'area_min': None,
             'room_types': ['40.28m2', '53.34m2'], 'updated_at': '2026/04/10 16:18'},
            {'id': 'b', 'name': 'D-room Kasumi', 'address': '北九州市門司区大里本町2丁目9-13',
             'vacancy_count': 1, 'rent_min': 70000, 'area_min': 40.39,
             'room_types': ['1LDK'], 'updated_at': '2026-03-28'},
        ]
        result = public_audit(rows)
        self.assertEqual(result['totals']['rent_missing_buildings'], 1)
        self.assertEqual(result['totals']['rent_missing_vacancies'], 3)
        self.assertEqual(result['totals']['area_text_in_layout_buildings'], 1)
        self.assertEqual(next(x for x in result['focus_pairs'] if x['name']=='D-room Kasumi')['ids'], ['a', 'b'])
        # No automatic amount transfer or alias recommendation is made.
        self.assertNotIn('repair_rent_yen', result)

    def test_requires_all_layouts_to_be_area_tokens(self):
        rows = [{'id':'a', 'name':'a', 'vacancy_count':1,'rent_min':None,'area_min':None,
                 'room_types':['1LDK','40.28m2']}]
        self.assertEqual(public_audit(rows)['totals']['area_text_in_layout_buildings'], 0)
        self.assertTrue(AREA_AS_LAYOUT.fullmatch('54.78m2'))
        self.assertFalse(AREA_AS_LAYOUT.fullmatch('1LDK'))

    def test_duplicate_public_id_fails(self):
        rows = [{'id':'a','vacancy_count':0},{'id':'a','vacancy_count':0}]
        with self.assertRaisesRegex(ValueError, 'duplicate_public_building_id'):
            public_audit(rows)


if __name__ == '__main__':
    unittest.main()
