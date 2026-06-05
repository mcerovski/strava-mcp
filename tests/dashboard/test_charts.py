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
