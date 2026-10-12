"""Small, explicit SplitMix64 source for cross-runtime deterministic draws."""

from __future__ import annotations

MASK_64 = (1 << 64) - 1
_GAMMA = 0x9E3779B97F4A7C15


class SeededRandom:
    """SplitMix64 PRNG; its integer algorithm is part of generator v1."""

    def __init__(self, seed: int) -> None:
        self._state = seed & MASK_64

    def next_u64(self) -> int:
        self._state = (self._state + _GAMMA) & MASK_64
        value = self._state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & MASK_64
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & MASK_64
        return value ^ (value >> 31)

    def randbelow(self, upper_bound: int) -> int:
        if upper_bound <= 0:
            raise ValueError("upper_bound must be positive")
        limit = (1 << 64) - ((1 << 64) % upper_bound)
        while True:
            value = self.next_u64()
            if value < limit:
                return value % upper_bound

    def choice(self, values: tuple[object, ...]) -> object:
        if not values:
            raise ValueError("cannot choose from an empty sequence")
        return values[self.randbelow(len(values))]
