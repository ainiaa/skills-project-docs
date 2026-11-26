"""Record-backed business relation behavior. 作者：Jeff.Liu"""
import copy
import importlib.util
import json
import os
import py_compile
import shutil
import time
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from lifecycle_record import check_record, update_record, _record_lock
from test_lifecycle_record import record

SPEC = importlib.util.find_spec('lifecycle_relations')
relations = __import__('lifecycle_relations') if SPEC else None
ROOT = Path(__file__).resolve().parents[1]
TYPES = ('extends', 'depends_on', 'supersedes', 'resolves', 'conflicts_with', 'relates_to')


class RelationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(relations, 'record-backed relation tool is missing')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'record.json'
        self.original = record()
        self.path.write_text(json.dumps(self.original))

    def load(self):
        return json.loads(self.path.read_text())

    def test_six_types_use_single_source_and_preserve_history_evidence(self):
        for kind in TYPES:
            with self.subTest(kind=kind):
                self.path.write_text(json.dumps(self.original))
                self.path.with_name('record.json.rev-1.json').unlink(missing_ok=True)
                result = relations.set_relation(self.path, 'test', kind, 'issue', 1)
                current = self.load()
                self.assertEqual(result['status'], 'applied')
                self.assertEqual(current['revision'], 2)
                self.assertEqual(current['artifacts'][2]['version'], 2)
                self.assertEqual(current['artifacts'][2]['evidence'], self.original['artifacts'][2]['evidence'])
                self.assertEqual(json.loads(self.path.with_name('record.json.rev-1.json').read_text()), self.original)
                if kind == 'depends_on':
                    self.assertNotIn('depends_on', current['artifacts'][2].get('relations', {}))
                edges = relations.query(current, 'test', kind, 'outgoing')['edges']
                self.assertTrue(any(e['target'] == 'issue' for e in edges))
                self.assertTrue(check_record(current)['valid'])

    def test_query_symmetric_types_and_directed_reverse(self):
        for kind in TYPES:
            data = record()
            if kind == 'depends_on':
                data['artifacts'][2]['depends_on'].append({'id':'issue','version':1})
            else:
                data['artifacts'][2]['relations'] = {kind:[{'id':'issue','version':1}]}
            self.assertEqual(len(relations.query(data, 'issue', kind, 'incoming')['edges']), 1 if kind != 'depends_on' else 2)
            outgoing = relations.query(data, 'issue', kind, 'outgoing')['edges']
            self.assertEqual(len(outgoing), 1 if kind in ('relates_to','conflicts_with') else 0)
        self.assertEqual(relations.query(record(), 'issue', 'extends')['edges'], [])

    def test_only_dependencies_propagate_impact(self):
        data = record()
        extra = copy.deepcopy(data['artifacts'][2]);extra.update(id='context', depends_on=[], evidence=[])
        extra['relations'] = {'extends':[{'id':'issue','version':1}], 'conflicts_with':[{'id':'test','version':1}]}
        data['artifacts'].append(extra)
        impact = relations.impact(data, 'issue')
        self.assertEqual(impact['direct'], ['requirement'])
        self.assertEqual(impact['indirect'], ['test'])
        self.assertEqual(impact['affected'], ['issue','requirement','test'])
        self.assertTrue(any(e['source']=='context' for e in impact['context']))
        self.assertEqual(relations.impact(data,'context')['affected'], ['context'])

    def test_validation_malformed_duplicates_self_missing_and_cycles(self):
        for refs in (None, {}, ['bad'], [{'id':'issue','version':True}], [{'id':'issue','version':0}],
                     [{'id':'missing','version':1}], [{'id':'test','version':1}],
                     [{'id':'issue','version':1}]*2):
            for kind in TYPES:
                data = record()
                if kind == 'depends_on':data['artifacts'][2]['depends_on'] = refs
                else:data['artifacts'][2]['relations'] = {kind:refs}
                with self.subTest(kind=kind,refs=refs):
                    self.assertFalse(check_record(data)['valid'])
        for bad in (None, [], {'unknown':[]}, {'depends_on':[]}):
            data=record();data['artifacts'][0]['relations']=bad
            self.assertFalse(check_record(data)['valid'])
        data=record();data['artifacts'][0]['depends_on']=[{'id':'test','version':1}]
        self.assertFalse(relations.validate_relations(data)['valid'])
        for kind in ('extends','supersedes','resolves','conflicts_with','relates_to'):
            data=record();data['artifacts'][0]['relations']={kind:[{'id':'test','version':1}]}
            self.assertTrue(check_record(data)['valid'])

    def test_symmetric_reverse_duplicates_and_stale_versions(self):
        for kind in ('conflicts_with','relates_to'):
            data=record()
            data['artifacts'][0]['relations']={kind:[{'id':'test','version':1}]}
            data['artifacts'][2]['relations']={kind:[{'id':'issue','version':1}]}
            self.assertFalse(check_record(data)['valid'])
        data=record();data['artifacts'][0]['relations']={'resolves':[{'id':'test','version':2}]}
        self.assertTrue(check_record(data)['valid'])
        self.assertIn('issue', [item['id'] for item in check_record(data)['needs_review']])
        self.assertEqual(relations.validate_relations(data)['stale'][0]['target'],'test')

    def test_orphans_diagnoses_dangling_and_distinguishes_isolated(self):
        data=record();data['artifacts'][0]['relations']={'resolves':[{'id':'missing','version':1}]}
        result=relations.orphans(data)
        self.assertEqual(result['dangling'][0]['target'],'missing')
        self.assertEqual(result['isolated'],[])
        data=record()
        for node in data['artifacts']:node['depends_on']=[]
        self.assertEqual(relations.orphans(data)['isolated'], ['issue','requirement','test'])
        with self.assertRaises(ValueError):relations.query(data,'missing')
        for kwargs in ({'relation':'bad'},{'direction':'sideways'}):
            with self.assertRaises(ValueError):relations.query(data,'issue',**kwargs)

    def test_set_remove_noop_replay_and_cas_reject_unrelated_change(self):
        relations.set_relation(self.path,'test','extends','issue',1)
        first=self.path.read_bytes()
        self.assertEqual(relations.set_relation(self.path,'test','extends','issue',1)['status'],'resumed')
        self.assertEqual(self.path.read_bytes(),first)
        self.assertEqual(relations.set_relation(self.path,'test','extends','issue',2)['status'],'unchanged')
        relations.set_relation(self.path,'test','extends','issue',2,remove=True)
        self.assertEqual(relations.query(self.load(),'test','extends')['edges'],[])
        self.assertEqual(relations.set_relation(self.path,'test','extends','issue',2,remove=True)['status'],'resumed')
        with self.assertRaises(ValueError):relations.set_relation(self.path,'test','resolves','issue',1)
        for args in [('missing','extends','issue',3),('test','bad','issue',3),('test','extends','test',3),('test','extends','missing',3),('test','extends','issue',True)]:
            with self.assertRaises(ValueError):relations.set_relation(self.path,*args)
        before=self.path.read_bytes()
        with self.assertRaises(ValueError):relations.set_relation(self.path,'issue','depends_on','test',3)
        self.assertEqual(self.path.read_bytes(),before)

    def test_relation_cli_uses_current_record_without_a_persistent_index(self):
        sidecar = self.path.with_name(self.path.name + '.relations-index.json')
        sidecar.write_text('obsolete sidecar')
        relations.set_relation(self.path, 'test', 'extends', 'issue', 1)
        command = [sys.executable, str(ROOT / 'scripts/lifecycle_relations.py')]
        query = command + ['query', '--record', str(self.path), '--id', 'issue', '--type', 'extends']
        result = subprocess.run(query, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)['edges']), 1)
        self.assertEqual(sidecar.read_text(), 'obsolete sidecar')
        result = subprocess.run(query + ['--index'], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)

    @unittest.skipUnless(os.name=='posix','POSIX lock behavior')
    def test_live_writer_blocks_mutation(self):
        with _record_lock(self.path):
            with self.assertRaises(FileExistsError):
                relations.set_relation(self.path,'test','extends','issue',1)
        self.assertEqual(self.load(),self.original)

    def test_failed_record_replace_replays_from_retained_history(self):
        with patch('lifecycle_record.os.replace', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):relations.set_relation(self.path,'test','extends','issue',1)
        self.assertEqual(self.load(),self.original)
        self.assertTrue(self.path.with_name('record.json.rev-1.json').exists())
        self.assertEqual(relations.set_relation(self.path,'test','extends','issue',1)['status'],'applied')

    def test_legacy_dependency_metadata_remains_compatible(self):
        data=record();data['artifacts'][1]['depends_on'][0]['source']='existing-reference'
        self.assertTrue(check_record(data)['valid'])
        self.path.write_text(json.dumps(data))
        self.assertEqual(relations.set_relation(self.path,'requirement','depends_on','issue',1)['status'],'unchanged')
        self.assertEqual(self.load(),data)

    def test_noop_preserves_legacy_dependency_order_and_metadata(self):
        data=record();data['artifacts'][2]['depends_on']=[{'id':'requirement','version':1},{'id':'issue','version':1,'source':'legacy'}]
        self.path.write_text(json.dumps(data));before=self.path.read_bytes()
        self.assertEqual(relations.set_relation(self.path,'test','depends_on','requirement',1)['status'],'unchanged')
        self.assertEqual(self.path.read_bytes(),before)

    def test_symmetric_reverse_mutations_keep_original_storage_owner(self):
        for kind in relations.SYMMETRIC:
            with self.subTest(kind=kind):
                self.path.write_text(json.dumps(self.original))
                for history in self.path.parent.glob('*.rev-*.json'):history.unlink()
                relations.set_relation(self.path,'issue',kind,'test',1)
                self.assertEqual(relations.set_relation(self.path,'test',kind,'issue',2)['status'],'unchanged')
                relations.set_relation(self.path,'test',kind,'issue',2,remove=True)
                current=self.load()
                self.assertEqual(relations.query(current,'issue',kind)['edges'],[])
                self.assertEqual(current['artifacts'][0]['version'],3)
                self.assertEqual(current['artifacts'][2]['version'],1)

    def test_replay_rejects_wrong_history_revision(self):
        relations.set_relation(self.path,'test','extends','issue',1)
        history=self.path.with_name('record.json.rev-1.json')
        before=json.loads(history.read_text());before['revision']=9;history.write_text(json.dumps(before))
        with self.assertRaises(ValueError):relations.set_relation(self.path,'test','extends','issue',1)

    @unittest.skipUnless(os.name=='posix','POSIX processes')
    def test_real_competing_writers_commit_one_change(self):
        code="""import sys,time
from pathlib import Path
import lifecycle_relations as r
path,barrier,kind=sys.argv[1:]
while not Path(barrier).exists():time.sleep(.01)
try:r.set_relation(path,'test',kind,'issue',1)
except (ValueError,FileExistsError):sys.exit(3)
"""
        env={**os.environ,'PYTHONPATH':str(ROOT/'scripts')}
        barrier=self.path.parent/'start'
        children=[subprocess.Popen([sys.executable,'-c',code,str(self.path),str(barrier),kind],env=env,
                                  stdout=subprocess.PIPE,stderr=subprocess.PIPE) for kind in ('extends','resolves')]
        try:
            barrier.touch()
            for child in children:child.communicate(timeout=10)
            self.assertEqual(sorted(c.returncode for c in children),[0,3])
            self.assertEqual(self.load()['revision'],2)
            self.assertEqual(len(list(self.path.parent.glob('*.rev-*.json'))),1)
        finally:
            for child in children:
                if child.poll() is None:child.kill();child.wait()

    @unittest.skipUnless(os.name=='posix','POSIX hard exit')
    def test_real_hard_exit_before_and_after_commit_replays(self):
        env={**os.environ,'PYTHONPATH':str(ROOT/'scripts')}
        for after in (False,True):
            self.path.write_text(json.dumps(self.original))
            self.path.with_name('record.json.rev-1.json').unlink(missing_ok=True)
            code="""import os,sys
import lifecycle_relations as r
import lifecycle_record as records
replace=records.os.replace
def stop(source,target):
    if sys.argv[2]=='True':replace(source,target)
    os._exit(73)
records.os.replace=stop
r.set_relation(sys.argv[1],'test','extends','issue',1)
"""
            child=subprocess.run([sys.executable,'-c',code,str(self.path),str(after)],env=env,capture_output=True,timeout=10)
            self.assertEqual(child.returncode,73)
            self.assertEqual(self.load()['revision'],2 if after else 1)
            result=relations.set_relation(self.path,'test','extends','issue',1)
            self.assertEqual(result['status'],'resumed' if after else 'applied')
            self.assertEqual(self.load()['revision'],2)
            self.assertFalse(self.path.with_name('record.json.lock').exists())

    def test_cli_legacy_and_new_commands_use_real_files(self):
        def run(*argv):
            return subprocess.run([sys.executable,*argv],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(run('scripts/lifecycle_record.py','--record',str(self.path)).returncode,0)
        for command in ('query','impact','orphans','validate'):
            args=['scripts/lifecycle_relations.py',command,'--record',str(self.path)]
            if command in ('query','impact'):args+=['--id','issue']
            result=run(*args);self.assertEqual(result.returncode,0,result.stderr+result.stdout)
            self.assertIsInstance(json.loads(result.stdout),dict)
        args=['scripts/lifecycle_relations.py','set','--record',str(self.path),'--source','test','--type','resolves','--target','issue','--expected-revision','1']
        self.assertEqual(run(*args).returncode,0)
        self.assertEqual(run(*args).returncode,0)
        validation=run('scripts/lifecycle_relations.py','validate','--record',str(self.path))
        self.assertEqual(validation.returncode,1)
        self.assertTrue(json.loads(validation.stdout)['needs_review'])
        self.assertEqual(run('scripts/lifecycle_relations.py','validate','--record',str(self.path.parent/'missing')).returncode,1)


    def test_orphans_never_certifies_invalid_record_shapes_or_duplicate_ids(self):
        duplicate=record();duplicate['artifacts'].append(copy.deepcopy(duplicate['artifacts'][0]))
        for data in ({},[],{'artifacts':'bad'},duplicate):
            with self.subTest(data=data):
                result=relations.orphans(data)
                self.assertFalse(result['valid'])
                self.assertTrue(result['errors'])

    def test_impact_excludes_stale_edges_from_disconnected_branches(self):
        data=record()
        for identity in ('unrelated-source','unrelated-target'):
            node=copy.deepcopy(data['artifacts'][0]);node.update(id=identity,status='not_started',evidence=[])
            data['artifacts'].append(node)
        data['artifacts'][-2]['relations']={'extends':[{'id':'unrelated-target','version':2}]}
        result=relations.impact(data,'issue')
        self.assertEqual(result['affected'],['issue','requirement','test'])
        self.assertEqual(result['stale'],[])
        data['artifacts'][-2]['relations']['extends'].append({'id':'issue','version':2})
        self.assertEqual([e['target'] for e in relations.impact(data,'issue')['stale']],['issue'])

    def test_replay_rejects_typed_or_invalid_saved_history_after_progress(self):
        for invalid in (False,True):
            with self.subTest(invalid=invalid):
                data=record();data['artifacts'][2]['annotation']=1
                self.path.write_text(json.dumps(data))
                for path in self.path.parent.glob('*.rev-*.json'):path.unlink()
                relations.set_relation(self.path,'test','extends','issue',1)
                current=self.load();current.update(revision=3,owner='later-owner')
                update_record(self.path,current,2)
                history=self.path.with_name('record.json.rev-2.json');saved=json.loads(history.read_text())
                if invalid:saved['artifacts'][2]['evidence'][0]['subject']['version']=True
                else:saved['artifacts'][2]['annotation']=True
                history.write_text(json.dumps(saved));before=self.path.read_bytes()
                with self.assertRaises(ValueError):relations.set_relation(self.path,'test','extends','issue',1)
                self.assertEqual(self.path.read_bytes(),before)

    def test_old_validator_runs_alone_and_module_cli_keeps_working(self):
        scripts=self.path.parent/'scripts';scripts.mkdir()
        shutil.copy(ROOT/'scripts/lifecycle_record.py',scripts/'lifecycle_record.py')
        result=subprocess.run([sys.executable,'-B',str(scripts/'lifecycle_record.py'),'--record',str(self.path)],
                              cwd=self.path.parent,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        shutil.copy(ROOT/'scripts/lifecycle_relations.py',scripts/'lifecycle_relations.py')
        for module,arguments in [('scripts.lifecycle_record',[]),('scripts.lifecycle_relations',['query','--id','issue'])]:
            result=subprocess.run([sys.executable,'-B','-m',module,*arguments,'--record',str(self.path)],
                                  cwd=self.path.parent,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr+result.stdout)

    def test_current_validator_cannot_use_stale_relation_helper_bytecode(self):
        directory=self.path.parent/'runtime';directory.mkdir()
        for name in ('lifecycle_record.py','lifecycle_relations.py'):shutil.copy(ROOT/'scripts'/name,directory/name)
        helper=directory/'lifecycle_relations.py';actual=helper.read_bytes()
        stub=b"def validate_relations(data): return {'valid':True,'errors':[],'edges':[],'stale':[],'dangling':[]}\n#"
        helper.write_bytes(stub+b' '*(len(actual)-len(stub)));stat=helper.stat()
        py_compile.compile(str(helper),doraise=True);helper.write_bytes(actual);os.utime(helper,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        data=record();data['artifacts'][0]['relations']={'extends':[{'id':'issue','version':1}]}
        self.path.write_text(json.dumps(data))
        result=subprocess.run([sys.executable,'-B',str(directory/'lifecycle_record.py'),'--record',str(self.path)],
                              cwd=self.path.parent,capture_output=True,text=True)
        self.assertEqual(result.returncode,1,result.stderr+result.stdout)
        self.assertFalse(json.loads(result.stdout)['valid'])

    @unittest.skipUnless(os.name=='posix','POSIX interruption')
    def test_partial_history_creation_never_blocks_record_or_relation_replay(self):
        env={**os.environ,'PYTHONPATH':str(ROOT/'scripts')}
        for entry in ('relation','record'):
            with self.subTest(entry=entry):
                self.path.write_text(json.dumps(self.original))
                for path in self.path.parent.glob('*.rev-*.json'):path.unlink()
                code="""import os,sys,json
from pathlib import Path
import lifecycle_record as records
import lifecycle_relations as relations
original=records.os.fdopen
def stop(*args,**kwargs):
    output=original(*args,**kwargs)
    os._exit(74)
records.os.fdopen=stop
if sys.argv[2]=='relation':relations.set_relation(sys.argv[1],'test','extends','issue',1)
else:
    candidate=json.loads(Path(sys.argv[1]).read_text());candidate.update(revision=2,owner='later-owner')
    records.update_record(sys.argv[1],candidate,1)
"""
                child=subprocess.run([sys.executable,'-c',code,str(self.path),entry],env=env,capture_output=True,timeout=10)
                self.assertEqual(child.returncode,74,child.stderr.decode());self.assertEqual(self.load(),self.original)
                error=None
                try:
                    if entry=='relation':relations.set_relation(self.path,'test','extends','issue',1)
                    else:
                        candidate=copy.deepcopy(self.original);candidate.update(revision=2,owner='later-owner')
                        update_record(self.path,candidate,1)
                except (OSError,ValueError) as failure:error=str(failure)
                self.assertIsNone(error,'interrupted history publication must remain retryable')
                self.assertEqual(self.load()['revision'],2)
                self.assertEqual(json.loads(self.path.with_name('record.json.rev-1.json').read_text()),self.original)

    def test_history_publish_failure_preserves_current_and_foreign_history(self):
        history=self.path.resolve().with_name('record.json.rev-1.json');link=os.link
        for foreign in (False,True):
            history.unlink(missing_ok=True)
            def fail_publish(source,target):
                if Path(target)==history:
                    if foreign:history.write_bytes(b'foreign-history')
                    raise OSError('history publication failed')
                return link(source,target)
            with patch('lifecycle_record.os.link',side_effect=fail_publish):
                with self.assertRaises(OSError):relations.set_relation(self.path,'test','extends','issue',1)
            self.assertEqual(self.load(),self.original)
            if foreign:self.assertEqual(history.read_bytes(),b'foreign-history')
            else:self.assertFalse(history.exists())
            self.assertFalse(self.path.with_name('record.json.lock').exists())
            self.assertFalse(list(self.path.parent.glob('tmp*')))

    def test_context_binding_review_never_masquerades_as_dependency_propagation(self):
        for kind in ('extends','supersedes','resolves','conflicts_with','relates_to'):
            with self.subTest(kind=kind):
                data=record();nodes=data['artifacts'];ids=('base','context','consumer')
                for node,identity in zip(nodes,ids):
                    node.update(id=identity,branch=identity,depends_on=[])
                    node['evidence'][0]['subject']['id']=identity
                nodes[0]['version']=2;nodes[0]['evidence'][0]['subject']['version']=2
                nodes[1]['relations']={kind:[{'id':'base','version':1}]}
                nodes[2]['depends_on']=[{'id':'context','version':1}]
                data['branches']=[dict(id=i,route='development',required=[i]) for i in ids]
                checked=check_record(data)
                self.assertTrue(checked['valid'])
                self.assertEqual([n['id'] for n in checked['needs_review']],['context'])
                self.assertEqual(checked['branches']['consumer'],'recorded')
                self.assertEqual(relations.impact(data,'base')['affected'],['base'])
                nodes[1]['evidence'][0]['result']='failed'
                self.assertEqual({n['id'] for n in check_record(data)['needs_review']},{'context','consumer'})
                nodes[1]['evidence'][0]['result']='passed'
                nodes[1]['depends_on']=[{'id':'base','version':1}]
                self.assertEqual({n['id'] for n in check_record(data)['needs_review']},{'context','consumer'})


if __name__=='__main__':unittest.main()
