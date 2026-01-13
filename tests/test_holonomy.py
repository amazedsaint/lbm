import unittest

from lb.holonomy import Chart, random_orthogonal, holonomy_loop


class TestHolonomy(unittest.TestCase):
    def test_holonomy_defect_nonzero(self):
        d = 16
        v0 = [0.0] * d
        chart_a = Chart("A", random_orthogonal(d, seed=1))
        chart_b = Chart("B", random_orthogonal(d, seed=2))
        _, defect = holonomy_loop(v0, chart_a=chart_a, chart_b=chart_b, lr=0.2, k=5)
        self.assertGreater(defect, 1e-6)


if __name__ == "__main__":
    unittest.main()
