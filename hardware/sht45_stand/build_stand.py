"""Export the adjustable SHT45 stand as a watertight, millimetre-scale STL."""

import argparse
from collections import Counter
from itertools import product
from math import hypot, sqrt
from pathlib import Path


def stand_boxes(height, slot_bottom, slot_top, slot_width):
    if not 12 <= slot_bottom < slot_top <= height - 5 or not 3.2 <= slot_width <= 6:
        raise ValueError('Slot must leave room for the base, bridge and side walls')
    half = slot_width / 2
    return [(-38, 38, 0, 55, 0, 4),          # Base
            (-12, -half, 14, 21, 4, height),  # Left side of the upright
            (half, 12, 14, 21, 4, height),    # Right side of the upright
            (-half, half, 14, 21, 4, slot_bottom),
            (-half, half, 14, 21, slot_top, height),
            (-15, 15, 10, 25, 4, 8)]         # Foot reinforcement


BASE_HOLE_CENTERS = tuple(product((-26, 26), (11, 44)))


def round_base_holes(boxes, diameter):
    if not 3 <= diameter <= 6:
        raise ValueError('Base screw hole diameter must be between 3 and 6 mm')
    radius = diameter / 2
    cuts = [(x - radius, x + radius, y - radius, y + radius, 0, 4) for x, y in BASE_HOLE_CENTERS]
    offsets = [radius * i / 4 for i in range(-3, 4)]
    subdivisions = ([x + offset for x, _ in BASE_HOLE_CENTERS for offset in offsets],
                    [y + offset for _, y in BASE_HOLE_CENTERS for offset in offsets], [])

    def transform(point):
        x, y, z = point
        for cx, cy in BASE_HOLE_CENTERS:
            dx, dy = x - cx, y - cy
            if z <= 4 and abs(max(abs(dx), abs(dy)) - radius) < 1e-8:
                distance = hypot(dx, dy)
                return cx + dx * radius / distance, cy + dy * radius / distance, z
        return point

    return [(normal, tuple(transform(point) for point in tri))
            for normal, tri in mesh(boxes, cuts, subdivisions)]


def contains(box, point):
    return all(box[2 * axis] < point[axis] < box[2 * axis + 1] for axis in range(3))


def mesh(boxes, cuts=(), subdivisions=((), (), ())):
    axes = [sorted({box[axis * 2 + side] for box in [*boxes, *cuts] for side in (0, 1)}
                   | set(subdivisions[axis])) for axis in range(3)]
    solid = set()
    for cell in product(*(range(len(coords) - 1) for coords in axes)):
        mid = [(axis[i] + axis[i + 1]) / 2 for axis, i in zip(axes, cell, strict=True)]
        if any(contains(box, mid) for box in boxes) and not any(contains(cut, mid) for cut in cuts):
            solid.add(cell)
    triangles = []
    for cell in sorted(solid):
        for axis in range(3):
            for side in (-1, 1):
                neighbour = list(cell)
                neighbour[axis] += side
                if tuple(neighbour) in solid:
                    continue
                u, v = (axis + 1) % 3, (axis + 2) % 3
                corners = []
                for a, b in ((0, 0), (1, 0), (1, 1), (0, 1)):
                    point = list(cell)
                    point[axis] += int(side == 1)
                    point[u] += a
                    point[v] += b
                    corners.append(tuple(coords[i] for coords, i in zip(axes, point, strict=True)))
                if side < 0:
                    corners.reverse()
                normal = tuple(side if i == axis else 0 for i in range(3))
                triangles.extend((normal, (corners[0], corners[i], corners[i + 1])) for i in (1, 2))
    return triangles


def write_stl(triangles, output):
    edges = Counter(tuple(sorted((a, b))) for _, points in triangles
                    for a, b in zip(points, points[1:] + points[:1]))
    if not edges or any(count != 2 for count in edges.values()):
        raise ValueError('Mesh must be closed')
    with output.open('w', encoding='ascii', newline='\n') as file:
        file.write('solid sht45_stand\n')
        for _, points in triangles:
            a, b, c = points
            u, v = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
            cross = [u[(i + 1) % 3] * v[(i + 2) % 3] - u[(i + 2) % 3] * v[(i + 1) % 3] for i in range(3)]
            length = sqrt(sum(value * value for value in cross))
            normal = [value / length for value in cross]
            file.write('  facet normal {:g} {:g} {:g}\n    outer loop\n'.format(*normal))
            for point in points:
                file.write('      vertex {:.8g} {:.8g} {:.8g}\n'.format(*point))
            file.write('    endloop\n  endfacet\n')
        file.write('endsolid sht45_stand\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--height', type=float, default=105)
    parser.add_argument('--slot-bottom', type=float, default=20)
    parser.add_argument('--slot-top', type=float, default=95)
    parser.add_argument('--slot-width', type=float, default=3.6)
    parser.add_argument('--base-hole-diameter', type=float, default=3.6)
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('SHT45_stand_taban_kol.stl'))
    args = parser.parse_args()
    triangles = round_base_holes(stand_boxes(args.height, args.slot_bottom, args.slot_top, args.slot_width),
                                args.base_hole_diameter)
    write_stl(triangles, args.output)
    print(f'{args.output}: {len(triangles)} triangles, 76 x 55 x {args.height:g} mm')


if __name__ == '__main__':
    main()
