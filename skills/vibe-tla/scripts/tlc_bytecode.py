#!/usr/bin/env python3
"""Zero-dependency JVM bytecode & compiler helper for TLC `@TLAPlusOperator` overrides.

Works on both full JDK hosts (`javac` available) and headless JRE-only Linux/container
hosts (no `javac` installed) by emitting Java 5 (`49.0`) `.class` files directly from
Python `struct` primitives — Java `49.0` supports `RuntimeVisibleAnnotations`
(`@TLAPlusOperator`) without requiring `StackMapTable` verification frames.

Usage as a library (for custom hot-operator bytecode emitters in `<workspace>/tools/`):
    from tlc_bytecode import (
        ClassFileBuilder, CodeAsm, VAL_CLS, INT_CLS, BOOL_CLS, FCN_CLS, TUP_CLS, L_VAL, ARR_VAL
    )

Usage from CLI:
    # Compile `.java` override sources if `javac` is present:
    python3 tlc_bytecode.py compile --jar /path/to/tla2tools.jar --out /tmp/ov Src.java

    # Self-test bytecode emission + TLC `@TLAPlusOperator` loading on any JRE:
    python3 tlc_bytecode.py --self-test /path/to/tla2tools.jar
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile

# Core TLC runtime internal class descriptors (`tla2tools.jar`).
VAL_CLS = "tlc2/value/impl/Value"
INT_CLS = "tlc2/value/impl/IntValue"
BOOL_CLS = "tlc2/value/impl/BoolValue"
STR_CLS = "tlc2/value/impl/StringValue"
INTV_CLS = "tlc2/value/impl/IntervalValue"
FCN_CLS = "tlc2/value/impl/FcnRcdValue"
SETFCN_CLS = "tlc2/value/impl/SetOfFcnsValue"
TUP_CLS = "tlc2/value/impl/TupleValue"
RCD_CLS = "tlc2/value/impl/RecordValue"
SET_CLS = "tlc2/value/impl/SetEnumValue"
USTR_CLS = "util/UniqueString"

L_VAL = f"L{VAL_CLS};"
ARR_VAL = f"[{L_VAL}"
OP_ANNOT = "Ltlc2/overrides/TLAPlusOperator;"


class ConstantPool:
    """JVM classfile constant pool builder with automatic deduplication."""

    def __init__(self) -> None:
        self._entries: list[bytes] = []
        self._map: dict[tuple, int] = {}

    def _add(self, key: tuple, raw: bytes) -> int:
        idx = self._map.get(key)
        if idx is not None:
            return idx
        idx = len(self._entries) + 1
        self._entries.append(raw)
        self._map[key] = idx
        return idx

    def utf8(self, s: str) -> int:
        b = s.encode("utf-8")
        return self._add(("utf8", s), struct.pack(">BH", 1, len(b)) + b)

    def integer(self, v: int) -> int:
        return self._add(("int", v), struct.pack(">Bi", 3, v))

    def cls(self, internal_name: str) -> int:
        u = self.utf8(internal_name)
        return self._add(("cls", internal_name), struct.pack(">BH", 7, u))

    def string(self, s: str) -> int:
        u = self.utf8(s)
        return self._add(("str", s), struct.pack(">BH", 8, u))

    def nat(self, name: str, desc: str) -> int:
        n = self.utf8(name)
        d = self.utf8(desc)
        return self._add(("nat", name, desc), struct.pack(">BHH", 12, n, d))

    def fieldref(self, cls_name: str, name: str, desc: str) -> int:
        c = self.cls(cls_name)
        nt = self.nat(name, desc)
        return self._add(("field", cls_name, name, desc), struct.pack(">BHH", 9, c, nt))

    def methodref(self, cls_name: str, name: str, desc: str) -> int:
        c = self.cls(cls_name)
        nt = self.nat(name, desc)
        return self._add(("method", cls_name, name, desc), struct.pack(">BHH", 10, c, nt))

    def encode(self) -> bytes:
        return struct.pack(">H", len(self._entries) + 1) + b"".join(self._entries)


class CodeAsm:
    """Minimal JVM method bytecode assembler with symbolic branch labels."""

    def __init__(self, cp: ConstantPool) -> None:
        self.cp = cp
        self.buf = bytearray()
        self.labels: dict[str, int] = {}
        self.fixups: list[tuple[int, int, str]] = []

    def label(self, name: str) -> None:
        self.labels[name] = len(self.buf)

    def emit(self, *opcodes: int) -> None:
        self.buf.extend(opcodes)

    def iconst(self, v: int) -> None:
        if -1 <= v <= 5:
            self.emit(0x03 + v)
        elif -128 <= v <= 127:
            self.buf.extend(struct.pack(">Bb", 0x10, v))
        elif -32768 <= v <= 32767:
            self.buf.extend(struct.pack(">Bh", 0x11, v))
        else:
            idx = self.cp.integer(v)
            self.buf.extend(struct.pack(">BH", 0x13, idx))

    def ldc_str(self, s: str) -> None:
        self.buf.extend(struct.pack(">BH", 0x13, self.cp.string(s)))

    def ldc_cls(self, internal_name: str) -> None:
        self.buf.extend(struct.pack(">BH", 0x13, self.cp.cls(internal_name)))

    def iload(self, slot: int) -> None:
        self.emit(0x15, slot)

    def aload(self, slot: int) -> None:
        self.emit(0x19, slot)

    def istore(self, slot: int) -> None:
        self.emit(0x36, slot)

    def astore(self, slot: int) -> None:
        self.emit(0x3A, slot)

    def iinc(self, slot: int, delta: int) -> None:
        if -128 <= delta <= 127 and slot < 256:
            self.buf.extend(struct.pack(">BBb", 0x84, slot, delta))
        else:
            self.buf.extend(struct.pack(">BBHh", 0xC4, 0x84, slot, delta))

    def aaload(self) -> None:
        self.emit(0x32)

    def aastore(self) -> None:
        self.emit(0x53)

    def dup(self) -> None:
        self.emit(0x59)

    def pop(self) -> None:
        self.emit(0x57)

    def iadd(self) -> None:
        self.emit(0x60)

    def isub(self) -> None:
        self.emit(0x64)

    def imul(self) -> None:
        self.emit(0x68)

    def idiv(self) -> None:
        self.emit(0x6C)

    def irem(self) -> None:
        self.emit(0x70)

    def ishl(self) -> None:
        self.emit(0x78)

    def ishr(self) -> None:
        self.emit(0x7A)

    def iand(self) -> None:
        self.emit(0x7E)

    def ior(self) -> None:
        self.emit(0x80)

    def ireturn(self) -> None:
        self.emit(0xAC)

    def areturn(self) -> None:
        self.emit(0xB0)

    def vreturn(self) -> None:
        self.emit(0xB1)

    def _branch(self, op: int, target: str) -> None:
        op_pos = len(self.buf)
        self.buf.extend(b"\x00\x00\x00")
        self.buf[op_pos] = op
        self.fixups.append((op_pos + 1, op_pos, target))

    def ifeq(self, target: str) -> None:
        self._branch(0x99, target)

    def ifne(self, target: str) -> None:
        self._branch(0x9A, target)

    def iflt(self, target: str) -> None:
        self._branch(0x9B, target)

    def ifge(self, target: str) -> None:
        self._branch(0x9C, target)

    def ifgt(self, target: str) -> None:
        self._branch(0x9D, target)

    def ifle(self, target: str) -> None:
        self._branch(0x9E, target)

    def if_icmpeq(self, target: str) -> None:
        self._branch(0x9F, target)

    def if_icmpne(self, target: str) -> None:
        self._branch(0xA0, target)

    def if_icmplt(self, target: str) -> None:
        self._branch(0xA1, target)

    def if_icmpge(self, target: str) -> None:
        self._branch(0xA2, target)

    def if_icmpgt(self, target: str) -> None:
        self._branch(0xA3, target)

    def if_icmple(self, target: str) -> None:
        self._branch(0xA4, target)

    def if_acmpeq(self, target: str) -> None:
        self._branch(0xA5, target)

    def if_acmpne(self, target: str) -> None:
        self._branch(0xA6, target)

    def ifnull(self, target: str) -> None:
        self._branch(0xC6, target)

    def ifnonnull(self, target: str) -> None:
        self._branch(0xC7, target)

    def goto(self, target: str) -> None:
        self._branch(0xA7, target)

    def getstatic(self, cls_name: str, name: str, desc: str) -> None:
        self.buf.extend(struct.pack(">BH", 0xB2, self.cp.fieldref(cls_name, name, desc)))

    def putstatic(self, cls_name: str, name: str, desc: str) -> None:
        self.buf.extend(struct.pack(">BH", 0xB3, self.cp.fieldref(cls_name, name, desc)))

    def getfield(self, cls_name: str, name: str, desc: str) -> None:
        self.buf.extend(struct.pack(">BH", 0xB4, self.cp.fieldref(cls_name, name, desc)))

    def invokevirtual(self, cls_name: str, name: str, desc: str) -> None:
        self.buf.extend(struct.pack(">BH", 0xB6, self.cp.methodref(cls_name, name, desc)))

    def invokespecial(self, cls_name: str, name: str, desc: str) -> None:
        self.buf.extend(struct.pack(">BH", 0xB7, self.cp.methodref(cls_name, name, desc)))

    def invokestatic(self, cls_name: str, name: str, desc: str) -> None:
        self.buf.extend(struct.pack(">BH", 0xB8, self.cp.methodref(cls_name, name, desc)))

    def new(self, cls_name: str) -> None:
        self.buf.extend(struct.pack(">BH", 0xBB, self.cp.cls(cls_name)))

    def anewarray(self, cls_name: str) -> None:
        self.buf.extend(struct.pack(">BH", 0xBD, self.cp.cls(cls_name)))

    def checkcast(self, cls_name: str) -> None:
        self.buf.extend(struct.pack(">BH", 0xC0, self.cp.cls(cls_name)))

    def instanceof(self, cls_name: str) -> None:
        self.buf.extend(struct.pack(">BH", 0xC1, self.cp.cls(cls_name)))

    def arraylength(self) -> None:
        self.emit(0xBE)

    def finish(self, max_stack: int = 12, max_locals: int = 16) -> bytes:
        for patch_pos, op_pos, target in self.fixups:
            rel = self.labels[target] - op_pos
            if not (-32768 <= rel <= 32767):
                raise ValueError(f"branch offset out of 16-bit range for label {target}: {rel}")
            struct.pack_into(">h", self.buf, patch_pos, rel)
        code_bytes = bytes(self.buf)
        code_attr_name = self.cp.utf8("Code")
        body = (
            struct.pack(">HHI", max_stack, max_locals, len(code_bytes))
            + code_bytes
            + struct.pack(">HH", 0, 0)
        )
        return struct.pack(">HI", code_attr_name, len(body)) + body


class ClassFileBuilder:
    """Java 5 (`49.0`) class file writer supporting `@TLAPlusOperator` without `StackMapTable`."""

    def __init__(
        self,
        this_cls: str,
        super_cls: str = "java/lang/Object",
        interfaces: list[str] | None = None,
    ) -> None:
        self.this_cls = this_cls
        self.cp = ConstantPool()
        self.this_idx = self.cp.cls(this_cls)
        self.super_idx = self.cp.cls(super_cls)
        self.iface_idxs = [self.cp.cls(i) for i in (interfaces or [])]
        self.fields: list[bytes] = []
        self.methods: list[bytes] = []

    def add_default_ctor(self) -> None:
        c = CodeAsm(self.cp)
        c.aload(0)
        c.invokespecial("java/lang/Object", "<init>", "()V")
        c.vreturn()
        self.add_method(0x0001, "<init>", "()V", c.finish(2, 1))

    def add_field(self, access: int, name: str, desc: str) -> None:
        self.fields.append(struct.pack(">HHHH", access, self.cp.utf8(name), self.cp.utf8(desc), 0))

    def _op_annot_attr(self, identifier: str, module: str, warn: bool = False) -> bytes:
        attr_name = self.cp.utf8("RuntimeVisibleAnnotations")
        type_idx = self.cp.utf8(OP_ANNOT)
        k_id = self.cp.utf8("identifier")
        v_id = self.cp.utf8(identifier)
        k_mod = self.cp.utf8("module")
        v_mod = self.cp.utf8(module)
        k_warn = self.cp.utf8("warn")
        v_warn = self.cp.integer(1 if warn else 0)
        annot = (
            struct.pack(">HH", type_idx, 3)
            + struct.pack(">HBH", k_id, ord("s"), v_id)
            + struct.pack(">HBH", k_mod, ord("s"), v_mod)
            + struct.pack(">HBH", k_warn, ord("Z"), v_warn)
        )
        payload = struct.pack(">H", 1) + annot
        return struct.pack(">HI", attr_name, len(payload)) + payload

    def add_method(
        self,
        access: int,
        name: str,
        desc: str,
        code_attr: bytes,
        tla_op: tuple[str, str] | None = None,
        warn: bool = False,
    ) -> None:
        attrs = [code_attr]
        if tla_op is not None:
            attrs.append(self._op_annot_attr(tla_op[0], tla_op[1], warn=warn))
        self.methods.append(
            struct.pack(">HHHH", access, self.cp.utf8(name), self.cp.utf8(desc), len(attrs))
            + b"".join(attrs)
        )

    def build(self) -> bytes:
        header = struct.pack(">IHH", 0xCAFEBABE, 0, 49)
        cp_bytes = self.cp.encode()
        cls_hdr = struct.pack(
            ">HHHH", 0x0021, self.this_idx, self.super_idx, len(self.iface_idxs)
        )
        ifaces = b"".join(struct.pack(">H", idx) for idx in self.iface_idxs)
        f_sec = struct.pack(">H", len(self.fields)) + b"".join(self.fields)
        m_sec = struct.pack(">H", len(self.methods)) + b"".join(self.methods)
        a_sec = struct.pack(">H", 0)
        return header + cp_bytes + cls_hdr + ifaces + f_sec + m_sec + a_sec

    def write_to(self, out_root: Path) -> Path:
        cls_path = out_root / f"{self.this_cls}.class"
        cls_path.parent.mkdir(parents=True, exist_ok=True)
        cls_path.write_bytes(self.build())
        return cls_path


def write_tlc_overrides_registry(out_root: Path, internal_class_names: list[str]) -> Path:
    """Emit `tlc2/overrides/TLCOverrides.class` implementing `ITLCOverrides.get()`.

    TLC's override loader discovers `tlc2.overrides.TLCOverrides` on the classpath and
    registers every `@TLAPlusOperator` static method found on the classes returned by
    `get()`. Always call this helper after writing your custom override class(es) into
    `out_root`.
    """
    me = "tlc2/overrides/TLCOverrides"
    cb = ClassFileBuilder(me, interfaces=["tlc2/overrides/ITLCOverrides"])
    cb.add_default_ctor()

    c = CodeAsm(cb.cp)
    c.iconst(len(internal_class_names))
    c.anewarray("java/lang/Class")
    for idx, cls_name in enumerate(classes := internal_class_names):
        c.dup()
        c.iconst(idx)
        c.ldc_cls(cls_name)
        c.aastore()
    c.areturn()
    cb.add_method(0x0001, "get", "()[Ljava/lang/Class;", c.finish(max(5, len(classes) + 2), 1))
    return cb.write_to(out_root)


def compile_java_sources(jar: Path, out_dir: Path, sources: list[Path]) -> None:
    javac = shutil.which("javac")
    if not javac:
        raise RuntimeError(
            "javac not found on this host (JRE-only). Author overrides in Python using "
            "tlc_bytecode.ClassFileBuilder + write_tlc_overrides_registry instead."
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [javac, "--release", "11", "-cp", str(jar), "-d", str(out_dir)] + [
        str(s) for s in sources
    ]
    subprocess.run(cmd, check=True)


def run_self_test(jar: Path) -> int:
    import os

    if not jar.is_file():
        print(f"tlc_bytecode.py: jar not found: {jar}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="tlc_bc_smoke.") as tmp_s:
        tmp = Path(tmp_s)
        ov_dir = tmp / "overrides"
        ov_cls = "tlc2/overrides/SmokeBcModOverrides"
        cb = ClassFileBuilder(ov_cls)
        cb.add_default_ctor()
        c = CodeAsm(cb.cp)
        c.aload(0)
        c.checkcast(INT_CLS)
        c.getfield(INT_CLS, "val", "I")
        c.iconst(1)
        c.iadd()
        c.invokestatic(INT_CLS, "gen", f"(I)L{INT_CLS};")
        c.areturn()
        cb.add_method(
            0x0009,
            "FastStep",
            f"({L_VAL}){L_VAL}",
            c.finish(4, 1),
            tla_op=("FastStep", "SmokeBcMod"),
            warn=True,
        )
        cb.write_to(ov_dir)
        write_tlc_overrides_registry(ov_dir, [ov_cls])

        tla = tmp / "SmokeBcMod.tla"
        tla.write_text(
            "---- MODULE SmokeBcMod ----\n"
            "EXTENDS Naturals\n"
            "VARIABLE x\n"
            "FastStep(v) == v + 1\n"
            "Init == x = 0\n"
            "Next == IF x < 3 THEN x' = FastStep(x) ELSE UNCHANGED x\n"
            "Inv == x \\in 0..3\n"
            "====\n"
        )
        cfg = tmp / "SmokeBcMod.cfg"
        cfg.write_text("INIT Init\nNEXT Next\nINVARIANT Inv\n")

        cp_with = f"{ov_dir}{os.pathsep}{jar}"
        base_cmd = [
            "java",
            "-XX:+TieredCompilation",
            "-XX:TieredStopAtLevel=1",
            "-cp",
        ]
        r_plain = subprocess.run(
            base_cmd + [str(jar), "tlc2.TLC", "-checkpoint", "0", "-metadir", str(tmp / "s1"), "-config", "SmokeBcMod.cfg", "SmokeBcMod.tla"],
            cwd=tmp,
            capture_output=True,
            text=True,
        )
        r_ov = subprocess.run(
            base_cmd + [cp_with, "tlc2.TLC", "-checkpoint", "0", "-metadir", str(tmp / "s2"), "-config", "SmokeBcMod.cfg", "SmokeBcMod.tla"],
            cwd=tmp,
            capture_output=True,
            text=True,
        )
        if r_plain.returncode != 0 or r_ov.returncode != 0:
            print("Self-test failed:", r_plain.stdout, r_ov.stdout, file=sys.stderr)
            return 1
        if "4 distinct states found" not in r_plain.stdout or "4 distinct states found" not in r_ov.stdout:
            print("Unexpected state counts:", r_plain.stdout, r_ov.stdout, file=sys.stderr)
            return 1
        if "SmokeBcModOverrides" not in r_ov.stdout:
            print("Override class was not bound by TLC:", r_ov.stdout, file=sys.stderr)
            return 1
        print("tlc_bytecode.py self-test OK: SmokeBcModOverrides bound and matched 4 distinct states.")
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="TLC @TLAPlusOperator bytecode helper")
    ap.add_argument("--self-test", metavar="TLA_TOOLS_JAR", help="Run bytecode + TLC self-test")
    sub = ap.add_subparsers(dest="cmd")
    cp_p = sub.add_parser("compile", help="Compile .java override sources with javac")
    cp_p.add_argument("--jar", required=True, type=Path)
    cp_p.add_argument("--out", required=True, type=Path)
    cp_p.add_argument("sources", nargs="+", type=Path)
    args = ap.parse_args()

    if args.self_test:
        return run_self_test(Path(args.self_test))
    if args.cmd == "compile":
        compile_java_sources(args.jar, args.out, args.sources)
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
