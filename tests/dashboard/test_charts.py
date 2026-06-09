"""T017 [US2] inline-SVG chart generation, downsampling, absent-stream handling."""

from __future__ import annotations

from strava_mcp.dashboard import charts


def test_one_chart_per_present_type_absent_omitted() -> None:
    payload = {
        "streams": {
            "time": {"data": list(range(5))},
            "distance": {"data": [0, 100, 200, 300, 400]},
            "heartrate": {"data": [120, 130, 140, 150, 145]},
            "watts": {"data": [150, 180, 200, 220, 190]},
            # no altitude/cadence → no chart for those
            "latlng": {"data": [[1, 2]] * 5},  # never plotted
        }
    }
    svgs = charts.build_activity_charts(payload)
    assert len(svgs) == 2  # heartrate + watts only
    joined = "\n".join(svgs)
    assert "Heart rate" in joined and "Power" in joined
    assert "<polyline" in joined
    assert "Distance (km)" in joined  # distance chosen as x-axis


def test_no_streams_returns_no_charts() -> None:
    assert charts.build_activity_charts(None) == []
    assert charts.build_activity_charts({"streams": {}}) == []


def test_all_zero_streams_suppressed() -> None:
    # Indoor/no-GPS shape: altitude + grade_smooth are present but all zero.
    payload = {
        "streams": {
            "time": {"data": list(range(5))},
            "heartrate": {"data": [120, 130, 140, 150, 145]},
            "altitude": {"data": [0, 0, 0, 0, 0]},
            "grade_smooth": {"data": [0, 0, 0, 0, 0]},
        }
    }
    svgs = charts.build_activity_charts(payload)
    joined = "\n".join(svgs)
    assert len(svgs) == 1  # heart rate only
    assert "Heart rate" in joined
    assert "Elevation" not in joined  # all-zero altitude suppressed
    assert "Grade" not in joined  # all-zero grade suppressed


def test_mixed_zero_stream_kept() -> None:
    # Rowing-style cadence: zeros during rest, real values otherwise -> keep it.
    payload = {
        "streams": {
            "time": {"data": list(range(5))},
            "cadence": {"data": [0, 0, 25, 33, 0]},
        }
    }
    svgs = charts.build_activity_charts(payload)
    joined = "\n".join(svgs)
    assert len(svgs) == 1
    assert "Cadence" in joined


def test_constant_nonzero_stream_kept() -> None:
    # A flat but non-zero stream (e.g. steady temperature) is real data -> keep it.
    payload = {
        "streams": {
            "time": {"data": list(range(5))},
            "temp": {"data": [26, 26, 26, 26, 26]},
        }
    }
    svgs = charts.build_activity_charts(payload)
    assert len(svgs) == 1
    assert "Temperature" in "\n".join(svgs)


def test_negative_values_stream_kept() -> None:
    # "All-zero" means literally every value is 0; negatives are real data.
    payload = {
        "streams": {
            "time": {"data": list(range(4))},
            "grade_smooth": {"data": [-1.9, -0.5, 0.0, 0.6]},
        }
    }
    svgs = charts.build_activity_charts(payload)
    assert len(svgs) == 1
    assert "Grade" in "\n".join(svgs)


def test_all_plottable_streams_all_zero_returns_empty() -> None:
    # US2: every plottable stream is all-zero -> no charts (fallback handled by render).
    payload = {
        "streams": {
            "time": {"data": list(range(5))},
            "distance": {"data": [0, 100, 200, 300, 400]},
            "altitude": {"data": [0, 0, 0, 0, 0]},
            "grade_smooth": {"data": [0, 0, 0, 0, 0]},
            "velocity_smooth": {"data": [0, 0, 0, 0, 0]},
        }
    }
    assert charts.build_activity_charts(payload) == []


def test_downsampling_bounds_point_count() -> None:
    n = 50_000
    xs = [float(i) for i in range(n)]
    ys = [float(i % 200) for i in range(n)]
    rx, ry = charts.downsample(xs, ys, max_points=1000)
    assert len(rx) == len(ry)
    assert len(rx) <= 1001  # at most max_points (+1 for the preserved last sample)
    assert ry[-1] == ys[-1]  # last sample preserved


def test_charts_built_from_large_stream_stay_bounded() -> None:
    n = 20_000
    payload = {"streams": {"time": {"data": list(range(n))}, "heartrate": {"data": [130] * n}}}
    svgs = charts.build_activity_charts(payload)
    assert len(svgs) == 1
    # Point count in the polyline is bounded by downsampling.
    points = svgs[0].split('points="')[1].split('"')[0].split()
    assert len(points) <= charts.MAX_POINTS + 1
