"""Regression tests for vibe-tla shell and bytecode helpers."""
import importlib.util
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import time
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load_tlc_bytecode():
    spec = importlib.util.spec_from_file_location("tlc_bytecode", SCRIPTS / "tlc_bytecode.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


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

    def test_anchors_check_fails_when_locked_source_file_is_deleted_and_update_is_idempotent(self):
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
        lock_file = level / "02_models" / "anchors.lock"
        first_lock = lock_file.read_text(encoding="utf-8")

        # Re-running update with unchanged anchors must preserve anchors.lock byte-for-byte.
        upd_again = subprocess.run(
            ["bash", str(SCRIPTS / "anchors.sh"), "update", str(self.ws)],
            capture_output=True, text=True,
        )
        self.assertEqual(upd_again.returncode, 0, upd_again.stderr)
        self.assertEqual(lock_file.read_text(encoding="utf-8"), first_lock)

        chk = subprocess.run(
            ["bash", str(SCRIPTS / "anchors.sh"), "check", str(self.ws), "L1_evict"],
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

    def test_run_apalache_inductive_parallel_failfast_and_bmc_counterexample_cleanup(self):
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
            "if [[ \"$init\" == \"SlowFailInit\" && \"$length\" == \"0\" ]]; then\n"
            "  exit 12\n"
            "fi\n"
            "if [[ \"$inv\" == \"SlowStepInv\" && \"$length\" == \"1\" ]]; then\n"
            "  sleep 8\n"
            "  exit 0\n"
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

        # 1. Explicit typecheck mode invokes Snowcat typecheck.
        tc = subprocess.run(
            ["bash", str(SCRIPTS / "run_apalache.sh"), "typecheck", str(spec)],
            capture_output=True, text=True,
        )
        self.assertEqual(tc.returncode, 0, tc.stdout + tc.stderr)
        self.assertIn("CALL typecheck", tc.stdout)

        # 2. Inductive run executes base (k=0), step (k=1), and entailment (k=0) in parallel
        #    without wasting a redundant standalone typecheck JVM cold-start.
        ind = subprocess.run(
            [
                "bash", str(SCRIPTS / "run_apalache.sh"), "inductive", str(spec),
                "--cinit=ConstInit", "--init=SymInit", "--indinv=IndInv", "--inv=KeyInjective",
            ],
            capture_output=True, text=True,
        )
        self.assertEqual(ind.returncode, 0, ind.stdout + ind.stderr)
        self.assertNotIn("CALL typecheck", ind.stdout)
        self.assertIn("CALL check init=SymInit inv=IndInv len=0", ind.stdout)
        self.assertIn("CALL check init=IndInv inv=IndInv len=1", ind.stdout)
        self.assertIn("CALL check init=IndInv inv=KeyInjective len=0", ind.stdout)
        self.assertIn("INDUCTIVE PROOF COMPLETE", ind.stdout)
        self.assertEqual(list(level.glob(".apalache_tmp.*")), [])

        # 3. Failing base obligation cancels slow sibling step obligation via fail-fast.
        t0 = time.monotonic()
        ind_fail = subprocess.run(
            [
                "bash", str(SCRIPTS / "run_apalache.sh"), "inductive", str(spec),
                "--init=SlowFailInit", "--indinv=SlowStepInv",
            ],
            capture_output=True, text=True,
        )
        elapsed = time.monotonic() - t0
        self.assertEqual(ind_fail.returncode, 12, ind_fail.stdout + ind_fail.stderr)
        self.assertLess(elapsed, 5.0, "fail-fast should cancel slow sibling obligation promptly")

        # 4. Failing BMC prints counterexample1.tla witness and still cleans temporary out-dir.
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

    def _install_mock_java(self, body: str) -> tuple[Path, dict[str, str]]:
        fake_jar = self.ws / "tools" / "tla2tools.jar"
        fake_jar.parent.mkdir(parents=True, exist_ok=True)
        fake_jar.write_text("mock-jar\n", encoding="utf-8")
        with (self.ws / "config.env").open("a", encoding="utf-8") as fh:
            fh.write(f"TLA_TOOLS_JAR={fake_jar}\n")

        bin_dir = self.repo / "mock_bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        mock_java = bin_dir / "java"
        mock_java.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body, encoding="utf-8")
        mock_java.chmod(0o755)
        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '/usr/bin:/bin')}"
        return fake_jar, env

    def test_run_tlc_fast_jit_and_isolated_view_injection(self):
        _, env = self._install_mock_java(
            "echo \"JAVA_ARGS: $*\"\n"
            "echo \"SCRATCH_TLA:\"\n"
            "cat Smoke.tla\n"
            "echo \"SCRATCH_CFG:\"\n"
            "cat Smoke.cfg\n"
            "exit 0\n"
        )
        m_dir = self.ws / "exec_models" / "smoke" / "L0_smoke" / "02_models"
        m_dir.mkdir(parents=True)
        orig_tla = "---- MODULE Smoke ----\nVARIABLE x\nInit == x = 0\nNext == x' = x\n====\n"
        orig_cfg = "INIT Init\nNEXT Next\n"
        tla_p = m_dir / "Smoke.tla"
        cfg_p = m_dir / "Smoke.cfg"
        tla_p.write_text(orig_tla, encoding="utf-8")
        cfg_p.write_text(orig_cfg, encoding="utf-8")

        res = subprocess.run(
            [
                "bash", str(SCRIPTS / "run_tlc.sh"), str(tla_p),
                "--fast-jit", "--coverage", "--view", "SmokeView",
                "--view-def", "SmokeView == <<x>>",
            ],
            env=env, capture_output=True, text=True,
        )
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("-XX:TieredStopAtLevel=1", res.stdout)
        self.assertIn("-coverage 60", res.stdout)
        self.assertIn("SmokeView == <<x>>", res.stdout)
        self.assertIn("VIEW SmokeView", res.stdout)
        # Committed 02_models/ files must remain untouched.
        self.assertEqual(tla_p.read_text(encoding="utf-8"), orig_tla)
        self.assertEqual(cfg_p.read_text(encoding="utf-8"), orig_cfg)

    def test_coverage_all_cfgs_deduplicates_periodic_coverage_blocks(self):
        _, env = self._install_mock_java(
            "echo 'The coverage statistics at 2026-01-01T00:01:00'\n"
            "echo '<Step line 4, col 1 to line 4, col 10 of module Smoke>: 0:0'\n"
            "echo 'End of coverage statistics.'\n"
            "echo 'The coverage statistics at 2026-01-01T00:02:00'\n"
            "echo '<Step line 4, col 1 to line 4, col 10 of module Smoke>: 2:5'\n"
            "echo 'End of coverage statistics.'\n"
            "exit 0\n"
        )
        m_dir = self.ws / "exec_models" / "cov" / "L0_cov" / "02_models"
        m_dir.mkdir(parents=True)
        tla_p = m_dir / "Smoke.tla"
        tla_p.write_text("---- MODULE Smoke ----\nVARIABLE x\n====\n", encoding="utf-8")
        (m_dir / "Smoke_a.cfg").write_text("INIT Init\nNEXT Next\n", encoding="utf-8")
        (m_dir / "Smoke_b.cfg").write_text("INIT Init\nNEXT Next\n", encoding="utf-8")

        res = subprocess.run(
            ["bash", str(SCRIPTS / "coverage.sh"), str(tla_p), "--all-cfgs"],
            env=env, capture_output=True, text=True,
        )
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertNotIn("DEAD", res.stdout)
        self.assertIn("RESULT: all actions fired in every cfg checked.", res.stdout)

    def test_run_suite_coverage_dedup_and_dead_action_failsafe(self):
        call_log = self.repo / "suite_calls.log"
        _, env = self._install_mock_java(
            "cfg=\"\"; has_cov=0; offheap=0\n"
            "prev=\"\"\n"
            "for a in \"$@\"; do\n"
            "  [[ \"$prev\" == \"-config\" ]] && cfg=\"$a\"\n"
            "  [[ \"$a\" == \"-coverage\" ]] && has_cov=1\n"
            "  [[ \"$a\" == *\"OffHeapDiskFPSet\"* ]] && offheap=1\n"
            "  prev=\"$a\"\n"
            "done\n"
            "has_view=0\n"
            "grep -q '^VIEW ScaleView' \"$cfg\" && has_view=1 || true\n"
            f"echo \"$cfg cov=$has_cov offheap=$offheap view=$has_view\" >> \"{call_log}\"\n"
            "echo '10 states generated, 5 distinct states found, 0 states left on queue.'\n"
            "echo 'The depth of the complete state graph search is 3.'\n"
            "if [[ \"$has_cov\" == \"1\" ]]; then\n"
            "  echo 'The coverage statistics at 2026-01-01T00:00:01'\n"
            "  echo '<CommonStep line 5 of module M>: 2:4'\n"
            "  if [[ \"${RARE_ONLY_IN_SCALE:-0}\" == \"1\" && \"$cfg\" == \"M_small.cfg\" ]]; then\n"
            "    echo '<RareStep line 9 of module M>: 0:0'\n"
            "  else\n"
            "    echo '<RareStep line 9 of module M>: 1:2'\n"
            "  fi\n"
            "fi\n"
            "exit 0\n"
        )

        lvl = self.ws / "ring_models" / "sched" / "L0_suite"
        m_dir = lvl / "02_models"
        m_dir.mkdir(parents=True)
        (m_dir / "M.tla").write_text("---- MODULE M ----\nVARIABLE x\n====\n", encoding="utf-8")
        (m_dir / "M_small.cfg").write_text("INIT Init\nNEXT Next\n", encoding="utf-8")
        (m_dir / "M_scale.cfg").write_text(
            "INIT Init\nNEXT Next\n\\* @vibe-view: ScaleView\n", encoding="utf-8"
        )
        # Seed historical state counts: M_small < 2M (coverage-enabled), M_scale >= 2M (deduped).
        (lvl / "03_run_log.md").write_text(
            "| Config | Distinct | Generated |\n"
            "| `M_small.cfg` | `500` | `1,000` |\n"
            "| `M_scale.cfg` | `2,500,000` | `5,000,000` |\n",
            encoding="utf-8",
        )

        # Case A: M_small covers all actions -> M_scale runs once coverage-free with @vibe-view.
        res_ok = subprocess.run(
            ["bash", str(SCRIPTS / "run_suite.sh"), str(lvl), "--jobs", "4"],
            env=env, capture_output=True, text=True,
        )
        self.assertEqual(res_ok.returncode, 0, res_ok.stdout + res_ok.stderr)
        self.assertIn("1/1 module(s) PASS", res_ok.stdout)
        calls_a = call_log.read_text(encoding="utf-8").splitlines()
        self.assertIn("M_small.cfg cov=1 offheap=0 view=0", calls_a)
        self.assertIn("M_scale.cfg cov=0 offheap=1 view=1", calls_a)
        self.assertEqual(len(calls_a), 2)

        # Case B: RareStep is 0:0 in M_small -> failsafe re-runs M_scale with -coverage 60.
        call_log.unlink()
        env_rare = dict(env)
        env_rare["RARE_ONLY_IN_SCALE"] = "1"
        res_fb = subprocess.run(
            ["bash", str(SCRIPTS / "run_suite.sh"), str(lvl), "--jobs", "4"],
            env=env_rare, capture_output=True, text=True,
        )
        self.assertEqual(res_fb.returncode, 0, res_fb.stdout + res_fb.stderr)
        calls_b = call_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(calls_b), 3)
        self.assertTrue(any(ln.startswith("M_scale.cfg cov=1") for ln in calls_b))

    def test_tlc_bytecode_emits_valid_java49_classes_and_overrides_registry(self):
        bc = load_tlc_bytecode()
        out_dir = self.repo / "ov_classes"
        cb = bc.ClassFileBuilder("tlc2/overrides/TestModOverrides")
        cb.add_default_ctor()
        asm = bc.CodeAsm(cb.cp)
        asm.iload(0)
        asm.iconst(7)
        asm.iadd()
        asm.ireturn()
        cb.add_method(
            0x0009, "AddSeven", "(I)I", asm.finish(4, 1), tla_op=("AddSeven", "TestMod")
        )
        cls_path = cb.write_to(out_dir)
        reg_path = bc.write_tlc_overrides_registry(out_dir, ["tlc2/overrides/TestModOverrides"])

        raw = cls_path.read_bytes()
        magic, minor, major = struct.unpack(">IHH", raw[:8])
        self.assertEqual(magic, 0xCAFEBABE)
        self.assertEqual((major, minor), (49, 0))
        self.assertIn(b"RuntimeVisibleAnnotations", raw)
        self.assertIn(b"Ltlc2/overrides/TLAPlusOperator;", raw)
        self.assertTrue(reg_path.is_file())

        # When a local JVM is installed, verify the emitted bytecode passes the real JVM verifier.
        java_bin = shutil.which("java")
        if java_bin:
            # Emit stub interface `tlc2/overrides/ITLCOverrides` (access 0x0601 = public abstract interface)
            iface = bc.ClassFileBuilder("tlc2/overrides/ITLCOverrides")
            iface_bytes = bytearray(iface.build())
            # Patch access_flags right after constant pool to 0x0601 (ACC_PUBLIC | ACC_INTERFACE | ACC_ABSTRACT).
            cp_len = len(iface.cp.encode())
            struct.pack_into(">H", iface_bytes, 8 + cp_len, 0x0601)
            (out_dir / "tlc2/overrides/ITLCOverrides.class").write_bytes(bytes(iface_bytes))

            # Emit `VerifyMain` calling `TestModOverrides.AddSeven(35) == 42` and `new TLCOverrides().get().length == 1`.
            main_cb = bc.ClassFileBuilder("VerifyMain")
            m = bc.CodeAsm(main_cb.cp)
            m.iconst(35)
            m.invokestatic("tlc2/overrides/TestModOverrides", "AddSeven", "(I)I")
            m.iconst(42)
            m.if_icmpne("bad")
            m.new("tlc2/overrides/TLCOverrides")
            m.dup()
            m.invokespecial("tlc2/overrides/TLCOverrides", "<init>", "()V")
            m.invokevirtual("tlc2/overrides/TLCOverrides", "get", "()[Ljava/lang/Class;")
            m.arraylength()
            m.iconst(1)
            m.if_icmpne("bad")
            m.vreturn()
            m.label("bad")
            m.iconst(9)
            m.invokestatic("java/lang/System", "exit", "(I)V")
            m.vreturn()
            main_cb.add_method(0x0009, "main", "([Ljava/lang/String;)V", m.finish(4, 1))
            main_cb.write_to(out_dir)

            jvm_res = subprocess.run(
                [java_bin, "-cp", str(out_dir), "VerifyMain"],
                capture_output=True, text=True,
            )
            self.assertEqual(jvm_res.returncode, 0, jvm_res.stdout + jvm_res.stderr)


if __name__ == "__main__":
    unittest.main()
