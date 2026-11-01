"""Offline tests of audit rules and parity failure detection, no model training."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from packaging.requirements import Requirement
from packaging.utils import parse_wheel_filename
from packaging.version import Version

sys.path.insert(0,str(Path(__file__).resolve().parent))
from resolve_arm64_metadata import active, target_environment, target_tags, resolve, Index
from portability_models import bundle_file, sha, source_sha, verify_bundle
from compare_portability import compare_arrays, compare
from probe_linux_environment import collect


class DependencyRules(unittest.TestCase):
    def test_linux_markers_do_not_inherit_windows_host(self):
        for python in ('3.11','3.12'):
            env=target_environment(python)
            self.assertTrue(active(Requirement('x; sys_platform == "linux" and platform_machine == "aarch64"'),env))
            self.assertFalse(active(Requirement('x; os_name == "nt"'),env))
            self.assertFalse(active(Requirement('x; extra == "cuda"'),env))
            self.assertTrue(active(Requirement('x; extra == "audio"'),env,['audio']))

    def test_abi_glibc_architecture_and_abi3(self):
        tags=target_tags('3.11','2.36')
        def fits(name): return bool(parse_wheel_filename(name)[3] & tags)
        self.assertTrue(fits('x-1.0-cp311-cp311-manylinux_2_28_aarch64.whl'))
        self.assertTrue(fits('x-1.0-cp37-abi3-manylinux2014_aarch64.whl'))
        self.assertFalse(fits('x-1.0-cp312-cp312-manylinux2014_aarch64.whl'))
        self.assertFalse(fits('x-1.0-cp311-cp311-manylinux_2_39_aarch64.whl'))
        self.assertFalse(fits('x-1.0-cp311-cp311-manylinux_2_28_x86_64.whl'))
        self.assertFalse(fits('x-1.0-cp311-cp311-linux_aarch64.whl'))

    def test_resolver_backtracks_and_applies_transitive_constraints(self):
        class Fake:
            def candidates(self,name,requirements,constraints):
                records={'a':[('2',['b>=2']),('1',['b<2'])], 'b':[('2',[]),('1',[])]}
                for version,deps in records[name]:
                    if all(Version(version) in r.specifier for r in requirements+constraints):
                        yield dict(name=name,version=version,requires_dist=deps)
        result,_,_=resolve(Fake(),[Requirement('a'),Requirement('b<2')],{},target_environment('3.12'))
        self.assertEqual(result['a']['version'],'1')
        self.assertEqual(result['b']['version'],'1')
        result,_,_=resolve(Fake(),[Requirement('a==2'),Requirement('b<2')],{},target_environment('3.12'))
        self.assertIsNone(result)

    def test_late_extra_expands_selected_package(self):
        class Fake:
            def candidates(self,name,*_):
                deps={'a':['b; extra == "audio"'],'z':['a[audio]'],'b':[]}
                yield dict(name=name,version='1',requires_dist=deps[name])
        result,_,_=resolve(Fake(),[Requirement('a'),Requirement('z')],{},target_environment('3.12'))
        self.assertEqual(set(result),{'a','b','z'})

    def test_metadata_client_refuses_wheel_and_firmware_bodies(self):
        with tempfile.TemporaryDirectory() as temp:
            index=Index('3.12','2.39',temp,offline=True)
            for url in ['https://example.org/model.whl','https://example.org/update.img','http://example.org/index']:
                with self.assertRaises(ValueError): index.get(url)


class NumericalComparison(unittest.TestCase):
    def test_small_difference_and_large_drift(self):
        a=np.array([.1,.9],dtype=np.float32)
        self.assertTrue(compare_arrays(a,a+1e-7,1e-5,1e-4)['passed'])
        self.assertFalse(compare_arrays(a,a+.1,1e-5,1e-4)['passed'])

    def test_missing_infinite_shape_dtype_and_validity(self):
        a=np.array([np.nan,1.],dtype=np.float32)
        self.assertTrue(compare_arrays(a,a,1e-5,1e-4)['passed'])
        for b in [np.array([0.,1.],np.float32),np.array([np.nan,np.inf],np.float32),a.astype(np.float64),a[None]]:
            self.assertFalse(compare_arrays(a,b,1e-5,1e-4)['passed'])
        self.assertFalse(compare_arrays(np.array([np.nan]),np.array([np.nan]),1e-5,1e-4)['passed'])
        self.assertFalse(compare_arrays(np.array([True]),np.array([False]),0,0)['passed'])

    def test_manifest_mismatch_is_not_numeric_success(self):
        with tempfile.TemporaryDirectory() as temp:
            a=Path(temp)/'a';b=Path(temp)/'b';a.mkdir();b.mkdir()
            for p,value in [(a,'first'),(b,'different')]:
                (p/'report.json').write_text(json.dumps(dict(passed=True,manifest_sha256=value,results={'eye':True})))
            with self.assertRaisesRegex(ValueError,'manifest'): compare(a,b,{})

    def test_top1_difference_and_corrupt_outputs_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            a=Path(temp)/'a';b=Path(temp)/'b';a.mkdir();b.mkdir()
            for p,values in [(a,[.500001,.499999]),(b,[.499999,.500001])]:
                (p/'report.json').write_text(json.dumps(dict(passed=True,manifest_sha256='same',results={'eye':True})))
                np.savez(p/'eye.npz',probabilities=np.array([values],np.float32))
                (p/'eye.json').write_text(json.dumps(dict(passed=True,manifest_sha256='same',model_sha256='model',
                                                         device='cpu',output_sha256=sha(p/'eye.npz'))))
            result=compare(a,b,dict(eye=dict(atol=1e-5,rtol=1e-4)))
            self.assertFalse(result['passed'])
            self.assertTrue(result['results']['eye']['arrays']['probabilities']['passed'])
            (b/'eye.npz').write_bytes(b'corrupted')
            with self.assertRaisesRegex(ValueError,'corrupt'): compare(a,b,dict(eye=dict(atol=1e-5,rtol=1e-4)))

    def test_bundle_tamper_and_path_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);(p/'x.npy').write_bytes(b'input')
            (p/'manifest.json').write_text(json.dumps(dict(inputs={'x':dict(path='x.npy',sha256=sha(p/'x.npy'))},
                                                         models={},source_sha256={})))
            verify_bundle(p)
            (p/'x.npy').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'SHA256'): verify_bundle(p)
            with self.assertRaises(ValueError): bundle_file(p,'../outside')

    def test_source_line_endings_do_not_relax_model_byte_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            a=Path(temp)/'a'; b=Path(temp)/'b'
            a.write_bytes(b'x = 1\r\n'); b.write_bytes(b'x = 1\n')
            self.assertEqual(source_sha(a),source_sha(b))
            self.assertNotEqual(sha(a),sha(b))


class ReadOnlyInventory(unittest.TestCase):
    def test_default_inventory_does_not_spawn_or_open_devices(self):
        with patch('probe_linux_environment.subprocess.run',side_effect=AssertionError('no subprocess expected')):
            result=collect()
        self.assertEqual(result['commands'],{})
        self.assertEqual(result['board_validation'],'待板端验证')
        self.assertTrue(all(item['opened'] is False for item in result['video']))


if __name__ == '__main__': unittest.main()
