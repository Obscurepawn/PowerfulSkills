"""Regression tests for clear-answer-writing style checker."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ai_style_check as checker


class StyleCheckTests(unittest.TestCase):
    def write_doc(self, content: str) -> Path:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = Path(td.name) / "article.md"
        path.write_text(content, encoding="utf-8")
        return path

    def test_comma_question_heading_is_not_flagged_as_conclusion(self):
        # Recommended directly in references/long-form.md
        self.assertFalse(checker.is_conclusion_heading("中间隔了五台交换机，要比几只钟？"))
        self.assertTrue(checker.is_conclusion_heading("从一条行情到一笔订单，先标清测量边界"))
        self.assertTrue(checker.is_conclusion_heading("多台交换机不必然带来逐跳时钟比较"))

    def test_heading_prefix_distinguishes_english_terms_and_two_char_words(self):
        doc = self.write_doc(
            "# 测试\n\n"
            "## PTP 对时协议\n正文。\n\n"
            "## PHC 硬件时钟\n正文。\n\n"
            "## PMU 性能计数\n正文。\n\n"
            "## PCIe 传输延迟\n正文。\n"
        )
        m, flags, _ = checker.analyze(doc)
        self.assertEqual(m["heading_same_prefix"], 1)
        self.assertNotIn("heading_same_prefix", {f["metric"] for f in flags})

        repeated = self.write_doc(
            "# 测试\n\n"
            "## 如何测量时钟成本\n正文。\n\n"
            "## 如何核对网卡硬件戳\n正文。\n\n"
            "## 如何排查 phc2sys 退出\n正文。\n\n"
            "## 如何收敛尾延迟\n正文。\n"
        )
        m2, flags2, _ = checker.analyze(repeated)
        self.assertEqual(m2["heading_same_prefix"], 4)
        self.assertIn("heading_same_prefix", {f["metric"] for f in flags2})

    def test_blockquotes_nested_fences_and_list_items_are_handled_cleanly(self):
        doc = self.write_doc(
            "# 测试\n\n"
            "> 本文将介绍很多背景，这里要分开两种能力，不是 A 而是 B。\n\n"
            "````markdown\n"
            "```bash\n"
            "echo 本文将介绍\n"
            "```\n"
            "````\n\n"
            "- 第一条配置核对主机网卡驱动版本与固件状态。\n"
            "- 第二条配置核对交换机端口队列与时间戳导出。\n"
            "- 第三条配置在极端拥塞下可能触发丢包。\n"
        )
        m, _, _ = checker.analyze(doc)
        self.assertEqual(m["meta_count"], 0)
        self.assertEqual(m["distinguish_count"], 0)
        self.assertEqual(m["not_a_but_b_count"], 0)
        # Three short list items (< 40 chars each) must not merge into one >= 40-char paragraph.
        self.assertEqual(m["caveat_tail_ratio"], 0.0)

    def test_count_thresholds_scale_for_very_long_articles(self):
        filler = "处理器直接读取计数器并完成换算。" * 500  # ~8000 chars
        doc = self.write_doc(
            "# 长文\n\n## 第一节\n"
            + filler
            + "\n这里区分两种硬件路径，再区分内核与用户态边界，同时区分采样周期与上报周期，最后区分冷启动与稳态，以及区分单机与跨机。\n"
        )
        m, flags, _ = checker.analyze(doc)
        self.assertGreater(m["chars"], 7000)
        self.assertEqual(m["distinguish_count"], 5)
        self.assertNotIn("distinguish_count", {f["metric"] for f in flags})


if __name__ == "__main__":
    unittest.main()
