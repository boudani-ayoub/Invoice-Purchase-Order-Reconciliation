from reconcile.persistence.intelligence import median


def test_observed_day_median_is_deterministic_for_odd_even_and_empty_sets():
    assert median([]) is None
    assert median([9, 1, 5]) == "5"
    assert median([8, 2, 4, 6]) == "5"
    assert median([1, 2]) == "1.5"
