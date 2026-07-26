import ast
import string
import unittest
from pathlib import Path

from seaweed_browser.i18n import (
    DEFAULT_LANGUAGE,
    LANGUAGE_NAMES,
    catalogs,
    get_language,
    normalize_language,
    set_language,
    tr,
)


def placeholder_names(template: str) -> set[str]:
    return {
        field_name
        for _, field_name, _, _ in string.Formatter().parse(template)
        if field_name
    }


class I18nTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_language(DEFAULT_LANGUAGE)

    def test_supported_languages_and_locale_normalization(self) -> None:
        self.assertEqual(set(LANGUAGE_NAMES), {"zh_CN", "en", "fr"})
        self.assertEqual(normalize_language("zh-CN"), "zh_CN")
        self.assertEqual(normalize_language("en_US"), "en")
        self.assertEqual(normalize_language("fr-FR"), "fr")
        self.assertEqual(normalize_language("de_DE"), DEFAULT_LANGUAGE)

    def test_translation_and_chinese_fallback(self) -> None:
        set_language("en")
        self.assertEqual(get_language(), "en")
        self.assertEqual(tr("取消"), "Cancel")
        self.assertEqual(
            tr("已加载 {count} 条", count=3),
            "Loaded 3 entries",
        )
        set_language("fr")
        self.assertEqual(tr("取消"), "Annuler")
        self.assertEqual(tr("未登记文本"), "未登记文本")

    def test_catalogs_have_identical_keys_and_placeholders(self) -> None:
        translation_catalogs = catalogs()
        english_keys = set(translation_catalogs["en"])
        french_keys = set(translation_catalogs["fr"])
        self.assertEqual(english_keys, french_keys)
        for source in sorted(english_keys):
            expected = placeholder_names(source)
            with self.subTest(source=source, language="en"):
                self.assertEqual(
                    placeholder_names(translation_catalogs["en"][source]),
                    expected,
                )
            with self.subTest(source=source, language="fr"):
                self.assertEqual(
                    placeholder_names(translation_catalogs["fr"][source]),
                    expected,
                )

    def test_all_literal_translation_calls_exist_in_catalogs(self) -> None:
        source_paths = [Path("main.py"), *Path("seaweed_browser").glob("*.py")]
        used_sources = set()
        for path in source_paths:
            if path.name == "i18n.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "tr"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    used_sources.add(node.args[0].value)
        for language, catalog in catalogs().items():
            with self.subTest(language=language):
                self.assertEqual(used_sources - set(catalog), set())

    def test_chinese_user_text_is_wrapped_for_translation(self) -> None:
        source_paths = [Path("main.py"), *Path("seaweed_browser").glob("*.py")]
        unwrapped = []
        for path in source_paths:
            if path.name == "i18n.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            parents = {
                child: parent
                for parent in ast.walk(tree)
                for child in ast.iter_child_nodes(parent)
            }
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and any("\u4e00" <= char <= "\u9fff" for char in node.value)
                ):
                    continue
                current = node
                while current in parents:
                    current = parents[current]
                    if (
                        isinstance(current, ast.Call)
                        and isinstance(current.func, ast.Name)
                        and current.func.id == "tr"
                    ):
                        break
                else:
                    unwrapped.append(f"{path}:{node.lineno}")
        self.assertEqual(unwrapped, [])


if __name__ == "__main__":
    unittest.main()
