"""Regression tests for vibe-tla shell helpers."""
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


class VibeTlaScriptTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.repo = Path(td.name) / "repo"
        (self.repo / "src").mkdir(parents=True)
        self.ws = self.repo / "tla"
        self.ws.mkdir(parents=True)
        (self.ws / "config.env").write_text(
            f"REPO_ROOT={self.repo}\nWORKSPACE_DIR=tla\n", encoding="utf-8"
        )

    def test_anchors_check_fails_when_locked_source_file_is_deleted(self):
        src = self.repo / "src" / "cache.cc"
        src.write_text("int a = 1;\nint b = 2;\n", encoding="utf-8")
        level = self.ws / "cache_models" / "lru" / "L1_evict"
        (level / "02_models").mkdir(parents=True)
        (level / "00_input.md").write_text("- src/cache.cc:2 — evict guard\n", encoding="utf-8")
        (level / "02_models" / "L1_evict.tla").write_text(
            "---- MODULE L1_evict ----\n\\* src/cache.cc:1\n====\n", encoding="utf-8"
        )

        upd = subprocess.run(
            ["bash", str(SCRIPTS / "anchors.sh"), "update", str(self.ws)],
            capture_output=True, text=True,
        )
        self.assertEqual(upd.returncode, 0, upd.stderr)
        chk = subprocess.run(
            ["bash", str(SCRIPTS / "anchors.sh"), "check", str(self.ws)],
            capture_output=True, text=True,
        )
        self.assertEqual(chk.returncode, 0, chk.stdout + chk.stderr)

        # Deleting a locked file must trigger DRIFT and exit 1.
        src.unlink()
        chk_deleted = subprocess.run(
            ["bash", str(SCRIPTS / "anchors.sh"), "check", str(self.ws)],
            capture_output=True, text=True,
        )
        self.assertEqual(chk_deleted.returncode, 1, chk_deleted.stdout + chk_deleted.stderr)
        self.assertIn("DRIFT", chk_deleted.stdout)

    def test_anchors_update_prefers_v2_spec_over_frozen_v1_and_00_input(self):
        src = self.repo / "src" / "writer.cc"
        # Post-fix file has only 3 lines; frozen v1/00_input cited old line 10.
        src.write_text("line1\nline2_fixed\nline3\n", encoding="utf-8")
        level = self.ws / "wal_models" / "flush" / "L1_flush"
        (level / "02_models").mkdir(parents=True)
        (level / "00_input.md").write_text("- src/writer.cc:10 — old pre-fix anchor\n", encoding="utf-8")
        (level / "02_models" / "L1_flush.tla").write_text(
            "---- MODULE L1_flush ----\n\\* src/writer.cc:10\n====\n", encoding="utf-8"
        )
        (level / "02_models" / "L1_flush_v2.tla").write_text(
            "---- MODULE L1_flush_v2 ----\n\\* src/writer.cc:2\n====\n", encoding="utf-8"
        )
        (level / "02_models" / "L1_flush_Unsafe.tla").write_text(
            "---- MODULE L1_flush_Unsafe ----\n\\* src/writer.cc:99\n====\n", encoding="utf-8"
        )

        upd = subprocess.run(
            ["bash", str(SCRIPTS / "anchors.sh"), "update", str(self.ws)],
            capture_output=True, text=True,
        )
        self.assertEqual(upd.returncode, 0, upd.stderr)
        self.assertNotIn("out-of-range anchor", upd.stderr)
        lock = (level / "02_models" / "anchors.lock").read_text(encoding="utf-8")
        self.assertIn("src/writer.cc\t2\t", lock)
        self.assertNotIn("src/writer.cc\t10\t", lock)

    def test_install_tlc_fails_cleanly_on_corrupt_jar_without_writing_config(self):
        bad_jar = self.repo / "corrupt.jar"
        bad_jar.write_text("not a zip/jar\n", encoding="utf-8")
        fresh_ws = self.repo / "tla_fresh"
        res = subprocess.run(
            ["bash", str(SCRIPTS / "install_tlc.sh"), str(fresh_ws)],
            env={"PATH": "/usr/bin:/bin", "HOME": str(self.repo), "TLA_TOOLS_JAR": str(bad_jar)},
            capture_output=True, text=True,
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertFalse((fresh_ws / "config.env").exists())

    def test_install_apalache_records_bin_and_preserves_existing_config(self):
        fake_bin = self.repo / "fake-apalache-mc"
        fake_bin.write_text(
            "#!/usr/bin/env bash\n"
            "echo 'PASS #2: TypeCheckerSnowcat'\n"
            "echo 'Type checker [OK]'\n"
            "echo 'The outcome is: NoError'\n"
            "exit 0\n",
            encoding="utf-8",
        )
        fake_bin.chmod(0o755)
        res = subprocess.run(
            ["bash", str(SCRIPTS / "install_apalache.sh"), str(self.ws)],
            env={"PATH": "/usr/bin:/bin", "HOME": str(self.repo), "APALACHE_BIN": str(fake_bin)},
            capture_output=True, text=True,
        )
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        cfg = (self.ws / "config.env").read_text(encoding="utf-8")
        self.assertIn(f"REPO_ROOT={self.repo}\n", cfg)
        self.assertIn(f"APALACHE_BIN={fake_bin}\n", cfg)
        self.assertIn("APALACHE_TIMEOUT=1800\n", cfg)

    def test_run_apalache_inductive_and_bmc_counterexample_cleanup(self):
        fake_bin = self.repo / "mock-apalache-mc"
        fake_bin.write_text(
            "#!/usr/bin/env bash\n"
            "subcmd=\"$1\"; shift\n"
            "out_dir=\"\"\n"
            "inv=\"\"\n"
            "init=\"\"\n"
            "length=\"\"\n"
            "for arg in \"$@\"; do\n"
            "  case \"$arg\" in\n"
            "    --out-dir=*) out_dir=\"${arg#*=}\" ;;\n"
            "    --inv=*) inv=\"${arg#*=}\" ;;\n"
            "    --init=*) init=\"${arg#*=}\" ;;\n"
            "    --length=*) length=\"${arg#*=}\" ;;\n"
            "  esac\n"
            "done\n"
            "echo \"CALL $subcmd init=$init inv=$inv len=$length\"\n"
            "if [[ \"$inv\" == \"BrokenInv\" ]]; then\n"
            "  mkdir -p \"$out_dir/run1\"\n"
            "  printf 'State 0 == x = 42\\n' > \"$out_dir/run1/counterexample1.tla\"\n"
            "  exit 12\n"
            "fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        fake_bin.chmod(0o755)
        with (self.ws / "config.env").open("a", encoding="utf-8") as fh:
            fh.write(f"APALACHE_BIN={fake_bin}\nAPALACHE_TIMEOUT=0\n")

        level = self.ws / "key_models" / "enc" / "L0_pack" / "02_models"
        level.mkdir(parents=True)
        spec = level / "L0_pack.tla"
        spec.write_text("---- MODULE L0_pack ----\nVARIABLE x\n====\n", encoding="utf-8")

        # 1. Inductive run executes typecheck, base (k=0), step (k=1), and entailment (k=0).
        ind = subprocess.run(
            [
                "bash", str(SCRIPTS / "run_apalache.sh"), "inductive", str(spec),
                "--cinit=ConstInit", "--init=SymInit", "--indinv=IndInv", "--inv=KeyInjective",
            ],
            capture_output=True, text=True,
        )
        self.assertEqual(ind.returncode, 0, ind.stdout + ind.stderr)
        self.assertIn("CALL typecheck", ind.stdout)
        self.assertIn("CALL check init=SymInit inv=IndInv len=0", ind.stdout)
        self.assertIn("CALL check init=IndInv inv=IndInv len=1", ind.stdout)
        self.assertIn("CALL check init=IndInv inv=KeyInjective len=0", ind.stdout)
        self.assertIn("INDUCTIVE PROOF COMPLETE", ind.stdout)
        self.assertEqual(list(level.glob(".apalache_tmp.*")), [])

        # 2. Failing BMC prints counterexample1.tla witness and still cleans temporary out-dir.
        bmc_fail = subprocess.run(
            [
                "bash", str(SCRIPTS / "run_apalache.sh"), "bmc", str(spec),
                "--inv=BrokenInv", "--length=5", "--no-deadlock",
            ],
            capture_output=True, text=True,
        )
        self.assertEqual(bmc_fail.returncode, 12)
        self.assertIn("State 0 == x = 42", bmc_fail.stdout)
        self.assertEqual(list(level.glob(".apalache_tmp.*")), [])


if __name__ == "__main__":
    unittest.main()
