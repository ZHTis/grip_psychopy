import json
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import matplotlib.pyplot as plt
import pandas as pd

from export_grip_ppt import export_folder, P, R
from view_data import load_session, plot_session


class ExportTests(unittest.TestCase):
    def session(self, root, name, status='complete'):
        folder = root/name
        folder.mkdir(parents=True)
        (folder/'metadata.json').write_text(json.dumps({'status': status, 'duration_s': 20}))
        pd.DataFrame([{'id': 1, 'kind': 'grip', 't_host_s': 1, 'voltage': .9},
                      {'id': 2, 'kind': 'grip', 't_host_s': 10, 'voltage': 1.1}]).to_csv(folder/'grip.csv', index=False)
        pd.DataFrame([{'id': 3, 'kind': 'marker_request', 't_host_s': 15,
                       'name': 'run_end', 'code': 7}]).to_csv(folder/'events.csv', index=False)
        return folder

    def test_all_sessions_order_full_time_and_embedded_images(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = self.session(root/'data', '20260910_second', 'aborted')
            self.session(root/'data', '20260909_first')
            self.session(root/'data', '20260911_running', 'recording')
            out = root/'report.pptx'
            manifest = export_folder(root/'data', out, dpi=72)
            self.assertEqual([Path(row['source']).name for row in manifest['slides']],
                             ['20260909_first', '20260910_second'])
            self.assertEqual(len(manifest['skipped']), 1)
            with ZipFile(out) as archive:
                for name in archive.namelist():
                    if name.endswith(('.xml', '.rels')):
                        ET.fromstring(archive.read(name))
                presentation = ET.fromstring(archive.read('ppt/presentation.xml'))
                self.assertEqual(len(presentation.find(f'{{{P}}}sldIdLst')), 2)
                for i in (1,2):
                    self.assertTrue(archive.read(f'ppt/media/image{i}.png').startswith(b'\x89PNG'))
                    slide = ET.fromstring(archive.read(f'ppt/slides/slide{i}.xml'))
                    self.assertEqual(len(slide.findall(f'.//{{{P}}}pic')), 1)
            session = load_session(folder.parent, folder.name)
            fig = plot_session(session, start=0, raw_only=True)
            self.assertEqual(len(fig.axes), 1)
            self.assertEqual(fig.axes[0].get_xlim(), (0,20))
            bars = [line for line in fig.axes[0].lines if line.get_gid() == 'event-marker-bar']
            self.assertEqual(len(bars),1)
            self.assertEqual(bars[0].get_xdata()[0],15)
            plt.close(fig)
            with self.assertRaises(FileExistsError):
                export_folder(root/'data', out)

    def test_empty_and_nonfinite_grip_are_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.session(root/'data', '01_valid')
            for name, voltage in [('02_empty', None), ('03_nan', float('nan')),
                                  ('04_inf', float('inf'))]:
                folder = self.session(root/'data', name)
                rows = [] if voltage is None else [
                    {'id': 1, 'kind': 'grip', 't_host_s': 1, 'voltage': voltage}]
                pd.DataFrame(rows, columns=['id','kind','t_host_s','voltage']).to_csv(
                    folder/'grip.csv', index=False)
            manifest = export_folder(root/'data', root/'valid.pptx', dpi=72)
            self.assertEqual(len(manifest['slides']), 1)
            self.assertEqual(len(manifest['skipped']), 3)
            self.assertTrue(all(row['reason'] == 'no valid grip voltage samples'
                                for row in manifest['skipped']))

    def test_missing_exports_do_not_make_empty_deck(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = self.session(root/'data','test')
            (folder/'events.csv').unlink()
            with self.assertRaises(ValueError):
                export_folder(root/'data',root/'report.pptx')
            self.assertFalse((root/'report.pptx').exists())


if __name__ == '__main__':
    unittest.main()
