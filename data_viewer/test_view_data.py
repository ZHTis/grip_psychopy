import tempfile
import unittest
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from view_data import marker_table, read_table, plot_session


class ViewerTests(unittest.TestCase):
    def test_repeated_codes_link_by_id_and_simulation(self):
        df = pd.DataFrame([
            dict(id=1,kind='marker_request',t_host_s=1,trial=1,code=3,name='start'),
            dict(id=2,kind='marker_request',t_host_s=2,trial=2,code=3,name='start'),
            dict(id=3,kind='marker_ack',t_host_s=2.02,event_id=2,device_micros=2**32-5000,simulated=True),
            dict(id=4,kind='marker_done',t_host_s=2.03,event_id=2,device_micros=5000)])
        result = marker_table(df)
        self.assertEqual(result.iloc[0].status,'no_ack')
        self.assertEqual(result.iloc[1].status,'done')
        self.assertTrue(result.iloc[1].simulated)
        self.assertAlmostEqual(result.iloc[1].request_to_ack_ms,20)
        self.assertAlmostEqual(result.iloc[1].device_pulse_ms,10)

    def test_json_only_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'grip.csv'
            pd.DataFrame([dict(id=1,kind='grip',t_host_s=1,trial=1,payload_json='{"voltage":0.91}')]).to_csv(path,index=False)
            self.assertEqual(read_table(path).iloc[0].voltage,.91)

    def test_empty_data_plot(self):
        empty = pd.DataFrame(columns=['id','kind','t_host_s','trial'])
        session = dict(path=Path('empty'),metadata={},grip=empty,task=empty,events=empty)
        fig = plot_session(session)
        self.assertEqual(len(fig.axes),2)
        plt.close(fig)


if __name__=='__main__': unittest.main()
