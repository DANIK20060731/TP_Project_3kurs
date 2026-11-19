"""Целочисленный максимальный поток по алгоритму Диница."""

from collections import deque
from dataclasses import dataclass


@dataclass(slots=True)
class Edge:
    """Остаточная ёмкость ребра и индекс обратного ребра."""

    target: int
    reverse: int
    capacity: int


class Network:
    """Сеть с целочисленными ёмкостями."""

    def __init__(self, size: int) -> None:
        self.edges: list[list[Edge]] = [[] for _ in range(size)]

    def add_vertex(self) -> int:
        index = len(self.edges)
        self.edges.append([])
        return index

    def add_edge(self, source: int, target: int, capacity: int) -> Edge:
        edge = Edge(target, len(self.edges[target]), capacity)
        reverse = Edge(source, len(self.edges[source]), 0)
        self.edges[source].append(edge)
        self.edges[target].append(reverse)
        return edge

    def _levels(self, source: int) -> list[int]:
        levels = [-1] * len(self.edges)
        levels[source] = 0
        queue = deque([source])
        while queue:
            vertex = queue.popleft()
            for edge in self.edges[vertex]:
                if edge.capacity and levels[edge.target] == -1:
                    levels[edge.target] = levels[vertex] + 1
                    queue.append(edge.target)
        return levels

    def _augment(
        self, source: int, sink: int, levels: list[int], next_edges: list[int], limit: int
    ) -> int:
        path: list[tuple[int, Edge]] = []
        vertex = source
        while vertex != sink:
            edges = self.edges[vertex]
            while next_edges[vertex] < len(edges):
                edge = edges[next_edges[vertex]]
                if edge.capacity and levels[edge.target] == levels[vertex] + 1:
                    path.append((vertex, edge))
                    vertex = edge.target
                    break
                next_edges[vertex] += 1
            else:
                if not path:
                    return 0
                vertex, _ = path.pop()
                next_edges[vertex] += 1

        amount = min(limit, min(edge.capacity for _, edge in path))
        for _, edge in path:
            edge.capacity -= amount
            self.edges[edge.target][edge.reverse].capacity += amount
        return amount

    def max_flow(self, source: int, sink: int, required: int) -> int:
        """Наращивает поток до required или до исчерпания остаточных путей."""
        flow = 0
        while flow < required:
            levels = self._levels(source)
            if levels[sink] == -1:
                return flow
            next_edges = [0] * len(self.edges)
            while flow < required:
                added = self._augment(source, sink, levels, next_edges, required - flow)
                if not added:
                    break
                flow += added
        return flow
