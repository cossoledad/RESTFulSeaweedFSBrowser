import unittest

from seaweed_browser.cache import LruCache


class LruCacheTests(unittest.TestCase):
    def test_evicts_least_recently_used_entry(self) -> None:
        cache: LruCache[str, int] = LruCache(2)
        cache.put("first", 1)
        cache.put("second", 2)

        self.assertEqual(cache.get("first"), 1)
        evicted = cache.put("third", 3)

        self.assertEqual(evicted, ("second", 2))
        self.assertIsNone(cache.get("second"))
        self.assertEqual(list(cache.keys()), ["first", "third"])

    def test_replacing_entry_does_not_grow_cache(self) -> None:
        cache: LruCache[str, int] = LruCache(1)
        cache.put("key", 1)

        self.assertIsNone(cache.put("key", 2))
        self.assertEqual(len(cache), 1)
        self.assertEqual(cache.get("key"), 2)

    def test_can_store_none_as_a_value(self) -> None:
        cache: LruCache[str, object] = LruCache(1)
        cache.put("key", None)

        self.assertIn("key", list(cache.keys()))
        self.assertIsNone(cache.get("key"))

    def test_rejects_non_positive_capacity(self) -> None:
        with self.assertRaises(ValueError):
            LruCache(0)


if __name__ == "__main__":
    unittest.main()
