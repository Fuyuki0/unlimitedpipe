from datetime import UTC, datetime

import pytest

from unlimitedpipe.sources.quakes import (
    Quakes,
    gfz_reports,
    jma_reports,
    merge,
    usgs_reports,
)

GFZ_TEXT = (
    "#EventID|Time|Latitude|Longitude|Depth/km|Author|Catalog|Contributor|ContributorID|"
    "MagType|Magnitude|MagAuthor|EventLocationName|EventType\n"
    "gfz2026tjvk|2026-10-03T18:12:44.05|20.651|93.367|10.0|||GFZ|gfz2026tjvk|mb|5.03||Myanmar|"
    "earthquake\n"
    "gfz2026x|2026-10-03T10:00:00|1|1|10|||GFZ|x|mb|4.9||Somewhere|quarry blast\n"
)
USGS_DOC = {
    "features": [
        {
            "id": "us6000tzdp",
            "properties": {
                "mag": 4.9,
                "time": 1791051166916,
                "place": "72 km NE of Sittwe, Burma (Myanmar)",
                "title": "M 4.9 - 72 km NE of Sittwe, Burma (Myanmar)",
                "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us6000tzdp",
                "type": "earthquake",
            },
            "geometry": {"coordinates": [93.4, 20.6, 10]},
        }
    ]
}
JMA_LIST = [
    {
        "eid": "20261001212700",
        "at": "2026-10-01T21:27:00+09:00",
        "en_ttl": "Earthquake Information",
        "cod": "+35.7+140.7-40000/",
        "mag": "5.1",
        "maxi": "",
        "en_anm": "Northeastern Chiba Prefecture",
    },
    {
        "eid": "20261001212700",
        "at": "2026-10-01T21:27:00+09:00",
        "en_ttl": "Earthquake and Seismic Intensity Information",
        "cod": "+35.7+140.7-40000/",
        "mag": "5.1",
        "maxi": "3",
        "en_anm": "Northeastern Chiba Prefecture",
    },
    {  # small, but strong shaking
        "eid": "2",
        "at": "2026-10-02T01:00:00+09:00",
        "en_ttl": "Earthquake and Seismic Intensity Information",
        "cod": "+33.0+131.0-10000/",
        "mag": "4.1",
        "maxi": "5-",
        "en_anm": "Kumamoto",
    },
    {
        "eid": "3",
        "at": "2026-10-02T02:00:00+09:00",
        "en_ttl": "Distant Earthquake Information",
        "cod": "-20+170/",
        "mag": "7.0",
        "maxi": "",
        "en_anm": "Tonga",
    },
    {
        "eid": "4",
        "at": "2026-10-02T03:00:00+09:00",
        "en_ttl": "Earthquake Information",
        "cod": "+33+131-10000/",
        "mag": "2.0",
        "maxi": "1",
        "en_anm": "Oita",
    },
]


def test_each_agency_is_read_into_reports():
    (gfz,) = gfz_reports(GFZ_TEXT)  # the quarry blast is left out
    assert gfz["title"] == "M 5.0 - Myanmar" and gfz["link"].endswith("id=gfz2026tjvk")
    (usgs,) = usgs_reports(USGS_DOC)
    assert usgs["title"].startswith("M 4.9 - 72 km NE of Sittwe") and usgs["t"] == 1791051166.916
    jma = jma_reports(JMA_LIST, 4.5)
    assert [r["title"] for r in jma] == [
        "M 5.1 - Northeastern Chiba Prefecture, Japan (JMA intensity 3)",
        "M 4.1 - Kumamoto, Japan (JMA intensity 5 lower)",
    ]
    assert jma[0]["t"] == datetime(2026, 10, 1, 12, 27, tzinfo=UTC).timestamp()  # JST + 9
    assert (jma[0]["lat"], jma[0]["lon"]) == (35.7, 140.7)


def test_reports_of_one_quake_join_the_first():
    clusters = merge(gfz_reports(GFZ_TEXT), [], now=1791051700)
    assert [c["key"] for c in clusters] == ["gfz:gfz2026tjvk"]
    # a later run: USGS reports it 15 minutes later, 10 km away, 3 seconds apart
    clusters = merge(gfz_reports(GFZ_TEXT) + usgs_reports(USGS_DOC), clusters, now=1791052600)
    assert len(clusters) == 1
    (quake,) = clusters
    assert quake["key"] == "gfz:gfz2026tjvk" and quake["first"] == "GFZ"
    assert sorted(quake["reports"]) == ["GFZ", "USGS"]
    assert quake["title"] == "M 5.0 - Myanmar"  # the first report's, for good


def test_options_are_checked():
    with pytest.raises(ValueError):
        Quakes(agency=["EMSC"])  # not read
    with pytest.raises(ValueError):
        Quakes(days=30)
    assert Quakes(agency=["jma", "geonet"]).agency == ["JMA", "GeoNet"]


def test_bmkg_and_geonet_read_in_english():
    from unlimitedpipe.sources.quakes import bmkg_reports, geonet_reports

    bmkg = {
        "Infogempa": {
            "gempa": [
                {
                    "DateTime": "2026-10-01T14:20:00+00:00",
                    "Coordinates": "-7.07,120.80",
                    "Magnitude": "5.1",
                    "Wilayah": "111 km Tenggara SELAYAR-SULSEL",
                    "Potensi": "Tidak berpotensi tsunami",
                },
                {
                    "DateTime": "2026-10-02T01:00:00+00:00",
                    "Coordinates": "-3.5,128.2",
                    "Magnitude": "7.0",
                    "Wilayah": "20 km Barat Daya AMBON-MALUKU",
                    "Potensi": "Berpotensi tsunami",
                },
            ]
        }
    }
    calm, strong = bmkg_reports(bmkg)
    assert calm["title"] == "M 5.1 - 111 km SE of Selayar, Sulsel, Indonesia"
    assert (
        strong["title"] == "M 7.0 - 20 km SW of Ambon, Maluku, Indonesia (tsunami possible, BMKG)"
    )
    geonet = {
        "features": [
            {
                "geometry": {"coordinates": [174.3, -39.1]},
                "properties": {
                    "publicID": "2026p740000",
                    "time": "2026-10-02T13:57:00.000Z",
                    "magnitude": 5.3,
                    "locality": "25 km east of New Plymouth",
                    "quality": "best",
                },
            },
            {
                "geometry": {"coordinates": [178.3, -37.9]},
                "properties": {
                    "publicID": "x",
                    "time": "2026-10-02T19:46:36.555Z",
                    "magnitude": 2.9,
                    "locality": "Ruatoria",
                    "quality": "deleted",
                },
            },
        ]
    }
    (quake,) = geonet_reports(geonet)
    assert quake["title"] == "M 5.3 - 25 km east of New Plymouth, New Zealand"
    assert quake["link"] == "https://www.geonet.org.nz/earthquake/2026p740000"


def test_emsc_stream_messages_become_reports():
    from unlimitedpipe.sources.quakes import emsc_report

    message = {
        "action": "create",
        "data": {
            "properties": {
                "unid": "20261004_0000100",
                "time": "2026-10-04T05:57:54.4Z",
                "flynn_region": "STATE OF YAP, MICRONESIA",
                "lat": 11.24,
                "lon": 139.34,
                "mag": 4.7,
                "evtype": "ke",
            }
        },
    }
    report = emsc_report(message)
    assert report["agency"] == "EMSC" and report["mag"] == 4.7
    assert report["title"] == "M 4.7 - State of Yap, Micronesia"
    assert report["link"].endswith("unid=20261004_0000100")
    assert emsc_report({**message, "action": "delete"}) is None
    blast = {
        "action": "create",
        "data": {"properties": {**message["data"]["properties"], "evtype": "kx"}},
    }
    assert emsc_report(blast) is None  # an explosion, not a quake


def test_emsc_needs_listening_time():
    import pytest

    from unlimitedpipe.sources.quakes import Quakes

    assert "EMSC" not in Quakes().agency
    assert "EMSC" in Quakes(listen=25).agency
    with pytest.raises(ValueError):
        Quakes(agency=["EMSC"])
