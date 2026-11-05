import json
import tempfile
import unittest
from pathlib import Path

from interaction_evidence import collect

FIXTURE = Path(__file__).with_name('fixtures') / 'accepted-question.jsonl'
SESSION = '01a1ab12-1e53-7111-9ba8-7f9efd0c1c32'


class EvidenceTest(unittest.TestCase):
    def sample(self, rows=None, trace=''):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / 'logs').mkdir()
        (root / 'logs/trace.txt').write_text('session id: ' + SESSION + '\n' + trace)
        if rows is not None:
            path = root / 'codex-home/sessions/rollout.jsonl'
            path.parent.mkdir(parents=True)
            meta = {'type': 'session_meta', 'payload': {'id': SESSION}}
            path.write_text('\n'.join(json.dumps(o) for o in [meta, *rows]))
        return collect(root)

    def setUp(self):
        self.rows = [json.loads(s) for s in FIXTURE.read_text().splitlines()]

    def test_real_async_call_is_accepted_but_display_unknown(self):
        evidence = self.sample(self.rows)
        call, = evidence['calls']
        message, = evidence['async_messages']
        self.assertEqual(message['call_id'], call['call_id'])
        self.assertEqual(message['host_displayed'], 'unknown')
        self.assertIn('具体金额和币种', call['questions'][0])
        self.assertEqual(call['accepted'], True)
        self.assertEqual(call['host_displayed'], 'unknown')

    def test_orphan_or_conflicting_results_do_not_prove_acceptance(self):
        call, event, reply = self.rows
        for output, identity, expected in [
                ('{"accepted":false}', call['payload']['call_id'], False),
                ('{"accepted":"true"}', call['payload']['call_id'], 'unknown'),
                ('{"accepted":true}', 'other', 'unknown')]:
            changed = dict(reply, payload=dict(reply['payload'], output=output, call_id=identity))
            self.assertEqual(self.sample([call,event,changed])['calls'][0]['accepted'], expected)
        self.assertEqual(self.sample([call,event])['calls'][0]['accepted'], 'unknown')
        self.assertEqual(self.sample([call,self.rows[2],self.rows[2]])['calls'][0]['accepted'], 'unknown')

    def test_cli_only_preserves_intermediate_request_without_claiming_a_call(self):
        data = self.sample(trace='codex\n请提供审批金额与币种。\nexec\ncat prd.md\n')
        self.assertEqual(data['rollout_status'], 'unknown')
        self.assertEqual(data['calls'], [])
        self.assertIn('请提供审批金额与币种。', data['cli_messages'][0]['text'])

    def test_mismatched_session_is_excluded(self):
        self.rows.insert(0, {'type':'session_meta','payload':{'id':'unrelated'}})
        self.assertFalse(self.sample(self.rows)['calls'])

    def test_return_from_another_turn_does_not_match(self):
        turn = {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'later'}}
        call, event, reply = self.rows
        data = self.sample([call, event, turn, reply])
        self.assertEqual(data['calls'][0]['accepted'], 'unknown')

    def test_malformed_event_does_not_produce_evidence(self):
        data = self.sample([*self.rows, {'payload': None}])
        self.assertEqual(data['rollout_status'], 'unknown')
        self.assertTrue(data['evidence_gaps'])

    def test_unknown_runtime_item_is_a_gap(self):
        malformed = {'type': 'event_msg',
                     'payload': {'type': 'item_completed', 'item': None}}
        evidence = self.sample([*self.rows, malformed])
        self.assertEqual(evidence['rollout_status'], 'unknown')
        self.assertEqual(evidence['calls'][0]['accepted'], True)
        self.assertTrue(evidence['evidence_gaps'])

    def test_packet_preserves_unknown_and_frozen_criteria_without_overwriting(self):
        from prepare_judge import prepare
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            root = base / 'candidate-demo'
            (root / 'work').mkdir(parents=True)
            (root / 'logs').mkdir()
            (root / 'work/input.txt').write_text('采购')
            (root / 'logs/answer.txt').write_text(f'见 {root}/work/prd.md')
            key = base / 'key.json'
            key.write_text(json.dumps({'sample-01': root.name}))
            (base / 'criteria.md').write_bytes(b'frozen\n')
            dest = base / 'blind'
            prepare(key, dest)
            raw = (dest / 'sample-01/interaction-evidence.json').read_text()
            self.assertNotIn(root.name, raw)
            self.assertEqual(json.loads(raw)['rollout_status'], 'unknown')
            self.assertEqual((dest / 'criteria.md').read_bytes(), b'frozen\n')
            with self.assertRaises(FileExistsError):
                prepare(key, dest)
