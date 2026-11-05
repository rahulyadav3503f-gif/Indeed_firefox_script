"""The active 110-city list -- RE-EXPORTED from the AUTHORITATIVE file.

"Use the active ``city_by_states`` dictionary from the newly provided
``new_mylib.py``.  Do not use the old ``job_by_department`` dictionary.  Do
not create another hardcoded list of job roles or cities."

The 110 cities are counted, not quoted: see tests/test_city_distribution.py.

Like ``target_audience_roles.py`` next to it, this file declares no data of
its own.  It loads the ORIGINAL ``new_mylib.py`` and re-publishes the two
names this project needs:

    city_by_states   the ACTIVE dictionary -- 110 cities, order preserved
    city_to_state    city name -> state name, used to fill the "state" column

``city_by_states_original`` is deliberately NOT re-exported.  It is the
historical larger list and the brief forbids its use, so making it
unreachable from this project is the cheapest way to guarantee that.

ORDER MATTERS.  Rank slicing is positional (``get_cities_by_rank``), so
re-ordering the dictionary would silently reassign cities between ranks.
``all_cities()`` therefore de-duplicates with ``dict.fromkeys`` -- which
preserves first-seen order -- exactly as the original does.
"""

from upstream import load_vendored as _load_vendored

# The AUTHORITATIVE new_mylib.py, copied into vendor/ (md5 in
# vendor/PROVENANCE.json).  At the time of vendoring it was byte-identical
# to the original project's copy, so no city changed; the vendored copy
# records that rather than depending on it staying true.
_upstream = _load_vendored("new_mylib")

#: The ACTIVE city dictionary: 110 cities, insertion order preserved.
city_by_states = _upstream.city_by_states

#: Fuzzy city -> state resolution, reused so the "state" column matches.
city_to_state = _upstream.city_to_state

#: Absolute path of the file these names actually come from.
SOURCE_FILE = getattr(_upstream, "__file__", "")


def all_cities():
    """The flat, de-duplicated city list -- ORDER PRESERVED (it is positional).

    Identical to ``find_indeed_job.all_cities()`` in the original project.
    """
    cities = [city for group in city_by_states.values() for city in group]
    return list(dict.fromkeys(cities))


__all__ = ["city_by_states", "city_to_state", "all_cities", "SOURCE_FILE"]
