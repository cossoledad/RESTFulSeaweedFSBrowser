from collections import OrderedDict
from typing import Generic, Iterator, Optional, Tuple, TypeVar, cast


K = TypeVar("K")
V = TypeVar("V")
_MISSING = object()


class LruCache(Generic[K, V]):
    """A small bounded least-recently-used cache."""

    def __init__(self, max_entries: int):
        if max_entries <= 0:
            raise ValueError("max_entries 必须大于 0")
        self.max_entries = max_entries
        self._items: OrderedDict[K, V] = OrderedDict()

    def get(self, key: K) -> Optional[V]:
        value = self._items.get(key, _MISSING)
        if value is _MISSING:
            return None
        self._items.move_to_end(key)
        return cast(V, value)

    def put(self, key: K, value: V) -> Optional[Tuple[K, V]]:
        self._items[key] = value
        self._items.move_to_end(key)
        if len(self._items) <= self.max_entries:
            return None
        return self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()

    def remove(self, key: K) -> Optional[V]:
        value = self._items.pop(key, _MISSING)
        if value is _MISSING:
            return None
        return cast(V, value)

    def __len__(self) -> int:
        return len(self._items)

    def keys(self) -> Iterator[K]:
        return iter(self._items.keys())
