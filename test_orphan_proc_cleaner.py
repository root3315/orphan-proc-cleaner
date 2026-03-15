#!/usr/bin/env python3
"""Unit tests for orphan_proc_cleaner process detection functions."""

import os
import signal
import time
import unittest
from pathlib import Path
from unittest.mock import mock_open, patch

import orphan_proc_cleaner as opc


class TestGetBootTime(unittest.TestCase):
    """Tests for get_boot_time function."""

    def test_reads_btime_from_proc_stat(self):
        """Should parse boot time from /proc/stat."""
        mock_content = "cpu  1 2 3 4 5 6 7 8 9\nbtime 1234567890\nintr 1 2 3\n"
        
        with patch("builtins.open", mock_open(read_data=mock_content)):
            boot_time = opc.get_boot_time()
        
        self.assertEqual(boot_time, 1234567890.0)

    def test_fallback_on_error(self):
        """Should return current time on read error."""
        with patch("builtins.open", side_effect=FileNotFoundError):
            boot_time = opc.get_boot_time()
        
        self.assertIsInstance(boot_time, float)
        self.assertGreater(boot_time, 0)


class TestGetProcessStartTime(unittest.TestCase):
    """Tests for get_process_start_time function."""

    def test_parses_starttime_from_stat(self):
        """Should parse starttime field from /proc/[pid]/stat."""
        mock_stat = "123 (test) S 1 1 1 0 -1 4194304 0 0 0 0 0 0 0 0 20 0 1 0 100 0 0 18446744073709551615 0 0 17 0 0 0 0 0 0"
        
        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=mock_stat)):
                with patch("os.sysconf", return_value=100):
                    with patch.object(opc, "get_boot_time", return_value=1000000.0):
                        start_time = opc.get_process_start_time(123)
        
        expected = 1000000.0 + (100 / 100)
        self.assertEqual(start_time, expected)

    def test_returns_none_on_missing_file(self):
        """Should return None when stat file doesn't exist."""
        with patch("pathlib.Path.exists", return_value=False):
            result = opc.get_process_start_time(99999)
        self.assertIsNone(result)

    def test_returns_none_on_malformed_stat(self):
        """Should return None for malformed stat content."""
        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data="malformed")):
                result = opc.get_process_start_time(123)
        self.assertIsNone(result)


class TestGetProcessInfo(unittest.TestCase):
    """Tests for get_process_info function."""

    def test_returns_process_info_dict(self):
        """Should return dict with all expected fields."""
        mock_stat = "456 (bash) S 1 456 456 0 -1 4194304 0 0 0 0 0 0 0 0 20 0 1 0 100 0 0 18446744073709551615 0 0 17 0 0 0 0 0 0"
        mock_cmdline = "bash\x00-c\x00echo test"
        
        def mock_file_open(filepath, *args, **kwargs):
            if "cmdline" in str(filepath):
                return mock_open(read_data=mock_cmdline).return_value
            return mock_open(read_data=mock_stat).return_value
        
        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", side_effect=mock_file_open):
                with patch.object(opc, "get_process_start_time", return_value=1234567.0):
                    info = opc.get_process_info(456)
        
        self.assertIsNotNone(info)
        self.assertEqual(info["pid"], 456)
        self.assertEqual(info["ppid"], 1)
        self.assertEqual(info["pgrp"], 456)
        self.assertEqual(info["state"], "S")
        self.assertEqual(info["start_time"], 1234567.0)

    def test_returns_none_on_missing_proc(self):
        """Should return None when process doesn't exist."""
        with patch("pathlib.Path.exists", return_value=False):
            result = opc.get_process_info(99999)
        self.assertIsNone(result)

    def test_handles_empty_cmdline(self):
        """Should use PID as fallback when cmdline is empty."""
        mock_stat = "789 (test) S 1 789 789 0 -1 4194304 0 0 0 0 0 0 0 0 20 0 1 0 100 0 0 18446744073709551615 0 0 17 0 0 0 0 0 0"
        
        def mock_file_open(filepath, *args, **kwargs):
            if "cmdline" in str(filepath):
                return mock_open(read_data="").return_value
            return mock_open(read_data=mock_stat).return_value
        
        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", side_effect=mock_file_open):
                with patch.object(opc, "get_process_start_time", return_value=1234567.0):
                    info = opc.get_process_info(789)
        
        self.assertEqual(info["cmdline"], "[789]")


class TestGetAllPids(unittest.TestCase):
    """Tests for get_all_pids function."""

    def test_returns_set_of_ints(self):
        """Should return a set of integer PIDs."""
        mock_entries = ["1", "2", "100", "notapid", "999"]
        
        with patch.object(opc.Path, "iterdir") as mock_iterdir:
            mock_iterdir.return_value = [Path(name) for name in mock_entries]
            pids = opc.get_all_pids()
        
        self.assertIsInstance(pids, set)
        self.assertEqual(pids, {1, 2, 100, 999})

    def test_handles_permission_error(self):
        """Should return empty set on permission error."""
        with patch.object(opc.Path, "iterdir", side_effect=PermissionError):
            pids = opc.get_all_pids()
        self.assertEqual(pids, set())


class TestFilterByMinAge(unittest.TestCase):
    """Tests for filter_by_min_age function."""

    def test_returns_all_when_min_age_zero(self):
        """Should return all processes when min_age is 0."""
        processes = [{"pid": 1, "start_time": 1000.0}]
        result = opc.filter_by_min_age(processes, 0)
        self.assertEqual(result, processes)

    def test_filters_by_age(self):
        """Should filter out processes younger than min_age."""
        current_time = time.time()
        old_proc = {"pid": 1, "start_time": current_time - 100}
        young_proc = {"pid": 2, "start_time": current_time - 5}
        
        processes = [old_proc, young_proc]
        result = opc.filter_by_min_age(processes, min_age=10)
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pid"], 1)

    def test_skips_missing_start_time(self):
        """Should skip processes without start_time."""
        processes = [{"pid": 1}, {"pid": 2, "start_time": time.time() - 100}]
        result = opc.filter_by_min_age(processes, min_age=10)
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pid"], 2)


class TestFindOrphanedProcesses(unittest.TestCase):
    """Tests for find_orphaned_processes function."""

    def test_finds_orphans_with_ppid_one(self):
        """Should find processes with PPID=1 that aren't known daemons."""
        orphan_proc = {
            "pid": 12345,
            "ppid": 1,
            "pgrp": 12345,
            "session": 12345,
            "state": "S",
            "cmdline": "/tmp/rogue_script.py",
            "start_time": time.time() - 100,
        }
        daemon_proc = {
            "pid": 12346,
            "ppid": 1,
            "pgrp": 12346,
            "session": 12346,
            "state": "S",
            "cmdline": "/usr/sbin/sshd",
            "start_time": time.time() - 100,
        }
        
        with patch.object(opc, "get_all_pids", return_value={12345, 12346}):
            with patch.object(opc, "get_process_info") as mock_info:
                mock_info.side_effect = lambda pid: orphan_proc if pid == 12345 else daemon_proc
                orphans = opc.find_orphaned_processes()
        
        self.assertEqual(len(orphans), 1)
        self.assertEqual(orphans[0]["pid"], 12345)

    def test_excludes_pid_one(self):
        """Should not include init/systemd itself."""
        init_proc = {
            "pid": 1,
            "ppid": 0,
            "pgrp": 1,
            "session": 1,
            "state": "S",
            "cmdline": "/sbin/init",
            "start_time": time.time() - 1000,
        }
        
        with patch.object(opc, "get_all_pids", return_value={1}):
            with patch.object(opc, "get_process_info", return_value=init_proc):
                orphans = opc.find_orphaned_processes()
        
        self.assertEqual(orphans, [])

    def test_filters_known_daemons(self):
        """Should filter out known daemon patterns."""
        daemon_patterns = ["systemd", "docker", "nginx", "python", "node", "java"]
        
        def make_proc(pid, cmdline):
            return {
                "pid": pid,
                "ppid": 1,
                "pgrp": pid,
                "session": pid,
                "state": "S",
                "cmdline": cmdline,
                "start_time": time.time() - 100,
            }
        
        procs = [make_proc(i, cmd) for i, cmd in enumerate(daemon_patterns, start=100)]
        pids = {p["pid"] for p in procs}
        
        with patch.object(opc, "get_all_pids", return_value=pids):
            with patch.object(opc, "get_process_info") as mock_info:
                mock_info.side_effect = lambda pid: next((p for p in procs if p["pid"] == pid), None)
                orphans = opc.find_orphaned_processes()
        
        self.assertEqual(orphans, [])

    def test_filters_by_state(self):
        """Should only include processes in R, S, or D state."""
        running_proc = {"pid": 10, "ppid": 1, "state": "R", "cmdline": "rogue_script", "start_time": time.time() - 100}
        zombie_proc = {"pid": 11, "ppid": 1, "state": "Z", "cmdline": "rogue_script", "start_time": time.time() - 100}
        sleeping_proc = {"pid": 12, "ppid": 1, "state": "S", "cmdline": "rogue_script", "start_time": time.time() - 100}
        stopped_proc = {"pid": 13, "ppid": 1, "state": "T", "cmdline": "rogue_script", "start_time": time.time() - 100}
        
        with patch.object(opc, "get_all_pids", return_value={10, 11, 12, 13}):
            with patch.object(opc, "get_process_info") as mock_info:
                mock_info.side_effect = lambda pid: {
                    10: running_proc, 11: zombie_proc, 12: sleeping_proc, 13: stopped_proc
                }.get(pid)
                orphans = opc.find_orphaned_processes()
        
        self.assertEqual(len(orphans), 2)
        self.assertEqual({o["pid"] for o in orphans}, {10, 12})


class TestFindZombieProcesses(unittest.TestCase):
    """Tests for find_zombie_processes function."""

    def test_finds_zombie_state(self):
        """Should find processes with state Z."""
        zombie1 = {"pid": 100, "state": "Z", "cmdline": "[python]", "start_time": time.time() - 100}
        zombie2 = {"pid": 101, "state": "Z", "cmdline": "[node]", "start_time": time.time() - 100}
        running = {"pid": 102, "state": "S", "cmdline": "bash", "start_time": time.time() - 100}
        
        with patch.object(opc, "get_all_pids", return_value={100, 101, 102}):
            with patch.object(opc, "get_process_info") as mock_info:
                mock_info.side_effect = lambda pid: {100: zombie1, 101: zombie2, 102: running}.get(pid)
                zombies = opc.find_zombie_processes()
        
        self.assertEqual(len(zombies), 2)
        self.assertEqual({z["pid"] for z in zombies}, {100, 101})


class TestFindDefunctProcesses(unittest.TestCase):
    """Tests for find_defunct_processes function."""

    def test_finds_defunct_in_cmdline(self):
        """Should find processes with <defunct> in cmdline."""
        defunct1 = {"pid": 200, "state": "Z", "cmdline": "[python] <defunct>", "start_time": time.time() - 100}
        defunct2 = {"pid": 201, "state": "Z", "cmdline": "java <defunct>", "start_time": time.time() - 100}
        normal = {"pid": 202, "state": "S", "cmdline": "python app.py", "start_time": time.time() - 100}
        
        with patch.object(opc, "get_all_pids", return_value={200, 201, 202}):
            with patch.object(opc, "get_process_info") as mock_info:
                mock_info.side_effect = lambda pid: {200: defunct1, 201: defunct2, 202: normal}.get(pid)
                defunct = opc.find_defunct_processes()
        
        self.assertEqual(len(defunct), 2)
        self.assertEqual({d["pid"] for d in defunct}, {200, 201})


class TestSendSignalToProcess(unittest.TestCase):
    """Tests for send_signal_to_process function."""

    def test_returns_true_on_success(self):
        """Should return True when signal is sent successfully."""
        with patch("os.kill", return_value=None):
            result = opc.send_signal_to_process(123, signal.SIGTERM)
        self.assertTrue(result)

    def test_returns_false_on_process_lookup_error(self):
        """Should return False when process doesn't exist."""
        with patch("os.kill", side_effect=ProcessLookupError):
            result = opc.send_signal_to_process(99999, signal.SIGTERM)
        self.assertFalse(result)

    def test_returns_false_on_permission_error(self):
        """Should return False when lacking permission."""
        with patch("os.kill", side_effect=PermissionError):
            result = opc.send_signal_to_process(1, signal.SIGTERM)
        self.assertFalse(result)


class TestGracefulTerminate(unittest.TestCase):
    """Tests for graceful_terminate function."""

    def test_terminates_with_sigterm(self):
        """Should terminate process with SIGTERM and return True."""
        proc_info = {"pid": 123, "ppid": 1, "state": "S", "cmdline": "test", "start_time": time.time() - 100}
        
        with patch.object(opc, "get_process_info", side_effect=[proc_info, None]):
            with patch("os.kill", return_value=None):
                with patch("time.sleep"):
                    result = opc.graceful_terminate(123, timeout=1)
        
        self.assertTrue(result)

    def test_falls_back_to_sigkill(self):
        """Should fall back to SIGKILL if SIGTERM doesn't work."""
        proc_info = {"pid": 123, "ppid": 1, "state": "S", "cmdline": "test", "start_time": time.time() - 100}
        
        # First call: initial check (process exists)
        # Second call: after SIGKILL (process is gone)
        with patch.object(opc, "get_process_info", side_effect=[proc_info, None]):
            with patch("os.kill", return_value=None):
                with patch("time.sleep"):
                    result = opc.graceful_terminate(123, timeout=0)
        
        self.assertTrue(result)

    def test_returns_false_when_process_not_found(self):
        """Should return False when process doesn't exist."""
        with patch.object(opc, "get_process_info", return_value=None):
            result = opc.graceful_terminate(99999)
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
