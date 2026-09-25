import json
import tempfile
import unittest
from pathlib import Path
from threading import Thread
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import duckdb
import pandas as pd
from level2_detail_server import Service, calculate, source_identity, make_handler, add_detail_controls


class DetailTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.day = '20260922'
        audit = self.root / '_conversion_audit' / self.day
        audit.mkdir(parents=True)
        (audit / 'COMMITTED').write_text('committed')
        (audit / 'manifest.json').write_text(json.dumps({'commit_state': 'COMMITTED'}))
        self.expected = {'code': '600000.SH', 'amount': 1200, 'net': 800}
        con = duckdb.connect()
        trades = pd.DataFrame([
            ['600000.SH', self.day, '93000000', '100000', '100', 'B', '11', '12'],
            ['600000.SH', self.day, '100001000', '100000', '20', 'S', '13', '14'],
            ['600000.SH', self.day, '100002000', '0', '20', '', '13', '14'],
        ], columns=['万得代码', '自然日', '时间', '成交价格', '成交数量', 'BS标志', '叫买序号', '叫卖序号'])
        orders = pd.DataFrame([['600000.SH', self.day, '0', 'B', '120']],
                              columns=['万得代码', '自然日', '委托类型', '委托代码', '委托数量'])
        snapshots = pd.DataFrame([
            ['600000.SH', self.day, '93000000', '99000', '101000', '100', '200'],
            ['600000.SH', self.day, '95957000', '100000', '102000', '200', '100'],
        ], columns=['万得代码', '自然日', '时间', '申买价1', '申卖价1', '申买量1', '申卖量1'])
        for level in range(2, 11):
            snapshots[f'申买价{level}'] = snapshots['申买价1'].astype(int).sub(1000 * (level - 1)).astype(str)
            snapshots[f'申卖价{level}'] = snapshots['申卖价1'].astype(int).add(1000 * (level - 1)).astype(str)
            snapshots[f'申买量{level}'] = str(10 * level)
            snapshots[f'申卖量{level}'] = str(5 * level)
        con.register('trades_fixture', trades)
        con.register('orders_fixture', orders)
        con.register('snapshots_fixture', snapshots)
        con.execute(f"COPY trades_fixture TO '{self.root}/deal_{self.day}.parquet' (FORMAT PARQUET)")
        con.execute(f"COPY orders_fixture TO '{self.root}/order_raw_{self.day}.parquet' (FORMAT PARQUET)")
        con.execute(f"COPY snapshots_fixture TO '{self.root}/snapshot_{self.day}.parquet' (FORMAT PARQUET)")
        con.close()
        self.report = {'markets': [{'day': self.day}], 'cards': [self.expected]}

    def tearDown(self):
        self.temp.cleanup()

    def test_real_calculator_fixture(self):
        result = calculate('600000.SH', self.day, self.expected, lambda _: None, self.root)
        self.assertEqual(result['regularCoverage'], 100)
        self.assertEqual(result['tradeRows'], 2)
        self.assertEqual(sum(r['n'] for r in result['parents']), 800)
        self.assertEqual(result['segments'][0]['a'], 1000)
        self.assertEqual(result['orders'][0]['r'], 1)
        self.assertEqual(result['quotePath']['status'],'AVAILABLE')
        self.assertAlmostEqual(result['quotePath']['segments'][0]['midChangePct'],1)
        self.assertEqual(result['quotePath']['segments'][0]['depthValid'],2)
        self.assertEqual(result['quotePath']['segments'][0]['tenLevelValid'],2)

    def test_unknown_direction_is_not_zero(self):
        con=duckdb.connect();path=self.root/f'deal_{self.day}.parquet'
        con.execute('CREATE TABLE t AS SELECT * FROM read_parquet(?)',[str(path)])
        con.execute('UPDATE t SET "BS标志"=\'?\' WHERE "BS标志"=\'B\'')
        con.execute('COPY t TO ? (FORMAT PARQUET)',[str(path)]);con.close()
        result=calculate('600000.SH',self.day,{'amount':1200,'net':None},lambda _:None,self.root)
        self.assertIsNone(result['net']);self.assertEqual(result['unknownAmount'],1000)
        self.assertEqual(result['knownNet'],-200);self.assertIsNone(result['segments'][0]['n'])

    def test_snapshot_change_invalidates_detail_identity(self):
        before=source_identity(self.day,self.root)
        source=self.root/f'snapshot_{self.day}.parquet'
        with source.open('ab') as stream:stream.write(b'changed')
        self.assertNotEqual(before,source_identity(self.day,self.root))

    def test_cache_validation_and_allowlist(self):
        service = Service(self.report, self.root, self.root / 'cache')
        with self.assertRaises(ValueError):
            service.start('../../etc/passwd')
        service.start('600000.SH')
        service.pool.shutdown(wait=True)
        self.assertEqual(service.status('600000.SH')['status'], 'done')
        self.assertEqual(service.start('600000.SH')['status'], 'done')
        before = source_identity(self.day, self.root)
        (self.root / '_conversion_audit' / self.day / 'COMMITTED').write_text('new commit')
        self.assertNotEqual(before, source_identity(self.day, self.root))
        self.assertEqual(service.status('600000.SH')['status'], 'idle')

    def test_failed_job_is_retryable(self):
        def fail(*args):
            raise ValueError('测试失败')
        service = Service(self.report, self.root, self.root / 'cache', fail)
        service.start('600000.SH')
        service.pool.submit(lambda: None).result(timeout=5)
        state = service.status('600000.SH')
        self.assertEqual(state['status'], 'error')
        self.assertIn('测试失败', state['message'])
        self.assertFalse(service.path('600000.SH').exists())
        service.calculator = calculate
        service.start('600000.SH')
        service.pool.shutdown(wait=True)
        self.assertEqual(service.status('600000.SH')['status'], 'done')

    def test_duplicate_submission_is_not_recomputed(self):
        from threading import Event
        entered, release = Event(), Event()
        calls = []
        def blocking(*args):
            calls.append(args[0])
            entered.set()
            if not release.wait(timeout=5):
                raise ValueError('test timed out')
            return calculate(*args)
        service = Service(self.report, self.root, self.root / 'cache', blocking)
        try:
            service.start('600000.SH')
            self.assertTrue(entered.wait(timeout=5))
            self.assertEqual(service.start('600000.SH')['status'], 'running')
        finally:
            release.set()
            service.pool.shutdown(wait=True)
        self.assertEqual(calls, ['600000.SH'])
        self.assertEqual(service.status('600000.SH')['status'], 'done')

    def test_origin_and_static_file_restrictions(self):
        service = Service(self.report, self.root, self.root / 'cache')
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(service, 0))
        port = server.server_port
        server.RequestHandlerClass = make_handler(service, port)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(f'http://127.0.0.1:{port}/api/detail', data=b'{"code":"600000.SH"}',
                              headers={'Content-Type': 'application/json', 'Origin': 'https://example.com'})
            with self.assertRaises(HTTPError) as context:
                urlopen(request)
            self.assertEqual(context.exception.code, 403)
            with self.assertRaises(HTTPError) as context:
                urlopen(f'http://127.0.0.1:{port}/generate_level2_report.py')
            self.assertEqual(context.exception.code, 404)
            self.assertFalse(service.jobs)
        finally:
            server.shutdown()
            server.server_close()
            service.pool.shutdown()

    def test_ui_install_idempotent(self):
        html = add_detail_controls('<html><body>report</body></html>')
        self.assertEqual(add_detail_controls(html), html)
        self.assertIn('点击计算', html)


if __name__ == '__main__':
    unittest.main()
