import json
import base64
import zlib
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

import preview_export as preview
from preview_plot import render_preview


class PreviewTests(unittest.TestCase):
    def test_preview_transport_accepts_complete_reply_after_api_chatter(self):
        from client import Client
        data = {'available': False, 'message': 'synthetic response'}
        encoded = base64.b64encode(zlib.compress(json.dumps({'ok': True, 'data': data}).encode()))
        process = SimpleNamespace(returncode=0, communicate=lambda *a, **k: (b'API message\nLUMERICAL_PREVIEW_V1:' + encoded + b'\n', b''), kill=lambda: None)
        with patch('client.subprocess.Popen', return_value=process):
            self.assertEqual(Client(persistent=False).prepare_preview('sample.fsp'), data)

    def test_interrupted_preview_connection_is_reported_before_decoding(self):
        from client import Client
        process = SimpleNamespace(returncode=255, communicate=lambda *a, **k: (b'LUMERICAL_PREVIEW_V1:abc', b'connection closed'), kill=lambda: None)
        with patch('client.subprocess.Popen', return_value=process):
            with self.assertRaisesRegex(RuntimeError, '连接中断'):
                Client(persistent=False).prepare_preview('sample.fsp')

    def test_incomplete_preview_reply_has_recoverable_message(self):
        from client import Client
        process = SimpleNamespace(returncode=0, communicate=lambda *a, **k: (b'LUMERICAL_PREVIEW_V1:abc', b''), kill=lambda: None)
        with patch('client.subprocess.Popen', return_value=process):
            with self.assertRaisesRegex(RuntimeError, '读取缓存'):
                Client(persistent=False).prepare_preview('sample.fsp')

    def test_running_guard_uses_latest_snapshot_and_pipeline_descendants(self):
        from app import Monitor
        monitor = SimpleNamespace(snapshot={'jobs': [{'path': 'batch', 'kind': 'pipeline', 'pids': [123]}]})
        self.assertTrue(Monitor._preview_is_running(monitor, 'batch/sample.fsp'))
        self.assertFalse(Monitor._preview_is_running(monitor, 'another/sample.fsp'))
        monitor.snapshot = {'jobs': []}
        self.assertFalse(Monitor._preview_is_running(monitor, 'batch/sample.fsp'))

    def test_bundled_interpreter_is_used_when_system_numpy_is_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            api = root / 'api' / 'python' / 'lumapi.py'
            api.parent.mkdir(parents=True)
            api.write_text('# synthetic')
            python = root / 'python' / 'bin' / 'python3'
            python.parent.mkdir(parents=True)
            python.write_text('# synthetic')
            with patch.object(preview, '_api_candidates', return_value=[api]), patch('preview_export.importlib.util.find_spec', return_value=None), patch('preview_export.os.access', return_value=True), patch.dict('os.environ', {'LUMERICAL_PYTHON': ''}):
                self.assertEqual(preview.preview_interpreter(), python)
    def test_missing_cache_and_stale_source_are_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project = root / 'sample.fsp'
            project.write_bytes(b'synthetic project')
            info = preview.read_preview(root, 'sample.fsp')
            self.assertFalse(info['available'])
            doc = preview.empty_document(project, root)
            doc['parameters'] = [{'name': 'synthetic', 'value': 1, 'unit': ''}]
            preview.write_preview(root, 'sample.fsp', doc)
            self.assertFalse(preview.read_preview(root, 'sample.fsp')['stale'])
            project.write_bytes(b'changed synthetic project')
            self.assertTrue(preview.read_preview(root, 'sample.fsp')['stale'])

    def test_paths_and_sidecar_symlinks_never_escape_root(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as outside:
            root = Path(folder)
            (root / 'sample.fsp').write_bytes(b'project')
            with self.assertRaises(ValueError):
                preview.read_preview(root, '../outside.fsp')
            with self.assertRaises(ValueError):
                preview.read_preview(root, outside)
            target = Path(outside) / 'private.json'
            target.write_text('{}')
            try:
                (root / 'sample.fsp.preview.json').symlink_to(target)
            except OSError:
                return
            with self.assertRaises(ValueError):
                preview.read_preview(root, 'sample.fsp')

    def test_field_slice_preserves_nonuniform_axes_and_nearest_wavelength(self):
        axes = {'x': np.array([0, 1, 4]) * 1e-6, 'y': np.array([0, 2]) * 1e-6,
                'z': np.array([0.0]), 'lambda': np.array([1.3e-6, 1.55e-6])}
        field = np.zeros((3, 2, 1, 2, 3), dtype=complex)
        field[:, :, 0, 1, 0] = np.array([[1, 2], [3, 4], [5, 6]])
        result = preview.field_slice({**axes, 'E': field}, 'field', wavelength_m=1.55e-6)
        self.assertEqual(result['x'], axes['x'].tolist())
        self.assertEqual(result['y'], axes['y'].tolist())
        self.assertEqual(result['values'], [[1, 4], [9, 16], [25, 36]])
        self.assertEqual(result['wavelength_m'], 1.55e-6)

    def test_transmission_is_sorted_without_changing_direction_or_clipping(self):
        data = {'lambda': np.array([1.6e-6, 1.5e-6]), 'T': np.array([-0.2, 1.1])}
        result = preview.spectrum(data, 'power')
        self.assertEqual(result['wavelength_m'], [1.5e-6, 1.6e-6])
        self.assertEqual(result['values'], [1.1, -0.2])

    def test_rendered_data_is_real_png_and_does_not_mutate_input(self):
        entry = {'name': 'Synthetic power', 'wavelength_m': [1.5e-6, 1.6e-6], 'values': [0.8, 0.9]}
        original = json.dumps(entry)
        image = render_preview('spectrum', entry, (640, 360))
        self.assertTrue(image.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertEqual(json.dumps(entry), original)

    def test_prepare_only_reads_saved_project_and_writes_sidecar(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project = root / 'sample.fsp'
            original = b'synthetic saved project'
            project.write_bytes(original)
            session = FakeSession()
            result = preview.prepare_preview(root, 'sample.fsp', session_factory=lambda *a, **k: session)
            self.assertTrue(result['available'])
            self.assertEqual(project.read_bytes(), original)
            self.assertTrue(session.closed)
            self.assertTrue((root / 'sample.fsp.preview.json').is_file())

    def test_object_walk_restores_scope_and_visits_layer_builder_children(self):
        class Object(dict):
            def getChildren(self):
                session.scope = '::model::builder'
                if self['type'] != 'LayerBuilder':
                    raise AssertionError('Only containers have children')
                return [Object(name='core', type='Rectangle', material='Silicon')]
        class Session:
            scope = '::model'
            def groupscope(self, value=None):
                if value is not None:
                    self.scope = value
                return self.scope
            def selectall(self):
                pass
            def getAllSelectedObjects(self):
                return [Object(name='builder', type='LayerBuilder'), Object(name='power', type='DFTMonitor')]
        session = Session()
        result = preview._objects(session)
        self.assertEqual(session.scope, '::model')
        self.assertIn('::model::builder::core', [name for name, _ in result])
        self.assertIn('Silicon', [preview._get(obj, 'material') for _, obj in result])

    def test_layer_builder_fallback_is_labeled_as_local_gds_not_a_z_slice(self):
        geometry = {'1:0': [np.array([[0, 0], [2e-6, 0], [1e-6, 1e-6]])]}
        class Session(FakeSession):
            def groupscope(self, value=None):
                return '::model'
            def getAllSelectedObjects(self):
                return [{'name': 'builder', 'type': 'LayerBuilder', 'geometry': geometry}]
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / 'sample.fsp'
            project.write_bytes(b'synthetic')
            doc = preview.extract_session(Session(), project, folder)
            self.assertEqual(doc['model']['plane'], 'gds_local_xy')
            self.assertEqual(len(doc['model']['layers']), 1)
            self.assertEqual(doc['model']['layers'][0]['polygons'][0]['contours'][0], geometry['1:0'][0].tolist())
            self.assertTrue(any('GDS' in warning for warning in doc['warnings']))

    def test_polystencil_receives_numeric_matrix_for_z_not_cell_array(self):
        class Session(FakeSession):
            def groupscope(self, value=None):
                return '::model'
            def getAllSelectedObjects(self):
                return [{'name': 'core', 'type': 'Polygon', 'material': 'Silicon'}]
            def polystencil(self, request):
                if not isinstance(request['z'], np.ndarray):
                    raise ValueError('z must be a numeric matrix, not a cell array')
                return [[[np.array([[0, 0], [1e-6, 0], [0, 1e-6]])]]]
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / 'sample.fsp'
            project.write_bytes(b'synthetic')
            doc = preview.extract_session(Session(), project, folder)
            self.assertEqual(len(doc['model']['layers']), 1)

    def test_invalid_nonfinite_or_oversized_cache_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project = root / 'sample.fsp'
            project.write_bytes(b'synthetic')
            sidecar = root / 'sample.fsp.preview.json'
            sidecar.write_text('{"version":1,"bad":NaN}')
            with self.assertRaises(ValueError):
                preview.read_preview(root, 'sample.fsp')
            sidecar.write_text('x' * 200)
            with patch.object(preview, 'MAX_CACHE_BYTES', 100):
                with self.assertRaises(ValueError):
                    preview.read_preview(root, 'sample.fsp')


class FakeSession:
    closed = False
    def load(self, path):
        self.path = path
    def selectall(self):
        pass
    def getAllSelectedObjects(self):
        return []
    def getresult(self, *args):
        return ''
    def close(self):
        self.closed = True
    def __getattr__(self, name):
        if name in {'save', 'run', 'runsweep', 'switchtolayout', 'setnamed'}:
            raise AssertionError('Preview must never mutate or solve the project')
        raise AttributeError(name)


if __name__ == '__main__':
    unittest.main()
