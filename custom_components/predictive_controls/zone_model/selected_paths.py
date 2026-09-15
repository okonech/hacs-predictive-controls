"""Bounded selected anonymous paths, independent of belief, policy and storage.

REQ-PATH-001..004 and REQ-PATH-STATE-001. Only live episode effects enter
``observe``; startup levels enter ``reconcile`` and cannot establish origins.
Records are immutable and serializable with dataclasses.asdict. Observation
identity is (node, episode, UTC occurrence), not a slot or an unbounded counter.
Equal-time observations retain their actual order in the bounded visit tuples.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import cast

from ..model import PredictiveMap
from .types import EpisodeEffect, EpisodeState, PhysicalNode, TraversalAuthorization

_KINDS = frozenset({"positive", "correlated_positive", "interaction"})
_ORIGINS = frozenset({"none", "ordinary", "correlated", "interaction"})
_LIMIT = 4


def _utc(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Selected occurrence must be an aware UTC datetime")
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError("Selected occurrence must be UTC")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Selected identity must be a nonempty string")
    return value


def _generation(node_id: str, episode_id: str, at: datetime) -> int:
    _text(node_id)
    _text(episode_id)
    _utc(at)
    prefix = f"{node_id}:"
    if not episode_id.startswith(prefix):
        raise ValueError("Selected episode belongs to another node")
    generation, separator, timestamp = episode_id[len(prefix):].partition(":")
    if not separator or not generation.isascii() or not generation.isdecimal():
        raise ValueError("Selected episode generation is invalid")
    number = int(generation)
    if number < 1 or generation != str(number) or timestamp != at.isoformat():
        raise ValueError("Selected episode identity and occurrence disagree")
    return number


@dataclass(frozen=True)
class SelectedVisit:
    """One real physical observation; inactive history never regains authority."""

    node_id: str
    zone: str
    episode_id: str
    at: datetime
    kind: str
    branch_active: bool = True

    def __post_init__(self) -> None:
        _text(self.zone)
        _generation(self.node_id, self.episode_id, self.at)
        if self.kind not in _KINDS or type(self.branch_active) is not bool:
            raise ValueError("Selected visit kind or branch flag is invalid")


def _visit_key(visit: SelectedVisit) -> tuple[datetime, str, str, str, str, bool]:
    return (visit.at, visit.node_id, visit.zone, visit.episode_id,
            visit.kind, visit.branch_active)


@dataclass(frozen=True)
class SelectedPath:
    """One located anonymous slot with independent history and connected route.

    ``spatial_at`` changes on a different-zone move, not on resident aliases or
    interaction. ``updated_at`` includes every assigned physical observation.
    Neither confidence nor a timestamp is an occupancy-expiry deadline.
    """

    visits: tuple[SelectedVisit, ...]
    route: tuple[SelectedVisit, ...]
    spatial_at: datetime
    track_confidence: str = "provisional"
    endpoint_eligible: bool = True

    def __post_init__(self) -> None:
        _utc(self.spatial_at)
        if self.track_confidence not in {"provisional", "confirmed"}:
            raise ValueError("Selected track confidence is invalid")
        if type(self.endpoint_eligible) is not bool:
            raise ValueError("Selected endpoint eligibility must be boolean")
        for records in (self.visits, self.route):
            if type(records) is not tuple or not 1 <= len(records) <= _LIMIT:
                raise ValueError("Selected history and route require 1..4 visits")
            if any(not isinstance(item, SelectedVisit) for item in records):
                raise ValueError("Selected path contains an invalid visit")
            if len({item.episode_id for item in records}) != len(records):
                raise ValueError("Selected path repeats an observation")
            if any(a.at > b.at for a, b in zip(records, records[1:], strict=False)):
                raise ValueError("Selected observations are out of order")
            generations: dict[str, int] = {}
            for visit in records:
                generation = _generation(visit.node_id, visit.episode_id, visit.at)
                if generation <= generations.get(visit.node_id, 0):
                    raise ValueError("Selected same-node generations are out of order")
                generations[visit.node_id] = generation
        if self.visits[-1] != self.route[-1] or self.spatial_at > self.updated_at:
            raise ValueError("Selected endpoint or spatial frontier is inconsistent")
        if not self.endpoint_eligible and self.endpoint.branch_active:
            raise ValueError("Revoked endpoint cannot retain branch authority")
        # Before the first eviction, admission and every spatial frontier are
        # still observable. Once four visits are retained, an older origin may
        # legitimately be gone; never pretend bounded history proves that past.
        if len(self.visits) < _LIMIT:
            if self.visits[0].kind == "correlated_positive":
                raise ValueError("Correlation cannot admit a selected path")
        if (len(self.visits) < _LIMIT or self.spatial_at >= self.visits[0].at):
            if self.spatial_at not in {visit.at for visit in self.visits}:
                raise ValueError("Selected spatial frontier was not observed")
        if self.track_confidence == "confirmed" and len(self.visits) < 3:
            raise ValueError("Confirmed selection requires three observed visits")
        by_node: dict[str, dict[int, datetime]] = {}
        for visit in (*self.visits, *self.route):
            generation = _generation(visit.node_id, visit.episode_id, visit.at)
            times = by_node.setdefault(visit.node_id, {})
            if times.setdefault(generation, visit.at) != visit.at:
                raise ValueError("Selected generation has conflicting occurrences")
        for times in by_node.values():
            ordered = [times[generation] for generation in sorted(times)]
            if ordered != sorted(ordered):
                raise ValueError("Selected generation chronology is inconsistent")
        history = {visit.episode_id: visit for visit in self.visits}
        route = {visit.episode_id: visit for visit in self.route}
        if any(history[key] != route[key] for key in history.keys() & route.keys()):
            raise ValueError("Selected history and route disagree on a visit")
        if tuple(v.episode_id for v in self.visits if v.episode_id in route) != tuple(
            v.episode_id for v in self.route if v.episode_id in history
        ):
            raise ValueError("Selected history and route disagree on causal order")
        if any(v.branch_active and v.episode_id not in route for v in self.visits):
            raise ValueError("Retired history cannot retain branch authority")

    @property
    def endpoint(self) -> SelectedVisit:
        return self.route[-1]

    @property
    def updated_at(self) -> datetime:
        return self.visits[-1].at


def _path_key(path: SelectedPath) -> tuple[
    tuple[tuple[datetime, str, str, str, str, bool], ...],
    tuple[tuple[datetime, str, str, str, str, bool], ...], datetime, str, bool,
]:
    # Full causal records, including duplicate nodes, define canonical order.
    return (tuple(map(_visit_key, path.route)), tuple(map(_visit_key, path.visits)),
            path.spatial_at, path.track_confidence, path.endpoint_eligible)


def _canonical(
    paths: tuple[SelectedPath | None, ...],
) -> tuple[SelectedPath | None, ...]:
    located = tuple(sorted((p for p in paths if p is not None), key=_path_key))
    return located + (None,) * (len(paths) - len(located))


@dataclass(frozen=True)
class SelectedSource:
    """Latest observed generation per node, including irrevocable consumption.

    ``ordinary`` and not consumed is the only pending-origin class. The other
    classes record accounted generations but never bootstrap a pair. A count0
    observation is recorded consumed, so count increases cannot bank it.
    """

    node_id: str
    episode_id: str | None = None
    at: datetime | None = None
    origin: str = "none"
    consumed: bool = False

    def __post_init__(self) -> None:
        _text(self.node_id)
        if self.origin not in _ORIGINS or type(self.consumed) is not bool:
            raise ValueError("Selected source class or consumption is invalid")
        if self.origin == "none":
            if self.episode_id is not None or self.at is not None or self.consumed:
                raise ValueError("An unobserved source cannot carry provenance")
        else:
            if self.episode_id is None or self.at is None:
                raise ValueError("Observed source requires its episode and occurrence")
            _generation(self.node_id, self.episode_id, self.at)
            if self.origin != "ordinary" and not self.consumed:
                raise ValueError("Only ordinary observations can seed a path")


class SelectedPaths:
    """Event-driven reducer selecting at most one slot per physical positive."""

    def __init__(
        self, predictive_map: PredictiveMap,
        nodes: tuple[PhysicalNode, ...], count: int,
    ) -> None:
        if not self._valid_count(count):
            raise ValueError("Selected count must be an integer in [0, 2]")
        self._nodes = {node.node_id: node for node in nodes}
        if (len(self._nodes) != len(nodes)
            or set(self._nodes) != set(predictive_map.nodes)):
            raise ValueError("Selected nodes must exactly match the physical map")
        for node in nodes:
            configured = predictive_map.nodes[node.node_id]
            if (node.zone != configured.occupancy_zone
                    or set(node.aliases) != set(configured.entities.values())):
                raise ValueError("Selected physical node disagrees with its map")
        self._neighbors = {
            node_id: frozenset(predictive_map.neighbors(node_id))
            for node_id in self._nodes
        }
        self._count = count
        self._paths: tuple[SelectedPath | None, ...] = (None,) * count
        self._sources = {key: SelectedSource(key) for key in sorted(self._nodes)}
        self._at: datetime | None = None

    @property
    def paths(self) -> tuple[SelectedPath | None, ...]:
        return self._paths

    @property
    def sources(self) -> tuple[SelectedSource, ...]:
        return tuple(self._sources.values())

    @property
    def covered_nodes(self) -> frozenset[str]:
        return frozenset(
            visit.node_id for path in self._paths if path is not None
            for visit in path.route if visit.branch_active or visit == path.endpoint
        )

    @property
    def covered_zones(self) -> frozenset[str]:
        return frozenset(self._nodes[node_id].zone for node_id in self.covered_nodes)

    @staticmethod
    def _valid_count(count: object) -> bool:
        return type(count) is int and 0 <= count <= 2

    def _matches(self, state: EpisodeState | None, node_id: str) -> bool:
        node = self._nodes[node_id]
        return bool(
            state is not None and state.node_id == node_id and state.zone == node.zone
            and state.profile_name == node.profile_name
            and len(state.alias_states) == len(node.aliases)
            and {alias for alias, _ in state.alias_states} == set(node.aliases)
        )

    def _adjacent(self, source: SelectedVisit, target: SelectedVisit) -> bool:
        return source.zone == target.zone or target.node_id in self._neighbors[
            source.node_id
        ]

    def reconcile(self, states: tuple[EpisodeState, ...], at: datetime) -> None:
        """Revoke branch/origin authority only; never infer visits from raw levels.

        Clear withdraws branch coverage even at an endpoint, but that endpoint
        remains covered and can continue after OFF. Unknown/mismatched endpoints
        stay located without supplying neighboring authority until fresh evidence.
        Revoked flags never become true again on a timer or an alias callback.
        """
        _utc(at)
        if self._at is not None and at < self._at:
            return
        current = {state.node_id: state for state in states}
        if len(current) != len(states):
            raise ValueError("Selected reconciliation repeats a physical node")
        if any(
            frontier is not None and _utc(frontier) > at for state in states
            for frontier in (state.started_at, state.last_event_at, state.advanced_at)
        ):
            raise ValueError("Selected reconciliation cannot use future episode state")

        def eligible(node_id: str, episode_id: str | None, *, live: bool) -> bool:
            state = current.get(node_id)
            return bool(
                self._matches(state, node_id) and state is not None
                and state.episode_id == episode_id
                and state.status not in {"baseline", "clear", "unavailable"}
                and (not live or state.known_on)
            )

        def prune(visit: SelectedVisit) -> SelectedVisit:
            if visit.branch_active and not eligible(
                visit.node_id, visit.episode_id, live=False,
            ):
                return replace(visit, branch_active=False)
            return visit

        def endpoint_eligible(path: SelectedPath) -> bool:
            endpoint = path.endpoint
            state = current.get(endpoint.node_id)
            return bool(
                path.endpoint_eligible and self._matches(state, endpoint.node_id)
                and state is not None and state.episode_id == endpoint.episode_id
                and state.status not in {"baseline", "unavailable"}
            )

        self._paths = _canonical(tuple(
            None if path is None else replace(
                path, visits=tuple(map(prune, path.visits)),
                route=tuple(map(prune, path.route)),
                endpoint_eligible=endpoint_eligible(path),
            ) for path in self._paths
        ))
        self._sources = {
            node_id: replace(source, consumed=True)
            if source.origin == "ordinary" and not source.consumed
            and not eligible(node_id, source.episode_id, live=True) else source
            for node_id, source in self._sources.items()
        }
        self._at = at

    def _fresh(self, effect: EpisodeEffect, state: EpisodeState) -> bool:
        if effect.kind not in _KINDS or effect.node_id not in self._nodes:
            return False
        if (not self._matches(state, effect.node_id)
                or effect.zone != state.zone or effect.episode_id != state.episode_id
                or state.started_at != effect.at or state.last_event_at != effect.at
                or (self._at is not None and effect.at < self._at)):
            return False
        generation = _generation(effect.node_id, effect.episode_id, effect.at)
        if generation != state.generation:
            return False
        if effect.kind == "interaction":
            return bool(self._nodes[effect.node_id].interaction_aliases
                        and state.status == "clearing")
        return bool(not self._nodes[effect.node_id].interaction_aliases
                    and state.known_on and state.status == "asserted"
                    and state.cadence_correlated
                    == (effect.kind == "correlated_positive"))

    def _accounted(self, effect: EpisodeEffect) -> bool:
        previous = self._sources[effect.node_id]
        if previous.at is None or previous.episode_id is None:
            return False
        return (effect.at < previous.at or _generation(
            effect.node_id, effect.episode_id, effect.at,
        ) <= _generation(previous.node_id, previous.episode_id, previous.at))

    @staticmethod
    def _visit(effect: EpisodeEffect) -> SelectedVisit:
        return SelectedVisit(effect.node_id, effect.zone, effect.episode_id,
                             effect.at, effect.kind)

    def _eligible_sources(
        self, target: SelectedVisit, states: dict[str, EpisodeState],
    ) -> tuple[tuple[SelectedPath, int], ...]:
        """The identical reconciled generation/flag basis for movement and diagnosis."""
        sources: list[tuple[SelectedPath, int]] = []
        for path in self._paths:
            if path is None:
                continue
            endpoint = path.endpoint
            state = states.get(endpoint.node_id)
            # Fresh exact-node evidence may rebind a retained OFF/unknown endpoint.
            usable = endpoint.node_id == target.node_id or bool(
                path.endpoint_eligible
                and self._matches(state, endpoint.node_id) and state is not None
                and state.episode_id == endpoint.episode_id
                and state.status not in {"baseline", "unavailable"}
            )
            if usable:
                sources.append((path, len(path.route) - 1))
            for index, visit in enumerate(path.route[:-1]):
                if visit.branch_active:
                    sources.append((path, index))
        return tuple(sources)

    def unsupported_jump(
        self, effect: EpisodeEffect, state: EpisodeState,
        before: tuple[EpisodeState, ...],
    ) -> bool:
        """Read-only candidate, captured before observe consumes this generation.

        No reconstructed route or intermediate visit is returned. The caller must
        still reject this candidate when any legitimate authorization succeeds.
        """
        if (not self._count or effect.kind not in {"positive", "correlated_positive"}
                or not self._fresh(effect, state) or self._accounted(effect)):
            return False
        target = self._visit(effect)
        states = {item.node_id: item for item in before}
        for path, index in self._eligible_sources(target, states):
            source = path.route[index]
            if self._adjacent(source, target):
                continue
            if any(target.node_id in self._neighbors[middle]
                   for middle in self._neighbors[source.node_id]):
                return True
        return False

    def _continuation(
        self, target: SelectedVisit, states: dict[str, EpisodeState],
    ) -> tuple[SelectedPath, int] | None:
        endpoints: list[SelectedPath] = []
        branches: list[tuple[SelectedPath, int]] = []
        for path, index in self._eligible_sources(target, states):
            if not self._adjacent(path.route[index], target):
                continue
            if index == len(path.route) - 1:
                endpoints.append(path)
            else:
                branches.append((path, index))
        if endpoints:
            residents = [p for p in endpoints if p.endpoint.zone == target.zone]
            if residents:
                latest_resident = max(p.updated_at for p in residents)
                incoming = [p for p in endpoints if p.endpoint.zone != target.zone
                            and p.spatial_at > latest_resident]
                endpoints = incoming or residents
            selected = max(endpoints, key=lambda p: (p.updated_at, _path_key(p)))
            return selected, len(selected.route) - 1
        return max(branches, key=lambda item: (
            item[0].route[item[1]].at, item[0].updated_at,
            _path_key(item[0]), item[1],
        ), default=None)

    def _origin(
        self, target: SelectedVisit, states: dict[str, EpisodeState],
    ) -> SelectedVisit | None:
        candidates: list[SelectedVisit] = []
        for source in self._sources.values():
            if (source.origin != "ordinary" or source.consumed
                    or source.node_id == target.node_id):
                continue
            state = states.get(source.node_id)
            # Same-basis reconciliation already consumed every ineligible origin.
            assert state is not None
            assert source.episode_id is not None and source.at is not None
            visit = SelectedVisit(source.node_id, state.zone, source.episode_id,
                                  source.at, "positive")
            if self._adjacent(visit, target):
                candidates.append(visit)
        return max(candidates, key=_visit_key, default=None)

    def _advance_path(
        self, old: SelectedPath, index: int, target: SelectedVisit,
    ) -> SelectedPath:
        # Truncate at the actual selected occurrence BEFORE append/bounding.
        route = (*old.route[:index + 1], target)[-_LIMIT:]
        retained = {v.episode_id for v in route}
        visits = tuple(
            v if v.episode_id in retained else replace(v, branch_active=False)
            for v in (*old.visits, target)[-_LIMIT:]
        )
        confidence = old.track_confidence
        if target.kind == "positive" and len(route) >= 3:
            a, b, c = route[-3:]
            if (len({a.node_id, b.node_id, c.node_id}) == 3
                    and a.zone != b.zone and b.zone != c.zone):
                confidence = "confirmed"
        spatial_at = (target.at if target.zone != old.endpoint.zone
                      else old.spatial_at)
        return SelectedPath(visits, route, spatial_at, confidence)

    def _install(self, path: SelectedPath, old: SelectedPath | None = None) -> None:
        slots = list(self._paths)
        if old is not None:
            index = slots.index(old)
        elif None in slots:
            index = slots.index(None)
        else:
            index = min(range(len(slots)), key=lambda i: self._weakness(slots[i]))
        slots[index] = path
        self._paths = _canonical(tuple(slots))

    @staticmethod
    def _weakness(path: SelectedPath | None) -> tuple[object, ...]:
        if path is None:
            return (0,)
        return (1, path.track_confidence == "confirmed",
            path.spatial_at, _path_key(path))

    def _record(self, effect: EpisodeEffect, *, consumed: bool) -> None:
        origin = {"positive": "ordinary", "correlated_positive": "correlated",
                  "interaction": "interaction"}[effect.kind]
        self._sources[effect.node_id] = SelectedSource(
            effect.node_id, effect.episode_id, effect.at, origin,
            consumed or origin != "ordinary",
        )

    def observe(
        self, effect: EpisodeEffect, state: EpisodeState,
        states: tuple[EpisodeState, ...],
        *, before: tuple[EpisodeState, ...] | None = None,
    ) -> TraversalAuthorization | None:
        """Select from PRE-event ledger before recording the new target origin.

        The caller must not supply bootstrap observations as live effects. A
        nonmatching/duplicate/flap effect cannot assign a slot or rearm a source.
        Legacy authorization runs only after this returns None, then may be adopted.
        """
        if not self._fresh(effect, state) or self._accounted(effect):
            return None
        current = {item.node_id: item for item in states}
        if len(current) != len(states) or current.get(state.node_id) != state:
            raise ValueError("Selected observation requires the current target state")
        # The engine supplies deadline-reconciled physical states immediately
        # before this input. They preserve only operation-local prior-generation
        # eligibility; final current-state reconciliation occurs before return.
        basis = states if before is None else before
        self.reconcile(basis, effect.at)
        current = {item.node_id: item for item in basis}
        if not self._count:
            self._record(effect, consumed=True)
            self.reconcile(states, effect.at)
            return None
        target = self._visit(effect)
        continuation = self._continuation(target, current)
        old: SelectedPath | None = None
        source: SelectedVisit | None = None
        if continuation is not None:
            old, index = continuation
            source = old.route[index]
            path = self._advance_path(old, index, target)
        else:
            source = self._origin(target, current)
            if source is not None:
                path = SelectedPath((source, target), (source, target), target.at)
            elif effect.kind == "interaction":
                path = SelectedPath((target,), (target,), target.at)
            else:
                self._record(effect, consumed=False)
                self.reconcile(states, effect.at)
                return None
        authorization = TraversalAuthorization(
            effect.node_id, effect.zone, effect.episode_id, effect.at,
            True, "selected_path", track_confidence=path.track_confidence,
            path_node_ids=tuple(v.node_id for v in path.route[-3:]),
            provenance_kind="selected_path",
            selected_source_episode_ids=() if source is None else (source.episode_id,),
        )
        self._install(path, old)
        if source is not None:
            record = self._sources[source.node_id]
            if record.episode_id == source.episode_id:
                self._sources[source.node_id] = replace(record, consumed=True)
        self._record(effect, consumed=True)
        self.reconcile(states, effect.at)
        return authorization

    def adopt(
        self, effect: EpisodeEffect, state: EpisodeState,
        authorization: TraversalAuthorization,
    ) -> None:
        """Record an independently authorized ordinary target, not its token past.

        Correlation/prediction cannot create a new selected slot. The just-recorded
        ordinary pending origin proves observe ran first and returned None. Its
        consumption also makes adoption idempotent after replacement or restart.
        """
        if (not self._count or not self._fresh(effect, state)
            or effect.kind != "positive"):
            return
        source = self._sources[effect.node_id]
        if (source.episode_id != effect.episode_id or source.consumed
                or source.origin != "ordinary" or self._at != effect.at
                or not authorization.authorized
                or authorization.reason in {"selected_path", "prediction_authorized"}
                or authorization.provenance_kind in {"selected_path", "prediction"}
                or authorization.target_node_id != effect.node_id
                or authorization.target_zone != effect.zone
                or authorization.target_episode_id != effect.episode_id
                or authorization.authorized_at != effect.at):
            return
        target = self._visit(effect)
        self._install(SelectedPath((target,), (target,), target.at))
        self._record(effect, consumed=True)

    def set_count(self, count: int, at: datetime) -> None:
        """Invalid counts retain N; reduction is not an observed departure."""
        _utc(at)
        if not self._valid_count(count) or (self._at is not None and at < self._at):
            return
        slots = list(self._paths)
        while len(slots) > count:
            index = min(range(len(slots)), key=lambda i: self._weakness(slots[i]))
            slots.pop(index)
        slots.extend([None] * (count - len(slots)))
        self._paths = _canonical(tuple(slots))
        self._count = count
        self._at = at
        if not count:
            self._sources = {
                key: replace(source, consumed=True)
                if source.origin != "none" else source
                for key, source in self._sources.items()
            }

    def restore(
        self, paths: tuple[SelectedPath | None, ...],
        sources: tuple[SelectedSource, ...], at: datetime,
    ) -> None:
        """Validate the entire snapshot before replacing any reducer state.

        Episode-state reconciliation is a separate revoke-only step, so map/raw
        mismatches cannot manufacture a visit while restoring held endpoints.
        """
        _utc(at)
        if (type(paths) is not tuple or len(paths) != self._count
                or any(p is not None and not isinstance(p, SelectedPath) for p in paths)
                or type(sources) is not tuple
                or any(not isinstance(s, SelectedSource) for s in sources)):
            raise ValueError("Selected snapshot cardinality or record type is invalid")
        if (tuple(s.node_id for s in sources) != tuple(sorted(self._nodes))
                or paths != _canonical(paths)):
            raise ValueError("Selected snapshot node set or ordering is invalid")
        records = {s.node_id: s for s in sources}
        for source in sources:
            source.__post_init__()
            if source.origin != "none" and (
                (source.origin == "interaction")
                != bool(self._nodes[source.node_id].interaction_aliases)
            ):
                raise ValueError("Selected source physical class disagrees with map")
            if source.at is not None and source.at > at:
                raise ValueError("Selected source occurs after restore")
            if not self._count and source.origin != "none" and not source.consumed:
                raise ValueError("Count zero cannot retain usable origins")
        accounted: set[str] = set()
        occurrences: dict[tuple[str, int], str] = {}
        chronology: dict[str, dict[int, datetime]] = {
            source.node_id: {
                _generation(source.node_id, source.episode_id, source.at): source.at,
            } for source in sources
            if source.episode_id is not None and source.at is not None
        }
        for path in paths:
            if path is None:
                continue
            path.__post_init__()
            if path.updated_at > at:
                raise ValueError("Selected path occurs after restore")
            local: set[str] = set()
            for visit in (*path.visits, *path.route):
                visit.__post_init__()
                node = self._nodes.get(visit.node_id)
                if node is None or node.zone != visit.zone:
                    raise ValueError("Selected visit is incompatible with map")
                if (visit.kind == "interaction") != bool(node.interaction_aliases):
                    raise ValueError("Selected visit physical class disagrees with map")
                if visit.episode_id in accounted:
                    raise ValueError("One observation cannot belong to multiple paths")
                local.add(visit.episode_id)
                source = records[visit.node_id]
                if source.episode_id is None or source.at is None:
                    raise ValueError("Selected visit lacks its consumption ledger")
                generation = _generation(visit.node_id, visit.episode_id, visit.at)
                latest = _generation(source.node_id, source.episode_id, source.at)
                chronology[visit.node_id][generation] = visit.at
                identity = visit.node_id, generation
                if (occurrences.setdefault(identity, visit.episode_id)
                    != visit.episode_id):
                    raise ValueError("Selected generation has conflicting occurrences")
                if latest < generation or source.at < visit.at:
                    raise ValueError("Selected visit is newer than its source ledger")
                if latest > generation and (
                    visit.branch_active
                    or (visit == path.endpoint and path.endpoint_eligible)
                ):
                    raise ValueError("Superseded generation cannot supply authority")
                if latest == generation and (
                    source.episode_id != visit.episode_id or not source.consumed
                    or source.origin != {"positive": "ordinary",
                                         "correlated_positive": "correlated",
                                         "interaction": "interaction"}[visit.kind]
                ):
                    raise ValueError("Selected visit is not accounted by its ledger")
            accounted.update(local)
            if any(not self._adjacent(a, b) for a, b in zip(
                path.route, path.route[1:], strict=False,
            )):
                raise ValueError("Selected route contains an unobserved graph edge")
        for times in chronology.values():
            ordered = [times[generation] for generation in sorted(times)]
            if ordered != sorted(ordered):
                raise ValueError("Selected generation chronology differs across paths")
        self._paths = paths
        self._sources = records
        self._at = at


def _object(value: object, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("Selected JSON record has missing or unexpected fields")
    return cast(dict[str, object], value)


def _array(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Selected JSON collection must be a list")
    return value


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Selected JSON timestamp must be an ISO string")
    try:
        return _utc(datetime.fromisoformat(value))
    except ValueError as exc:
        raise ValueError("Selected JSON timestamp must be aware UTC") from exc


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise ValueError("Selected JSON flag must be boolean")
    return value


def _decode_visit(value: object) -> SelectedVisit:
    data = _object(value, {
        "node_id", "zone", "episode_id", "at", "kind", "branch_active",
    })
    return SelectedVisit(_text(data["node_id"]), _text(data["zone"]),
                         _text(data["episode_id"]), _timestamp(data["at"]),
                         _text(data["kind"]), _boolean(data["branch_active"]))


def decode_paths(value: object) -> tuple[SelectedPath | None, ...]:
    """Strict JSON leaves; map/count/ledger validation belongs to restore."""
    result: list[SelectedPath | None] = []
    for item in _array(value):
        if item is None:
            result.append(None)
            continue
        data = _object(item, {
            "visits", "route", "spatial_at", "track_confidence", "endpoint_eligible",
        })
        result.append(SelectedPath(
            tuple(_decode_visit(v) for v in _array(data["visits"])),
            tuple(_decode_visit(v) for v in _array(data["route"])),
            _timestamp(data["spatial_at"]), _text(data["track_confidence"]),
            _boolean(data["endpoint_eligible"]),
        ))
    paths = tuple(result)
    if len(paths) > 2 or paths != _canonical(paths):
        raise ValueError("Selected JSON paths are not bounded and canonical")
    return paths


def decode_sources(value: object) -> tuple[SelectedSource, ...]:
    """Decode one canonical consumption record per node, never infer an origin."""
    result: list[SelectedSource] = []
    for item in _array(value):
        data = _object(item, {"node_id", "episode_id", "at", "origin", "consumed"})
        result.append(SelectedSource(
            _text(data["node_id"]),
            None if data["episode_id"] is None else _text(data["episode_id"]),
            None if data["at"] is None else _timestamp(data["at"]),
            _text(data["origin"]), _boolean(data["consumed"]),
        ))
    ids = tuple(item.node_id for item in result)
    if ids != tuple(sorted(set(ids))):
        raise ValueError("Selected JSON sources must have unique canonical node order")
    return tuple(result)
