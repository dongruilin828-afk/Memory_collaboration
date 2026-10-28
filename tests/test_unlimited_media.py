"""Unlimited summary outputs do not remove isolated media extraction limits."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from gui import service
from scripts import gemini_summarizer as summary
from scripts.doubao_media import DIAGRAM_OCR_MODEL, _read_diagram


class UnlimitedMediaTests(unittest.TestCase):
    def test_literal_reader_remains_bounded_without_mutating_summary_gateway(self):
        for limit, expected in ((None, 4096), (2048, 2048), (16384, 4096)):
            with self.subTest(limit=limit), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "diagram.png"
                Image.new("RGB", (12, 12), "white").save(path)
                asset = summary.MediaAsset("M1", 1, "image", "流程图", "./diagram.png",
                                           local_path=path, mime_type="image/png")
                config = summary.SummaryConfig(provider="siliconflow", model="Qwen/Qwen3-8B",
                                               max_output_tokens=limit, thinking_level="auto")
                gateway = summary.SiliconFlowGateway(config, api_key="test-placeholder")
                calls = []

                def read(reader, *_args, **_kwargs):
                    calls.append((reader.config, reader._doubao_visual_model))
                    return {"text_lines": ["Visible diagram label"], "small_labels": [],
                            "unreadable_fragments": [], "source_anomalies": []}

                with patch.object(summary.SiliconFlowGateway, "generate_json", new=read):
                    result = _read_diagram(asset, gateway, Path(directory))
                self.assertEqual(result["status"], "described")
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][0].max_output_tokens, expected)
                self.assertEqual(calls[0][0].retries, 1)
                self.assertEqual(calls[0][1], DIAGRAM_OCR_MODEL)
                self.assertIs(gateway.config, config)
                self.assertEqual(gateway.config.max_output_tokens, limit)
                self.assertFalse(hasattr(gateway, "_doubao_visual_model"))

    def test_doubao_visual_gateway_keeps_its_extraction_cap(self):
        for limit, expected in ((None, 8192), (2048, 2048), (16384, 8192)):
            with self.subTest(limit=limit), tempfile.TemporaryDirectory() as directory:
                vision = summary.SummaryConfig(provider="siliconflow", model="Qwen/Qwen3-8B",
                                               max_output_tokens=limit)
                captured = []

                class ConfigCaptured(Exception):
                    pass

                def create(config, **kwargs):
                    captured.append((config, kwargs))
                    raise ConfigCaptured()

                # Stop immediately after constructing the separate visual
                # gateway; no model request or summary output is needed.
                with patch.object(summary.SummaryConfig, "from_env", return_value=vision), \
                        patch.object(summary, "create_gateway", side_effect=create):
                    with self.assertRaises(ConfigCaptured):
                        service.generate_output_bundle(
                            [{"role": "User", "content": "读取图片"}], {"normal": True}, Path(directory),
                            config=summary.SummaryConfig(), gateway=object(),
                            api_keys={"siliconflow": "test-placeholder"}, source_platform="doubao")
                self.assertEqual(len(captured), 1)
                self.assertEqual(captured[0][0].provider, "siliconflow")
                self.assertEqual(captured[0][0].max_output_tokens, expected)
                self.assertEqual(captured[0][1]["api_key"], "test-placeholder")
                self.assertEqual(vision.max_output_tokens, limit)


if __name__ == "__main__":
    unittest.main()
