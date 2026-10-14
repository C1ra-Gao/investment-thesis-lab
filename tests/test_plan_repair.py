"""Internal mechanical repairs do not change semantic text or bypass strict checks."""
from copy import deepcopy
import unittest
from thesislab.plan_repair import prepare_candidate
from thesislab.workspace import manual_design
from thesislab.domain import ContractError

class PlanRepairTests(unittest.TestCase):
    def test_unique_literal_position_fixed_original_untouched(self):
        original='收入增长，但毛利率未改善。';d=manual_design(original);d['claims'][0]['spans'][0]['end']-=1
        before=deepcopy(d);fixed,changes=prepare_candidate(d,original)
        self.assertEqual(d,before);self.assertEqual(len(changes),1)
        self.assertEqual(fixed['claims'][0]['spans'][0]['end'],len(original))
        self.assertEqual(fixed['claims'][0]['statement'],original)
    def test_invented_text_not_repaired(self):
        d=manual_design('收入增长。');d['claims'][0]['spans'][0]['text']='盈利增长。'
        with self.assertRaises(ContractError):prepare_candidate(d,'收入增长。')
    def test_duplicate_substring_not_guessed(self):
        d=manual_design('增长，增长。');d['claims'][0]['spans']=[{'start':1,'end':2,'text':'增长'}]
        with self.assertRaises(ContractError):prepare_candidate(d,d['statement'])
    def test_missing_refute_task_not_hidden_or_invented(self):
        d=manual_design('收入增长。');d['tasks']=d['tasks'][:1]
        with self.assertRaises(ContractError):prepare_candidate(d,d['statement'])
    def test_changed_original_not_accepted(self):
        with self.assertRaises(ContractError):prepare_candidate(manual_design('收入未增长。'),'收入增长。')
