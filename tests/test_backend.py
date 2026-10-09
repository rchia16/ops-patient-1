import base64
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
from backend import Backend, CUE
from validation import CaseError
from mcp_server import TOOLS, execute_tool

class PatientTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data=Path(self.tmp.name)/'data'
        shutil.copytree(ROOT/'data',self.data)
        self.db=Path(self.tmp.name)/'log.sqlite3'
        self.b=Backend(self.data,self.db,'conversation-A')
        self.addCleanup(self.b.db.close)
        self.case=json.loads((self.data/'patient_1.json').read_text())
    def alter(self,fn):
        fn(self.case)
        (self.data/'patient_1.json').write_text(json.dumps(self.case,ensure_ascii=False))
    def load(self): return self.b.load_case(self.case['case_id'])['session_id']
    def error(self,code,fn):
        with self.assertRaises(CaseError) as ctx: fn()
        self.assertEqual(ctx.exception.code,code)
    def test_actual_case_validates_without_conflicts(self):
        loaded=self.b.load_case(self.case['case_id'])
        self.assertEqual(loaded['validation_issues'],[])
        self.assertTrue(loaded['initial_image_required'])
    def test_demographics_exact_no_expanded_initials(self):
        sid=self.load()
        self.assertEqual(self.b.get_patient_fact(sid,'identity')['value'],{'name':'EF','age':65,'sex':'M'})
        f=self.b.get_patient_fact(sid,'name')
        self.assertEqual(f['message'],'My name is EF.')
        self.assertTrue(self.b.validate_response(sid,f['message'],[f['evidence_ref']])['may_show'])
        self.assertFalse(self.b.validate_response(sid,'My name is Edward Foster.',[f['evidence_ref']])['may_show'])
    def test_history_nested_and_missing_no_invention(self):
        sid=self.load()
        self.assertEqual(self.b.get_patient_fact(sid,'history_of_presenting_illness.onset')['value'],'Acute, 1-day duration.')
        self.error('FORBIDDEN_FIELD',lambda:self.b.get_patient_fact(sid,'occupation'))
        self.error('FORBIDDEN_FIELD',lambda:self.b.get_patient_fact(sid,'history_of_presenting_illness.secret'))
    def test_history_missing_returns_error(self):
        self.alter(lambda c:c['profile']['history'].pop('age'))
        sid=self.load()
        self.error('MISSING_FIELD',lambda:self.b.get_patient_fact(sid,'age'))
        self.error('MISSING_FIELD',lambda:self.b.get_patient_fact(sid,'identity'))
    def test_numerical_values_all_from_examination(self):
        sid=self.load()
        expected={'iop':('55 mmHg (on medication)','20 mmHg (on medication)'),
                  'cct':('495 µm','500 µm'),
                  'visual_acuity':('RE: 6/38 (no improvement with pinhole)','LE: 6/12 → 6/9 with pinhole')}
        for test,vals in expected.items():
            for eye,value in zip(['right','left'],vals):
                with self.subTest(test=test,eye=eye):
                    out=self.b.get_test_result(sid,test,eye)
                    self.assertTrue(out['message'].endswith(value))
                    self.assertEqual(out['message'].count('[NURSE]'),1)
                    self.assertNotIn('\n',out['message'])
        self.assertIn('-18 dB',self.b.get_test_result(sid,'perimetry','left')['message'])
        self.assertIn('~4.5 mm',self.b.get_test_result(sid,'pupils','right')['message'])
        self.assertNotIn('4.5',self.b.get_test_result(sid,'pupils','left')['message'])
    def test_laterality_and_unknown_test(self):
        sid=self.load()
        self.assertIn('55 mmHg',self.b.get_test_result(sid,'iop','OD')['message'])
        self.assertNotIn('55',self.b.get_test_result(sid,'iop','OS')['message'])
        self.error('INVALID_EYE',lambda:self.b.get_test_result(sid,'iop','bad'))
        self.error('UNVERIFIABLE_LATERALITY',lambda:self.b.get_test_result(sid,'oct','right'))
        self.error('UNKNOWN_TEST',lambda:self.b.get_test_result(sid,'RAPD','both'))
    def test_notes_cannot_supply_missing_numbers(self):
        self.alter(lambda c:c['profile']['examination'].pop('iop'))
        sid=self.load()
        self.error('SOURCE_CONFLICT',lambda:self.b.get_test_result(sid,'iop','right'))
    def test_missing_test_without_notes(self):
        self.alter(lambda c:(c['profile']['examination'].pop('iop'),c.update(case_notes='')))
        sid=self.load()
        self.error('MISSING_FIELD',lambda:self.b.get_test_result(sid,'iop','right'))
    def test_conflicts_numeric_fields(self):
        for old,new,test in [('55/20','60/20','iop'),('495/500','510/500','cct'),
                             ('6/38 RE','6/60 RE','visual_acuity'),('C/D 0.9 RE','C/D 0.7 RE','fundus'),
                             ('−18 dB','−10 dB','perimetry'),('4.5 mm','5.5 mm','pupils')]:
            with self.subTest(test=test):
                c=copy.deepcopy(self.case); c['case_notes']=c['case_notes'].replace(old,new)
                (self.data/'patient_1.json').write_text(json.dumps(c))
                b=Backend(self.data,':memory:','x')
                self.addCleanup(b.db.close)
                loaded=b.load_case(c['case_id'])
                self.assertIn('profile.examination.'+test,loaded['blocked_fields'])
                self.error('SOURCE_CONFLICT',lambda:b.get_test_result(loaded['session_id'],test,'both'))
    def test_conflicting_gonio_and_identity(self):
        self.alter(lambda c:c.update(case_notes=c['case_notes'].replace('RE closed','RE open').replace('65M;','70M;')))
        out=self.b.load_case(self.case['case_id']); sid=out['session_id']
        self.error('SOURCE_CONFLICT',lambda:self.b.get_test_result(sid,'gonioscopy','right'))
        self.error('SOURCE_CONFLICT',lambda:self.b.get_patient_fact(sid,'identity'))
    def test_unparseable_note_blocks_before_use(self):
        self.alter(lambda c:c.update(case_notes=c['case_notes'].replace('55/20 (GAT)','RE pressure fifty-five, left unknown')))
        sid=self.load()
        self.error('SOURCE_CONFLICT',lambda:self.b.get_test_result(sid,'iop','right'))
    def test_image_selection_bytes_and_state(self):
        sid=self.load()
        for eye,filename in [('right','1_right.png'),('left','1_left.png')]:
            out=self.b.get_linked_image(sid,'Fundus image',eye)
            self.assertEqual([i['filename'] for i in out['images']],[filename])
            self.assertEqual(base64.b64decode(out['images'][0]['data']),(self.data/'images'/filename).read_bytes())
            self.assertNotIn('description',out['images'][0])
            self.assertTrue(self.b.disclosed(sid,filename))
            self.assertEqual(out['message'].count(CUE),1)
            self.assertEqual(out['message'].count('[NURSE]'),1)
            self.assertTrue(self.b.validate_response(sid,out['message'],[out['evidence_ref']])['may_show'])
        out=self.b.get_linked_image(sid,'None','both')
        self.assertEqual(out['images'][0]['filename'],'1.png')
    def test_both_eye_images_and_mandatory_disclosure(self):
        sid=self.load()
        out=self.b.get_test_result(sid,'fundus','both')
        self.assertEqual(self.b.validate_response(sid,out['message'],[out['evidence_ref']])['reason'],'IMAGE_NOT_DISCLOSED')
        image=self.b.get_linked_image(sid,'fundus','both')
        self.assertEqual({x['filename'] for x in image['images']},{'1_left.png','1_right.png'})
        self.assertTrue(self.b.validate_response(sid,out['message'],[out['evidence_ref']])['may_show'])
    def test_image_missing_and_corruption_at_start(self):
        (self.data/'images/1_left.png').unlink()
        self.error('IMAGE_UNAVAILABLE',self.load)
        (self.data/'images/1_left.png').write_bytes(b'invalid')
        self.error('IMAGE_REFERENCE_ERROR',self.load)
    def test_image_missing_after_load_and_change(self):
        sid=self.load()
        p=self.data/'images/1_left.png'; p.unlink()
        self.error('IMAGE_UNAVAILABLE',lambda:self.b.get_linked_image(sid,'Fundus image','left'))
        p.write_bytes(b'changed')
        self.error('IMAGE_CHANGED',lambda:self.b.get_linked_image(sid,'Fundus image','left'))
    def test_schema_and_path_traversal(self):
        self.alter(lambda c:c['profile']['history'].update(age='65'))
        self.error('SCHEMA_ERROR',self.load)
        self.alter(lambda c:(c['profile']['history'].update(age=65),c['images_linked'][0].update(filename='../1.png')))
        self.error('SCHEMA_ERROR',self.load)
    def test_source_missing_changed_and_end_still_works(self):
        sid=self.load(); p=self.data/'patient_1.json'; p.unlink()
        self.error('SOURCE_UNAVAILABLE',lambda:self.b.get_patient_fact(sid,'name'))
        self.assertEqual(self.b.end_case(sid)['status'],'ended')
        p.write_text(json.dumps(self.case)); sid=self.load()
        self.alter(lambda c:c['profile']['history'].update(name='ZZ'))
        self.error('SOURCE_CHANGED',lambda:self.b.get_patient_fact(sid,'name'))
    def test_diagnosis_and_hidden_metadata_not_exposed(self):
        sid=self.load()
        for field in ['diagnosis','plan_summary','case_notes','required_skills','emotional_affect','images_linked.description','notes','profile.history.name']:
            self.error('FORBIDDEN_FIELD',lambda:self.b.get_patient_fact(sid,field))
        self.assertFalse(self.b.validate_response(sid,self.case['diagnosis'],[])['may_show'])
        f=self.b.get_patient_fact(sid,'age')
        for response in ['You have acute angle closure.', 'I am 70 years old.', f['message']+' My name is John.']:
            self.assertFalse(self.b.validate_response(sid,response,[f['evidence_ref']])['may_show'])
    def test_session_continuity_and_one_active_case(self):
        sid=self.load(); self.b.record_interaction(sid,{'actor':'user','text':'What is your age?'})
        self.b.get_linked_image(sid,'None','both')
        again=Backend(self.data,self.db,'conversation-A'); self.addCleanup(again.db.close)
        self.error('ACTIVE_CASE_EXISTS',lambda:again.load_case(self.case['case_id']))
        self.assertEqual(again.get_patient_fact(sid,'age')['value'],65)
        self.assertTrue(again.disclosed(sid,'1.png'))
        other=Backend(self.data,self.db,'conversation-B'); self.addCleanup(other.db.close)
        self.error('SESSION_NOT_FOUND',lambda:other.get_patient_fact(sid,'age'))
        sid2=other.load_case(self.case['case_id'])['session_id']
        ref=self.b.get_patient_fact(sid,'age')['evidence_ref']
        self.assertFalse(other.validate_response(sid2,"I'm 65 years old.",[ref])['may_show'])
        self.b.end_case(sid)
        self.error('SESSION_ENDED',lambda:self.b.get_patient_fact(sid,'age'))
        self.assertNotEqual(self.load(),sid)
    def test_evidence_validation_tone_and_tampered_tests(self):
        sid=self.load(); f=self.b.get_patient_fact(sid,'age')
        self.assertTrue(self.b.validate_response(sid,'Well, '+f['message'],[f['evidence_ref']])['may_show'])
        test=self.b.get_test_result(sid,'iop','right')
        self.assertFalse(self.b.validate_response(sid,test['message'].replace('55','20'),[test['evidence_ref']])['may_show'])
        self.assertFalse(self.b.validate_response(sid,test['message']+'\nDone.',[test['evidence_ref']])['may_show'])
        self.error('UNVERIFIED_RESPONSE',lambda:self.b.record_interaction(sid,{'actor':'assistant','text':'I am 70.'}))
        self.b.record_interaction(sid,{'actor':'assistant','text':f['message'],'evidence_refs':[f['evidence_ref']]})
    def test_feedback_double_gate_and_real_manual_pages(self):
        sid=self.load()
        self.b.record_interaction(sid,{'actor':'user','text':'give me feedback'})
        self.error('FEEDBACK_LOCKED',lambda:self.b.evaluate_case(sid))
        self.b.end_case(sid)
        self.error('FEEDBACK_NOT_REQUESTED',lambda:self.b.evaluate_case(sid))
        self.b.record_interaction(sid,{'actor':'assistant','text':'give me feedback'})
        self.error('FEEDBACK_NOT_REQUESTED',lambda:self.b.evaluate_case(sid))
        self.b.record_interaction(sid,{'actor':'user','text':'Please give me feedback.'})
        out=self.b.evaluate_case(sid)
        self.assertFalse(out['feedback_generated'])
        self.assertIn('NO PDF',out['override'])
        self.assertTrue(all(p['pdf_page']>0 and p['text'] for p in out['manual_pages']))
        self.assertIn('diagnosis',out['case'])
        seq=[e['seq'] for e in out['events']]; self.assertEqual(seq,sorted(seq))
    def test_feedback_sources_unavailable(self):
        sid=self.load(); self.b.end_case(sid)
        self.b.record_interaction(sid,{'actor':'user','text':'evaluate me'})
        (self.data/'feedback/evaluate.md').unlink()
        self.error('FEEDBACK_SOURCE_UNAVAILABLE',lambda:self.b.evaluate_case(sid))
    def test_tool_contracts_schema_errors_and_image_content(self):
        self.assertEqual(len(TOOLS),8)
        self.assertTrue(all('owner_id' not in tool['inputSchema'].get('properties',{}) for tool in TOOLS))
        self.error('SCHEMA_ERROR',lambda:execute_tool(self.b,'load_case',{'case_id':self.case['case_id'],'extra':True}))
        sid=self.load()
        output,images=execute_tool(self.b,'get_linked_image',{'session_id':sid,'test':'None','eye':'both'})
        self.assertTrue(images[0]['data'])
        self.assertNotIn('data',output['images'][0])
    def test_gateway_never_renders_unverified_patient_text(self):
        from host_gateway import ResponseGateway
        sid=self.load(); shown=[]; gate=ResponseGateway(self.b,shown.append)
        f=self.b.get_patient_fact(sid,'age')
        gate.show(sid,'I am 99 years old.',[f['evidence_ref']])
        self.assertEqual(shown,['This response cannot be verified against the authoritative case.'])
        gate.show(sid,f['message'],[f['evidence_ref']])
        self.assertEqual(shown[-1],f['message'])
    def test_new_notes_syntax_fails_closed(self):
        self.alter(lambda c:c.update(case_notes=c['case_notes']+'; IOP: RE 999 mmHg'))
        sid=self.load()
        self.error('SOURCE_CONFLICT',lambda:self.b.get_test_result(sid,'iop','right'))
    def test_stale_image_evidence_cannot_be_validated(self):
        sid=self.load(); f=self.b.get_linked_image(sid,'Fundus image','right')
        (self.data/'images/1_right.png').unlink()
        self.error('IMAGE_UNAVAILABLE',lambda:self.b.validate_response(sid,f['message'],[f['evidence_ref']]))
    def test_duplicate_image_mapping_and_required_external_image(self):
        self.alter(lambda c:c['images_linked'].append(copy.deepcopy(c['images_linked'][0])))
        self.error('IMAGE_REFERENCE_ERROR',self.load)
        self.alter(lambda c:c.update(images_linked=c['images_linked'][1:-1]))
        self.error('IMAGE_REFERENCE_ERROR',self.load)
if __name__=='__main__': unittest.main()
