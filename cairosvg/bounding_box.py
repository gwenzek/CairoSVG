# This file is part of CairoSVG
# Copyright © 2010-2016 Kozea
#
# This library is free software: you can redistribute it and/or modify it under
# the terms of the GNU Lesser General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# This library is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more
# details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with CairoSVG.  If not, see <http://www.gnu.org/licenses/>.

"""
Calculate bounding box for SVG shapes and paths.

A bounding box is a (minx, miny, width, height) tuple.

"""

from math import isinf, fmod, pi, radians, sin, cos, tan, acos, atan, sqrt

from .helpers import PATH_LETTERS, normalize, point
from .defs import parse_url
from .parser import Tree
from .features import match_features


EMPTY_BOUNDING_BOX = float('inf'), float('inf'), 0, 0


def calculate_bounding_box(node):
    """Calculate ``node``'s bounding box.

    See https://www.w3.org/TR/SVG/coords.html#ObjectBoundingBox

    """
    if 'bounding_box' not in node and node.tag in BOUNDING_BOX_METHODS:
        bounding_box = BOUNDING_BOX_METHODS[node.tag](node)
        if is_non_empty_bounding_box(bounding_box):
            node['bounding_box'] = bounding_box
    return node.get('bounding_box')


def bounding_box_rect(node):
    """Get the bounding box of a ``rect`` node."""
    x = float(node.get('x', '0'))
    y = float(node.get('y', '0'))
    width = max(float(node.get('width', '0')), 0)
    height = max(float(node.get('height', '0')), 0)
    return x, y, width, height


def bounding_box_circle(node):
    """Get the bounding box of a ``circle`` node."""
    center_x = float(node.get('cx', '0'))
    center_y = float(node.get('cy', '0'))
    radius = max(float(node.get('r', '0')), 0)
    return center_x - radius, center_y - radius, 2 * radius, 2 * radius


def bounding_box_ellipse(node):
    """Get the bounding box of an ``ellipse`` node."""
    center_x = float(node.get('cx', '0'))
    center_y = float(node.get('cy', '0'))
    radius_x = max(float(node.get('rx', '0')), 0)
    radius_y = max(float(node.get('ry', '0')), 0)
    return center_x - radius_x, center_y - radius_y, 2 * radius_x, 2 * radius_y


def bounding_box_line(node):
    """Get the bounding box of a ``line`` node."""
    x1 = float(node.get('x1', '0'))
    y1 = float(node.get('y1', '0'))
    x2 = float(node.get('x2', '0'))
    y2 = float(node.get('y2', '0'))
    x, y = min(x1, x2), min(y1, y2)
    width, height = max(x1, x2) - x, max(y1, y2) - y
    return x, y, width, height


def bounding_box_polyline(node):
    """Get the bounding box of a ``polyline`` or ``polygon`` node."""
    bounding_box = EMPTY_BOUNDING_BOX
    points = []
    normalized_points = normalize(node.get('points', ''))
    while points:
        x, y, normalized_points = point(None, normalized_points)
        points.append((float(x), float(y)))
    return extend_bounding_box(bounding_box, points)


def bounding_box_path(node):
    """Get the bounding box of a ``path`` node."""
    path_data = node.get('d', '')

    # Normalize path data for correct parsing
    for letter in PATH_LETTERS:
        path_data = path_data.replace(letter, ' {} '.format(letter))
    path_data = normalize(path_data)

    bounding_box = EMPTY_BOUNDING_BOX
    previous_x = 0
    previous_y = 0
    letter = 'M'    # Move as default
    while path_data:
        path_data = path_data.strip()
        if path_data.split(' ', 1)[0] in PATH_LETTERS:
            letter, path_data = (path_data + ' ').split(' ', 1)

        if letter in 'aA':
            # Elliptical arc curve
            rx, ry, path_data = point(None, path_data)
            rotation, path_data = path_data.split(' ', 1)
            rotation = radians(float(rotation))

            # The large and sweep values are not always separated from the
            # following values, here is the crazy parser
            large, path_data = path_data[0], path_data[1:].strip()
            while not large[-1].isdigit():
                large, path_data = large + path_data[0], path_data[1:].strip()
            sweep, path_data = path_data[0], path_data[1:].strip()
            while not sweep[-1].isdigit():
                sweep, path_data = sweep + path_data[0], path_data[1:].strip()

            large, sweep = bool(int(large)), bool(int(sweep))

            x, y, path_data = point(None, path_data)

            # Relative coordinate, convert to absolute
            if letter == 'a':
                x += previous_x
                y += previous_y

            # Only extend bounding box with end coordinate
            arc_bounding_box = bounding_box_elliptical_arc(
                previous_x, previous_y, rx, ry, rotation, large, sweep, x, y)
            points = (arc_bounding_box[0:2], arc_bounding_box[2:])
            bounding_box = extend_bounding_box(bounding_box, points)
            previous_x = x
            previous_y = y

        elif letter in 'cC':
            # Curve
            x1, y1, path_data = point(None, path_data)
            x2, y2, path_data = point(None, path_data)
            x, y, path_data = point(None, path_data)

            # Relative coordinates, convert to absolute
            if letter == 'c':
                x1 += previous_x
                y1 += previous_y
                x2 += previous_x
                y2 += previous_y
                x += previous_x
                y += previous_y

            # Extend bounding box with all coordinates
            bounding_box = extend_bounding_box(
                bounding_box, ((x1, y1), (x2, y2), (x, y)))
            previous_x = x
            previous_y = y

        elif letter in 'hH':
            # Horizontal line
            x, path_data = (path_data + ' ').split(' ', 1)

            # Relative coordinate, convert to absolute
            if letter == 'h':
                x += previous_x

            # Extend bounding box with coordinate
            bounding_box = extend_bounding_box(
                bounding_box, ((x, previous_y),))
            previous_x = x

        elif letter in 'lLmMtT':
            # Line/Move/Smooth quadratic curve
            x, y, path_data = point(None, path_data)

            # Relative coordinate, convert to absolute
            if letter in 'lmt':
                x += previous_x
                y += previous_y

            # Extend bounding box with coordinate
            bounding_box = extend_bounding_box(bounding_box, ((x, y),))
            previous_x = x
            previous_y = y

        elif letter in 'qQsS':
            # Quadratic curve/Smooth curve
            x1, y1, path_data = point(None, path_data)
            x, y, path_data = point(None, path_data)

            # Relative coordinates, convert to absolute
            if letter in 'qs':
                x1 += previous_x
                y1 += previous_y
                x += previous_x
                y += previous_y

            # Extend bounding box with coordinates
            bounding_box = extend_bounding_box(
                bounding_box, ((x1, y1), (x, y)))
            previous_x = x
            previous_y = y

        elif letter in 'vV':
            # Vertical line
            y, path_data = (path_data + ' ').split(' ', 1)

            # Relative coordinate, convert to absolute
            if letter == 'v':
                y += previous_y

            # Extend bounding box with coordinate
            bounding_box = extend_bounding_box(
                bounding_box, ((previous_x, y),))
            previous_y = y

        path_data = path_data.strip()

    return bounding_box


def bounding_box_text(node):
    """Get the bounding box of a ``text`` node."""
    return node.get('text_bounding_box')


def angle(bx, by):
    """Get the angle between vector (1,0) and vector (bx,by)."""
    return fmod(
        2 * pi + (1 if by > 0 else -1) * acos(bx / sqrt(bx * bx + by * by)),
        2 * pi)


def bounding_box_elliptical_arc(x1, y1, rx, ry, phi, large, sweep, x, y):
    """Get the bounding box of an elliptical arc described by the parameters.

    See following website for original code:
    http://fridrich.blogspot.nl/2011/06/bounding-box-of-svg-elliptical-arc.html

    """
    rx, ry = abs(rx), abs(ry)
    if rx == 0 or ry == 0:
        return min(x, x1), min(y, y1), max(x, x1), max(y, y1)

    x1prime = cos(phi) * (x1 - x) / 2 + sin(phi) * (y1 - y) / 2
    y1prime = -sin(phi) * (x1 - x) / 2 + cos(phi) * (y1 - y) / 2

    radicant = (
        rx ** 2 * ry ** 2 - rx ** 2 * y1prime ** 2 - ry ** 2 * x1prime ** 2)
    radicant /= rx ** 2 * y1prime ** 2 + ry ** 2 * x1prime ** 2
    cxprime = cyprime = 0

    if radicant < 0:
        ratio = rx / ry
        radicant = y1prime ** 2 + x1prime ** 2 / ratio ** 2
        if radicant < 0:
            return min(x, x1), min(y, y1), max(x, x1), max(y, y1)
        ry = sqrt(radicant)
        rx = ratio * ry
    else:
        factor = (-1 if large == sweep else 1) * sqrt(radicant)

        cxprime = factor * rx * y1prime / ry
        cyprime = -factor * ry * x1prime / rx

    cx = cxprime * cos(phi) - cyprime * sin(phi) + (x1 + x) / 2
    cy = cxprime * sin(phi) + cyprime * cos(phi) + (y1 + y) / 2

    if phi == 0 or phi == pi:
        minx = cx - rx
        tminx = angle(-rx, 0)
        maxx = cx + rx
        tmaxx = angle(rx, 0)
        miny = cy - ry
        tminy = angle(0, -ry)
        maxy = cy + ry
        tmaxy = angle(0, ry)
    elif phi == pi / 2 or phi == 3 * pi / 2:
        minx = cx - ry
        tminx = angle(-ry, 0)
        maxx = cx + ry
        tmaxx = angle(ry, 0)
        miny = cy - rx
        tminy = angle(0, -rx)
        maxy = cy + rx
        tmaxy = angle(0, rx)
    else:
        tminx = -atan(ry * tan(phi) / rx)
        tmaxx = pi - atan(ry * tan(phi) / rx)
        minx = cx + rx * cos(tminx) * cos(phi) - ry * sin(tminx) * sin(phi)
        maxx = cx + rx * cos(tmaxx) * cos(phi) - ry * sin(tmaxx) * sin(phi)
        if minx > maxx:
            minx, maxx = maxx, minx
            tminx, tmaxx = tmaxx, tminx
        tmp_y = cy + rx * cos(tminx) * sin(phi) + ry * sin(tminx) * cos(phi)
        tminx = angle(minx - cx, tmp_y - cy)
        tmp_y = cy + rx * cos(tmaxx) * sin(phi) + ry * sin(tmaxx) * cos(phi)
        tmaxx = angle(maxx - cx, tmp_y - cy)

        tminy = atan(ry / (tan(phi) * rx))
        tmaxy = atan(ry / (tan(phi) * rx)) + pi
        miny = cy + rx * cos(tminy) * sin(phi) + ry * sin(tminy) * cos(phi)
        maxy = cy + rx * cos(tmaxy) * sin(phi) + ry * sin(tmaxy) * cos(phi)
        if miny > maxy:
            miny, maxy = maxy, miny
            tminy, tmaxy = tmaxy, tminy
        tmp_x = cx + rx * cos(tminy) * cos(phi) - ry * sin(tminy) * sin(phi)
        tminy = angle(tmp_x - cx, miny - cy)
        tmp_x = cx + rx * cos(tmaxy) * cos(phi) - ry * sin(tmaxy) * sin(phi)
        tmaxy = angle(tmp_x - cx, maxy - cy)

    angle1 = angle(x1 - cx, y1 - cy)
    angle2 = angle(x - cx, y - cy)

    if not sweep:
        angle1, angle2 = angle2, angle1

    other_arc = False
    if angle1 > angle2:
        angle1, angle2 = angle2, angle1
        other_arc = True

    if ((not other_arc and (angle1 > tminx or angle2 < tminx)) or
            (other_arc and not (angle1 > tminx or angle2 < tminx))):
        minx = min(x, x1)
    if ((not other_arc and (angle1 > tmaxx or angle2 < tmaxx)) or
            (other_arc and not (angle1 > tmaxx or angle2 < tmaxx))):
        maxx = max(x, x1)
    if ((not other_arc and (angle1 > tminy or angle2 < tminy)) or
            (other_arc and not (angle1 > tminy or angle2 < tminy))):
        miny = min(y, y1)
    if ((not other_arc and (angle1 > tmaxy or angle2 < tmaxy)) or
            (other_arc and not (angle1 > tmaxy or angle2 < tmaxy))):
        maxy = max(y, y1)

    return minx, miny, maxx - minx, maxy - miny


def bounding_box_group(node):
    """Get the bounding box of a ``g`` node."""
    bounding_box = EMPTY_BOUNDING_BOX
    for child in node.children:
        bounding_box = combine_bounding_box(
            bounding_box, calculate_bounding_box(child))
    return bounding_box


def bounding_box_use(node):
    """Get the bounding box of a ``use`` node."""
    href = parse_url(node.get('{http://www.w3.org/1999/xlink}href')).geturl()
    tree = Tree(url=href, parent=node)
    if not match_features(tree.xml_tree):
        return None
    return calculate_bounding_box(tree)


def extend_bounding_box(bounding_box, points):
    """Extend the ``bounding_box`` by the points."""
    minx, miny, width, height = bounding_box
    maxx, maxy = (
        float('-inf') if isinf(minx) else minx + width,
        float('-inf') if isinf(miny) else miny + height)
    x_list, y_list = zip(*points)
    minx, miny, maxx, maxy = (
        min(minx, *x_list), min(miny, *y_list),
        max(maxx, *x_list), max(maxy, *y_list))
    return minx, miny, maxx - minx, maxy - miny


def combine_bounding_box(bounding_box, another_bounding_box):
    """Combine the ``bounding_box`` with ``another_bounding_box``."""
    if is_valid_bounding_box(another_bounding_box):
        minx, miny, width, height = another_bounding_box
        maxx, maxy = minx + width, miny + height
        bounding_box = extend_bounding_box(
            bounding_box, ((minx, miny), (maxx, maxy)))
    return bounding_box


def is_valid_bounding_box(bounding_box):
    """Know whether bounding box has been initialized."""
    # If 'minx' or 'miny' is set, 'maxx' and 'maxy' will also be set (resulting
    # in a valid bounding box)
    return bounding_box and not isinf(bounding_box[0] + bounding_box[1])


def is_non_empty_bounding_box(bounding_box):
    """Know whether bounding box is valid and has a size."""
    return is_valid_bounding_box(bounding_box) and 0 not in bounding_box[2:]


BOUNDING_BOX_METHODS = {
    'rect': bounding_box_rect,
    'circle': bounding_box_circle,
    'ellipse': bounding_box_ellipse,
    'line': bounding_box_line,
    'polyline': bounding_box_polyline,
    'polygon': bounding_box_polyline,
    'path': bounding_box_path,
    'text': bounding_box_text,
    'tspan': bounding_box_text,
    'textPath': bounding_box_text,
    'g': bounding_box_group,
    'use': bounding_box_use,
    'marker': bounding_box_group,
}
