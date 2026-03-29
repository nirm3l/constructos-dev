from features.bootstrap.cache import bootstrap_cache_status, clear_bootstrap_cache, get_or_compute_bootstrap_cache


def test_bootstrap_cache_get_or_compute_tracks_hits_and_misses():
    key = "test-bootstrap-cache-key"
    clear_bootstrap_cache(key=key)

    computed_values: list[int] = []

    def _compute():
        computed_values.append(1)
        return {"value": len(computed_values)}

    first, first_hit = get_or_compute_bootstrap_cache(
        key=key,
        ttl_seconds=60.0,
        force_refresh=False,
        compute=_compute,
    )
    second, second_hit = get_or_compute_bootstrap_cache(
        key=key,
        ttl_seconds=60.0,
        force_refresh=False,
        compute=_compute,
    )
    status = bootstrap_cache_status(key=key)

    assert first_hit is False
    assert second_hit is True
    assert first["value"] == 1
    assert second["value"] == 1
    assert status["miss_count"] == 1
    assert status["hit_count"] >= 1
