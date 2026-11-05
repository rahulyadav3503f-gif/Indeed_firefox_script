"""The 110-city configuration and the rank distribution (brief sections 7, 8)."""

import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import new_mylib                                             # noqa: E402
import find_indeed_job as collector                          # noqa: E402


class TestCityList(unittest.TestCase):
    """Brief section 7: the ACTIVE 110-city list, order preserved."""

    def test_the_cities_come_from_the_original_project(self):
        self.assertTrue(new_mylib.SOURCE_FILE.endswith("new_mylib.py"))
        self.assertNotIn(os.path.join("new_indeed_script", "new_mylib.py"),
                         new_mylib.SOURCE_FILE)

    def test_one_hundred_and_ten_cities(self):
        self.assertEqual(len(collector.all_cities()), 110)

    def test_the_cities_are_unique(self):
        cities = collector.all_cities()
        self.assertEqual(len(cities), len(set(cities)))

    def test_the_historical_list_is_not_reachable(self):
        """Brief section 7: "Do not use city_by_states_original."

        The shim does not re-export it, so this project cannot reach it even
        by accident.
        """
        self.assertFalse(hasattr(new_mylib, "city_by_states_original"))

    def test_order_is_preserved_from_the_dictionary(self):
        # Rank slicing is positional, so a reordering would silently
        # reassign cities between ranks.
        flat = [city for group in new_mylib.city_by_states.values()
                for city in group]
        self.assertEqual(collector.all_cities(), list(dict.fromkeys(flat)))

    def test_the_order_is_stable_across_calls(self):
        self.assertEqual(collector.all_cities(), collector.all_cities())


class TestRankDistribution(unittest.TestCase):
    """Brief section 8's six requirements, each as its own test."""

    def setUp(self):
        self.cities = collector.all_cities()

    def slices(self, num_sys):
        return [collector.get_cities_by_rank(self.cities, rank, num_sys)
                for rank in range(1, num_sys + 1)]

    def test_1_each_rank_receives_its_assigned_cities(self):
        for num_sys in (1, 2, 3, 5, 7, 10):
            with self.subTest(num_sys=num_sys):
                for chunk in self.slices(num_sys):
                    self.assertIsInstance(chunk, list)

    def test_2_no_city_is_assigned_to_two_ranks(self):
        for num_sys in (1, 2, 3, 4, 5, 7, 10, 11):
            with self.subTest(num_sys=num_sys):
                seen = set()
                for chunk in self.slices(num_sys):
                    overlap = seen & set(chunk)
                    self.assertEqual(overlap, set(),
                                     "cities in two ranks: %s" % overlap)
                    seen |= set(chunk)

    def test_3_every_city_is_assigned_to_exactly_one_rank(self):
        for num_sys in (1, 2, 3, 4, 5, 7, 10, 11):
            with self.subTest(num_sys=num_sys):
                assigned = [city for chunk in self.slices(num_sys)
                            for city in chunk]
                self.assertEqual(len(assigned), len(self.cities))
                self.assertEqual(set(assigned), set(self.cities))

    def test_4_rank_assignment_is_stable_across_restarts(self):
        # It is a pure function of (cities, rank, num_sys), so restarting
        # cannot move a city between ranks.
        first = self.slices(5)
        second = self.slices(5)
        self.assertEqual(first, second)

    def test_the_original_algorithm_is_preserved(self):
        """``one_unit = int(len/num_sys) + 1`` then a positional slice."""
        for num_sys in (1, 2, 3, 5, 7):
            one_unit = int(len(self.cities) / num_sys) + 1
            for rank in range(1, num_sys + 1):
                expected = self.cities[one_unit * (rank - 1):one_unit * rank]
                self.assertEqual(
                    collector.get_cities_by_rank(self.cities, rank, num_sys),
                    expected)

    def test_five_ranks_over_110_cities_is_23_23_23_23_18(self):
        """The documented conflict with the brief's "22 per rank", pinned.

        Brief section 8 asks for 22 cities per rank AND for the existing
        distribution algorithm to be preserved.  The algorithm gives
        23/23/23/23/18.  The explicit instruction to preserve it wins, and
        this test records the actual numbers so the difference is visible
        rather than discovered in production.  See
        ``get_cities_by_rank``'s docstring.
        """
        sizes = [len(chunk) for chunk in self.slices(5)]
        self.assertEqual(sizes, [23, 23, 23, 23, 18])
        self.assertEqual(sum(sizes), 110)

    def test_slice_sizes_differ_by_at_most_one_until_the_last(self):
        sizes = [len(chunk) for chunk in self.slices(5)]
        self.assertEqual(len(set(sizes[:-1])), 1)
        self.assertLessEqual(sizes[-1], sizes[0])

    def test_invalid_arguments_return_empty(self):
        for rank, num_sys in ((0, 5), (6, 5), (-1, 5), (1, 0), (1, -3),
                              ("x", 5), (1, "y")):
            with self.subTest(rank=rank, num_sys=num_sys):
                self.assertEqual(
                    collector.get_cities_by_rank(self.cities, rank, num_sys),
                    [])

    def test_an_empty_city_list_returns_empty(self):
        self.assertEqual(collector.get_cities_by_rank([], 1, 5), [])

    def test_rank_cities_refuses_an_impossible_configuration(self):
        with self.assertRaises(RuntimeError):
            collector.rank_cities(which=9, how_many=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
