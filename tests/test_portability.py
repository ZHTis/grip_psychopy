"""Exercise a copied project from a different working directory."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PortabilityTests(unittest.TestCase):
    def test_relocated_project_and_nested_config(self):
        with tempfile.TemporaryDirectory(prefix='grip relocation ') as temp:
            moved = Path(temp)/'experiment folder'
            moved.mkdir()
            for folder in ('gripflight','assets','maps'):
                shutil.copytree(ROOT/folder,moved/folder,ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copyfile(ROOT/'run_task.py',moved/'run_task.py')
            config = json.loads((ROOT/'config.json').read_text(encoding='utf-8'))
            (moved/'configs').mkdir()
            (moved/'configs/session.json').write_text(json.dumps(config),encoding='utf-8')
            result = subprocess.run([sys.executable,'-B',str(moved/'run_task.py'),
                '--simulate','--headless','--config','configs/session.json'],
                cwd=temp,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            outputs = list((moved/'data').glob('*/metadata.json'))
            self.assertEqual(len(outputs),1)
            self.assertEqual(json.loads(outputs[0].read_text())['status'],'complete')
            self.assertFalse((moved/'configs/data').exists())
            self.assertFalse((Path(temp)/'data').exists())


if __name__=='__main__': unittest.main()
