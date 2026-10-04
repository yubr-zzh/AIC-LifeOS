import tempfile
import unittest
from pathlib import Path

from lifeos.storage.sqlite import StructuredStore
from lifeos.storage.vault import VaultManager


class VaultManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.store = StructuredStore(self.root / "lifeos.db")
        self.manager = VaultManager(
            settings_path=self.root / "vault.json",
            structured_store=self.store,
        )

    def test_configure_rejects_missing_path(self):
        with self.assertRaises(ValueError):
            self.manager.configure(str(self.root / "missing"))

    def test_export_and_import_markdown_round_trip(self):
        status = self.manager.configure(str(self.vault), "LifeOS")
        self.assertTrue(status["configured"])
        entry = self.store.upsert({
            "kind": "daily_plan",
            "entry_date": "2026-10-04",
            "title": "今日规划",
            "content": "- [ ] 完成 Vault 联调",
            "metadata": {"intent": "验证导出"},
        })

        exported = self.manager.export_entry(entry["id"])
        markdown_path = self.vault / exported["relative_path"]
        self.assertTrue(markdown_path.is_file())
        text = markdown_path.read_text(encoding="utf-8")
        self.assertIn("lifeos_kind: \"daily_plan\"", text)
        self.assertIn("- [ ] 完成 Vault 联调", text)
        self.assertIn(exported["relative_path"], [
            item["path"] for item in self.manager.list_files("daily_plan", 20)
        ])

        imported_store = StructuredStore(self.root / "imported.db")
        importer = VaultManager(
            settings_path=self.root / "vault.json",
            structured_store=imported_store,
        )
        imported = importer.import_file(exported["relative_path"])
        self.assertEqual(imported["entry"]["kind"], "daily_plan")
        self.assertEqual(imported["entry"]["title"], "今日规划")
        self.assertIn("完成 Vault 联调", imported["entry"]["content"])

        edited = markdown_path.read_text(encoding="utf-8").replace(
            "- [ ] 完成 Vault 联调",
            "- [x] 完成 Vault 联调\n\n## 用户补充\n这是后来直接在 Obsidian 写入的内容。#用户输入",
        )
        markdown_path.write_text(edited, encoding="utf-8")
        synced = self.manager.sync_entry(entry["id"])["entry"]
        self.assertEqual(synced["id"], entry["id"])
        self.assertIn("这是后来直接在 Obsidian 写入的内容", synced["content"])
        self.assertEqual(synced["metadata"]["intent"], "验证导出")
        self.assertIn("用户输入", synced["metadata"]["tags"])
        self.assertEqual(synced["metadata"]["vault_path"], exported["relative_path"])

    def test_relative_path_cannot_escape_vault(self):
        self.manager.configure(str(self.vault), "LifeOS")
        with self.assertRaises(ValueError):
            self.manager.read_file("../outside.md")


if __name__ == "__main__":
    unittest.main()
