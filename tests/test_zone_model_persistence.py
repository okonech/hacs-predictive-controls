from __future__ import annotations

import base64
import hashlib
import json
import zlib
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

from benchmarks.occupancy_performance import _build_workload
from custom_components.predictive_controls.model import PredictiveMap
from custom_components.predictive_controls.yaml_config import load_predictive_map
from custom_components.predictive_controls.zone_model.engine import ZoneModelEngine
from custom_components.predictive_controls.zone_model.persistence import (
    _decode_snapshot,
    _is_pre_feature_v4_snapshot,
    _target_map_fingerprint_payload,
    decode_v2_seed,
    legacy_target_map_fingerprint,
    migrate_schema6_seed,
    migrate_v2_seed,
    pre_feature_target_map_fingerprint,
    restore_target_state,
    serialize_target_state,
    target_map_fingerprint,
)
from custom_components.predictive_controls.zone_model.policy import POLICY_CALIBRATIONS
from custom_components.predictive_controls.zone_model.types import (
    CountInput,
    SensorInput,
)
from tests.test_prediction import NOW as PREDICTION_NOW
from tests.test_prediction import make_map as prediction_map
from tests.test_prediction import seed_mature_route
from tests.test_zone_model_count import (
    conflict_map,
    engine_with_two_front_conflict,
)
from tests.test_zone_model_engine import (
    correlated_continuity_map,
    engine_before_stale_transfer,
    interaction_map,
    mixed_same_zone_map,
    stale_transfer_map,
    target_map,
)

NOW = datetime(2026, 7, 18, 23, 0, tzinfo=UTC)
pytestmark = pytest.mark.target_model


def test_deterministic_coalesced_origin_later_than_creation_round_trips() -> None:
    """Retain the semantic workload's real least-ID/min-created writer frontier."""
    predictive_map = load_predictive_map(
        (Path(__file__).parents[1] / "benchmarks/reference-map.yaml").read_text()
    )
    started_at = datetime(2026, 7, 18, 12, tzinfo=UTC)
    workload = _build_workload(
        predictive_map, event_count=100, started_at=started_at,
        occupants=2, trace_profile="deterministic",
    )
    engine = ZoneModelEngine(predictive_map, 2, workload.bootstrap_at)
    for event, receipt in zip(
        workload.events[:30], workload.receive_at[:30], strict=True,
    ):
        engine.observe(event, processing_at=receipt)
    previous, = engine.snapshot.anonymous_supports
    result = engine.observe(workload.events[30], processing_at=workload.receive_at[30])
    support, = result.snapshot.anonymous_supports
    origin = next(
        token for token in result.snapshot.traversal_tokens
        if "support:" + token.token_id == support.support_id
    )
    assert workload.events[30].entity_id == "binary_sensor.benchmark_gym_motion"
    assert origin.accepted_at == started_at + timedelta(milliseconds=31)
    assert support.created_at == previous.created_at == (
        started_at + timedelta(milliseconds=9)
    )
    assert support.support_id == min(previous.support_id, "support:" + origin.token_id)
    assert support.last_transition == "coalesced"
    assert support.updated_at == origin.accepted_at
    assert origin.track_confidence == "confirmed"
    assert origin.provenance_kind == "adjacent" and len(set(origin.path_node_ids)) == 3
    assert all(a.settled_handoff is None for a in result.authorizations)
    payload = serialize_target_state(predictive_map, engine)
    restored = restore_target_state(predictive_map, payload, result.snapshot.updated_at)
    assert serialize_target_state(predictive_map, restored) == payload
    # Descendants need not retain a coalesced last-transition marker. Replay the
    # rest of the identical workload, without changing receipt order or history.
    for event, receipt in zip(
        workload.events[31:], workload.receive_at[31:], strict=True,
    ):
        assert restored.observe(event, processing_at=receipt) == engine.observe(
            event, processing_at=receipt,
        )
        state = serialize_target_state(predictive_map, engine)
        assert serialize_target_state(predictive_map, restored) == state
        restored = restore_target_state(
            predictive_map, state, engine.snapshot.updated_at,
        )
        assert serialize_target_state(predictive_map, restored) == state


# Frozen *actual writer* snapshots, captured by executing the named git revisions
# in memory. Tests never invoke git or today's writer to construct history.
# 2628173: disconnected hall transition / room PIR; room on@0, off@10, on@12
# (warning); hall on@0, advance@90 (health). All offsets start at NOW.
# 3b78f34: same-zone sticky presence+interaction; presence on, scene_001 pulse,
# scene_002 unknown, all at NOW (reselected). This is pre-handoff current v4.
# 9fe1510: PIR a-b-c chain plus isolated target, count1; on target@0,a@1,b@2,c@3;
# pending snapshot@3, degraded snapshot@63. These are pre-cadence *v3*, not
# relabeled v4. zlib/base64 preserves every snapshot field without huge audit rows.
HISTORICAL_SNAPSHOTS = {
    "warning": (
        "eJztV+tu2zoMfhf9PWkgX5P4OfZvCATFYhKhqmRIctqs2LsfypfYid0tWYfhAGco0sYUSZEfyY/u"
        "O6krwT0Ixj0pSEzj/ImunqL1lzgpKC2i+B/8TSlZEKikMwKY86jvSPH1nejwLAUaHrlSqPPNaBie"
        "Kmv2UgHT/CVIveXaSS+NZnvuPCpwJbkbHH4lO6m5PTMH2hm77NzU+lmbV0222wU5gAbLgw9S0CGm"
        "EIOulVqQ4KxGZ2THHSiJ4TQy26fYaim8n8EJtB8JuThxXd4DRamAWzZ128oFcNHc3EmPRglWay/V"
        "5SbnwDZAeFtjJFeHCNMJrOOKnRCfG0sBB8vF1aWtqMGEWeAuQDMOB16kxzBJsefKAYYDXPkje+VW"
        "S324iEt0i9nfyL8vxlW2xrwMVe6ebqqMqJxZJe3Py9vZm2llo+vKNjcVUTEpCaWXklzq3mKL+V7X"
        "fVrPkfFNO/yw9n+iS6ZukyHYD5rnxibKxgn+V3oKI4bvWOwdjibsx1TyIHMoc2BGCLR9ipebNE2T"
        "9Wa1ifI8TWnSFfRuZiuN9vAWtJrs0ORV+qOpPcMPxh56aWhPNiWdvudmjjoP7HJHV+0PAEMtK3d1"
        "uCfgsg3zd++4DZjQ5SbP6CZDUNKM0k0U/Toko3n6AIN7xnMWoXsMP4ffO/np7D9LHUJRpsTpqExo"
        "sxMMCLAd7I2FH/ZGr8r3Huw1ZH1NcNyV56RIlutNtMZ4NusoonmcZ49SXeiID8o3SQoUrxyGLKDk"
        "57mcRpE+kARd0ihdrfI8iterOMsozt1vTCP+c2lgHZJVmq3yJEmydJWkD6exDXQ20Ks3z9BOLoZS"
        "WxtWSiNDf52Y19g/Vn5rB6l20KsbZOWWEknxTuCtgjJMTCNvduLsW8tIOLBO38dsxJyDydzp1UZw"
        "gAH3PrvwhOQHbZyXZRDQRfeDDIX+lCzPn2BzXjZD109xlxJX9X1kVYEWyAK4qXBEHb6hSlw6fS4W"
        "9hbcEYsu6qpNpTqiFvrEt5Gym/bmS1sRjBYz5yMXFY69LFvee0OuBTcGczh0pra47aZLYKSD3nd8"
        "J5X05zkPdVUZO7yRDlHNLJ3hkM9ZXO/t0QHiXz4HQt3LZj3PqFQcybV77+vbdg4h1k7oxH6CxMPL"
        "7G9L/D9aYjvUquT4V3QcciHEEBTSi++EFjzHt2bB5jmXa6PPL6Z2PW6dvHvquBj/Dwk3thH8C0HL"
        "FYY="
    ),
    "health": (
        "eJztV11v6ygQ/S9+3TbCsfPl37FvVxEiZpKgErAAp82t9r/vYHBMUkdJtnvvy6760Ho8wJkzx2fo"
        "Z9Y2nDnglLmsyqZkOn8li9d8+ee0qEheFeQPQipCspcMGmE1B2od5tus+vGZKf8sOC7cMykx56dW"
        "MDw1Rm+FBKrYwUedYcoKJ7SiW2YdJjApmB02/JFthGLmRC0oq80kbqNVtl6/ZDtQYJhfnlX5AOd8"
        "fJVXV/A98DN8f0qLp2QcdoZx4CFmbtV+sVgiXgpHUO5+LuNHpupHGK0lMENTEKqVso9zYFwKz2eI"
        "7rXktFVOyDEA+WwAYC2YjmZnWsR9Y02egsbeHMFYJukRm3I+J5zcM3ajomSbkNk1iRpg1vcqxSMO"
        "oFt3Lh0OwmHpWbVl0gKWCEy6PX1nRgm1yyrEj9Eaz0ZCh3CX/ddLqj+j9WHQX3y60h8SfaKNMPeF"
        "F9e36k3p96/qI5fqCySd9bVhFrq+XeorZF0JKQR/h2LiSePSCC8f10Aaumx2Cuded2P4RnuR8w3y"
        "CNvUcJ70F6l3VHOOa1+nE1IU+ayYzRb5siiWZRGb8bD/1Vo5+HCJg9BAZ2clgz7os87U7/L0QvyU"
        "kDROz8hi28e/IkwyYtN6iIHMu072JpRHInWNmmi05/YIAxN0A1ttPPNdv7GAd+H2CIpGYEkq2zow"
        "Zy/oGOubg7KVjmVVMVnOyWK6WuQ5KclsNSufNXlvCXctKhYFkjUWIXOo2WmspgTpE0WgzspyNidl"
        "MZ+XxSpf/MoaYqOTgfZMFWMqvi6HTMi/V0DxfBPGMP6TOl7JZEaKZbFaTadz/P7nq/nTda19ZY8O"
        "mAvnWZVlWSxXi1WOoijJN5zn9od2w39S279ymPDqQQ/pvfrKRNbepoe54fQbhDimtsb4MdfF8MAY"
        "Zi0iN+JngNpa6NM1jptg9Vn1mcFHA7VH3MW7C9/o6EyCQ029VdFkIgxLxt5ejDoLCLjfM8Ljgu2U"
        "tk7UPkBe4g9qAveToj59Y0qxuvPVnuNYEpPtY+poQHHsEY5gFIfF+7nAadrXYmBrwHqP4G0TSmn2"
        "mIV74o2njobe/RE6gmixcpZs0aDgRB2U9YHqBpuSOby0ujU4xr9KLMnB3TdsI6Rwp7Ed2qbRZrgW"
        "DahGJD28ZGMrLi8kyQvkv37zct+K7t4xktIwlH68W/ayHWOIBhv7sv4LE+FTecI+/pfEf0MS66FX"
        "NcPfPHrI2RA9KLQXF4MGHMMLPqfjnsuUVqeDbm3PW4zHp+jF+L+OPzEg+BtI2WLL"
    ),
    "reselected": (
        "eJztV9tyGjEM/Zd9LWF2uSTpfkffOoxH2AI8cewdX0hoJv9eedcLBjaB0D70oQMDrCzLR9KRLN6K"
        "0AjwKBj4oi4m5eT+rny4qx5/TKZ1WdL7W/tZjApspDMCmfOk74r651uh47MUtFFqjxa4l0aT6i+j"
        "kYTWmGd6aqxZSYVMw3OU0v4dayw61BxpGZQEd7D6s8Ataj+Om5njqJGVZUV6QT9p86KLxWhQZZKr"
        "LEbFmsQWWkB1dUB/irau6s+cjrACwSLTsAWpYKmwE9urgqbAedaivawLYgsUkiuscoVgWQ5CB6V6"
        "uUAQSsYMdNKNUYIF7aUaNDs/AHAObQwK8zYQ7uE90yMo3sIWrQPFtpTI/TndyQLXFsQRxE7U5oVZ"
        "BBfTk4PHZ+nJqaJegXJI4BGU37AXsFrq9V7MySzF6kO5DXooPmm1zQoh1062QM41+I7gMG7InaIu"
        "M7mxFhXkCE+gHHn1PsqLJCP9n1XIUmqwO0brzthxMmIu8763eS3pO0KQr/8Zf5Hxp+dM8j3/TiF8"
        "HuVP6uOqjX+rbIjHS1QSV/lt86WaUWbNjBC0c1qOy0TLq+86buiGePXHJXCoLHZLVfWWbtpsgqdA"
        "CbYHloj+ASlIy8pliFi72F30+EnqCEcZTsRuTEz8Fg+RYEtcGRsD3bKTvHiRfkOoWEKWqcKKbtfj"
        "0PXZoEpVHop6Nr6nS33+cD+bVfez+ezhlkYVm+vX/DqeUs5cywB/wZfJ43g6m00eq+l0Tk49fp/f"
        "OG28LyLvD+3Fmyds00dSHqiAqKW2MjKbxBAoCVb+6lgZHPbqsQK72inqtwJfG+SReqkyq7M23dEp"
        "E0bknbAnw/CFObR6NAM4JMC9zQRPSFhr47zkUVCO0mvxHu0pyXc3l30MM/G2pnaOe39AhevKvkEt"
        "ul5EJHc06spoNTlicUXnbCjtIjQtshtnyiYslXSbq2bu10bSoSeK339U1QlzyOqGEEem8lS57Y+O"
        "GBQ0SgC0ztDsLEWKFgVOSN51tOyklNnDojPBUqvO/T3ToTOWsJRK+t2QhdA0xu5tZ9huDGJm4fKY"
        "cdDtb5nBhpDpEZv5U+y2qxSs2JPMVjpaBHUSXaAWnKa8SNmjP0OLDxLBPmlM2YazyLcV1OY7cZUD"
        "fYtULfvSj8ipkHwSWvRA85Fgw90FtNG7ZxNcn6ckT0+p69DUGU/cm6SptMv3/g43vOtTvAPz/htP"
        "Wrbn"
    ),
    "v3_pending": (
        "eJztWm1vozgQ/i98vW5kcEggv2O/rSJkwEl8pcDZJttu1f9+Y14CCQQb0jbR6bRSNzH2MC/PjJ9x"
        "/G4VeUwkjQMirY3lIGf1A61/2N5PB28Q2iD8l/qLrCeL5kxkMQ2EhPnC2vx6t1L1ncWwkMCEP1lK"
        "6485z3YsoUFKXtQQLHkLcsbhCUkYEa2MX1bIUsLfAkFTkfGFWpyl1nb7ZO1pSjmRDL5u7Pb11es2"
        "9qavq33SVckvhJooBOVgXjXGRwxtFydEyIAeaSr1c0l8JGlk4r4ooYQHXSXSIkma8ZiSOGHKf9Xo"
        "IUvioEglS4bE4o4CpYHgpEDyAvQeXmO7XaUlJ0fKBUmCI4Tj6nvs7ntiuuckPtO8GiojFHBKhApU"
        "1yb6wqRy/WZHEkHBJkoSeQh+E56ydH8ajkAsuPBi/OOpC6+whVd4C7xCM3iFg/ByboGXMwFezr3h"
        "5cyAlzMDXs6DwCtq4RXdAq/IDF7RILzwLfDCE+CF7w0vPANeeAa88IPAC7y2p7LF2On7bKCdJBig"
        "rZo7CDl0C+TQBMihe0MOzYAcmgE5dD/IAQxCmjC66zI0I06WZPsgi2NYgRa+i/DSc33fX3qOb6/r"
        "6BqzxChLJX2V50hq4RlMonGNiGmrskKCa+LgpMq7JbKCg8cmiTHdvD6uBwoU4CwslOFVOLR88pml"
        "SrckiwBseSaYZEfaujUI6S7j5T6lEAOe+c3kAQwOaqM7U8lOUn4ehybQkD2JJNYGLzzf9kAf37Nt"
        "tHJW7iSeraqclsLUFtGE5AL0jWlE3oYM6qg5wQK0QMheekvso5XrOivbd73PsgF/rw2O56vUA1tc"
        "Zzmt4fnYKjOMCHKb6/YCI8fxlsuV76/WCHvLL811HaceznXdKsNc14kxZRKfkOu9zHiUXB/30ZRc"
        "J5wz8ChssCRVVsE+94nJgl28Xi+xs/SRj1frz7LiW7PddjwPipWttlrbx9Ns6Cb7eLtynuy27bqr"
        "JfZc7LrY+dJk13U4w8muW9VL9pr63ZiRvcg/SkaO+2MKlu+ZkRorumg2aIzOuSq4D5iq7WEAtv+l"
        "iDbqooZhbbT0i7CNHhXbBk4ZAXiPMN+PXt5myDfz5FGOeZsl38yWbQz48tbYXTv++nIDNbFkqxrm"
        "trGX2TOtU6n82NBuXZd49ScQniVN6RotaNMa4iiiudGPGOYn++CD6FnVnR0rzxVgOmh7ZAJqC0mU"
        "7gQqUG2n8hCYty0tOtJUneUEzSYT/00idQiUk8qyfwq16aiRUjp/AcWF5DTdy8NZKWNpweRbwGmW"
        "Q/ltj0wU3DrRCDc6Hn/1F4NZ0dC2LJpomPcXzk3ReAIT7xORaKPjbFcP2WdFRMsrNRHBxhHBYxE5"
        "Oe96PMCN4zH5nHDAK6KCcyWiCUuphD5VdKEDyaQABsDZn4oOFYLOqI9VKZ7WjTdno13kB1UYSAQ+"
        "46XjG+30+Te5jAwprYPeSekOXmqI6DVt2bCKN6CyOsNVxxn0NaeRgnQ5Xh7vX5y3V0yxM6j0rQYb"
        "ntch/p0lQ0/rjKgmCAo+a2Sq4IN6MSP7NBOSRWoAPdX/gMaDvIRFb5OPn0lUUtEG77UhJCnMaDxk"
        "RAzcGJIDiKuggWBlklYWcLrjVByAPMRFXhmQH2AWyGRp/eJagwrlbcKevARwY1HVEbyCxlR0Xdg+"
        "HDh36s0B6SEJWQLJPCShyPOMn2R3tOoL7TwkQyvOf1/oPOiXs96Uy5K2veKhuqT11vc8UQoxPqJs"
        "8CB58dVweJ+24edFmDBxMNnxu1BpJ/o/bfviMKcFpA6OFj3WIXs8UBpwpTO8jt966MNYsxWMwfuC"
        "P43gvKVSY3DvsSod8jWs3vw4736Jodv8tImBTRMD/9cSQ09ZdYkxOHeMboxmw5WZ4zTWKB9MUmG8"
        "TEw8C7wTcajX/c8bvok3bNtQRQT+jwfun864YjP9jDYC5xhdiBmucQOXROZcLAG4shMW7AVS/oGm"
        "MQP37OCvrFxTfjRt0s9aR4PG8GqdUN7vj17UAK14419jT92SgiX0HrXtdfs2gI76ySVIhvo902tT"
        "k27lGdem9npT3/6zm4Jt3CfEr3c3SXmSU0mYOlwYOBTdfvwLSrZXqQ=="
    ),
    "v3_degraded": (
        "eJztWttyozgQ/RdeN5OSEFd/x7xNuSgZZEc7BFghPMmk8u/b4mKwwUjYiZ2a3UqVYwtJ9Ok+3XS3"
        "eLOqIqGSJRGV1sqyke19Q/43HHy3yQrhFSJ/IbRCyHqwWMHLPGFRKWF+aa1+vFmZ+s0TWEhhwu88"
        "Y+3XQuRbnrIoo89qCJa8RgUXcIWmnJb9Hj+sDc+oeI1KlpW5eFSL88xarx+sHcuYoJLDzxXub9/c"
        "boVXJ7KClPggq9q/KtXEsmQC4DVj4hzQo8UpLWXE9iyT+rk02dMsNlFfnDIqoqEQWZWm3XjCaJJy"
        "pb9m9ClPk6jKJE+nBCADAWqAoKRIigrknl6D3aHQUtA9EyVNoz2Y4+x98PA+CdsJmhxJ3gzVFooE"
        "o6Uy1BATe+ZSqX61pWnJABOjqXyKflGR8Wx3GI5hW1Dhyfj7w5Bem55em2votTGj12aSXvY19LIX"
        "0Mu+N73sC+hlX0Av+4vQK+7pFV9Dr9iMXvEkvcg19CIL6EXuTS9yAb3IBfQiX4ReoLUdkz3HDr8v"
        "JtphBwO2NXMnKYfGlOs0paccWkA5dG/KoQsoh3SUGxLJBNEU5aw4h92iOM+2KY+lZUo/EP48+4AR"
        "G5Zyth0ma0bpWZrvojxJYAV+RMTzHDsMQuKGDvHC1tDGCSNgkuxFHsexnqnRooyu22LZqrySoJok"
        "OojyZpV5JUBji7YxfY69nw8TIIDgm0oBb8yhTS1/8kzJluYx8K7ISy75nvVqjTZsm4v6kaUIA5r5"
        "xeUTAI5a0IOpdCuZOLZDZ2hwpFRSa0UegxAHIE8YYIw823MXpdwq4GmzmRYRS2lRgrwJi+nrFKCB"
        "mAsQoEeEsBM4JESe69oeDt3gozCQ22KwgxARJwAsru0sq33OgcA3BRF4NoSMIHQwxo5rL0OwVhiM"
        "sv1htCKeH5LA8eGunhc4nxqsdPXBdLDSrTIMVrptTLOiDwhWI9f+KsFqXkdLghUVgoNGIVmgmUIF"
        "z+wPdBTiEt93iO2EKAQCfxSKm4YrbAcBRFsMAcvFIfkQDLeNVp7ruQ5CJLRDz3G9ZQiG0Wq+eDyO"
        "Vl7g+xjiFfZD3/3UaKUrN6ejlW7VKFq1efiVIWVk9q8SUub1scQZ7xlSLkNxa3f0bQwOGXiOY+Pg"
        "NKJoIAz90aDQPi54AkR8j9ghcmzXJZd7ZV8T6t3TqD6f9lGjpYaO2haUpn6KvqqfGuhkxllH5df9"
        "ipXrgNy46pqtWK5DcuPaCxPgV+ATCEKhfxp7rkBy8wIM+Z4DHhJ4yCPO5+JoY8mgd7gEyVSwnIB0"
        "AYS16oT1zTuZ/2RtVKu/dtWorv1z9phT5Gn3OJl9yCzrdMUxK4wOKs1P70AH8c+6ycjrhiFMB2n3"
        "vIQwT1MlOwX7tTiVhgDeuka0Z5nq10Zd7pL8TWPV6C1og+yfSuUyrG1hcvEMgpdSsGwnn46yP55V"
        "XL5GguUFPAj7hq7i2cAam5Wuvj17KniRNbSlvMYa5nW3fZU1HgDifSwSr3SlwNmDtIssoi1XNBYh"
        "xhYhcxY5KO+8PUCN8zb5GHPALeJKCLVFZ5ZGCG3g0juTzrhwb1pBuib47yZ1rUp2QQRtgvWyPtbh"
        "hGTgG1FjKBqDVkVtmk46vYcuDjRTQuvIeRB6wKiWRHpJ+xrmoT0Wqo9vVCOQvRQsVqSvx+tDvpNT"
        "tyarHwwqeZvBLikfVJyDJVNXjw64SgY66/ZUxgfxEk53WV5KHqsB9ND+QfEF+6U8fl188kTjum7o"
        "PKIFQtPKrPYCn0mgjgH3gSqjZFHJazduEAi2FaxUCUpSFQ2A4glmwZ48a2/cStCwvHfpg5aAbjxu"
        "qrcXkJiVQxX2Fyc6tqM5sPuGbngK7j61Q1UUuTjsPZBqvOngIp1acXywPbgwDnijKadBb31GQ23Q"
        "G60faaLexLi33/GhqUs/lQ5vy1KCotqkvHwyyQmGVOknht8xPmki9oTU0dFi+9ZkX4+UBtnUEV/n"
        "330a01jzKJij90mGNcPzPtmao/so79IxX5P3m7eR7+cYuoef1jGIqWOQP80x9EmtzjEm586lG7Pe"
        "cGbmfKJr5A8mrjAfJhZ2cP9PHP4bicO6t1VM4X/S5pdr9aaayGF4C5+ySTnrr6b161FVZVARnXUQ"
        "Rdrx6An5tdsbH+AfyoTu7bG2Mmvqlon3D9srp741VeiYvjW46KVUY6fs3+6bnTa0+wL7mb6xpxQs"
        "mKRcleMTbcT1+79IXj8F"
    ),
}


def historical_payload(kind: str) -> dict[str, Any]:
    snapshot = json.loads(zlib.decompress(base64.b64decode(HISTORICAL_SNAPSHOTS[kind])))
    fingerprint = (
        "a7deefdcd68f8ba1a9b037f9a492b37af42228a3342be289d6d52de6aa8c4d7a"
        if kind.startswith("v3_")
        else "ccbc9c06b2ab3294860b44e03717cd2abe5de76bace9328887b89bc3ed7f233e"
        if kind == "reselected"
        else "f5143467f623123cb6c71d8912a0f1e05b2330484cfb0ec8e9a58ae4eb6357a8"
    )
    return {
        "schema": "zone-belief-v3" if kind.startswith("v3_") else "zone-belief-v4",
        "map_fingerprint": fingerprint,
        "snapshot": snapshot,
        "audit": [],
    }


def historical_map(kind: str) -> PredictiveMap:
    if kind == "reselected":
        nodes: dict[str, Any] = {
            "presence": {
                "zone": "room", "role": "room_occupancy",
                "occupancy_behavior": "sticky",
                "entities": {"mmwave": "binary_sensor.room"},
            },
            "interaction": {
                "zone": "room", "role": "room_occupancy",
                "occupancy_behavior": "sticky",
                "entities": {
                    "interaction_scene_001": "event.room_scene_001",
                    "interaction_scene_002": "event.room_scene_002",
                },
            },
        }
    elif kind.startswith("v3_"):
        adjacency = {"a": ["b"], "b": ["a", "c"], "c": ["b"], "target": []}
        nodes = {
            node: {
                "role": "room_occupancy",
                "entities": {"motion": f"binary_sensor.{node}"},
                "adjacent": neighbors,
            }
            for node, neighbors in adjacency.items()
        }
    else:
        nodes = {
            node: {"role": role, "entities": {"motion": f"binary_sensor.{node}"}}
            for node, role in (("hall", "transition_gate"), ("room", "room_occupancy"))
        }
    return PredictiveMap.from_mapping({"nodes": nodes})


def assert_historical_rejected(kind: str, *, relabel: bool = False) -> None:
    predictive_map = historical_map(kind)
    payload = historical_payload(kind)
    if relabel:
        payload["map_fingerprint"] = target_map_fingerprint(predictive_map)
    before = deepcopy(payload)
    at = datetime.fromisoformat(payload["snapshot"]["updated_at"])
    with pytest.raises(ValueError, match="schema|map fingerprint"):
        restore_target_state(predictive_map, payload, at)
    assert payload == before


def entry_map() -> PredictiveMap:
    return PredictiveMap.from_mapping(
        {
            "nodes": {
                "entry": {
                    "role": "entry_boundary",
                    "occupancy_behavior": "sustained",
                    "entities": {"motion": "binary_sensor.entry"},
                }
            }
        }
    )


def occupied_engine() -> ZoneModelEngine:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    engine.observe(SensorInput("binary_sensor.room", "on", NOW + timedelta(seconds=2)))
    return engine


def as_pre_feature_v4(
    predictive_map: PredictiveMap,
    payload: dict[str, object],
) -> dict[str, object]:
    """Malformed-shape mutator only; not evidence of a historical writer."""
    legacy = deepcopy(payload)
    legacy["map_fingerprint"] = pre_feature_target_map_fingerprint(predictive_map)
    snapshot = legacy["snapshot"]
    assert isinstance(snapshot, dict)
    snapshot.pop("reliability_warning_occurrences")
    episodes = snapshot["episode_states"]
    assert isinstance(episodes, list)
    for episode in episodes:
        assert isinstance(episode, dict)
        for key in (
            "cadence_run_started_at",
            "cadence_last_transition_at",
            "cadence_cycle_count",
            "cadence_correlated",
            "cadence_warning_reason",
        ):
            episode.pop(key)
    return legacy


def predicted_payload() -> tuple[PredictiveMap, dict[str, object]]:
    predictive_map = prediction_map()
    engine = ZoneModelEngine(predictive_map, 1, PREDICTION_NOW)
    seed_mature_route(engine.prediction_manager)
    engine.observe(SensorInput("binary_sensor.office", "on", PREDICTION_NOW))
    engine.observe(
        SensorInput(
            "binary_sensor.hall",
            "on",
            PREDICTION_NOW + timedelta(seconds=1),
        )
    )
    engine.observe(
        SensorInput(
            "binary_sensor.kitchen",
            "on",
            PREDICTION_NOW + timedelta(seconds=2),
        )
    )
    return predictive_map, serialize_target_state(predictive_map, engine)


def engine_at_restart_frontier(frontier: str) -> ZoneModelEngine:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    if frontier == "traversal":
        return engine
    engine.observe(SensorInput("binary_sensor.room", "on", NOW + timedelta(seconds=2)))
    if frontier == "assertion":
        return engine
    engine.observe(SensorInput("binary_sensor.room", "off", NOW + timedelta(seconds=3)))
    if frontier == "clear":
        return engine
    engine.advance(NOW + timedelta(seconds=8))
    if frontier == "decay":
        return engine
    engine.advance(NOW + timedelta(seconds=560))
    return engine


def test_target_state_round_trips_deterministically() -> None:
    engine = occupied_engine()
    payload = serialize_target_state(target_map(), engine)
    encoded = str(payload)
    assert "strong_front" not in encoded
    assert "stationary_anchor" not in encoded

    restored = restore_target_state(target_map(), payload, engine.snapshot.updated_at)

    assert restored.snapshot == engine.snapshot
    assert restored.audit_rows == engine.audit_rows
    assert serialize_target_state(target_map(), restored) == payload


def test_handoff_fingerprint_discriminator_and_historical_recipes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    predictive_map = historical_map("warning")
    current = _target_map_fingerprint_payload(predictive_map)
    assert type(current["settled_adjacent_transfer_version"]) is int
    assert current["settled_adjacent_transfer_version"] == 1
    old = deepcopy(current)
    old.pop("settled_adjacent_transfer_version")
    old_fingerprint = hashlib.sha256(
        json.dumps(old, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert old_fingerprint == (
        "e5741a7c71744863ca85bbafa3576ce102e71da1ef01c3f7017f67f508bd561c"
    )
    assert pre_feature_target_map_fingerprint(predictive_map) == (
        "1b0494301c398bfa60bad3c5d7648950aef79964f99b6c77b4e09bd09627a39d"
    )
    historical = _target_map_fingerprint_payload(predictive_map, pre_feature=True)
    assert "settled_adjacent_transfer_version" not in historical
    profiles = historical["profiles"]
    assert isinstance(profiles, dict)
    assert all(
        "cycle_correlation_window" not in profile for profile in profiles.values()
    )

    # Actual archived writers used 120s; pin their hash under that historical
    # calibration as well, without importing their inference into the engine.
    module = import_module(
        "custom_components.predictive_controls.zone_model.persistence"
    )
    old_profiles = dict(module.SHARED_PROFILES)
    old_profiles["stay_presence"] = replace(
        old_profiles["stay_presence"], traversal_context_window=timedelta(seconds=120)
    )
    with monkeypatch.context() as patch:
        patch.setattr(module, "SHARED_PROFILES", old_profiles)
        for kind in ("warning", "v3_pending"):
            assert pre_feature_target_map_fingerprint(historical_map(kind)) == (
                historical_payload(kind)["map_fingerprint"]
            )

    # Known old-reader fingerprint comparison rejects a new snapshot even before
    # any handoff. The new reader rejects both genuine historical boundaries
    # before attempting nested decoding; deliberately poison that decoder.
    engine = ZoneModelEngine(predictive_map, 1, NOW)
    payload = serialize_target_state(predictive_map, engine)
    assert payload["map_fingerprint"] != old_fingerprint
    assert "settled_adjacent_transfer_version" not in payload
    assert engine.snapshot.anonymous_supports == ()

    def unexpected_decode(*args: object, **kwargs: object) -> None:
        pytest.fail("Incompatible fingerprints must reject before decoding")

    monkeypatch.setattr(module, "_decode_snapshot", unexpected_decode)
    for fingerprint in (
        old_fingerprint, pre_feature_target_map_fingerprint(predictive_map)
    ):
        incompatible = deepcopy(payload)
        incompatible["map_fingerprint"] = fingerprint
        with pytest.raises(ValueError, match="map fingerprint"):
            restore_target_state(predictive_map, incompatible, NOW)


def handoff_validation_payload() -> tuple[PredictiveMap, dict[str, Any]]:
    """Synthetic structural specimen, not a claim of observed handoff selection.

    An authentic a-b-source creation is retained. Its independently accepted
    target transfer is projected into the new pair representation. Live writer
    and long-age selection are tested separately; no historical fixture uses this.
    """
    adjacency = {
        "a": ["b"], "b": ["a", "source"],
        "source": ["b", "target"], "target": ["source", "c"],
        "c": ["target", "d"], "d": ["c"],
    }
    predictive_map = PredictiveMap.from_mapping({
        "nodes": {
            node: {
                "role": "room_occupancy",
                "entities": {"mmwave": f"binary_sensor.{node}"},
                "adjacent": neighbors,
            }
            for node, neighbors in adjacency.items()
        }
    })
    engine = ZoneModelEngine(predictive_map, 1, NOW)
    for seconds, node in enumerate(("a", "b", "source", "target")):
        engine.observe(SensorInput(
            f"binary_sensor.{node}", "on", NOW + timedelta(seconds=seconds)
        ))
    payload: dict[str, Any] = dict(serialize_target_state(predictive_map, engine))
    snapshot = payload["snapshot"]
    source = next(s for s in snapshot["episode_states"] if s["node_id"] == "source")
    token = next(t for t in snapshot["traversal_tokens"] if t["node_id"] == "target")
    token.update(
        path_node_ids=["source", "target"], track_confidence="provisional",
        equivalent_confirmed_strength=True, provenance_kind="settled_adjacent_transfer",
    )
    support = snapshot["anonymous_supports"][0]
    support.update(
        path_node_ids=["source", "target"], provenance_kind="settled_adjacent_transfer"
    )
    snapshot["support_token_bindings"] = [{
        "token_id": token["token_id"], "support_id": support["support_id"],
    }]
    snapshot["authorization_uses"] = [
        use for use in snapshot["authorization_uses"]
        if use["target_episode_id"] != token["episode_id"]
    ]
    policy = next(p for p in snapshot["policy_states"] if p["zone"] == "target")
    policy.update(
        activation_reason="settled_adjacent_transfer",
        activation_provenance_kind="settled_adjacent_transfer",
        activation_track_confidence="provisional",
        activation_path_node_ids=["source", "target"],
        activation_source_episode_ids=[source["episode_id"]],
    )
    row = next(
        row for row in payload["audit"]
        if row["zone"] == "target" and row["event_kind"] == "acquired"
    )
    row.update(
        traversal_reason="settled_adjacent_transfer",
        evidence_ids=[token["episode_id"], source["episode_id"]],
    )
    payload["audit"] = [row]
    # The provisional projection cannot retain the ordinary confirmed target's
    # diagnostic prediction leases. Route statistics are independent history.
    payload["prediction"]["leases"] = []
    return predictive_map, payload


def test_handoff_snapshot_round_trips_without_audit_or_source_binding() -> None:
    predictive_map, payload = handoff_validation_payload()
    payload["audit"] = []
    at = NOW + timedelta(seconds=3)
    restored = restore_target_state(predictive_map, payload, at)
    assert serialize_target_state(predictive_map, restored) == payload
    for frontier in (NOW + timedelta(seconds=183), NOW + timedelta(seconds=1803)):
        restored.advance(frontier, emit_events=False)
        state = serialize_target_state(predictive_map, restored)
        replayed = restore_target_state(predictive_map, state, frontier)
        assert serialize_target_state(predictive_map, replayed) == state
        assert replayed.snapshot.anonymous_supports[0].provenance_kind == (
            "settled_adjacent_transfer"
        )


@pytest.mark.parametrize("offset", (-1, 0, 1))
def test_moving_handoff_restore_preserves_exact_target_deadline(offset: int) -> None:
    predictive_map, payload = handoff_validation_payload()
    snapshot = payload["snapshot"]
    token = next(t for t in snapshot["traversal_tokens"] if t["node_id"] == "target")
    support = snapshot["anonymous_supports"][0]
    support.update(state="moving", valid_until=token["valid_until"])
    deadline = datetime.fromisoformat(token["valid_until"])
    at = deadline + timedelta(microseconds=offset)
    uninterrupted = restore_target_state(
        predictive_map, payload, NOW + timedelta(seconds=3)
    )
    uninterrupted.advance(at, emit_events=False)
    restored = restore_target_state(predictive_map, payload, at)
    assert serialize_target_state(predictive_map, restored) == (
        serialize_target_state(predictive_map, uninterrupted)
    )
    assert bool(restored.snapshot.anonymous_supports) is (offset < 0)
    if offset < 0:
        assert restored.snapshot.anonymous_supports[0].valid_until == deadline


def test_forged_support_update_cannot_hide_current_binding_provenance() -> None:
    predictive_map, payload = handoff_validation_payload()
    engine = restore_target_state(predictive_map, payload, NOW + timedelta(seconds=3))
    engine.advance(NOW + timedelta(seconds=4), emit_events=False)
    invalid: dict[str, Any] = dict(serialize_target_state(predictive_map, engine))
    support = invalid["snapshot"]["anonymous_supports"][0]
    support.update(
        updated_at=(NOW + timedelta(seconds=4)).isoformat(),
        provenance_kind="adjacent",
    )
    with pytest.raises(ValueError, match="target binding"):
        restore_target_state(predictive_map, invalid, NOW + timedelta(seconds=4))


@pytest.mark.parametrize("mutation", (
    "no_source", "self_source", "multiple_sources", "wrong_pair_source",
    "confirmed_policy", "policy_two_hop", "token_two_hop", "token_confirmed",
    "token_not_equivalent", "support_two_hop", "support_one_node",
    "origin_node", "origin_precreation", "origin_handoff", "binding_path",
))
def test_handoff_restore_rejects_malformed_cross_component_state(mutation: str) -> None:
    predictive_map, payload = handoff_validation_payload()
    snapshot = payload["snapshot"]
    policy = next(p for p in snapshot["policy_states"] if p["zone"] == "target")
    token = next(t for t in snapshot["traversal_tokens"] if t["node_id"] == "target")
    support = snapshot["anonymous_supports"][0]
    if mutation == "no_source":
        policy["activation_source_episode_ids"] = []
    elif mutation == "self_source":
        policy["activation_source_episode_ids"] = [token["episode_id"]]
    elif mutation in {"multiple_sources", "wrong_pair_source"}:
        other = next(e for e in snapshot["episode_states"] if e["node_id"] == "b")
        policy["activation_source_episode_ids"] = [other["episode_id"]] + (
            policy["activation_source_episode_ids"]
            if mutation == "multiple_sources" else []
        )
    elif mutation == "confirmed_policy":
        policy["activation_track_confidence"] = "confirmed"
    elif mutation == "policy_two_hop":
        policy["activation_path_node_ids"] = ["b", "target"]
    elif mutation == "token_two_hop":
        token["path_node_ids"] = ["b", "target"]
    elif mutation == "token_confirmed":
        token["track_confidence"] = "confirmed"
    elif mutation == "token_not_equivalent":
        token["equivalent_confirmed_strength"] = False
    elif mutation == "support_two_hop":
        support["path_node_ids"] = ["b", "target"]
    elif mutation == "support_one_node":
        support["path_node_ids"] = ["target"]
    elif mutation == "origin_node":
        support["support_id"] = "support:missing:" + token["episode_id"]
        snapshot["support_token_bindings"][0]["support_id"] = support["support_id"]
    elif mutation == "origin_precreation":
        support["created_at"] = (NOW + timedelta(seconds=2, microseconds=1)).isoformat()
    elif mutation == "origin_handoff":
        support["support_id"] = "support:" + token["token_id"]
        support["created_at"] = token["accepted_at"]
        snapshot["support_token_bindings"][0]["support_id"] = support["support_id"]
    else:
        token["provenance_kind"] = "adjacent"
        token["equivalent_confirmed_strength"] = False
    before = deepcopy(payload)
    with pytest.raises(ValueError):
        restore_target_state(predictive_map, payload, NOW + timedelta(seconds=3))
    assert payload == before


@pytest.mark.parametrize("provenance", ("settled_endpoint", "adjacent"))
def test_transferred_support_accepts_endpoint_derivative_and_later_adjacent_pair(
    provenance: str,
) -> None:
    predictive_map, payload = handoff_validation_payload()
    snapshot = payload["snapshot"]
    token = next(t for t in snapshot["traversal_tokens"] if t["node_id"] == "target")
    token["provenance_kind"] = provenance
    token["equivalent_confirmed_strength"] = False
    if provenance == "settled_endpoint":
        token["path_node_ids"] = ["target"]
        policy = next(p for p in snapshot["policy_states"] if p["zone"] == "target")
        policy.update(
            activation_reason="settled_endpoint_reacquired",
            activation_provenance_kind="settled_endpoint",
            activation_path_node_ids=["target"],
            activation_source_episode_ids=[],
        )
        payload["audit"] = []
    else:
        snapshot["anonymous_supports"][0]["provenance_kind"] = "adjacent"
    restored = restore_target_state(predictive_map, payload, NOW + timedelta(seconds=3))
    assert serialize_target_state(predictive_map, restored) == payload
    assert restored.snapshot.traversal_tokens[-1].track_confidence == "provisional"


@pytest.mark.parametrize("recover_source", (False, True))
def test_handoff_policy_and_audit_source_references_are_historical(
    recover_source: bool,
) -> None:
    predictive_map, payload = handoff_validation_payload()
    engine = restore_target_state(predictive_map, payload, NOW + timedelta(seconds=3))
    engine.observe(SensorInput(
        "binary_sensor.source", "unavailable", NOW + timedelta(seconds=4)
    ))
    if recover_source:
        engine.observe(SensorInput(
            "binary_sensor.source", "on", NOW + timedelta(seconds=35)
        ))
    state = serialize_target_state(predictive_map, engine)
    restored = restore_target_state(predictive_map, state, engine.snapshot.updated_at)
    assert serialize_target_state(predictive_map, restored) == state
    historical_policy = next(
        policy for policy in restored.snapshot.policy_states if policy.zone == "target"
    )
    assert historical_policy.activation_source_episode_ids == (
        f"source:1:{(NOW + timedelta(seconds=2)).isoformat()}",
    )
    if recover_source:
        invalid: dict[str, Any] = dict(state)
        invalid = deepcopy(invalid)
        snapshot = invalid["snapshot"]
        source = next(e for e in snapshot["episode_states"] if e["node_id"] == "source")
        policy = next(p for p in snapshot["policy_states"] if p["zone"] == "target")
        policy["activation_source_episode_ids"] = [source["episode_id"]]
        with pytest.raises(ValueError, match="acquisition episode"):
            restore_target_state(predictive_map, invalid, engine.snapshot.updated_at)


@pytest.mark.parametrize("mutation", (
    "missing_source", "wrong_source", "unknown_source", "future_event",
    "wrong_target", "repeat_evidence", "untrusted", "unauthorized", "wrong_kind",
))
def test_handoff_audit_rejects_malformed_historical_proof(mutation: str) -> None:
    predictive_map, payload = handoff_validation_payload()
    row = payload["audit"][0]
    if mutation == "missing_source":
        row["evidence_ids"] = [row["episode_id"]]
    elif mutation == "wrong_source":
        row["evidence_ids"][1] = f"a:1:{NOW.isoformat()}"
    elif mutation == "unknown_source":
        row["evidence_ids"][1] = "missing:1:" + NOW.isoformat()
    elif mutation == "future_event":
        row["event_at"] = (NOW + timedelta(seconds=2)).isoformat()
    elif mutation == "wrong_target":
        row["node_id"] = "source"
    elif mutation == "repeat_evidence":
        row["evidence_ids"][1] = row["episode_id"]
    elif mutation == "untrusted":
        row["local_trustworthy"] = False
    elif mutation == "unauthorized":
        row["authorization_authorized"] = False
    else:
        row["local_evidence_kind"] = "stable_clear"
    with pytest.raises(ValueError):
        restore_target_state(predictive_map, payload, NOW + timedelta(seconds=3))


@pytest.mark.parametrize("retain_origin", (False, True))
@pytest.mark.parametrize(
    "mutation", ("origin_precreation", "origin_identity", "interaction"),
)
def test_transferred_support_origin_and_endpoint_validation_survive_eviction(
    retain_origin: bool,
    mutation: str,
) -> None:
    predictive_map, payload = handoff_validation_payload()
    engine = restore_target_state(predictive_map, payload, NOW + timedelta(seconds=3))
    at = NOW + timedelta(seconds=184 if retain_origin else 1804)
    engine.advance(at, emit_events=False)
    invalid: dict[str, Any] = dict(serialize_target_state(predictive_map, engine))
    snapshot = invalid["snapshot"]
    support = snapshot["anonymous_supports"][0]
    origins = snapshot["retained_traversal_tokens"]
    assert any(
        t["token_id"] == support["support_id"][8:] for t in origins
    ) is retain_origin
    # Forging updated_at cannot hide either current interaction misuse or origin
    # identity/time corruption, even once the complete creation route is evicted.
    support["updated_at"] = at.isoformat()
    if mutation == "origin_precreation":
        support["created_at"] = (NOW + timedelta(seconds=2, microseconds=1)).isoformat()
    elif mutation == "origin_identity":
        support["support_id"] = "support:target:" + support["support_id"].removeprefix(
            "support:source:"
        )
    else:
        support["provenance_kind"] = "local_interaction"
    with pytest.raises(ValueError):
        restore_target_state(predictive_map, invalid, at)


@pytest.mark.parametrize("path", (["source", "target"], ["target"]))
def test_provisional_endpoint_cannot_claim_confirmed_or_equivalent_strength(
    path: list[str],
) -> None:
    predictive_map, payload = handoff_validation_payload()
    token = next(
        t for t in payload["snapshot"]["traversal_tokens"] if t["node_id"] == "target"
    )
    token.update(provenance_kind="settled_endpoint", path_node_ids=path)
    with pytest.raises(ValueError):
        restore_target_state(predictive_map, payload, NOW + timedelta(seconds=3))


@pytest.mark.parametrize("retain_origin", (False, True))
def test_interaction_support_provenance_cannot_hide_behind_forged_update(
    retain_origin: bool,
) -> None:
    predictive_map = interaction_map()
    engine = ZoneModelEngine(predictive_map, 1, NOW)
    engine.observe(SensorInput("event.room_scene_001", "pressed", NOW))
    engine.advance(NOW + timedelta(seconds=1))
    payload: dict[str, Any] = dict(serialize_target_state(predictive_map, engine))
    snapshot = payload["snapshot"]
    support = snapshot["anonymous_supports"][0]
    support["updated_at"] = snapshot["updated_at"]
    support["provenance_kind"] = "adjacent"
    if not retain_origin:
        snapshot["traversal_tokens"] = []
        snapshot["retained_traversal_tokens"] = []
        snapshot["current_token_ids"] = []
        snapshot["support_token_bindings"] = []
    with pytest.raises(ValueError, match="[Ii]nteraction"):
        restore_target_state(predictive_map, payload, NOW + timedelta(seconds=1))


@pytest.mark.parametrize("retain_origin", (False, True))
def test_compacted_support_history_cannot_disprove_earlier_creation(
    retain_origin: bool,
) -> None:
    """Earlier inherited creation is not proof of corruption after compaction."""
    predictive_map, payload = handoff_validation_payload()
    engine = restore_target_state(predictive_map, payload, NOW + timedelta(seconds=3))
    at = NOW + timedelta(seconds=184 if retain_origin else 1804)
    engine.advance(at, emit_events=False)
    payload = dict(serialize_target_state(predictive_map, engine))
    support = payload["snapshot"]["anonymous_supports"][0]
    support["created_at"] = NOW.isoformat()
    assert any(
        t["token_id"] == support["support_id"].removeprefix("support:")
        for t in payload["snapshot"]["retained_traversal_tokens"]
    ) is retain_origin
    assert serialize_target_state(
        predictive_map, restore_target_state(predictive_map, payload, at),
    ) == payload


@pytest.mark.parametrize("mutation", ("precreation", "postmutation", "future"))
def test_support_origin_occurrence_outside_lifetime_rejects_atomically(
    mutation: str,
) -> None:
    predictive_map, payload = handoff_validation_payload()
    engine = restore_target_state(predictive_map, payload, NOW + timedelta(seconds=3))
    at = NOW + timedelta(seconds=4)
    # D is disconnected from the supported target without a current C episode.
    # This supplies an authentic later origin reference, but no creation token.
    engine.observe(SensorInput("binary_sensor.d", "on", at))
    payload = dict(serialize_target_state(predictive_map, engine))
    snapshot = payload["snapshot"]
    support = snapshot["anonymous_supports"][0]
    assert support["updated_at"] == (NOW + timedelta(seconds=3)).isoformat()
    old_id = support["support_id"]
    node, occurrence = (
        ("a", NOW) if mutation == "precreation" else
        ("d", at + timedelta(seconds=1) if mutation == "future" else at)
    )
    support["support_id"] = f"support:{node}:{node}:1:{occurrence.isoformat()}"
    for binding in snapshot["support_token_bindings"]:
        if binding["support_id"] == old_id:
            binding["support_id"] = support["support_id"]
    before = deepcopy(payload)
    with pytest.raises(ValueError, match=(
        "Episode reference is outside stored state" if mutation == "future"
        else "Anonymous-support origin identity/time is incompatible"
    )):
        restore_target_state(predictive_map, payload, at)
    assert payload == before


@pytest.mark.parametrize("snapshot, expected", (
    (None, False),
    ({"reliability_warning_occurrences": []}, False),
    ({}, False),
    ({"episode_states": {}}, False),
    ({"episode_states": []}, True),
    ({"episode_states": [{}]}, True),
    ({"episode_states": [None]}, False),
    *(
        ({"episode_states": [{key: None}]}, False)
        for key in (
            "cadence_run_started_at", "cadence_last_transition_at",
            "cadence_cycle_count", "cadence_correlated", "cadence_warning_reason",
        )
    ),
))
def test_isolated_historical_shape_detector_has_no_public_restore_authority(
    snapshot: object, expected: bool,
) -> None:
    assert _is_pre_feature_v4_snapshot(snapshot) is expected


def test_reselected_asserted_context_round_trips_v4() -> None:
    predictive_map = mixed_same_zone_map()
    engine = ZoneModelEngine(predictive_map, 1, NOW)
    engine.observe(SensorInput("binary_sensor.room", "on", NOW))
    engine.observe(SensorInput("event.room_scene_001", "pressed", NOW))
    engine.observe(SensorInput("event.room_scene_002", "unknown", NOW))
    payload = serialize_target_state(predictive_map, engine)
    restored = restore_target_state(predictive_map, payload, NOW)
    presence = next(
        state
        for state in restored.snapshot.episode_states
        if state.node_id == "room_presence"
    )
    belief = restored.snapshot.belief_states[0]

    assert presence.episode_id is not None
    assert belief.context == "asserted"
    assert belief.generation_episode_id == presence.episode_id
    assert belief.asserted_episode_id == presence.episode_id


def test_reliability_warning_occurrence_round_trips_and_clears_in_place() -> None:
    predictive_map = target_map()
    engine = ZoneModelEngine(predictive_map, 1, NOW)
    engine.observe(SensorInput("binary_sensor.room", "on", NOW))
    engine.observe(
        SensorInput("binary_sensor.room", "off", NOW + timedelta(seconds=10))
    )
    warned = engine.observe(
        SensorInput("binary_sensor.room", "on", NOW + timedelta(seconds=12))
    )

    assert len(warned.snapshot.reliability_warning_occurrences) == 1
    occurrence = warned.snapshot.reliability_warning_occurrences[0]
    assert occurrence.node_id == "room"
    assert occurrence.kind == "flapping"
    assert occurrence.reason == "impossible_cadence"
    assert occurrence.first_observed_at == NOW + timedelta(seconds=12)
    assert occurrence.last_observed_at == NOW + timedelta(seconds=12)
    assert occurrence.cleared_at is None

    payload = serialize_target_state(predictive_map, engine)
    restored = restore_target_state(
        predictive_map,
        payload,
        NOW + timedelta(seconds=12),
    )
    assert restored.snapshot == engine.snapshot

    cleared = restored.observe(
        SensorInput(
            "binary_sensor.room",
            "unavailable",
            NOW + timedelta(seconds=13),
        )
    )
    assert len(cleared.snapshot.reliability_warning_occurrences) == 1
    occurrence = cleared.snapshot.reliability_warning_occurrences[0]
    assert occurrence.first_observed_at == NOW + timedelta(seconds=12)
    assert occurrence.last_observed_at == NOW + timedelta(seconds=13)
    assert occurrence.cleared_at == NOW + timedelta(seconds=13)


def test_pre_handoff_reselected_context_rejected_atomically() -> None:
    snapshot = _decode_snapshot(historical_payload("reselected")["snapshot"])
    belief = snapshot.belief_states[0]
    assert belief.context == "asserted"
    assert belief.generation_episode_id == belief.asserted_episode_id
    assert_historical_rejected("reselected")


def test_pre_handoff_warning_snapshot_rejected_atomically() -> None:
    assert_historical_rejected("warning")


def test_historical_warning_decoder_preserves_exact_timestamp_and_defaults() -> None:
    snapshot = _decode_snapshot(
        historical_payload("warning")["snapshot"], pre_feature_v4=True
    )
    room = next(
        state for state in snapshot.episode_states if state.node_id == "room"
    )
    occurrence = snapshot.reliability_warning_occurrences[0]
    assert room.cadence_warning_reason == "impossible_cadence"
    assert occurrence.reason == "impossible_cadence"
    assert occurrence.first_observed_at == room.last_event_at
    assert occurrence.last_observed_at == room.last_event_at
    assert occurrence.last_observed_at == NOW + timedelta(seconds=12)
    assert occurrence.cleared_at is None
    assert room.cadence_run_started_at is None
    assert room.cadence_last_transition_at is None
    assert room.cadence_cycle_count == 0
    assert not room.cadence_correlated


def test_pre_handoff_health_snapshot_rejected_atomically() -> None:
    assert_historical_rejected("health")


def test_historical_health_decoder_preserves_exact_timestamp() -> None:
    snapshot = _decode_snapshot(
        historical_payload("health")["snapshot"], pre_feature_v4=True
    )
    hall = next(state for state in snapshot.episode_states if state.node_id == "hall")
    occurrence = snapshot.reliability_warning_occurrences[0]
    assert occurrence.kind == "suspected_stuck"
    assert occurrence.reason == "assertion_timeout"
    assert occurrence.first_observed_at == hall.assertion_trust_until
    assert occurrence.last_observed_at == hall.degraded_at


def test_pre_feature_v4_rejects_mixed_episode_shape() -> None:
    predictive_map = target_map()
    legacy = as_pre_feature_v4(
        predictive_map,
        serialize_target_state(predictive_map, occupied_engine()),
    )
    snapshot = legacy["snapshot"]
    assert isinstance(snapshot, dict)
    episodes = snapshot["episode_states"]
    assert isinstance(episodes, list)
    first = episodes[0]
    assert isinstance(first, dict)
    first["cadence_cycle_count"] = 0

    with pytest.raises(ValueError, match="map fingerprint"):
        restore_target_state(predictive_map, legacy, NOW + timedelta(seconds=2))


def test_pre_feature_v4_rejects_current_snapshot_shape() -> None:
    predictive_map = target_map()
    payload = serialize_target_state(predictive_map, occupied_engine())
    payload["map_fingerprint"] = pre_feature_target_map_fingerprint(predictive_map)

    with pytest.raises(ValueError, match="map fingerprint"):
        restore_target_state(predictive_map, payload, NOW + timedelta(seconds=2))


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("cadence_timestamp", "cadence warning has no source timestamp"),
        ("health_timestamp", "health warning has no source timestamp"),
    ),
)
def test_pre_feature_v4_rejects_warning_without_migration_timestamp(
    mutation: str,
    message: str,
) -> None:
    legacy = historical_payload("warning")
    snapshot = legacy["snapshot"]
    assert isinstance(snapshot, dict)
    episodes = snapshot["episode_states"]
    assert isinstance(episodes, list)
    room = next(
        item
        for item in episodes
        if isinstance(item, dict) and item.get("node_id") == "room"
    )
    if mutation == "cadence_timestamp":
        room["cadence_warning"] = True
        room["last_event_at"] = None
    else:
        room["health_warning"] = True
        room["degradation_reason"] = "count_conflict"
        room["degraded_at"] = None

    with pytest.raises(ValueError, match=message):
        _decode_snapshot(snapshot, pre_feature_v4=True)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("unknown_node", "occurrence is incompatible"),
        ("wrong_zone", "occurrence is incompatible"),
        ("future", "occurrence is incompatible"),
        ("stale", "occurrence is stale"),
        ("missing", "occurrence is missing"),
    ),
)
def test_restore_rejects_inconsistent_reliability_warning_ledger(
    mutation: str,
    message: str,
) -> None:
    predictive_map = target_map()
    engine = ZoneModelEngine(predictive_map, 1, NOW)
    engine.observe(SensorInput("binary_sensor.room", "on", NOW))
    engine.observe(
        SensorInput("binary_sensor.room", "off", NOW + timedelta(seconds=10))
    )
    engine.observe(
        SensorInput("binary_sensor.room", "on", NOW + timedelta(seconds=12))
    )
    payload = serialize_target_state(predictive_map, engine)
    snapshot = payload["snapshot"]
    assert isinstance(snapshot, dict)
    occurrences = snapshot["reliability_warning_occurrences"]
    episodes = snapshot["episode_states"]
    assert isinstance(occurrences, list) and isinstance(occurrences[0], dict)
    assert isinstance(episodes, list)
    occurrence = occurrences[0]
    if mutation == "unknown_node":
        occurrence["node_id"] = "missing"
    elif mutation == "wrong_zone":
        occurrence["zone"] = "hall"
    elif mutation == "future":
        occurrence["last_observed_at"] = (NOW + timedelta(seconds=13)).isoformat()
    elif mutation == "stale":
        room = next(
            item
            for item in episodes
            if isinstance(item, dict) and item.get("node_id") == "room"
        )
        room["cadence_warning"] = False
        room["cadence_warning_reason"] = None
    else:
        occurrences.clear()

    with pytest.raises(ValueError, match=message):
        restore_target_state(predictive_map, payload, NOW + timedelta(seconds=12))


def test_restore_accepts_cleared_reliability_warning_history() -> None:
    predictive_map = target_map()
    engine = ZoneModelEngine(predictive_map, 1, NOW)
    engine.observe(SensorInput("binary_sensor.room", "on", NOW))
    engine.observe(
        SensorInput("binary_sensor.room", "off", NOW + timedelta(seconds=10))
    )
    engine.observe(
        SensorInput("binary_sensor.room", "on", NOW + timedelta(seconds=12))
    )
    engine.observe(
        SensorInput("binary_sensor.room", "unavailable", NOW + timedelta(seconds=13))
    )
    payload = serialize_target_state(predictive_map, engine)

    restored = restore_target_state(
        predictive_map,
        payload,
        NOW + timedelta(seconds=13),
    )

    assert restored.snapshot.reliability_warning_occurrences[0].cleared_at == (
        NOW + timedelta(seconds=13)
    )


def test_interaction_episode_round_trips_and_releases_on_the_same_frontier() -> None:
    predictive_map = PredictiveMap.from_mapping(
        {
            "nodes": {
                "room_interaction": {
                    "zone": "room",
                    "role": "room_occupancy",
                    "occupancy_behavior": "sticky",
                    "entities": {
                        "interaction_scene_001": "event.room_scene_001"
                    },
                }
            }
        }
    )
    engine = ZoneModelEngine(predictive_map, 1, NOW)
    press_at = NOW + timedelta(seconds=1)
    engine.observe(SensorInput("event.room_scene_001", "pressed", press_at))
    assert len(engine.snapshot.anonymous_supports) == 1
    payload = serialize_target_state(predictive_map, engine)
    clear_at = engine.snapshot.episode_states[0].clear_deadline
    assert clear_at is not None

    for restore_at in (
        clear_at - timedelta(microseconds=1),
        clear_at,
        clear_at + timedelta(microseconds=1),
    ):
        uninterrupted = ZoneModelEngine(predictive_map, 1, NOW)
        uninterrupted.observe(
            SensorInput("event.room_scene_001", "pressed", press_at)
        )
        expected = uninterrupted.advance(restore_at)
        restored = restore_target_state(predictive_map, payload, restore_at)
        assert restored.snapshot == expected.snapshot

    pending = ZoneModelEngine(predictive_map, 1, NOW)
    pending.observe(SensorInput("event.room_scene_001", "pressed", press_at))
    pending.advance(press_at + timedelta(minutes=61))
    pending_since = pending.snapshot.policy_states[0].pending_release_since
    assert pending_since is not None
    release_at = (
        pending_since
        + POLICY_CALIBRATIONS["stay_presence"].release_dwell
    )
    pending_payload = serialize_target_state(predictive_map, pending)

    restored_release = None
    for restore_at in (
        release_at - timedelta(microseconds=1),
        release_at,
        release_at + timedelta(microseconds=1),
    ):
        uninterrupted = ZoneModelEngine(predictive_map, 1, NOW)
        uninterrupted.observe(
            SensorInput("event.room_scene_001", "pressed", press_at)
        )
        uninterrupted.advance(press_at + timedelta(minutes=61))
        expected_release = uninterrupted.advance(restore_at)
        restored_release = restore_target_state(
            predictive_map,
            pending_payload,
            restore_at,
        )
        assert restored_release.snapshot == expected_release.snapshot

    assert restored_release is not None
    room = next(
        state
        for state in restored_release.snapshot.policy_states
        if state.zone == "room"
    )
    assert room.active is False


@pytest.mark.parametrize(
    "mutation",
    (
        "episode_contract",
        "contribution_contract",
        "contribution_identity",
        "contribution_occurrence",
        "token_contract",
        "support_contract",
        "policy_contract",
        "audit_contract",
        "audit_identity",
        "audit_trust",
    ),
)
def test_v4_restore_rejects_malformed_interaction_provenance(
    mutation: str,
) -> None:
    predictive_map = interaction_map()
    engine = ZoneModelEngine(predictive_map, 1, NOW)
    press_at = NOW + timedelta(seconds=1)
    engine.observe(SensorInput("event.room_scene_001", "pressed", press_at))
    payload = serialize_target_state(predictive_map, engine)
    snapshot = payload["snapshot"]
    assert isinstance(snapshot, dict)

    if mutation == "episode_contract":
        episodes = snapshot["episode_states"]
        assert isinstance(episodes, list) and isinstance(episodes[0], dict)
        episodes[0]["status"] = "asserted"
        aliases = episodes[0]["alias_states"]
        assert isinstance(aliases, list)
        episodes[0]["alias_states"] = [[item[0], "on"] for item in aliases]
        episodes[0]["clear_started_at"] = None
        episodes[0]["clear_deadline"] = None
    elif mutation in {
        "contribution_contract",
        "contribution_identity",
        "contribution_occurrence",
    }:
        beliefs = snapshot["belief_states"]
        assert isinstance(beliefs, list) and isinstance(beliefs[0], dict)
        contributions = beliefs[0]["contributions"]
        assert (
            isinstance(contributions, list)
            and isinstance(contributions[0], dict)
        )
        if mutation == "contribution_contract":
            contributions[0]["kind"] = "local_positive"
        elif mutation == "contribution_identity":
            contributions[0]["episode_id"] = None
        else:
            contributions[0]["at"] = NOW.isoformat()
    elif mutation == "token_contract":
        tokens = snapshot["traversal_tokens"]
        assert isinstance(tokens, list) and isinstance(tokens[0], dict)
        tokens[0]["provenance_kind"] = "adjacent"
        tokens[0]["equivalent_confirmed_strength"] = False
    elif mutation == "support_contract":
        supports = snapshot["anonymous_supports"]
        assert isinstance(supports, list) and isinstance(supports[0], dict)
        supports[0]["provenance_kind"] = "adjacent"
    elif mutation == "policy_contract":
        policies = snapshot["policy_states"]
        assert isinstance(policies, list) and isinstance(policies[0], dict)
        policies[0]["activation_reason"] = "boundary_authorized"
        policies[0]["activation_provenance_kind"] = "boundary"
    else:
        audit = payload["audit"]
        assert isinstance(audit, list) and isinstance(audit[0], dict)
        if mutation == "audit_contract":
            audit[0]["local_evidence_kind"] = "positive"
        elif mutation == "audit_identity":
            audit[0]["node_id"] = None
        else:
            audit[0]["local_trustworthy"] = False

    with pytest.raises(ValueError, match="[Ii]nteraction"):
        restore_target_state(predictive_map, payload, press_at)


def test_correlated_continuity_lineage_round_trips_dormant_and_reopened() -> None:
    predictive_map = correlated_continuity_map()
    engine = ZoneModelEngine(predictive_map, 2, NOW)
    top_at = NOW + timedelta(seconds=7)
    top_off_at = NOW + timedelta(seconds=50)
    dormant_at = top_at + timedelta(seconds=45, milliseconds=100)
    reasserted_at = top_off_at + timedelta(seconds=2, milliseconds=200)

    engine.observe(SensorInput("binary_sensor.bottom", "on", NOW))
    engine.observe(SensorInput("binary_sensor.top", "on", top_at))
    engine.observe(
        SensorInput("binary_sensor.bottom", "off", NOW + timedelta(seconds=21))
    )
    engine.observe(SensorInput("binary_sensor.top", "off", top_off_at))
    engine.advance(dormant_at)
    assert engine.snapshot.traversal_tokens == ()
    assert engine.snapshot.retained_traversal_tokens

    dormant_payload = serialize_target_state(predictive_map, engine)
    dormant = restore_target_state(predictive_map, dormant_payload, dormant_at)
    assert dormant.snapshot == engine.snapshot
    assert serialize_target_state(predictive_map, dormant) == dormant_payload

    reopened = dormant.observe(SensorInput("binary_sensor.top", "on", reasserted_at))
    assert any(token.node_id == "top" for token in reopened.snapshot.traversal_tokens)
    assert all(
        token.node_id != "top" for token in reopened.snapshot.retained_traversal_tokens
    )
    reopened_payload = serialize_target_state(predictive_map, dormant)
    restored = restore_target_state(predictive_map, reopened_payload, reasserted_at)
    assert restored.snapshot == dormant.snapshot
    assert serialize_target_state(predictive_map, restored) == reopened_payload


@pytest.mark.parametrize("frontier", ("idle", "unavailable", "count_arrival"))
def test_natural_no_generation_beliefs_round_trip(frontier: str) -> None:
    predictive_map = entry_map()
    initial_count = 0 if frontier == "count_arrival" else 1
    engine = ZoneModelEngine(predictive_map, initial_count, NOW)
    at = NOW + timedelta(seconds=1)
    if frontier == "idle":
        engine.advance(at)
    elif frontier == "unavailable":
        engine.observe(SensorInput("binary_sensor.entry", "unavailable", at))
    else:
        engine.observe_count(CountInput("arrival", 1, True, at))
    payload = serialize_target_state(predictive_map, engine)

    restored = restore_target_state(predictive_map, payload, at)

    assert restored.snapshot == engine.snapshot
    assert serialize_target_state(predictive_map, restored) == payload


def test_predicted_phase_and_nonrenewing_lease_survive_restart() -> None:
    predictive_map = prediction_map()
    engine = ZoneModelEngine(predictive_map, 1, PREDICTION_NOW)
    seed_mature_route(engine.prediction_manager)
    engine.observe(SensorInput("binary_sensor.office", "on", PREDICTION_NOW))
    engine.observe(
        SensorInput(
            "binary_sensor.hall",
            "on",
            PREDICTION_NOW + timedelta(seconds=1),
        )
    )
    engine.observe(
        SensorInput(
            "binary_sensor.kitchen",
            "on",
            PREDICTION_NOW + timedelta(seconds=2),
        )
    )
    payload = serialize_target_state(predictive_map, engine)
    living = next(
        state for state in engine.snapshot.policy_states if state.zone == "living"
    )
    assert living.prediction_expires_at is not None

    before = restore_target_state(
        predictive_map,
        payload,
        living.prediction_expires_at - timedelta(microseconds=1),
    )
    before_living = next(
        state for state in before.snapshot.policy_states if state.zone == "living"
    )
    assert before_living.active and before_living.phase == "predicted"
    assert before_living.prediction_expires_at == living.prediction_expires_at

    exact = restore_target_state(
        predictive_map,
        payload,
        living.prediction_expires_at,
    )
    exact_living = next(
        state for state in exact.snapshot.policy_states if state.zone == "living"
    )
    assert not exact_living.active
    assert exact_living.phase == "inactive"
    assert exact.prediction_manager.leases == ()


def test_restore_rejects_lease_canceled_by_later_target_evidence() -> None:
    predictive_map = prediction_map()
    engine = ZoneModelEngine(predictive_map, 1, PREDICTION_NOW)
    seed_mature_route(engine.prediction_manager)
    engine.observe(SensorInput("binary_sensor.office", "on", PREDICTION_NOW))
    engine.observe(
        SensorInput(
            "binary_sensor.hall",
            "on",
            PREDICTION_NOW + timedelta(seconds=1),
        )
    )
    engine.observe(
        SensorInput(
            "binary_sensor.kitchen",
            "on",
            PREDICTION_NOW + timedelta(seconds=2),
        )
    )
    stale_lease = engine.prediction_manager.serialize()["leases"]
    assert isinstance(stale_lease, list) and stale_lease
    engine.observe(
        SensorInput(
            "binary_sensor.living",
            "on",
            PREDICTION_NOW + timedelta(seconds=3),
        )
    )
    assert engine.prediction_manager.leases == ()
    payload = serialize_target_state(predictive_map, engine)
    prediction = payload["prediction"]
    assert isinstance(prediction, dict)
    prediction["leases"] = stale_lease

    with pytest.raises(ValueError, match="contradictory target evidence"):
        restore_target_state(
            predictive_map,
            payload,
            PREDICTION_NOW + timedelta(seconds=3),
        )


def test_count_conflict_dwell_survives_restart_without_extension() -> None:
    engine = engine_with_two_front_conflict()
    predictive_map = conflict_map()
    conflict = engine.snapshot.count_conflicts[0]
    payload = serialize_target_state(predictive_map, engine)

    before = restore_target_state(
        predictive_map,
        payload,
        conflict.deadline - timedelta(microseconds=1),
    )
    before_target = next(
        state
        for state in before.snapshot.episode_states
        if state.node_id == conflict.target_node_id
    )
    assert not before_target.health_warning
    assert before.snapshot.count_conflicts[0].deadline == conflict.deadline

    exact = restore_target_state(predictive_map, payload, conflict.deadline)
    exact_target = next(
        state
        for state in exact.snapshot.episode_states
        if state.node_id == conflict.target_node_id
    )
    assert exact_target.health_warning
    row = next(
        item for item in exact.audit_rows if item.reason == "stuck_count_conflict"
    )
    assert row.count_conflict_support_ids == conflict.support_ids


def test_restored_count_degraded_assertion_cancels_legacy_pending_release() -> None:
    predictive_map = conflict_map()
    engine = engine_with_two_front_conflict()
    conflict = engine.snapshot.count_conflicts[0]
    engine.advance(conflict.deadline)
    snapshot = engine.snapshot
    pending_at = conflict.deadline
    legacy_pending = replace(
        snapshot,
        policy_states=tuple(
            replace(state, pending_release_since=pending_at)
            if state.zone == "target"
            else state
            for state in snapshot.policy_states
        ),
    )

    restored = ZoneModelEngine.restore(
        predictive_map,
        legacy_pending,
        tuple(engine.audit_rows),
        pending_at,
    )
    due_at = pending_at + POLICY_CALIBRATIONS["stay_pir"].release_dwell
    replayed = restored.observe(
        SensorInput("binary_sensor.as", "on", due_at),
    )
    target_policy = next(
        state for state in replayed.snapshot.policy_states if state.zone == "target"
    )

    assert target_policy.active
    assert target_policy.pending_release_since is None
    assert not any(
        event.zone == "target" and event.kind == "released"
        for event in replayed.policy_events
    )
    assert any(
        row.zone == "target" and row.reason == "asserted_stay_hold"
        for row in restored.audit_rows
    )


@pytest.mark.parametrize("kind", ("v3_pending", "v3_degraded"))
def test_pre_handoff_v3_inference_rejected_atomically(kind: str) -> None:
    assert_historical_rejected(kind)


@pytest.mark.parametrize("kind", ("v3_pending", "v3_degraded"))
def test_current_fingerprint_cannot_relabel_v3_as_compatible(kind: str) -> None:
    assert_historical_rejected(kind, relabel=True)


@pytest.mark.parametrize("degraded", (False, True))
def test_historical_v3_decoder_invents_no_support(degraded: bool) -> None:
    kind = "v3_degraded" if degraded else "v3_pending"
    original = historical_payload(kind)["snapshot"]
    snapshot = _decode_snapshot(original, legacy_v3=True, pre_feature_v4=True)
    assert snapshot.anonymous_supports == ()
    assert snapshot.support_token_bindings == ()
    if degraded:
        assert len(snapshot.count_conflicts) == 1
        conflict = snapshot.count_conflicts[0]
        assert conflict.support_ids == tuple(
            original["count_conflicts"][0]["strong_front_ids"]
        )
        assert conflict.degraded_at == NOW + timedelta(seconds=63)
    else:
        assert snapshot.count_conflicts == ()


def test_settled_supports_survive_restart_after_source_tokens_expire() -> None:
    predictive_map = conflict_map()
    engine = engine_with_two_front_conflict()
    engine.advance(NOW + timedelta(seconds=100))
    assert engine.snapshot.traversal_tokens == ()
    supports = engine.snapshot.anonymous_supports
    assert len(supports) == 2

    restored = restore_target_state(
        predictive_map,
        serialize_target_state(predictive_map, engine),
        NOW + timedelta(seconds=100),
    )

    assert restored.snapshot.anonymous_supports == supports


def test_stale_transfer_authority_is_restart_equivalent() -> None:
    predictive_map = stale_transfer_map()
    engine = engine_before_stale_transfer(NOW)
    payload = serialize_target_state(predictive_map, engine)
    restored = restore_target_state(
        predictive_map,
        payload,
        engine.snapshot.updated_at,
    )
    uninterrupted_before = engine.diagnostic_counters[
        "support_stale_binding_ignored"
    ]
    restored_before = restored.diagnostic_counters[
        "support_stale_binding_ignored"
    ]
    second = SensorInput(
        "binary_sensor.second",
        "on",
        NOW + timedelta(seconds=4),
    )

    uninterrupted_result = engine.observe(second)
    restored_result = restored.observe(second)

    assert restored_result.snapshot == uninterrupted_result.snapshot
    assert restored_result.policy_events == uninterrupted_result.policy_events
    assert (
        restored_result.policy_decisions
        == uninterrupted_result.policy_decisions
    )
    assert restored_result.authorizations == uninterrupted_result.authorizations
    assert restored.audit_rows == engine.audit_rows
    assert (
        engine.diagnostic_counters["support_stale_binding_ignored"]
        - uninterrupted_before
        == restored.diagnostic_counters["support_stale_binding_ignored"]
        - restored_before
        == 1
    )
    retained = next(
        support
        for support in restored_result.snapshot.anonymous_supports
        if support.current_zone == "retained"
    )
    assert retained.updated_at == NOW + timedelta(seconds=3)


def test_correlated_support_continuation_is_restart_equivalent() -> None:
    correlated_incident = import_module(
        "tests.incidents."
        "test_inc_2026_09_06_1931z_correlated_intermediate_splits_support_lineage"
    )
    predictive_map = correlated_incident.incident_map()
    engine = correlated_incident.engine_before_correlated_intermediate()
    correlated_at = datetime.fromisoformat("2026-09-06T19:32:54.617692+00:00")
    restore_at = correlated_at - timedelta(microseconds=1)
    engine.advance(restore_at)
    restored = restore_target_state(
        predictive_map,
        serialize_target_state(predictive_map, engine),
        restore_at,
    )
    correlated = SensorInput(
        "binary_sensor.master_bedroom_closet",
        "on",
        correlated_at,
    )

    uninterrupted_result = engine.observe(correlated)
    restored_result = restored.observe(correlated)

    assert restored_result.snapshot == uninterrupted_result.snapshot
    assert restored_result.policy_events == uninterrupted_result.policy_events
    assert restored_result.policy_decisions == uninterrupted_result.policy_decisions
    assert restored_result.authorizations == uninterrupted_result.authorizations
    assert restored.audit_rows == engine.audit_rows
    assert restored_result.snapshot.anonymous_supports[0].current_node_id == (
        "master_bedroom_closet"
    )


@pytest.mark.parametrize(
    ("target_offset", "reason"),
    [
        (timedelta(seconds=179, microseconds=999999), "adjacent_authorized"),
        (timedelta(seconds=180), "settled_adjacent_transfer"),
    ],
)
def test_stay_presence_deadline_restore_eligible_settled_adjacent_fallback(
    target_offset: timedelta,
    reason: str,
) -> None:
    assert_stay_presence_deadline_restore(
        target_offset, eligible_source=True, authorized=True, reason=reason
    )


@pytest.mark.parametrize(
    ("target_offset", "authorized"),
    [
        (timedelta(seconds=179, microseconds=999999), True),
        (timedelta(seconds=180), False),
        (timedelta(seconds=180, microseconds=1), False),
    ],
)
def test_stay_presence_deadline_restore_without_eligible_settled_source_rejects(
    target_offset: timedelta,
    authorized: bool,
) -> None:
    assert_stay_presence_deadline_restore(
        target_offset, eligible_source=False, authorized=authorized
    )


def assert_stay_presence_deadline_restore(
    target_offset: timedelta,
    *,
    eligible_source: bool,
    authorized: bool,
    reason: str | None = None,
) -> None:
    incident = import_module(
        "tests.incidents."
        "test_inc_2026_09_08_1213z_stay_presence_authority_expires_before_closet_return"
    )
    predictive_map = incident._incident_map()
    engine = incident._engine_with_settled_bathroom_support(predictive_map, 1)
    source_at = datetime.fromisoformat("2026-09-08T12:14:24.044050+00:00")
    source = engine.observe(
        SensorInput("binary_sensor.bathroom", "on", source_at)
    )
    if not eligible_source:
        # Synthetic inverse: retain identical physical episodes and ordinary
        # token authority, but no alternative count-support authority.
        engine = ZoneModelEngine.restore(
            predictive_map,
            replace(
                engine.snapshot,
                anonymous_supports=(),
                support_token_bindings=(),
                count_conflicts=(),
            ),
            tuple(engine.audit_rows),
            source_at,
        )
    target_at = source_at + target_offset
    restore_at = target_at - timedelta(microseconds=1)
    engine.advance(restore_at)
    payload = serialize_target_state(predictive_map, engine)
    restored = restore_target_state(predictive_map, payload, restore_at)

    assert source.authorizations[0].reason == "settled_endpoint_reacquired"
    assert serialize_target_state(predictive_map, restored) == payload

    target = SensorInput("binary_sensor.closet", "on", target_at)
    processing_at = source_at + timedelta(seconds=181)
    uninterrupted_result = engine.observe(target, processing_at=processing_at)
    restored_result = restored.observe(target, processing_at=processing_at)
    authorization = uninterrupted_result.authorizations[0]
    closet = next(
        state
        for state in uninterrupted_result.snapshot.policy_states
        if state.zone == "closet"
    )

    assert authorization.authorized is authorized
    assert closet.active is authorized
    if reason is not None:
        assert authorization.reason == reason
    assert all(
        row.event_at == target_at and row.processing_at == processing_at
        for row in uninterrupted_result.policy_decisions
    )
    assert restored_result.snapshot == uninterrupted_result.snapshot
    assert restored_result.policy_events == uninterrupted_result.policy_events
    assert restored_result.policy_decisions == uninterrupted_result.policy_decisions
    assert restored_result.authorizations == uninterrupted_result.authorizations
    assert restored.audit_rows == engine.audit_rows
    post = serialize_target_state(predictive_map, engine)
    reloaded = restore_target_state(predictive_map, post, target_at)
    assert serialize_target_state(predictive_map, reloaded) == post


def test_weak_clear_retained_support_survives_restart() -> None:
    predictive_map = conflict_map()
    engine = engine_with_two_front_conflict()
    support = engine.snapshot.anonymous_supports[0]
    clear_started_at = engine.snapshot.updated_at + timedelta(seconds=1)
    engine.observe(
        SensorInput(
            f"binary_sensor.{support.current_node_id}",
            "off",
            clear_started_at,
        )
    )
    clearing = next(
        state
        for state in engine.snapshot.episode_states
        if state.node_id == support.current_node_id
    )
    assert clearing.clear_deadline is not None
    engine.advance(clearing.clear_deadline)
    retained = next(
        item
        for item in engine.snapshot.anonymous_supports
        if item.support_id == support.support_id
    )
    endpoint = next(
        state
        for state in engine.snapshot.episode_states
        if state.node_id == retained.current_node_id
    )
    assert endpoint.status == "clear"

    payload = serialize_target_state(predictive_map, engine)
    restored = restore_target_state(
        predictive_map,
        payload,
        engine.snapshot.updated_at,
    )

    assert restored.snapshot == engine.snapshot

    invalid = deepcopy(payload)
    invalid_snapshot = invalid["snapshot"]
    assert isinstance(invalid_snapshot, dict)
    beliefs = invalid_snapshot["belief_states"]
    assert isinstance(beliefs, list)
    endpoint_belief = next(
        item
        for item in beliefs
        if isinstance(item, dict) and item["zone"] == retained.current_zone
    )
    endpoint_belief["context"] = "cleared_with_outward"
    endpoint_belief["outward_context"] = {
        "source_episode_id": retained.current_episode_id,
        "valid_until": (
            engine.snapshot.updated_at + timedelta(seconds=1)
        ).isoformat(),
    }

    with pytest.raises(ValueError, match="Settled anonymous support"):
        restore_target_state(
            predictive_map,
            invalid,
            engine.snapshot.updated_at,
        )


def test_moving_support_with_exact_target_binding_survives_restart() -> None:
    predictive_map = conflict_map()
    payload = serialize_target_state(
        predictive_map,
        engine_with_two_front_conflict(),
    )
    snapshot = payload["snapshot"]
    assert isinstance(snapshot, dict)
    supports = snapshot["anonymous_supports"]
    bindings = snapshot["support_token_bindings"]
    tokens = snapshot["traversal_tokens"]
    assert (
        isinstance(supports, list)
        and supports
        and isinstance(supports[0], dict)
        and isinstance(bindings, list)
        and isinstance(tokens, list)
    )
    support = supports[0]
    bound_token_ids = {
        binding["token_id"]
        for binding in bindings
        if isinstance(binding, dict)
        and binding["support_id"] == support["support_id"]
    }
    target = next(
        token
        for token in tokens
        if isinstance(token, dict)
        and token["token_id"] in bound_token_ids
        and token["node_id"] == support["current_node_id"]
        and token["episode_id"] == support["current_episode_id"]
    )
    support["state"] = "moving"
    support["valid_until"] = target["valid_until"]
    support["last_transition"] = "advanced"

    restored = restore_target_state(
        predictive_map,
        payload,
        datetime.fromisoformat(str(snapshot["updated_at"])),
    )

    restored_support = restored.snapshot.anonymous_supports[0]
    assert restored_support.state == "moving"
    assert restored_support.valid_until == datetime.fromisoformat(
        str(target["valid_until"])
    )


def test_late_count_conflict_degradation_round_trips_after_trust_horizon() -> None:
    predictive_map = conflict_map()
    engine = ZoneModelEngine(predictive_map, 2, NOW)
    engine.observe(SensorInput("binary_sensor.target_source", "on", NOW))
    engine.observe(
        SensorInput("binary_sensor.target", "on", NOW + timedelta(seconds=1))
    )
    engine.advance(NOW + timedelta(seconds=900))
    for node_id, seconds in (
        ("a", 902),
        ("am", 903),
        ("as", 904),
        ("d", 905),
        ("dm", 906),
        ("ds", 907),
    ):
        engine.observe(
            SensorInput(
                f"binary_sensor.{node_id}",
                "on",
                NOW + timedelta(seconds=seconds),
            )
        )
    conflict = engine.snapshot.count_conflicts[0]
    assert conflict.deadline == NOW + timedelta(seconds=967)
    engine.advance(conflict.deadline)
    payload = serialize_target_state(predictive_map, engine)

    restored = restore_target_state(predictive_map, payload, conflict.deadline)

    target = next(
        state for state in restored.snapshot.episode_states if state.node_id == "target"
    )
    assert target.degradation_reason == "count_conflict"
    assert target.degraded_at == conflict.deadline


def test_v3_fingerprint_includes_reliability_route_prior_and_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def mapped(reliability: float, route_prior_weight: float) -> PredictiveMap:
        return PredictiveMap.from_mapping(
            {
                "nodes": {
                    "room": {
                        "entities": {"motion": "binary_sensor.room"},
                        "reliability": reliability,
                        "route_prior_weight": route_prior_weight,
                    }
                }
            }
        )

    baseline_map = mapped(0.9, 0.4)
    baseline = target_map_fingerprint(baseline_map)
    baseline_payload = serialize_target_state(
        baseline_map,
        ZoneModelEngine(baseline_map, 1, NOW),
    )
    assert target_map_fingerprint(mapped(0.8, 0.4)) != baseline
    assert target_map_fingerprint(mapped(0.9, 0.5)) != baseline

    persistence_module = import_module(
        "custom_components.predictive_controls.zone_model.persistence"
    )
    persistence_api: Any = persistence_module
    original_profiles = persistence_api.SHARED_PROFILES
    profiles = dict(original_profiles)
    profiles["stay_pir"] = replace(
        profiles["stay_pir"],
        track_bootstrap_window=(
            profiles["stay_pir"].track_bootstrap_window + timedelta(seconds=1)
        ),
    )
    monkeypatch.setattr(persistence_module, "SHARED_PROFILES", profiles)
    assert target_map_fingerprint(baseline_map) != baseline
    with pytest.raises(ValueError, match="fingerprint is incompatible"):
        restore_target_state(baseline_map, baseline_payload, NOW)
    monkeypatch.setattr(persistence_module, "SHARED_PROFILES", original_profiles)

    profiles = dict(original_profiles)
    profiles["stay_presence"] = replace(
        profiles["stay_presence"],
        traversal_context_window=(
            profiles["stay_presence"].traversal_context_window
            + timedelta(seconds=1)
        ),
    )
    monkeypatch.setattr(persistence_module, "SHARED_PROFILES", profiles)
    assert target_map_fingerprint(baseline_map) != baseline
    monkeypatch.setattr(persistence_module, "SHARED_PROFILES", original_profiles)

    original_beliefs = persistence_api.BELIEF_PROFILES
    beliefs = dict(original_beliefs)
    beliefs["stay_pir"] = replace(
        beliefs["stay_pir"],
        prior_probability=beliefs["stay_pir"].prior_probability + 0.001,
    )
    monkeypatch.setattr(persistence_module, "BELIEF_PROFILES", beliefs)
    assert target_map_fingerprint(baseline_map) != baseline
    monkeypatch.setattr(persistence_module, "BELIEF_PROFILES", original_beliefs)

    original_calibrations = persistence_api.POLICY_CALIBRATIONS
    calibrations = dict(original_calibrations)
    calibrations["stay_pir"] = replace(
        calibrations["stay_pir"],
        on_threshold=calibrations["stay_pir"].on_threshold + 0.01,
    )
    monkeypatch.setattr(persistence_module, "POLICY_CALIBRATIONS", calibrations)
    assert target_map_fingerprint(baseline_map) != baseline
    monkeypatch.setattr(
        persistence_module,
        "ARRIVAL_FROM_EMPTY_PROBABILITY",
        persistence_api.ARRIVAL_FROM_EMPTY_PROBABILITY + 0.001,
    )
    assert target_map_fingerprint(baseline_map) != baseline


def test_v3_fingerprint_includes_zone_role_resolved_profile() -> None:
    def mapped(zone_role: str) -> PredictiveMap:
        return PredictiveMap.from_mapping(
            {
                "zones": {
                    "room": {
                        "role": zone_role,
                        "occupancy_behavior": "transient",
                    }
                },
                "nodes": {
                    "room_sensor": {
                        "zone": "room",
                        "role": "room_occupancy",
                        "occupancy_behavior": "transient",
                        "entities": {"motion": "binary_sensor.room"},
                    }
                },
            }
        )

    stay = mapped("room_occupancy")
    transition = mapped("transition_gate")

    assert target_map_fingerprint(stay) != target_map_fingerprint(transition)


@pytest.mark.parametrize(
    ("frontier", "restore_offset"),
    (
        ("assertion", 3),
        ("clear", 8),
        ("traversal", 46),
        ("decay", 300),
        # The v3 stay-PIR decay crosses off at 608.9235 seconds; 670 is the
        # first whole-second fixture frontier beyond its 60-second dwell.
        ("release_dwell", 670),
    ),
)
def test_restore_advances_each_frontier_exactly_once(
    frontier: str,
    restore_offset: int,
) -> None:
    engine = engine_at_restart_frontier(frontier)
    payload = serialize_target_state(target_map(), engine)
    restore_at = NOW + timedelta(seconds=restore_offset)
    uninterrupted = restore_target_state(
        target_map(), payload, engine.snapshot.updated_at
    )

    expected = uninterrupted.advance(restore_at)
    restored = restore_target_state(target_map(), payload, restore_at)

    assert restored.snapshot == expected.snapshot
    if frontier == "release_dwell":
        assert expected.policy_events[0].kind == "released"
        assert restored.audit_rows[-1].reason == "released"
        assert restored.audit_rows[-1].event_kind is None


def test_external_positive_at_release_deadline_cannot_extend_old_active_phase() -> None:
    engine = engine_at_restart_frontier("release_dwell")
    engine.advance(NOW + timedelta(seconds=660))
    room = next(
        state for state in engine.snapshot.policy_states if state.zone == "room"
    )
    assert room.pending_release_since is not None
    deadline = room.pending_release_since + timedelta(seconds=60)

    result = engine.observe(SensorInput("binary_sensor.room", "on", deadline))

    room = next(
        state for state in result.snapshot.policy_states if state.zone == "room"
    )
    assert not room.active
    assert [event.kind for event in result.policy_events] == ["released"]


def test_target_restore_rejects_incompatible_state_atomically() -> None:
    payload = serialize_target_state(target_map(), occupied_engine())
    wrong_map = deepcopy(payload)
    wrong_map["map_fingerprint"] = "wrong"
    with pytest.raises(ValueError, match="map fingerprint"):
        restore_target_state(target_map(), wrong_map, NOW + timedelta(seconds=2))

    invalid_nested = deepcopy(payload)
    snapshot = invalid_nested["snapshot"]
    assert isinstance(snapshot, dict)
    beliefs = snapshot["belief_states"]
    assert isinstance(beliefs, list) and isinstance(beliefs[0], dict)
    beliefs[0]["profile_name"] = "unknown"
    with pytest.raises(ValueError, match="Unknown belief profile"):
        restore_target_state(target_map(), invalid_nested, NOW + timedelta(seconds=2))


def test_schema6_migration_uses_only_active_seed_and_raw_snapshot() -> None:
    predictive_map = target_map()
    payload = {
        "schema": "exact-augmented-v6",
        "map_fingerprint": legacy_target_map_fingerprint(predictive_map),
        "occupants": 1,
        "policy": {
            "states": {
                "hall": {"keep_on": False},
                "room": {"keep_on": True},
            }
        },
        "log_probabilities": [0.0],
        "message": {"ignored": "exact assignment is not imported"},
    }
    snapshot = (
        SensorInput("binary_sensor.hall", "off", NOW),
        SensorInput("binary_sensor.room", "on", NOW),
    )

    migrated = migrate_schema6_seed(predictive_map, payload, snapshot, NOW)

    assert {state.zone: state.active for state in migrated.snapshot.policy_states}[
        "room"
    ] is True
    assert migrated.snapshot.traversal_tokens == ()
    assert migrated.snapshot.authorization_uses == ()
    assert migrated.audit_rows == ()
    assert {state.zone: state.probability for state in migrated.snapshot.belief_states}[
        "room"
    ] > 0.7


def test_target_decoder_rejects_each_malformed_boundary() -> None:
    baseline = serialize_target_state(target_map(), occupied_engine())

    def rejected(mutator: object) -> None:
        payload = deepcopy(baseline)
        assert callable(mutator)
        mutator(payload)
        with pytest.raises(ValueError):
            restore_target_state(target_map(), payload, NOW + timedelta(seconds=2))

    rejected(lambda root: root.__setitem__("audit", {}))
    rejected(lambda root: root.__setitem__("snapshot", []))
    rejected(lambda root: root["snapshot"].__setitem__("episode_states", {}))
    rejected(
        lambda root: root["snapshot"]["episode_states"][0].__setitem__("node_id", 1)
    )
    rejected(
        lambda root: root["snapshot"]["episode_states"][0].__setitem__("episode_id", 1)
    )
    rejected(
        lambda root: root["snapshot"]["episode_states"][0].__setitem__(
            "alias_states", {}
        )
    )
    rejected(
        lambda root: root["snapshot"]["episode_states"][0].__setitem__(
            "clear_emitted", 1
        )
    )
    rejected(
        lambda root: root["snapshot"]["episode_states"][0].__setitem__(
            "generation", True
        )
    )
    rejected(
        lambda root: root["snapshot"]["belief_states"][0].__setitem__("log_odds", True)
    )
    rejected(lambda root: root["snapshot"].__setitem__("current_token_ids", [1]))
    rejected(lambda root: root["snapshot"].__setitem__("retained_traversal_tokens", {}))
    rejected(
        lambda root: root["snapshot"]["count_state"].__setitem__("diagnostics", [])
    )
    rejected(lambda root: root["snapshot"].__setitem__("updated_at", 1))
    rejected(lambda root: root["snapshot"].__setitem__("updated_at", "not-a-date"))
    rejected(
        lambda root: root["snapshot"]["policy_states"][0].__setitem__(
            "prediction_probability", True
        )
    )

    with pytest.raises(ValueError, match="string-keyed"):
        restore_target_state(target_map(), {1: "invalid"}, NOW)


@pytest.mark.parametrize(
    "update",
    (
        {"schema": "wrong"},
        {"map_fingerprint": "wrong"},
        {"occupants": True},
        {"policy": []},
        {"policy": {"states": {"room": {"keep_on": 1}}}},
        {"policy": {"states": {"unknown": {"keep_on": True}}}},
    ),
)
def test_schema6_decoder_rejects_invalid_seed_fields(update: dict[str, object]) -> None:
    payload: dict[str, object] = {
        "schema": "exact-augmented-v6",
        "map_fingerprint": legacy_target_map_fingerprint(target_map()),
        "occupants": 1,
    }
    payload.update(update)
    with pytest.raises(ValueError):
        migrate_schema6_seed(target_map(), payload, (), NOW)


def test_schema6_seed_allows_absent_policy() -> None:
    payload = {
        "schema": "exact-augmented-v6",
        "map_fingerprint": legacy_target_map_fingerprint(target_map()),
        "occupants": 1,
    }
    migrated = migrate_schema6_seed(target_map(), payload, (), NOW)
    assert all(not state.active for state in migrated.snapshot.policy_states)


def test_zero_count_migrations_never_restore_active_zones() -> None:
    schema6 = {
        "schema": "exact-augmented-v6",
        "map_fingerprint": legacy_target_map_fingerprint(target_map()),
        "occupants": 0,
        "policy": {"states": {"room": {"keep_on": True}}},
    }
    migrated_schema6 = migrate_schema6_seed(target_map(), schema6, (), NOW)
    assert all(not state.active for state in migrated_schema6.snapshot.policy_states)

    v2 = legacy_v2_payload(traversal_reason="adjacent_current")
    snapshot = v2["snapshot"]
    assert isinstance(snapshot, dict)
    count_state = snapshot["count_state"]
    assert isinstance(count_state, dict)
    count_state["expected_count"] = 0
    seed = decode_v2_seed(target_map(), v2)
    assert seed.active_seed["room"]
    migrated_v2 = migrate_v2_seed(target_map(), seed, (), NOW)
    assert all(not state.active for state in migrated_v2.snapshot.policy_states)


def test_v3_restore_rejects_zero_count_with_active_policy() -> None:
    payload = serialize_target_state(target_map(), occupied_engine())
    snapshot = payload["snapshot"]
    assert isinstance(snapshot, dict)
    count_state = snapshot["count_state"]
    assert isinstance(count_state, dict)
    count_state["expected_count"] = 0

    with pytest.raises(ValueError, match="Zero-count snapshot"):
        restore_target_state(target_map(), payload, NOW + timedelta(seconds=2))


@pytest.mark.parametrize(
    "provenance",
    (None, "source_free_corroborated", "junk"),
)
def test_v3_restore_rejects_invalid_active_policy_provenance(
    provenance: str | None,
) -> None:
    payload = serialize_target_state(target_map(), occupied_engine())
    snapshot = payload["snapshot"]
    assert isinstance(snapshot, dict)
    policies = snapshot["policy_states"]
    assert isinstance(policies, list)
    room = next(
        item
        for item in policies
        if isinstance(item, dict) and item.get("zone") == "room"
    )
    room["activation_provenance"] = provenance

    with pytest.raises(ValueError, match="provenance"):
        restore_target_state(target_map(), payload, NOW + timedelta(seconds=2))


def test_v3_restore_rejects_self_declared_evidence_active_policy() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    payload = serialize_target_state(target_map(), engine)
    snapshot = payload["snapshot"]
    assert isinstance(snapshot, dict)
    policies = snapshot["policy_states"]
    assert isinstance(policies, list)
    hall = next(
        item
        for item in policies
        if isinstance(item, dict) and item.get("zone") == "hall"
    )
    episodes = snapshot["episode_states"]
    assert isinstance(episodes, list)
    hall_episode = next(
        item
        for item in episodes
        if isinstance(item, dict) and item.get("node_id") == "hall"
    )
    hall.update(
        {
            "active": True,
            "phase": "active",
            "activation_provenance": "evidence",
            "activation_episode_id": hall_episode["episode_id"],
            "activation_at": hall_episode["started_at"],
            "activation_reason": "provisional_track_acquired",
            "activation_track_confidence": "provisional",
            "activation_path_node_ids": ["room", "hall"],
            "activation_provenance_kind": "adjacent_pair",
            "activation_source_episode_ids": [],
        }
    )

    with pytest.raises(ValueError, match="not bound to its acquisition episode"):
        restore_target_state(target_map(), payload, NOW)


def test_v3_restore_rejects_immature_or_lease_free_predicted_policy() -> None:
    predictive_map, valid = predicted_payload()
    immature = deepcopy(valid)
    snapshot = immature["snapshot"]
    assert isinstance(snapshot, dict)
    policies = snapshot["policy_states"]
    assert isinstance(policies, list)
    living = next(
        item
        for item in policies
        if isinstance(item, dict) and item.get("zone") == "living"
    )
    living["prediction_probability"] = 0.1
    living["prediction_support"] = 0.0
    with pytest.raises(ValueError, match="Predicted policy"):
        restore_target_state(
            predictive_map,
            immature,
            PREDICTION_NOW + timedelta(seconds=2),
        )

    lease_free = deepcopy(valid)
    prediction = lease_free["prediction"]
    assert isinstance(prediction, dict)
    prediction["leases"] = []
    with pytest.raises(ValueError, match="matching mature lease"):
        restore_target_state(
            predictive_map,
            lease_free,
            PREDICTION_NOW + timedelta(seconds=2),
        )


def test_v3_restore_rejects_prediction_support_or_source_without_state() -> None:
    predictive_map, support_mismatch = predicted_payload()
    prediction = support_mismatch["prediction"]
    assert isinstance(prediction, dict)
    counts = prediction["counts"]
    assert isinstance(counts, dict)
    kitchen = counts["kitchen"]
    assert isinstance(kitchen, dict)
    kitchen["living"] = 4.0
    with pytest.raises(ValueError, match="support exceeds"):
        restore_target_state(
            predictive_map,
            support_mismatch,
            PREDICTION_NOW + timedelta(seconds=2),
        )

    _predictive_map, forged_source = predicted_payload()
    prediction = forged_source["prediction"]
    assert isinstance(prediction, dict)
    leases = prediction["leases"]
    assert isinstance(leases, list)
    assert isinstance(leases[0], dict)
    leases[0]["source_episode_id"] = "kitchen:1:2026-07-18T11:59:59+00:00"
    snapshot = forged_source["snapshot"]
    assert isinstance(snapshot, dict)
    policies = snapshot["policy_states"]
    assert isinstance(policies, list)
    living = next(
        item
        for item in policies
        if isinstance(item, dict) and item.get("zone") == "living"
    )
    living["prediction_source_episode_id"] = leases[0]["source_episode_id"]
    with pytest.raises(ValueError, match="Episode reference"):
        restore_target_state(
            predictive_map,
            forged_source,
            PREDICTION_NOW + timedelta(seconds=2),
        )

    _predictive_map, inflated_probability = predicted_payload()
    prediction = inflated_probability["prediction"]
    snapshot = inflated_probability["snapshot"]
    assert isinstance(prediction, dict) and isinstance(snapshot, dict)
    leases = prediction["leases"]
    policies = snapshot["policy_states"]
    assert isinstance(leases, list) and isinstance(leases[0], dict)
    assert isinstance(policies, list)
    leases[0]["probability"] = 1.0
    living = next(
        item
        for item in policies
        if isinstance(item, dict) and item.get("zone") == "living"
    )
    living["prediction_probability"] = 1.0
    with pytest.raises(ValueError, match="probability exceeds"):
        restore_target_state(
            predictive_map,
            inflated_probability,
            PREDICTION_NOW + timedelta(seconds=2),
        )

    _predictive_map, competing_counts = predicted_payload()
    prediction = competing_counts["prediction"]
    assert isinstance(prediction, dict)
    counts = prediction["counts"]
    assert isinstance(counts, dict)
    kitchen = counts["kitchen"]
    assert isinstance(kitchen, dict)
    kitchen["hall"] = 100.0
    with pytest.raises(ValueError, match="probability exceeds"):
        restore_target_state(
            predictive_map,
            competing_counts,
            PREDICTION_NOW + timedelta(seconds=2),
        )

    _predictive_map, understated_support = predicted_payload()
    prediction = understated_support["prediction"]
    assert isinstance(prediction, dict)
    counts = prediction["counts"]
    assert isinstance(counts, dict)
    kitchen = counts["kitchen"]
    assert isinstance(kitchen, dict)
    kitchen["living"] = 6.0
    with pytest.raises(ValueError, match="support disagrees"):
        restore_target_state(
            predictive_map,
            understated_support,
            PREDICTION_NOW + timedelta(seconds=2),
        )

    _predictive_map, understated_probability = predicted_payload()
    prediction = understated_probability["prediction"]
    snapshot = understated_probability["snapshot"]
    assert isinstance(prediction, dict) and isinstance(snapshot, dict)
    leases = prediction["leases"]
    policies = snapshot["policy_states"]
    assert isinstance(leases, list) and isinstance(leases[0], dict)
    assert isinstance(policies, list)
    leases[0]["probability"] = 0.855
    living = next(
        item
        for item in policies
        if isinstance(item, dict) and item.get("zone") == "living"
    )
    living["prediction_probability"] = 0.855
    with pytest.raises(ValueError, match="probability disagrees"):
        restore_target_state(
            predictive_map,
            understated_probability,
            PREDICTION_NOW + timedelta(seconds=2),
        )


def test_v3_restore_rejects_mature_lease_from_isolated_source_episode() -> None:
    predictive_map = prediction_map()
    engine = ZoneModelEngine(predictive_map, 1, PREDICTION_NOW)
    seed_mature_route(engine.prediction_manager)
    engine.observe(SensorInput("binary_sensor.kitchen", "on", PREDICTION_NOW))
    payload = serialize_target_state(predictive_map, engine)
    snapshot = payload["snapshot"]
    prediction = payload["prediction"]
    assert isinstance(snapshot, dict) and isinstance(prediction, dict)
    episodes = snapshot["episode_states"]
    policies = snapshot["policy_states"]
    assert isinstance(episodes, list) and isinstance(policies, list)
    kitchen = next(
        item
        for item in episodes
        if isinstance(item, dict) and item.get("node_id") == "kitchen"
    )
    living = next(
        item
        for item in policies
        if isinstance(item, dict) and item.get("zone") == "living"
    )
    probability = 6 / 7
    source_episode_id = kitchen["episode_id"]
    prediction["leases"] = [
        {
            "source_node_id": "hall",
            "current_node_id": "kitchen",
            "target_node_id": "living",
            "target_zone": "living",
            "probability": probability,
            "support": 5.0,
            "source_episode_id": source_episode_id,
            "created_at": PREDICTION_NOW.isoformat(),
            "expires_at": (PREDICTION_NOW + timedelta(seconds=10)).isoformat(),
            "mature": True,
            "reason": "confirmed-track prediction",
        }
    ]
    living.update(
        {
            "active": True,
            "phase": "predicted",
            "activation_provenance": "prediction",
            "prediction_expires_at": (
                PREDICTION_NOW + timedelta(seconds=10)
            ).isoformat(),
            "prediction_source_episode_id": source_episode_id,
            "prediction_probability": probability,
            "prediction_support": 5.0,
        }
    )

    with pytest.raises(ValueError, match="confirmed traversal provenance"):
        restore_target_state(predictive_map, payload, PREDICTION_NOW)


def test_v3_restore_accepts_unexpired_tokens_from_overlapping_generations() -> None:
    predictive_map = target_map()
    engine = ZoneModelEngine(predictive_map, 1, NOW)
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    engine.observe(SensorInput("binary_sensor.room", "on", NOW + timedelta(seconds=2)))
    engine.observe(SensorInput("binary_sensor.room", "off", NOW + timedelta(seconds=3)))
    engine.observe(SensorInput("binary_sensor.room", "on", NOW + timedelta(seconds=33)))
    room_tokens = tuple(
        token for token in engine.snapshot.traversal_tokens if token.node_id == "room"
    )
    assert len(room_tokens) == 2
    assert len({token.episode_id for token in room_tokens}) == 2

    payload = serialize_target_state(predictive_map, engine)
    restored = restore_target_state(predictive_map, payload, engine.snapshot.updated_at)

    assert restored.snapshot == engine.snapshot
    assert (
        restored.prediction_manager.serialize() == engine.prediction_manager.serialize()
    )


def test_v3_restore_rejects_fabricated_token_path_and_pending_episode() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    engine.observe(SensorInput("binary_sensor.room", "on", NOW + timedelta(seconds=1)))
    fabricated_token = serialize_target_state(target_map(), engine)
    snapshot = fabricated_token["snapshot"]
    assert isinstance(snapshot, dict)
    tokens = snapshot["traversal_tokens"]
    assert isinstance(tokens, list)
    room = next(
        item
        for item in tokens
        if isinstance(item, dict) and item.get("node_id") == "room"
    )
    room["track_confidence"] = "confirmed"
    room["path_node_ids"] = ["missing", "hall", "room"]
    with pytest.raises(ValueError, match="unknown node"):
        restore_target_state(
            target_map(),
            fabricated_token,
            NOW + timedelta(seconds=1),
        )

    pending_source = ZoneModelEngine(target_map(), 1, NOW)
    pending_source.observe(SensorInput("binary_sensor.hall", "on", NOW))
    pending_payload = serialize_target_state(target_map(), pending_source)
    pending_snapshot = pending_payload["snapshot"]
    assert isinstance(pending_snapshot, dict)
    pending = pending_snapshot["pending_candidates"]
    assert isinstance(pending, list) and pending
    empty_payload = serialize_target_state(
        target_map(),
        ZoneModelEngine(target_map(), 1, NOW),
    )
    empty_snapshot = empty_payload["snapshot"]
    assert isinstance(empty_snapshot, dict)
    empty_snapshot["pending_candidates"] = deepcopy(pending)
    with pytest.raises(ValueError, match="Episode reference"):
        restore_target_state(target_map(), empty_payload, NOW)


@pytest.mark.parametrize("component", ("belief", "episode", "policy", "count"))
def test_v3_restore_rejects_component_newer_than_snapshot_frontier(
    component: str,
) -> None:
    payload = serialize_target_state(
        target_map(),
        ZoneModelEngine(target_map(), 1, NOW),
    )
    snapshot = payload["snapshot"]
    assert isinstance(snapshot, dict)
    future = (NOW + timedelta(seconds=10)).isoformat()
    if component == "belief":
        beliefs = snapshot["belief_states"]
        assert isinstance(beliefs, list) and isinstance(beliefs[0], dict)
        beliefs[0]["last_updated_at"] = future
    elif component == "episode":
        episodes = snapshot["episode_states"]
        assert isinstance(episodes, list) and isinstance(episodes[0], dict)
        episodes[0]["advanced_at"] = future
    elif component == "policy":
        policies = snapshot["policy_states"]
        assert isinstance(policies, list) and isinstance(policies[0], dict)
        policies[0]["last_evaluated_at"] = future
    else:
        count = snapshot["count_state"]
        assert isinstance(count, dict)
        count["last_event_at"] = future
        count["last_event_id"] = "future-count"

    with pytest.raises(ValueError, match="newer than its model frontier"):
        restore_target_state(target_map(), payload, NOW + timedelta(seconds=10))


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("belief_episode_zone", "zone-incompatible"),
        ("count_identity", "identity is incomplete"),
        ("duplicate_token", "duplicated"),
        ("token_frontier", "physical episode"),
        ("token_expiry", "physical episode"),
        ("token_provenance", "provenance is incompatible"),
        ("confirmed_without_path", "lacks a bounded path"),
        ("equivalent_strength", "strength is incompatible"),
        ("graph_path", "graph-incompatible"),
        ("missing_current", "does not exist"),
        ("noncurrent_token", "not physically current"),
        ("pending_calibration", "not bound to its episode"),
        ("outward_expiry", "calibrated bound"),
        ("refresh_expiry", "episode-derived"),
        ("missing_use_source", "source frontier"),
        ("use_before_target", "predates its target"),
        ("anonymous_support", "endpoint is incompatible"),
        ("count_conflict", "Count-conflict snapshot is incompatible"),
        ("conflict_deadline", "Count-conflict snapshot is incompatible"),
    ),
)
def test_v4_restore_rejects_cross_component_fabricated_authority(
    mutation: str,
    message: str,
) -> None:
    predictive_map = target_map()
    engine = occupied_engine()
    if mutation == "noncurrent_token":
        engine = occupied_engine()
        engine.observe(
            SensorInput("binary_sensor.hall", "off", NOW + timedelta(seconds=3))
        )
    elif mutation == "pending_calibration":
        engine = ZoneModelEngine(predictive_map, 1, NOW)
        engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    elif mutation in {
        "anonymous_support",
        "count_conflict",
        "conflict_deadline",
    }:
        predictive_map = conflict_map()
        engine = engine_with_two_front_conflict()
    payload = serialize_target_state(predictive_map, engine)
    snapshot = payload["snapshot"]
    assert isinstance(snapshot, dict)
    restore_at = datetime.fromisoformat(str(snapshot["updated_at"]))

    if mutation == "belief_episode_zone":
        beliefs = snapshot["belief_states"]
        episodes = snapshot["episode_states"]
        assert isinstance(beliefs, list) and isinstance(episodes, list)
        hall_belief = next(
            item
            for item in beliefs
            if isinstance(item, dict) and item.get("zone") == "hall"
        )
        room_episode = next(
            item
            for item in episodes
            if isinstance(item, dict) and item.get("node_id") == "room"
        )
        hall_belief["generation_episode_id"] = room_episode["episode_id"]
        hall_belief["asserted_episode_id"] = room_episode["episode_id"]
    elif mutation == "count_identity":
        count = snapshot["count_state"]
        assert isinstance(count, dict)
        count["last_event_id"] = "missing-time"
    elif mutation == "duplicate_token":
        tokens = snapshot["traversal_tokens"]
        assert isinstance(tokens, list) and tokens
        tokens.append(deepcopy(tokens[0]))
    elif mutation in {
        "token_frontier",
        "token_expiry",
        "token_provenance",
        "confirmed_without_path",
        "equivalent_strength",
        "graph_path",
    }:
        tokens = snapshot["traversal_tokens"]
        assert isinstance(tokens, list)
        token = next(item for item in tokens if isinstance(item, dict))
        if mutation == "token_frontier":
            token["accepted_at"] = (NOW + timedelta(seconds=1)).isoformat()
        elif mutation == "token_expiry":
            valid_until = datetime.fromisoformat(str(token["valid_until"]))
            token["valid_until"] = (valid_until + timedelta(seconds=1)).isoformat()
        elif mutation == "token_provenance":
            token["provenance_kind"] = "junk"
        elif mutation == "confirmed_without_path":
            token["track_confidence"] = "confirmed"
        elif mutation == "equivalent_strength":
            token["equivalent_confirmed_strength"] = True
        else:
            token["path_node_ids"] = [token["node_id"], token["node_id"]]
    elif mutation == "missing_current":
        snapshot["current_token_ids"] = ["missing"]
    elif mutation == "noncurrent_token":
        tokens = snapshot["traversal_tokens"]
        assert isinstance(tokens, list)
        hall_token = next(
            item
            for item in tokens
            if isinstance(item, dict) and item.get("node_id") == "hall"
        )
        snapshot["current_token_ids"] = [hall_token["token_id"]]
    elif mutation == "pending_calibration":
        pending = snapshot["pending_candidates"]
        assert isinstance(pending, list) and pending and isinstance(pending[0], dict)
        pending[0]["reliability"] = 0.5
    elif mutation == "outward_expiry":
        beliefs = snapshot["belief_states"]
        assert isinstance(beliefs, list)
        hall = next(
            item
            for item in beliefs
            if isinstance(item, dict) and item.get("zone") == "hall"
        )
        outward = hall["outward_context"]
        assert isinstance(outward, dict)
        outward["valid_until"] = (restore_at + timedelta(days=1)).isoformat()
    elif mutation == "refresh_expiry":
        policies = snapshot["policy_states"]
        assert isinstance(policies, list)
        room = next(
            item
            for item in policies
            if isinstance(item, dict) and item.get("zone") == "room"
        )
        dedup = room["refresh_dedup"]
        assert isinstance(dedup, list) and dedup and isinstance(dedup[0], dict)
        published_at = datetime.fromisoformat(str(dedup[0]["published_at"]))
        dedup[0]["expires_at"] = (published_at + timedelta(days=365)).isoformat()
    elif mutation in {"missing_use_source", "use_before_target"}:
        uses = snapshot["authorization_uses"]
        assert isinstance(uses, list) and uses and isinstance(uses[0], dict)
        if mutation == "missing_use_source":
            uses[0]["token_id"] = "missing"
        else:
            uses[0]["authorized_at"] = (NOW + timedelta(seconds=1)).isoformat()
    elif mutation == "anonymous_support":
        supports = snapshot["anonymous_supports"]
        assert (
            isinstance(supports, list)
            and supports
            and isinstance(supports[0], dict)
        )
        supports[0]["current_zone"] = "target"
    elif mutation == "count_conflict":
        conflicts = snapshot["count_conflicts"]
        assert (
            isinstance(conflicts, list) and conflicts and isinstance(conflicts[0], dict)
        )
        conflicts[0]["target_zone"] = "wrong"
    else:
        conflicts = snapshot["count_conflicts"]
        assert (
            isinstance(conflicts, list) and conflicts and isinstance(conflicts[0], dict)
        )
        started_at = datetime.fromisoformat(str(conflicts[0]["started_at"]))
        conflicts[0]["deadline"] = (started_at + timedelta(days=1)).isoformat()

    with pytest.raises(ValueError, match=message):
        restore_target_state(predictive_map, payload, restore_at)


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_support_field",
        "missing_binding_field",
        "duplicate_support",
        "unsorted_supports",
        "over_cap",
        "future_support",
        "graph_path",
        "missing_binding_token",
        "missing_binding_support",
        "duplicate_binding",
        "unsorted_bindings",
        "moving_without_target_binding",
        "moving_deadline_mismatch",
        "settled_with_deadline",
    ),
)
def test_v4_restore_strictly_rejects_malformed_support_tables(
    mutation: str,
) -> None:
    predictive_map = conflict_map()
    payload = serialize_target_state(
        predictive_map,
        engine_with_two_front_conflict(),
    )
    snapshot = payload["snapshot"]
    assert isinstance(snapshot, dict)
    supports = snapshot["anonymous_supports"]
    bindings = snapshot["support_token_bindings"]
    tokens = [
        *snapshot["traversal_tokens"],
        *snapshot["retained_traversal_tokens"],
    ]
    assert (
        isinstance(supports, list)
        and len(supports) == 2
        and all(isinstance(item, dict) for item in supports)
        and isinstance(bindings, list)
        and len(bindings) >= 2
        and all(isinstance(item, dict) for item in bindings)
        and all(isinstance(item, dict) for item in tokens)
    )
    first = supports[0]
    if mutation == "missing_support_field":
        first.pop("current_zone")
    elif mutation == "missing_binding_field":
        bindings[0].pop("support_id")
    elif mutation == "duplicate_support":
        supports[:] = [first, deepcopy(first)]
        bindings[:] = [
            binding
            for binding in bindings
            if binding["support_id"] == first["support_id"]
        ]
        snapshot["count_conflicts"] = []
    elif mutation == "unsorted_supports":
        supports.reverse()
        snapshot["count_conflicts"] = []
    elif mutation == "over_cap":
        extra = deepcopy(first)
        extra["support_id"] = "support:over-cap"
        supports.append(extra)
    elif mutation == "future_support":
        first["updated_at"] = (
            datetime.fromisoformat(str(snapshot["updated_at"]))
            + timedelta(microseconds=1)
        ).isoformat()
    elif mutation == "graph_path":
        other = supports[1]
        first["path_node_ids"] = [
            other["current_node_id"],
            first["current_node_id"],
        ]
    elif mutation == "missing_binding_token":
        bindings[0]["token_id"] = "missing-token"
        bindings.sort(key=lambda item: item["token_id"])
    elif mutation == "missing_binding_support":
        bindings[0]["support_id"] = "support:missing"
    elif mutation == "duplicate_binding":
        bindings.append(deepcopy(bindings[0]))
    elif mutation == "unsorted_bindings":
        bindings.reverse()
    elif mutation == "moving_without_target_binding":
        target_token = next(
            token
            for token in tokens
            if token["node_id"] == first["current_node_id"]
            and token["episode_id"] == first["current_episode_id"]
        )
        first["state"] = "moving"
        first["valid_until"] = target_token["valid_until"]
        bindings[:] = [
            binding
            for binding in bindings
            if binding["token_id"] != target_token["token_id"]
        ]
    elif mutation == "moving_deadline_mismatch":
        target_token = next(
            token
            for token in tokens
            if token["node_id"] == first["current_node_id"]
            and token["episode_id"] == first["current_episode_id"]
        )
        first["state"] = "moving"
        first["valid_until"] = (
            datetime.fromisoformat(str(target_token["valid_until"]))
            + timedelta(microseconds=1)
        ).isoformat()
    else:
        first["valid_until"] = (
            datetime.fromisoformat(str(snapshot["updated_at"]))
            + timedelta(seconds=1)
        ).isoformat()

    expected_message = (
        "unique and sorted"
        if mutation
        in {
            "duplicate_support",
            "unsorted_supports",
            "duplicate_binding",
            "unsorted_bindings",
        }
        else None
    )
    with pytest.raises(ValueError, match=expected_message):
        restore_target_state(
            predictive_map,
            payload,
            datetime.fromisoformat(str(snapshot["updated_at"])),
        )


def test_v3_restore_rejects_historical_episode_after_current_generation_start() -> None:
    predictive_map = target_map()
    engine = ZoneModelEngine(predictive_map, 1, NOW)
    engine.observe(SensorInput("binary_sensor.hall", "on", NOW))
    engine.observe(SensorInput("binary_sensor.room", "on", NOW + timedelta(seconds=2)))
    engine.observe(SensorInput("binary_sensor.room", "off", NOW + timedelta(seconds=3)))
    engine.observe(SensorInput("binary_sensor.room", "on", NOW + timedelta(seconds=33)))
    payload = serialize_target_state(predictive_map, engine)
    snapshot = payload["snapshot"]
    assert isinstance(snapshot, dict)
    episodes = snapshot["episode_states"]
    tokens = snapshot["traversal_tokens"]
    assert isinstance(episodes, list) and isinstance(tokens, list)
    current = next(
        item
        for item in episodes
        if isinstance(item, dict) and item.get("node_id") == "room"
    )
    old = next(
        item
        for item in tokens
        if isinstance(item, dict)
        and item.get("node_id") == "room"
        and item.get("episode_id") != current["episode_id"]
    )
    started_at = datetime.fromisoformat(str(current["started_at"]))
    fabricated_episode = f"room:1:{started_at.isoformat()}"
    old["episode_id"] = fabricated_episode
    old["token_id"] = f"room:{fabricated_episode}"
    old["accepted_at"] = started_at.isoformat()
    old["valid_until"] = (started_at + timedelta(seconds=90)).isoformat()

    with pytest.raises(ValueError, match="outside stored state"):
        restore_target_state(predictive_map, payload, started_at)


def test_v3_restore_rejects_extended_count_transition_and_invalid_seen_ids() -> None:
    engine = ZoneModelEngine(target_map(), 0, NOW)
    engine.observe_count(CountInput("arrival", 1, True, NOW))
    payload = serialize_target_state(target_map(), engine)
    snapshot = payload["snapshot"]
    assert isinstance(snapshot, dict)
    count = snapshot["count_state"]
    assert isinstance(count, dict)
    count["positive_transition_until"] = (NOW + timedelta(days=1)).isoformat()
    with pytest.raises(ValueError, match="transition expiry"):
        restore_target_state(target_map(), payload, NOW)

    for seen_ids in ([], ["arrival", *(f"extra-{i}" for i in range(32))]):
        invalid = serialize_target_state(target_map(), engine)
        invalid_snapshot = invalid["snapshot"]
        assert isinstance(invalid_snapshot, dict)
        invalid_count = invalid_snapshot["count_state"]
        assert isinstance(invalid_count, dict)
        invalid_count["seen_event_ids"] = seen_ids
        with pytest.raises(ValueError, match="event sequence"):
            restore_target_state(target_map(), invalid, NOW)


def test_v3_restore_rejects_zero_count_with_residual_belief_and_pending_track() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.room", "on", NOW))
    payload = serialize_target_state(target_map(), engine)
    snapshot = payload["snapshot"]
    assert isinstance(snapshot, dict)
    count_state = snapshot["count_state"]
    assert isinstance(count_state, dict)
    count_state["expected_count"] = 0

    with pytest.raises(ValueError, match="Zero-count snapshot"):
        restore_target_state(target_map(), payload, NOW)


def test_v3_restore_rejects_zero_count_unavailable_belief_context() -> None:
    engine = ZoneModelEngine(target_map(), 1, NOW)
    engine.observe(SensorInput("binary_sensor.room", "unavailable", NOW))
    payload = serialize_target_state(target_map(), engine)
    snapshot = payload["snapshot"]
    assert isinstance(snapshot, dict)
    count = snapshot["count_state"]
    assert isinstance(count, dict)
    count["expected_count"] = 0

    with pytest.raises(ValueError, match="nonbaseline belief"):
        restore_target_state(target_map(), payload, NOW)


def test_v3_zero_count_restore_accepts_only_baseline_belief_and_policy() -> None:
    empty = ZoneModelEngine(target_map(), 0, NOW)
    snapshot = empty.snapshot

    restored = ZoneModelEngine.restore(target_map(), snapshot, (), NOW)

    assert restored.snapshot == snapshot

    belief = snapshot.belief_states[0]
    residual_belief = replace(
        snapshot,
        belief_states=(
            replace(belief, log_odds=belief.log_odds + 0.1),
            *snapshot.belief_states[1:],
        ),
    )
    with pytest.raises(ValueError, match="nonbaseline belief"):
        ZoneModelEngine.restore(target_map(), residual_belief, (), NOW)

    policy = snapshot.policy_states[0]
    residual_policy = replace(
        snapshot,
        policy_states=(
            replace(policy, phase="pending"),
            *snapshot.policy_states[1:],
        ),
    )
    with pytest.raises(ValueError, match="policy authority"):
        ZoneModelEngine.restore(target_map(), residual_policy, (), NOW)


def test_zero_count_prediction_restore_rejects_lease_atomically() -> None:
    predictive_map = prediction_map()
    predicted = ZoneModelEngine(predictive_map, 1, PREDICTION_NOW)
    seed_mature_route(predicted.prediction_manager)
    predicted.observe(SensorInput("binary_sensor.office", "on", PREDICTION_NOW))
    predicted.observe(
        SensorInput(
            "binary_sensor.hall",
            "on",
            PREDICTION_NOW + timedelta(seconds=1),
        )
    )
    predicted.observe(
        SensorInput(
            "binary_sensor.kitchen",
            "on",
            PREDICTION_NOW + timedelta(seconds=2),
        )
    )
    lease_payload = predicted.prediction_manager.serialize()
    assert lease_payload["leases"]
    empty = ZoneModelEngine(predictive_map, 0, PREDICTION_NOW)
    baseline = empty.prediction_manager.serialize()

    with pytest.raises(ValueError, match="Zero-count state"):
        empty.restore_prediction_state(
            lease_payload,
            PREDICTION_NOW + timedelta(seconds=2),
        )

    assert empty.prediction_manager.serialize() == baseline


def legacy_v2_payload(*, traversal_reason: str) -> dict[str, object]:
    payload = serialize_target_state(target_map(), occupied_engine())
    payload["schema"] = "zone-belief-v2"
    payload["map_fingerprint"] = legacy_target_map_fingerprint(target_map())
    payload.pop("prediction")
    audit = payload["audit"]
    assert isinstance(audit, list)
    room_acquisition = next(
        row
        for row in audit
        if isinstance(row, dict)
        and row.get("zone") == "room"
        and row.get("event_kind") == "acquired"
    )
    room_acquisition["traversal_reason"] = traversal_reason
    return payload


def test_v2_import_preserves_only_proven_active_and_discards_inference_state() -> None:
    seed = decode_v2_seed(
        target_map(), legacy_v2_payload(traversal_reason="adjacent_current")
    )
    assert seed.active_seed["room"]
    migrated = migrate_v2_seed(
        target_map(),
        seed,
        (
            SensorInput("binary_sensor.hall", "off", NOW + timedelta(seconds=3)),
            SensorInput("binary_sensor.room", "on", NOW + timedelta(seconds=3)),
        ),
        NOW + timedelta(seconds=3),
    )
    assert next(
        state for state in migrated.snapshot.policy_states if state.zone == "room"
    ).active
    assert migrated.snapshot.traversal_tokens == ()
    assert migrated.snapshot.pending_candidates == ()
    assert migrated.prediction_manager.chain.counts["hall"]["room"] == 0.0


def test_v2_import_drops_source_free_or_unproven_active_without_public_edge() -> None:
    for reason in ("source_free_corroborated", ""):
        payload = legacy_v2_payload(traversal_reason="source_free_corroborated")
        if not reason:
            payload["audit"] = []
        seed = decode_v2_seed(target_map(), payload)
        assert not seed.active_seed["room"]
        migrated = migrate_v2_seed(
            target_map(),
            seed,
            (SensorInput("binary_sensor.room", "on", NOW + timedelta(seconds=3)),),
            NOW + timedelta(seconds=3),
        )
        room = next(
            state for state in migrated.snapshot.policy_states if state.zone == "room"
        )
        assert not room.active
        assert migrated.audit_rows == ()


def test_v2_import_rejects_incompatible_map_or_structure_atomically() -> None:
    wrong_schema = legacy_v2_payload(traversal_reason="adjacent_current")
    wrong_schema["schema"] = "wrong"
    with pytest.raises(ValueError, match="source is incompatible"):
        decode_v2_seed(target_map(), wrong_schema)

    wrong_map = legacy_v2_payload(traversal_reason="adjacent_current")
    wrong_map["map_fingerprint"] = "wrong"
    with pytest.raises(ValueError, match="map fingerprint"):
        decode_v2_seed(target_map(), wrong_map)

    malformed = legacy_v2_payload(traversal_reason="adjacent_current")
    malformed["audit"] = {}
    with pytest.raises(ValueError, match="audit"):
        decode_v2_seed(target_map(), malformed)

    wrong_zone = legacy_v2_payload(traversal_reason="adjacent_current")
    snapshot = wrong_zone["snapshot"]
    assert isinstance(snapshot, dict)
    policy_states = snapshot["policy_states"]
    assert isinstance(policy_states, list) and isinstance(policy_states[0], dict)
    policy_states[0]["zone"] = "missing"
    with pytest.raises(ValueError, match="zone is incompatible"):
        decode_v2_seed(target_map(), wrong_zone)
