"""Vigia do banco local no serviço Worker: o PostgreSQL como serviço (pg_ctl runservice) não volta sozinho se o
processo do banco cair (encontrado no CI Windows em 29/10/2026); com o banco fora por mais que o limite, o Worker
encerra com erro para o Windows reiniciá-lo — e subir antes o banco, que é dependência. Banco de volta: nada acontece."""

import socket
import threading
import time
import unittest


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Watchdog(unittest.TestCase):
    def run_watch(self, url, seconds=1.2):
        from vyonix.winservice import db_watchdog
        stop, fired = threading.Event(), []
        t = db_watchdog(url, stop=stop, on_down=lambda: fired.append(time.monotonic()), interval=0.1, limit=0.5)
        time.sleep(seconds)
        stop.set()
        if t:
            t.join(2)
        return t, fired

    def test_fires_when_local_database_is_down(self):
        _t, fired = self.run_watch(f"postgresql://u:p@127.0.0.1:{free_port()}/vyonix")
        self.assertTrue(fired)

    def test_quiet_while_database_answers(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(50)
        self.addCleanup(srv.close)
        _t, fired = self.run_watch(f"postgresql+psycopg://u:p@127.0.0.1:{srv.getsockname()[1]}/vyonix")
        self.assertEqual(fired, [])

    def test_remote_or_missing_database_not_watched(self):
        from vyonix.winservice import db_watchdog
        stop = threading.Event()
        self.assertIsNone(db_watchdog(None, stop=stop))
        self.assertIsNone(db_watchdog("postgresql://u:p@10.0.0.5:5432/x", stop=stop))


if __name__ == "__main__":
    unittest.main()
