"""Incremental running mean/std/"extreme" - Welford's online algorithm
for mean and variance, so tracking a session's summary stats doesn't
require storing full history (matches the drop counters' style: update
once per pair, read the summary whenever needed).

"extreme" is the largest-magnitude observation, sign preserved - not a
plain max(). This matches the design mockup's own example numbers ("HW
TS Sync avg/std/max: -38.2 / 0.6 / -40"): for a mostly-negative metric
like a HW timestamp gap, a plain max() would report the value CLOSEST to
zero (the best case, e.g. -37ish), not -40. The mockup's own "max" is
clearly the worst-case deviation from zero, sign preserved - so that's
what this tracks.
"""


class RunningStats:
    def __init__(self):
        self.count = 0
        self.mean = 0.0
        self.extreme = None
        self._m2 = 0.0

    def update(self, value):
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        delta2 = value - self.mean
        self._m2 += delta * delta2
        if self.extreme is None or abs(value) > abs(self.extreme):
            self.extreme = value

    @property
    def std(self):
        if self.count < 2:
            return 0.0
        return (self._m2 / self.count) ** 0.5

    def summary_text(self, ndigits=1):
        if self.count == 0:
            return "-"
        return "{:.{n}f} / {:.{n}f} / {:.{n}f}".format(self.mean, self.std, self.extreme, n=ndigits)
