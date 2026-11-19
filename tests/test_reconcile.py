import copy
import unittest
from reconcile import demo_case, reconcile


class ReconciliationTests(unittest.TestCase):
    def test_fifo_and_period(self):
        result = reconcile(demo_case())
        self.assertEqual(result['status'], 'illustrative', result['issues'])
        self.assertEqual(result['totals'], {'realized_gains': '2250', 'income': '180'})
        self.assertEqual(result['differences'], {'realized_gains': '250', 'income': '80'})
        self.assertEqual(result['disposals'][0]['basis'], '2750')
        self.assertEqual([m['quantity'] for m in result['disposals'][0]['matches']], ['2', '0.5'])
        self.assertTrue(result['human_review_required'])
        self.assertIsNone(result['pack']['jurisdiction'])

    def test_hash_stability_and_mutation(self):
        case = demo_case()
        self.assertEqual(reconcile(case)['evidence_hash'], reconcile(copy.deepcopy(case))['evidence_hash'])
        changed = copy.deepcopy(case)
        changed['events'][0]['price_source'] += '-corrected'
        self.assertNotEqual(reconcile(case)['evidence_hash'], reconcile(changed)['evidence_hash'])
        self.assertEqual(case, demo_case())

    def test_negative_difference(self):
        case = demo_case()
        case['declared']['realized_gains'] = '3000'
        self.assertEqual(reconcile(case)['differences']['realized_gains'], '-750')

    def test_missing_basis_is_all_or_nothing(self):
        case = demo_case()
        case['events'][2]['quantity'] = '4'
        result = reconcile(case)
        self.assertEqual(result['status'], 'blocked')
        self.assertIsNone(result['totals'])
        self.assertEqual(result['disposals'], [])
        self.assertIsNone(result['evidence_hash'])

    def test_invalid_inputs_block(self):
        mutations = [lambda c: c['events'][0].pop('unit_price'), lambda c: c['events'][0].update(unit_price='NaN'), lambda c: c['events'][0].update(unit_price=0.1), lambda c: c['events'][0].update(quantity='-2'), lambda c: c['events'][0].update(price_source=''), lambda c: c['events'].append(copy.deepcopy(c['events'][0])), lambda c: c['events'][1].update(source_ref=c['events'][0]['source_ref']), lambda c: c['events'][0].update(kind='transfer'), lambda c: c.update(currency='EUR'), lambda c: c.update(as_of='2026-06-01T00:00:00Z'), lambda c: c['events'][0].update(timestamp='2027-02-01T00:00:00Z'), lambda c: c['events'][0].update(timestamp='2026-01-01T00:00:00'), lambda c: c['declared'].update(income='-1')]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                case = demo_case()
                mutation(case)
                result = reconcile(case)
                self.assertEqual(result['status'], 'blocked')
                self.assertIsNone(result['totals'])

    def test_decimal_exactness(self):
        case = demo_case()
        case['events'] = case['events'][:1] + [case['events'][2]]
        case['events'][0].update(quantity='0.3', unit_price='0.1')
        case['events'][1].update(quantity='0.3', unit_price='0.2')
        self.assertEqual(reconcile(case)['totals']['realized_gains'], '0.03')

    def test_income_lot_can_be_disposed(self):
        case = demo_case()
        case['events'] = [case['events'][3]]
        sale = dict(case['events'][0], id='sale', source_ref='synthetic://sale', timestamp='2026-05-01T00:00:00Z', kind='disposal', unit_price='2000')
        case['events'].append(sale)
        result = reconcile(case)
        self.assertEqual(result['totals'], {'realized_gains': '20', 'income': '180'})

    def test_pre_period_disposal_consumes_basis_without_current_gain(self):
        case = demo_case()
        case['events'][2]['timestamp'] = '2025-12-02T00:00:00Z'
        case['events'][2]['quantity'] = '1'
        self.assertEqual(reconcile(case)['totals']['realized_gains'], '0')

    def test_no_events(self):
        case = demo_case()
        case['events'] = []
        self.assertEqual(reconcile(case)['totals'], {'realized_gains': '0', 'income': '0'})

    def test_loss_is_not_clamped(self):
        case = demo_case()
        case['events'][2]['unit_price'] = '500'
        self.assertEqual(reconcile(case)['totals']['realized_gains'], '-1500')

    def test_malformed_case(self):
        for case in [None, [], {}, {'case_id': 'x', 'currency':'USD'}]:
            self.assertEqual(reconcile(case)['status'], 'blocked')


if __name__ == '__main__':
    unittest.main()
