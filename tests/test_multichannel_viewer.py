import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('multichannel_viewer', ROOT/'data_viewer/view_multichannel.py')
viewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(viewer)


class ViewerExportTests(unittest.TestCase):
    def test_nested_sessions_and_protocol_display_assignment_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ['实验 A','实验 B']:
                session=root/name;session.mkdir()
                (session/'grip_multichannel.csv').write_text('csv content',encoding='utf-8')
                (session/'experiment_setup.json').write_text(json.dumps({'hand_assignment':{'source_hand':'left','display_hand':'right'}}))
            page=viewer.build_html(root)
            data=json.loads(re.search(r'<script id="embedded-data" type="application/json">(.*?)</script>',page,re.S).group(1))
            self.assertEqual([e['name'] for e in data],['实验 A','实验 B'])
            self.assertEqual(data[0]['setup']['hand_assignment'],{'source_hand':'left','display_hand':'right'})
            self.assertEqual(len(viewer.find_recordings(root/'实验 A')),1)
            self.assertEqual(len(viewer.find_recordings(root/'实验 A/grip_multichannel.csv')),1)

    def test_embedded_csv_cannot_close_script_or_execute_markup(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/'grip_multichannel.csv'
            text='</script><script>alert(1)</script> & 中文'
            f.write_text(text)
            page=viewer.build_html(f)
            payload=re.search(r'<script id="embedded-data" type="application/json">(.*?)</script>',page,re.S).group(1)
            self.assertNotIn('<',payload)
            self.assertEqual(json.loads(payload)[0]['csv'],text)

    def test_empty_folder_rejected_and_existing_output_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            with self.assertRaisesRegex(ValueError,'没有找到'):viewer.find_recordings(folder)
            source=folder/'grip_multichannel.csv';source.write_text('data')
            target=folder/'existing.html';target.write_text('keep')
            self.assertEqual(viewer.main(['--data-root',str(source),'--output',str(target),'--no-open']),1)
            self.assertEqual(target.read_text(),'keep')
            self.assertEqual(source.read_text(),'data')


if __name__=='__main__':unittest.main()
