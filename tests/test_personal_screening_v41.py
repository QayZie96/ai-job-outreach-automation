"""Offline regression tests: neither providers nor Gemini nor Sheets imported."""
import json
from pathlib import Path
import tempfile
import unittest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import personal_screening_v41 as cal


class V41Tests(unittest.TestCase):
    def test_joint_mandatory_spanish(self):
        desc = 'Excellent written and spoken English and Spanish language skills.'
        self.assertEqual(cal.mandatory_language('Teaching Assistant: Supply Chain Analyst', desc), 'Spanish')

    def test_joint_mandatory_ukrainian(self):
        self.assertEqual(cal.mandatory_language('P2P Growth Operations Manager',
            'Fluency in Ukrainian or Russian language is needed for this position'), 'Ukrainian')

    def test_optional_german_not_rejected(self):
        for statement in ('German is a plus. English required.', 'Fluent German is preferred, not required.',
                          'German language is nice to have.'):
            self.assertIsNone(cal.mandatory_language('Catalog Coordinator', statement))

    def test_german_requirement(self):
        self.assertEqual(cal.mandatory_language('Implementation Consultant', 'German fluency is essential.'), 'German')

    def test_degree_without_alternative_is_review_not_excluded(self):
        x = cal.calibrated_factors('Lead Analyst', "Bachelor's degree from an accredited college/university. "
            '7+ years of SAP functional experience.')
        self.assertTrue(x['force_review'])
        self.assertIn('formal_degree_not_verified', x['flags'])
        self.assertIsNone(x['hard_exclusion'])

    def test_degree_or_equivalent_not_flagged(self):
        x = cal.calibrated_factors('Business Operations Analyst',
           "Bachelor's degree or equivalent professional experience. Manage reports.")
        self.assertNotIn('formal_degree_not_verified', x['flags'])

    def test_parcelhero_leadership_downgraded(self):
        x = cal.calibrated_factors('Customer service manager (GR)',
           "A minimum of 10 years' customer service experience. A minimum of 7 years' "
           'experience in a customer service management role. Manage 50-strong team.')
        self.assertIn('substantial_people_leadership_required', x['flags'])
        self.assertTrue(x['force_review'])

    def test_ai_annotation_excluded_but_ai_automation_not(self):
        x = cal.calibrated_factors('Retail Trade & Operations Expert - Remote',
           'In this role you help train next-generation AI systems. Review simulated retail scenarios.')
        self.assertEqual(x['hard_exclusion'], 'incompatible_role')
        other = cal.calibrated_factors('AI Automation Specialist',
            'Build an AI automation workflow that optimizes marketplace pricing.')
        self.assertIsNone(other['hard_exclusion'])

    def test_marketing_ops_and_assistant_rank_above_weak_generic(self):
        a = cal.calibrated_factors('Marketing Operations Coordinator', 'Manage CRM and campaign data.')
        b = cal.calibrated_factors('Customer Experience Lead', 'Handle complaints.')
        self.assertGreater(a['priority_delta'], b['priority_delta'])
        c = cal.calibrated_factors('Office Assistant', 'Coordinate reports and office tasks.')
        self.assertTrue(c['promote_review'])

    def test_history_observation_not_seen_is_not_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'history.local.json'
            first = {'job_url':'https://example.com/a', 'company_name':'A', 'job_title':'Catalog Specialist',
                     'source':'Himalayas','review_only':True, 'precheck_eligibility':'uncertain'}
            second = {'job_url':'https://example.com/b', 'company_name':'B', 'job_title':'Analyst',
                      'source':'Jobicy','review_only':False,'precheck_eligibility':'eligible'}
            cal.update_history(p,[first], '2026-10-15T12:00:00Z')
            cal.update_history(p,[second], '2026-10-16T12:00:00Z')
            d = json.loads(p.read_text())
            self.assertEqual(d['https://example.com/a']['status'],'not_seen_in_latest_run_status_unknown')
            self.assertEqual(d['https://example.com/a']['first_seen'],'2026-10-15T12:00:00Z')
            cal.update_history(p,[first], '2026-10-17T12:00:00Z')
            self.assertEqual(json.loads(p.read_text())['https://example.com/a']['first_seen'],
                             '2026-10-15T12:00:00Z')

    def test_replay_frozen_inventory_is_read_only_and_preserves_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            csv_path=p/'audit.csv'
            csv_path.write_text('source,company,job_title,location,remote,job_url,description_excerpt,screen_outcome,priority,eligibility\n'
                'Himalayas,A,Teaching Assistant,,True,https://example.com/1,Excellent written and spoken English and Spanish language skills.,candidate,80,uncertain\n'
                'Jobicy,B,Software Engineer,,True,https://example.com/2,Fluent German mandatory.,role_out_of_scope,,not_checked\n')
            results=cal.replay_audit(csv_path,output_path=p/'replay.csv')
            self.assertEqual(results['total'],2)
            self.assertEqual(results['changed'],1)
            self.assertEqual(results['new']['role_out_of_scope'],1)
            self.assertEqual(results['new']['mandatory_language_excluded'],1)


if __name__ == '__main__':
    unittest.main()
