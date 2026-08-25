# MySQL Workbench Data Dictionary Generator Plugin with Relationship Visualization
# Version: 3.7 - Live Workbench 8.0 catalog compatibility
# This version combines the ERD functionality with the complete HTML generation from htmldatadict.py

from wb import *
import grt
import mforms
from datetime import datetime
import os
import html
import json
import math
import hashlib
import tempfile
from pathlib import Path

# Module registration info
ModuleInfo = DefineModule(name="DataDictionary", author="Albert L. and contributors", version="3.7", description="Generate an accessible HTML data dictionary with relationship visualization")

# ==================== CONFIGURATION ====================
DEFAULT_CONFIG = {
    'filename_prefix': 'data_dictionary',
    'include_views': True,
    'include_routines': True,
    'include_triggers': True,
    'include_indexes': True,
    'include_comments': True,
    'generate_ddl': True,
    'show_relationship_diagram': True,
    'diagram_layout': 'force-directed'  # 'force-directed' or 'hierarchical'
}

# ==================== HELPER FUNCTIONS ====================
def escape_html(text):
    """Safely escape HTML special characters"""
    if text is None:
        return ''
    return html.escape(str(text), quote=True)


def safe_json_for_html(value):
    """Serialize JSON for an inert ``application/json`` script element.

    A normal ``json.dumps`` call can contain a literal ``</script>`` sequence.
    Browsers end a script element at that sequence even when it occurs inside a
    JSON string. Escaping HTML-significant characters keeps catalog metadata
    inert until JavaScript explicitly parses it.
    """
    return (json.dumps(value, ensure_ascii=False, default=str)
            .replace('&', '\\u0026')
            .replace('<', '\\u003c')
            .replace('>', '\\u003e')
            .replace('\u2028', '\\u2028')
            .replace('\u2029', '\\u2029'))


def table_dom_id(table_name):
    """Return a stable HTML id that is safe for every MySQL identifier."""
    digest = hashlib.sha256(str(table_name).encode('utf-8')).hexdigest()[:16]
    return 'table-' + digest


def sql_identifier(name):
    """Quote a MySQL identifier, including embedded backticks."""
    return '`' + str(name).replace('`', '``') + '`'


def sql_string(value):
    """Quote a SQL string using portable doubled-apostrophe escaping."""
    return "'" + str(value).replace("'", "''") + "'"


def index_column(index_item):
    """Normalize Workbench 8.0/8.4 index-column wrapper objects."""
    return getattr(index_item, 'referencedColumn', index_item)


def index_column_name(index_item):
    """Return a column name from either a column or IndexColumn wrapper."""
    column = index_column(index_item)
    return getattr(column, 'name', str(column))


def index_contains_column(index, column):
    """Compare index membership by referenced column name across GRT versions."""
    return any(index_column_name(item) == column.name for item in index.columns)


def effective_not_null(table, column):
    """Return effective nullability, including MySQL's implicit PK rule."""
    return bool(getattr(column, 'isNotNull', False) or
                table.isPrimaryKeyColumn(column))


def display_default(table, column):
    """Suppress Workbench's spurious DEFAULT NULL sentinel on PK columns."""
    if getattr(column, 'generated', False):
        return None
    value = getattr(column, 'defaultValue', None)
    if table.isPrimaryKeyColumn(column) and str(value).upper() == 'NULL':
        return None
    return value


def table_checks(table):
    """Return check constraints exposed by different Workbench GRT versions."""
    found = []
    for attribute in ('checkConstraints', 'checks'):
        constraints = getattr(table, attribute, None)
        if constraints:
            found.extend(list(constraints))

    # Workbench 8.0.47 exposes CHECK constraints through db.Column.checks
    # rather than through a table-level collection. Keep support for both
    # shapes because models imported by older Workbench builds differ.
    for column in getattr(table, 'columns', []) or []:
        constraints = getattr(column, 'checks', None)
        if constraints:
            found.extend(list(constraints))

    unique = []
    seen = set()
    for position, check in enumerate(found, 1):
        key = (check_name(check, position), check_expression(check))
        if key not in seen:
            seen.add(key)
            unique.append(check)
    return unique


def check_name(check, position):
    """Return a useful check-constraint name without assuming a GRT shape."""
    return (getattr(check, 'name', '') or
            getattr(check, 'constraintName', '') or
            f'check_{position}')


def check_expression(check):
    """Return the expression from common Workbench check object shapes."""
    if isinstance(check, str):
        return check
    return (getattr(check, 'expression', '') or
            getattr(check, 'checkExpression', '') or
            getattr(check, 'searchCondition', '') or
            getattr(check, 'sqlDefinition', '') or '')

def get_type_class(type_str):
    """Determine CSS class for data type coloring"""
    type_str = type_str.upper()
    if any(t in type_str for t in ['INT', 'BIGINT', 'SMALLINT', 'MEDIUMINT', 'TINYINT']):
        return 'type-int'
    elif any(t in type_str for t in ['VARCHAR', 'CHAR']):
        return 'type-varchar'
    elif any(t in type_str for t in ['DATE', 'TIME', 'YEAR', 'TIMESTAMP']):
        return 'type-date'
    elif any(t in type_str for t in ['DECIMAL', 'FLOAT', 'DOUBLE', 'NUMERIC', 'REAL']):
        return 'type-decimal'
    elif 'TEXT' in type_str or 'BLOB' in type_str:
        return 'type-text'
    elif 'ENUM' in type_str or 'SET' in type_str:
        return 'type-enum'
    elif 'BOOL' in type_str or 'BOOLEAN' in type_str:
        return 'type-bool'
    elif 'JSON' in type_str:
        return 'type-json'
    elif 'BINARY' in type_str or 'VARBINARY' in type_str:
        return 'type-binary'
    return ''

def generate_table_ddl(table):
    """Generate reviewable reconstruction DDL from Workbench model metadata."""
    ddl = f"CREATE TABLE {sql_identifier(table.name)} (\n"

    # Columns
    column_definitions = []
    for column in table.columns:
        col_def = f"  {sql_identifier(column.name)} {column.formattedType}"
        generated_expression = (getattr(column, 'generatedExpression', '') or
                                getattr(column, 'expression', ''))
        if getattr(column, 'generated', False) and generated_expression:
            col_def += f" GENERATED ALWAYS AS ({generated_expression})"
            if getattr(column, 'generatedStorage', ''):
                col_def += f" {column.generatedStorage}"
        if effective_not_null(table, column):
            col_def += " NOT NULL"
        default_value = display_default(table, column)
        if default_value not in (None, '') and not getattr(column, 'generated', False):
            col_def += f" DEFAULT {default_value}"
        if column.autoIncrement:
            col_def += " AUTO_INCREMENT"
        if column.comment:
            col_def += f" COMMENT {sql_string(column.comment)}"
        column_definitions.append(col_def)

    # Primary key
    pk_columns = [col.name for col in table.columns if table.isPrimaryKeyColumn(col)]
    if pk_columns:
        column_definitions.append(
            f"  PRIMARY KEY ({', '.join(sql_identifier(c) for c in pk_columns)})"
        )

    # Secondary and unique indexes. Workbench may expose either direct columns
    # or db.IndexColumn wrappers depending on the catalog source/version.
    for index in table.indices:
        index_name = getattr(index, 'name', '')
        if not index_name or index_name.upper() == 'PRIMARY':
            continue
        index_columns = [index_column_name(item) for item in index.columns]
        if not index_columns:
            continue
        keyword = 'UNIQUE KEY' if getattr(index, 'unique', False) else 'KEY'
        column_definitions.append(
            f"  {keyword} {sql_identifier(index_name)} "
            f"({', '.join(sql_identifier(name) for name in index_columns)})"
        )

    # CHECK constraint objects differ across Workbench catalog versions, so
    # accept all common shapes and omit only constraints without an expression.
    for position, check in enumerate(table_checks(table), 1):
        expression = check_expression(check)
        if expression:
            column_definitions.append(
                f"  CONSTRAINT {sql_identifier(check_name(check, position))} "
                f"CHECK ({expression})"
            )

    # Foreign keys
    for fk in table.foreignKeys:
        fk_cols = ', '.join(sql_identifier(col.name) for col in fk.columns)
        ref_cols = ', '.join(sql_identifier(col.name) for col in fk.referencedColumns)
        fk_def = (
            f"  CONSTRAINT {sql_identifier(fk.name)} FOREIGN KEY ({fk_cols}) "
            f"REFERENCES {sql_identifier(fk.referencedTable.name)} ({ref_cols})"
        )
        delete_rule = getattr(fk, 'deleteRule', '')
        update_rule = getattr(fk, 'updateRule', '')
        if delete_rule:
            fk_def += f" ON DELETE {delete_rule}"
        if update_rule:
            fk_def += f" ON UPDATE {update_rule}"
        column_definitions.append(fk_def)

    ddl += ',\n'.join(column_definitions)
    ddl += "\n)"

    if table.comment:
        ddl += f" COMMENT={sql_string(table.comment)}"

    table_engine = getattr(table, 'tableEngine', '')
    if table_engine:
        ddl += f" ENGINE={table_engine}"

    ddl += ";"
    return ddl

def calculate_layout_positions(tables, relationships, layout_type='force-directed'):
    """Calculate positions for tables in the diagram with improved spacing"""
    positions = {}

    # Define constants for better spacing
    TABLE_WIDTH = 220
    TABLE_HEIGHT = 90
    HORIZONTAL_SPACING = 180  # Extra space between tables horizontally
    VERTICAL_SPACING = 120    # Extra space between tables vertically
    MARGIN = 80               # Margin from edges

    if layout_type == 'hierarchical':
        # Hierarchical layout: referenced/parent tables above child tables.
        # Self-references do not make an otherwise-root table into a child.
        levels = {}
        processed = set()

        # Relationships point from child to referenced parent.
        root_tables = []
        child_tables = {
            rel['from'] for rel in relationships if rel['from'] != rel['to']
        }

        for table_name in tables:
            if table_name not in child_tables:
                root_tables.append(table_name)
                levels[table_name] = 0
                processed.add(table_name)

        # If no root tables, pick the first one
        if not root_tables and tables:
            root_tables = [tables[0]]
            levels[tables[0]] = 0
            processed.add(tables[0])

        # Assign levels based on relationships
        current_level = 0
        max_iterations = 20
        while len(processed) < len(tables) and current_level < max_iterations:
            current_level += 1
            made_progress = False
            for rel in relationships:
                if rel['from'] == rel['to']:
                    continue
                if rel['to'] in levels and rel['from'] not in processed:
                    levels[rel['from']] = levels[rel['to']] + 1
                    processed.add(rel['from'])
                    made_progress = True
            if not made_progress:
                break

        # Assign remaining tables
        for table_name in tables:
            if table_name not in levels:
                levels[table_name] = current_level + 1

        # Calculate positions with better spacing
        level_counts = {}
        for table, level in levels.items():
            if level not in level_counts:
                level_counts[level] = 0
            level_counts[level] += 1

        level_indices = {level: 0 for level in level_counts}

        for table_name in tables:
            level = levels.get(table_name, 0)
            index = level_indices[level]
            total_in_level = level_counts[level]

            # Calculate x position with proper spacing
            total_width = (TABLE_WIDTH + HORIZONTAL_SPACING) * total_in_level
            start_x = (2000 - total_width) / 2  # Center horizontally
            x = start_x + index * (TABLE_WIDTH + HORIZONTAL_SPACING) + MARGIN

            # Calculate y position with proper spacing
            y = MARGIN + level * (TABLE_HEIGHT + VERTICAL_SPACING)

            positions[table_name] = {'x': x, 'y': y}
            level_indices[level] += 1

    else:  # Stable balanced-grid layout
        num_tables = len(tables)
        # Optimize columns for better layout
        cols = min(5, max(3, math.ceil(math.sqrt(num_tables))))

        for i, table_name in enumerate(tables):
            row = i // cols
            col = i % cols

            # Calculate position with generous spacing
            x = MARGIN + col * (TABLE_WIDTH + HORIZONTAL_SPACING)
            y = MARGIN + row * (TABLE_HEIGHT + VERTICAL_SPACING)

            positions[table_name] = {'x': x, 'y': y}

    return positions

def generate_relationship_diagram(schema, config):
    """Generate SVG relationship diagram"""

    # Collect relationships
    relationships = []
    tables_with_relationships = set()
    all_tables = [table.name for table in schema.tables]
    local_table_names = set(all_tables)

    for table in schema.tables:
        for fk in table.foreignKeys:
            # The report documents one selected schema. Keep cross-schema
            # relationships in the textual table details, but omit them from
            # this diagram because the external table has no local node.
            if fk.referencedTable.name not in local_table_names:
                continue
            relationships.append({
                'from': table.name,
                'to': fk.referencedTable.name,
                'name': fk.name,
                'columns': ', '.join([col.name for col in fk.columns]),
                'ref_columns': ', '.join([col.name for col in fk.referencedColumns])
            })
            tables_with_relationships.add(table.name)
            tables_with_relationships.add(fk.referencedTable.name)

    # Calculate layout
    positions = calculate_layout_positions(all_tables, relationships, config.get('diagram_layout', 'force-directed'))

    # Calculate SVG dimensions with generous padding
    if positions:
        max_x = max([pos['x'] for pos in positions.values()]) + 350  # Add space for table width + padding
        max_y = max([pos['y'] for pos in positions.values()]) + 200  # Add space for table height + padding
    else:
        max_x = 1200
        max_y = 800

    # Make SVG larger to prevent cramping
    svg_width = max(1600, min(4000, max_x))
    svg_height = max(1000, min(3000, max_y))

    # Generate SVG
    svg = f'''
    <div class="erd-container">
        <div class="erd-header">
            <h2 id="erd-heading">Entity Relationship Diagram</h2>
            <div class="erd-controls">
                <button type="button" onclick="zoomIn()" class="erd-btn" aria-label="Zoom in on diagram">Zoom in</button>
                <button type="button" onclick="zoomOut()" class="erd-btn" aria-label="Zoom out on diagram">Zoom out</button>
                <button type="button" onclick="resetZoom()" class="erd-btn">Reset</button>
                <button type="button" id="erdFullscreenButton" onclick="toggleERDFullscreen()" class="erd-btn" aria-pressed="false">Fullscreen</button>
            </div>
        </div>
        <div class="erd-wrapper" id="erdWrapper">
            <button type="button" id="erdFullscreenExit" class="erd-fullscreen-exit" onclick="toggleERDFullscreen()">Exit fullscreen</button>
            <svg id="erdDiagram" width="{svg_width}" height="{svg_height}" viewBox="0 0 {svg_width} {svg_height}"
                 role="img" aria-labelledby="erd-title erd-description">
                <title id="erd-title">Tables and foreign-key relationships</title>
                <desc id="erd-description">Select a table node to jump to its detailed column definition.</desc>
                <defs>
                    <!-- Arrow marker for relationships -->
                    <marker id="arrowhead" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto">
                        <polygon points="0 0, 10 5, 0 10" fill="#2563eb" />
                    </marker>

                    <!-- Shadow filter -->
                    <filter id="tableShadow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur in="SourceAlpha" stdDeviation="3"/>
                        <feOffset dx="0" dy="2" result="offsetblur"/>
                        <feFlood flood-color="#000000" flood-opacity="0.1"/>
                        <feComposite in2="offsetblur" operator="in"/>
                        <feMerge>
                            <feMergeNode/>
                            <feMergeNode in="SourceGraphic"/>
                        </feMerge>
                    </filter>

                    <!-- Gradient for table headers -->
                    <linearGradient id="tableGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%" style="stop-color:#1f2937;stop-opacity:1" />
                        <stop offset="100%" style="stop-color:#374151;stop-opacity:1" />
                    </linearGradient>
                </defs>

                <!-- Relationship lines -->
                <g id="relationships">
    '''

    # Draw relationship lines with improved curves
    for rel in relationships:
        from_pos = positions[rel['from']]
        to_pos = positions[rel['to']]

        # Calculate connection points (center of tables)
        from_x = from_pos['x'] + 110  # Center of 220px wide table
        from_y = from_pos['y'] + 45   # Center of 90px tall table
        to_x = to_pos['x'] + 110
        to_y = to_pos['y'] + 45

        if rel['from'] == rel['to']:
            # A normal center-to-center path has zero length for a self-FK.
            # Draw an explicit loop from the right edge back to the same node.
            start_x = from_pos['x'] + 220
            start_y = from_pos['y'] + 28
            end_x = from_pos['x'] + 220
            end_y = from_pos['y'] + 68
            loop_x = from_pos['x'] + 305
            path_d = (f"M {start_x} {start_y} C {loop_x} {start_y - 45}, "
                      f"{loop_x} {end_y + 45}, {end_x} {end_y}")
            mid_x = loop_x - 5
            mid_y = from_pos['y'] + 45
        else:
            mid_x = (from_x + to_x) / 2
            mid_y = (from_y + to_y) / 2
            dx = to_x - from_x
            dy = to_y - from_y
            distance = math.sqrt(dx * dx + dy * dy)
            if abs(dx) > abs(dy):
                control_x = mid_x
                control_y = mid_y + (distance * 0.15 if dy >= 0 else -distance * 0.15)
            else:
                control_x = mid_x + (distance * 0.15 if dx >= 0 else -distance * 0.15)
                control_y = mid_y
            path_d = f"M {from_x} {from_y} Q {control_x} {control_y} {to_x} {to_y}"

        # Relationship label - only show FK name if it's short
        rel_name = rel['name']
        if len(rel_name) > 20:
            rel_name = rel_name[:17] + '...'

        # Position label slightly offset from line
        label_y = mid_y - 8

        svg += f'''
                    <g class="relationship" data-from="{escape_html(rel['from'])}" data-to="{escape_html(rel['to'])}"
                       role="group" tabindex="0"
                       aria-label="{escape_html(rel['name'])}: {escape_html(rel['from'])}.{escape_html(rel['columns'])} references {escape_html(rel['to'])}.{escape_html(rel['ref_columns'])}">
                        <title>{escape_html(rel['name'])}: {escape_html(rel['from'])}.{escape_html(rel['columns'])} → {escape_html(rel['to'])}.{escape_html(rel['ref_columns'])}</title>
                        <path d="{path_d}"
                              stroke="#2563eb" stroke-width="1.5" fill="none"
                              marker-end="url(#arrowhead)" opacity="0.5"
                              class="relationship-line"/>
                        <!-- Background/outline for text readability -->
                        <text x="{mid_x}" y="{label_y}"
                              font-size="10" fill="none" stroke="white" stroke-width="3"
                              text-anchor="middle" class="relationship-label-bg">
                            {escape_html(rel_name)}
                        </text>
                        <!-- Actual text label -->
                        <text x="{mid_x}" y="{label_y}"
                              font-size="10" fill="#1f2937" text-anchor="middle"
                              class="relationship-label"
                              font-weight="600">
                            {escape_html(rel_name)}
                        </text>
                    </g>
        '''

    svg += '''
                </g>

                <!-- Table nodes -->
                <g id="tableNodes">
    '''

    # Draw table nodes
    for table in schema.tables:
        if table.name in positions:
            pos = positions[table.name]
            x = pos['x']
            y = pos['y']

            # Count columns and keys
            pk_count = sum(1 for col in table.columns if table.isPrimaryKeyColumn(col))
            fk_count = len(table.foreignKeys)
            col_count = len(table.columns)

            # Determine if this table has relationships
            has_relationships = table.name in tables_with_relationships
            node_class = 'table-node-connected' if has_relationships else 'table-node-isolated'

            # Truncate long table names for display
            display_name = table.name if len(table.name) <= 18 else table.name[:15] + '...'

            target_id = table_dom_id(table.name)
            svg += f'''
                    <g class="table-node {node_class}" data-table="{escape_html(table.name)}"
                       transform="translate({x}, {y})"
                       role="link" tabindex="0"
                       aria-label="View details for {escape_html(table.name)}"
                       onclick="jumpToTable('{target_id}')"
                       onkeydown="if (event.key === 'Enter' || event.key === ' ') {{ event.preventDefault(); jumpToTable('{target_id}'); }}">

                        <!-- Table background with clean shadow -->
                        <rect x="0" y="0" width="220" height="85" rx="10" ry="10"
                              fill="white" stroke="#cbd5e1" stroke-width="2"
                              filter="url(#tableShadow)"/>

                        <!-- Table header gradient -->
                        <rect x="0" y="0" width="220" height="35" rx="10" ry="10"
                              fill="url(#tableGradient)"/>
                        <rect x="0" y="25" width="220" height="10"
                              fill="#1f2937"/>

                        <!-- Table name with better positioning -->
                        <text x="110" y="23" font-size="13" font-weight="bold"
                              fill="white" text-anchor="middle" class="table-name-text">
                            {escape_html(display_name)}
                        </text>

                        <!-- Table statistics with cleaner layout -->
                        <text x="15" y="55" font-size="11" fill="#4b5563" font-weight="600">
                            📋 {col_count}
                        </text>
                        <text x="90" y="55" font-size="11" fill="#dc2626" font-weight="600">
                            🔑 {pk_count}
                        </text>
                        <text x="160" y="55" font-size="11" fill="#2563eb" font-weight="600">
                            🔗 {fk_count}
                        </text>

                        <!-- Stat labels -->
                        <text x="15" y="70" font-size="8" fill="#9ca3af">
                            cols
                        </text>
                        <text x="90" y="70" font-size="8" fill="#9ca3af">
                            PK
                        </text>
                        <text x="160" y="70" font-size="8" fill="#9ca3af">
                            FK
                        </text>

                        <!-- Hover effect rectangle -->
                        <rect x="0" y="0" width="220" height="85" rx="10" ry="10"
                              fill="transparent" stroke="transparent" stroke-width="0"
                              class="table-hover-rect"/>
                    </g>
            '''

    svg += '''
                </g>
            </svg>
        </div>
        <div class="erd-legend">
            <span class="erd-legend-item">
                <span style="color: #dc2626;">🔑</span> Primary Key
            </span>
            <span class="erd-legend-item">
                <span style="color: #2563eb;">🔗</span> Foreign Key
            </span>
            <span class="erd-legend-item">
                <span style="color: #2563eb;">→</span> Relationship
            </span>
            <span class="erd-legend-item">
                Click table to view details
            </span>
        </div>
    </div>
    '''

    return svg

def generate_erd_styles():
    """Generate CSS styles for ERD"""
    return '''
        /* ERD Styles */
        .erd-container {
            margin: 24px;
            background: white;
            border-radius: 10px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
            overflow: hidden;
            border: 1px solid var(--gray-200);
        }

        .erd-header {
            background: var(--gray-100);
            padding: 20px 24px;
            border-bottom: 2px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .erd-header h2 {
            font-size: 1.5rem;
            font-weight: 700;
            color: var(--text-primary);
            margin: 0;
        }

        .erd-controls {
            display: flex;
            gap: 12px;
        }

        .erd-btn {
            padding: 8px 16px;
            background: var(--white);
            border: 2px solid var(--gray-300);
            border-radius: 6px;
            color: var(--text-primary);
            font-weight: 600;
            cursor: pointer;
            transition: background-color 0.2s, color 0.2s, border-color 0.2s, transform 0.2s, box-shadow 0.2s;
            font-size: 0.875rem;
        }

        .erd-btn:hover {
            background: var(--primary);
            color: var(--white);
            border-color: var(--primary);
            transform: translateY(-1px);
            box-shadow: 0 2px 4px rgba(37, 99, 235, 0.2);
        }

        .erd-wrapper {
            position: relative;
            overflow: auto;
            max-height: 900px;
            background: linear-gradient(to bottom right, #f9fafb, #f3f4f6);
            padding: 40px;
            cursor: grab;
        }

        .erd-wrapper:active {
            cursor: grabbing;
        }

        .erd-wrapper.fullscreen {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            max-height: none;
            z-index: 9999;
            background: white;
        }

        .erd-fullscreen-exit {
            display: none;
        }

        .erd-wrapper.fullscreen .erd-fullscreen-exit {
            display: block;
            position: fixed;
            top: 16px;
            right: 16px;
            z-index: 10001;
            padding: 10px 16px;
            border: 2px solid var(--primary);
            border-radius: 8px;
            background: var(--white);
            color: var(--primary-dark);
            font-weight: 700;
            cursor: pointer;
        }

        #erdDiagram {
            transition: transform 0.3s ease;
            transform-origin: center center;
        }

        /* Table node styling - NO transform transitions to prevent stuttering */
        .table-node {
            cursor: pointer;
        }

        .table-node rect {
            transition: stroke 0.2s ease, stroke-width 0.2s ease;
        }

        .table-node:hover .table-hover-rect {
            stroke: var(--primary);
            stroke-width: 3;
        }

        /* Don't scale on hover - causes stuttering */
        .table-node-isolated {
            opacity: 0.7;
            transition: opacity 0.2s ease;
        }

        .table-node-isolated:hover {
            opacity: 1;
        }

        /* Relationship lines */
        .relationship-line {
            transition: stroke-width 0.2s ease, opacity 0.2s ease, stroke 0.2s ease;
        }

        .relationship:hover .relationship-line {
            stroke-width: 3;
            opacity: 1;
            stroke: var(--primary-light);
        }

        .relationship-label {
            transition: font-weight 0.2s ease, fill 0.2s ease;
            pointer-events: none;
            opacity: 0;
        }

        .relationship-label-bg {
            opacity: 0;
        }

        .relationship:hover .relationship-label,
        .relationship:hover .relationship-label-bg,
        .relationship:focus .relationship-label,
        .relationship:focus .relationship-label-bg {
            opacity: 1;
        }

        .relationship:hover .relationship-label,
        .relationship:focus .relationship-label {
            font-weight: bold;
            fill: var(--primary);
        }

        .relationship:focus {
            outline: none;
        }

        .relationship:focus .relationship-line {
            stroke-width: 3;
            opacity: 1;
        }

        .table-name-text {
            pointer-events: none;
        }

        .erd-legend {
            padding: 12px 24px;
            background: var(--gray-100);
            border-top: 1px solid var(--border-color);
            display: flex;
            gap: 24px;
            font-size: 0.875rem;
            color: var(--text-secondary);
        }

        .erd-legend-item {
            display: flex;
            align-items: center;
            gap: 6px;
        }

        /* Highlight connected tables on hover - simplified to avoid stutter */
        .table-node.highlight-source rect:first-of-type,
        .table-node.highlight-target rect:first-of-type {
            stroke-width: 3 !important;
        }

        .table-node.highlight-source rect:first-of-type {
            stroke: var(--primary) !important;
        }

        .table-node.highlight-target rect:first-of-type {
            stroke: var(--success) !important;
        }

        .relationship.highlight {
            opacity: 1 !important;
        }

        .relationship.highlight .relationship-line {
            stroke-width: 3 !important;
            stroke: var(--primary) !important;
            opacity: 1 !important;
        }

        @media print {
            .erd-controls {
                display: none !important;
            }

            .erd-wrapper {
                max-height: none !important;
                overflow: visible !important;
                padding: 20px !important;
            }
        }
    '''

def generate_erd_scripts():
    """Generate JavaScript for ERD interactions"""
    return '''
        // ERD interaction scripts
        let currentZoom = 1;
        const zoomStep = 0.1;
        const maxZoom = 2;
        const minZoom = 0.5;

        function zoomIn() {
            if (currentZoom < maxZoom) {
                currentZoom += zoomStep;
                applyZoom();
            }
        }

        function zoomOut() {
            if (currentZoom > minZoom) {
                currentZoom -= zoomStep;
                applyZoom();
            }
        }

        function resetZoom() {
            currentZoom = 1;
            applyZoom();
        }

        function applyZoom() {
            const svg = document.getElementById('erdDiagram');
            if (!svg.dataset.baseWidth) {
                svg.dataset.baseWidth = svg.getAttribute('width');
                svg.dataset.baseHeight = svg.getAttribute('height');
            }
            const width = Number(svg.dataset.baseWidth) * currentZoom;
            const height = Number(svg.dataset.baseHeight) * currentZoom;
            svg.style.width = `${width}px`;
            svg.style.height = `${height}px`;
            svg.style.transform = 'none';
        }

        function toggleERDFullscreen() {
            const wrapper = document.getElementById('erdWrapper');
            const toggleButton = document.getElementById('erdFullscreenButton');
            const exitButton = document.getElementById('erdFullscreenExit');
            wrapper.classList.toggle('fullscreen');

            if (wrapper.classList.contains('fullscreen')) {
                document.body.style.overflow = 'hidden';
                if (toggleButton) toggleButton.setAttribute('aria-pressed', 'true');
                if (exitButton) exitButton.focus();
            } else {
                document.body.style.overflow = '';
                if (toggleButton) {
                    toggleButton.setAttribute('aria-pressed', 'false');
                    toggleButton.focus();
                }
            }
        }

        function jumpToTable(tableId) {
            // Remove fullscreen if active
            const wrapper = document.getElementById('erdWrapper');
            if (wrapper.classList.contains('fullscreen')) {
                toggleERDFullscreen();
            }

            // Scroll to table
            const tableElement = document.getElementById(tableId);
            if (tableElement) {
                tableElement.scrollIntoView({ behavior: 'smooth', block: 'start' });

                // Highlight the table
                tableElement.style.transition = 'box-shadow 0.3s';
                tableElement.style.boxShadow = '0 0 30px rgba(37, 99, 235, 0.8)';
                setTimeout(() => {
                    tableElement.style.boxShadow = '';
                }, 2000);
            }
        }

        // Add hover effects for relationship highlighting
        document.addEventListener('DOMContentLoaded', function() {
            const tableNodes = document.querySelectorAll('.table-node');
            const relationships = document.querySelectorAll('.relationship');

            tableNodes.forEach(node => {
                const tableName = node.dataset.table;

                node.addEventListener('mouseenter', function() {
                    // Highlight relationships
                    relationships.forEach(rel => {
                        if (rel.dataset.from === tableName || rel.dataset.to === tableName) {
                            rel.classList.add('highlight');

                            // Highlight connected tables
                            if (rel.dataset.from === tableName) {
                                const targetNode = Array.from(tableNodes).find(
                                    candidate => candidate.dataset.table === rel.dataset.to
                                );
                                if (targetNode) targetNode.classList.add('highlight-target');
                            } else {
                                const sourceNode = Array.from(tableNodes).find(
                                    candidate => candidate.dataset.table === rel.dataset.from
                                );
                                if (sourceNode) sourceNode.classList.add('highlight-source');
                            }
                        }
                    });
                });

                node.addEventListener('mouseleave', function() {
                    // Remove highlights
                    relationships.forEach(rel => {
                        rel.classList.remove('highlight');
                    });

                    document.querySelectorAll('.table-node').forEach(n => {
                        n.classList.remove('highlight-source', 'highlight-target');
                    });
                });
            });

            // Pan and zoom with mouse
            let isPanning = false;
            let startX = 0;
            let startY = 0;
            let scrollLeft = 0;
            let scrollTop = 0;

            const erdWrapper = document.getElementById('erdWrapper');

            erdWrapper.addEventListener('mousedown', function(e) {
                if (e.target === erdWrapper || e.target.tagName === 'svg') {
                    isPanning = true;
                    startX = e.pageX - erdWrapper.offsetLeft;
                    startY = e.pageY - erdWrapper.offsetTop;
                    scrollLeft = erdWrapper.scrollLeft;
                    scrollTop = erdWrapper.scrollTop;
                    erdWrapper.style.cursor = 'grabbing';
                }
            });

            erdWrapper.addEventListener('mousemove', function(e) {
                if (!isPanning) return;
                e.preventDefault();
                const x = e.pageX - erdWrapper.offsetLeft;
                const y = e.pageY - erdWrapper.offsetTop;
                const walkX = (x - startX) * 1.5;
                const walkY = (y - startY) * 1.5;
                erdWrapper.scrollLeft = scrollLeft - walkX;
                erdWrapper.scrollTop = scrollTop - walkY;
            });

            erdWrapper.addEventListener('mouseup', function() {
                isPanning = false;
                erdWrapper.style.cursor = 'grab';
            });

            erdWrapper.addEventListener('mouseleave', function() {
                isPanning = false;
                erdWrapper.style.cursor = 'grab';
            });

            // Zoom with mouse wheel
            erdWrapper.addEventListener('wheel', function(e) {
                if (e.ctrlKey) {
                    e.preventDefault();
                    if (e.deltaY < 0) {
                        zoomIn();
                    } else {
                        zoomOut();
                    }
                }
            });
        });
    '''

def generate_html_content(schema, config):
    """
    Generate complete HTML content for the data dictionary with ERD.
    This function incorporates the complete implementation from htmldatadict.py
    plus the ERD functionality.
    """

    # Collect statistics
    stats = {
        'tables': len(schema.tables),
        'columns': sum(len(table.columns) for table in schema.tables),
        'foreign_keys': sum(len(table.foreignKeys) for table in schema.tables),
        'indexes': sum(len(table.indices) for table in schema.tables),
        'unique_groups': sum(
            1 for table in schema.tables for index in table.indices
            if getattr(index, 'unique', False)
            and not getattr(index, 'isPrimary', False)
            and getattr(index, 'name', '').upper() != 'PRIMARY'
        ),
        'checks': sum(len(table_checks(table)) for table in schema.tables),
        'generated_columns': sum(
            bool(getattr(column, 'generated', False))
            for table in schema.tables for column in table.columns
        ),
        'innodb_tables': sum(
            getattr(table, 'tableEngine', '').lower() == 'innodb'
            for table in schema.tables
        ),
        'views': 0,
        'routines': 0,
        'triggers': 0
    }

    if config.get('include_views', True) and hasattr(schema, 'views'):
        stats['views'] = len(schema.views)

    if config.get('include_routines', True) and hasattr(schema, 'routines'):
        stats['routines'] = len(schema.routines)

    if config.get('include_triggers', True):
        for table in schema.tables:
            if hasattr(table, 'triggers'):
                stats['triggers'] += len(table.triggers)

    # Generate timestamp
    generation_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Combine original styles with ERD styles
    styles = """
        :root {
            /* High Contrast Color Palette */
            --primary: #2563eb;
            --primary-dark: #1e40af;
            --primary-light: #3b82f6;
            --success: #059669;
            --warning: #d97706;
            --danger: #dc2626;
            --info: #0891b2;
            --dark: #111827;
            --gray-900: #1f2937;
            --gray-800: #374151;
            --gray-700: #4b5563;
            --gray-600: #6b7280;
            --gray-500: #9ca3af;
            --gray-400: #cbd5e1;
            --gray-300: #e5e7eb;
            --gray-200: #f3f4f6;
            --gray-100: #f9fafb;
            --white: #ffffff;

            /* Semantic Colors with High Contrast */
            --pk-color: #dc2626;
            --fk-color: #2563eb;
            --unique-color: #7c3aed;
            --index-color: #059669;
            --nullable-color: #6b7280;
            --not-null-color: #ea580c;
            --json-color: #0891b2;
            --text-primary: #111827;
            --text-secondary: #4b5563;
            --border-color: #d1d5db;
            --hover-bg: #f9fafb;
            --table-header-bg: #1f2937;
            --table-header-text: #ffffff;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.7;
            color: var(--text-primary);
            background: linear-gradient(135deg, #1e3a8a 0%, #312e81 100%);
            min-height: 100vh;
            padding: 30px;
            font-size: 15px;
        }

        .skip-link {
            position: fixed;
            top: 8px;
            left: 8px;
            z-index: 2000;
            padding: 10px 14px;
            color: var(--white);
            background: var(--dark);
            border-radius: 6px;
            transform: translateY(-160%);
        }

        .skip-link:focus {
            transform: translateY(0);
        }

        .sr-only {
            position: absolute;
            width: 1px;
            height: 1px;
            padding: 0;
            margin: -1px;
            overflow: hidden;
            clip: rect(0, 0, 0, 0);
            white-space: nowrap;
            border: 0;
        }

        :focus-visible {
            outline: 3px solid #f59e0b;
            outline-offset: 3px;
        }

        .quick-start {
            margin: 30px 36px 0;
            padding: 24px;
            border: 2px solid #bfdbfe;
            border-radius: 12px;
            background: #eff6ff;
        }

        .quick-start h2 {
            margin-bottom: 14px;
            font-size: 1.5rem;
        }

        .quick-start ol {
            margin-left: 24px;
            display: grid;
            gap: 8px;
        }

        .container {
            max-width: 1800px;
            margin: 0 auto;
            background: var(--white);
            border-radius: 12px;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
            overflow: hidden;
        }

        .header {
            background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
            color: var(--white);
            padding: 48px;
            position: relative;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }

        .header h1 {
            font-size: 3rem;
            font-weight: 800;
            margin-bottom: 12px;
            text-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }

        .header .subtitle {
            font-size: 1.25rem;
            opacity: 0.95;
            font-weight: 400;
        }

        .header .meta-info {
            position: absolute;
            top: 24px;
            right: 24px;
            text-align: right;
            font-size: 0.875rem;
            font-weight: 500;
            background: rgba(0, 0, 0, 0.2);
            padding: 8px 16px;
            border-radius: 8px;
        }

        .export-buttons {
            position: absolute;
            bottom: 24px;
            right: 24px;
            display: flex;
            gap: 12px;
        }

        .export-btn {
            padding: 10px 20px;
            background: rgba(255, 255, 255, 0.95);
            border: 2px solid transparent;
            border-radius: 8px;
            color: var(--primary-dark);
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            font-size: 0.9375rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }

        .export-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.15);
            background: var(--white);
        }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 24px;
            padding: 36px;
            background: var(--gray-100);
            border-bottom: 2px solid var(--border-color);
        }

        .stat-card {
            background: var(--white);
            padding: 24px;
            border-radius: 10px;
            text-align: center;
            box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px 0 rgba(0, 0, 0, 0.06);
            border: 1px solid var(--gray-200);
            transition: all 0.2s;
        }

        .stat-card:hover {
            transform: translateY(-3px);
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
            border-color: var(--primary-light);
        }

        .stat-number {
            font-size: 2.25rem;
            font-weight: 800;
            color: var(--primary);
            display: block;
            line-height: 1.2;
        }

        .stat-label {
            color: var(--text-secondary);
            font-size: 0.9375rem;
            font-weight: 600;
            margin-top: 8px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .legend {
            padding: 36px;
            background: var(--white);
            border-bottom: 2px solid var(--border-color);
        }

        .legend h2 {
            font-size: 1.5rem;
            font-weight: 700;
            color: var(--text-primary);
            margin-bottom: 20px;
        }

        .legend-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 16px;
        }

        .legend-item {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 8px;
            border-radius: 6px;
            transition: background 0.2s;
        }

        .legend-item:hover {
            background: var(--gray-100);
        }

        .legend-badge {
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 0.875rem;
            font-weight: 700;
            color: var(--white);
            text-shadow: 0 1px 2px rgba(0,0,0,0.1);
            min-width: 45px;
            text-align: center;
        }

        .badge-pk { background: var(--pk-color); }
        .badge-fk { background: var(--fk-color); }
        .badge-unique { background: var(--unique-color); }
        .badge-index { background: var(--index-color); }
        .badge-nn { background: var(--not-null-color); }
        .badge-null { background: var(--nullable-color); }

        .search-container {
            padding: 24px 36px;
            background: var(--white);
            border-bottom: 3px solid var(--primary);
            display: flex;
            gap: 16px;
            align-items: center;
        }

        .search-box {
            flex: 1;
            padding: 14px 20px;
            font-size: 1rem;
            border: 2px solid var(--gray-300);
            border-radius: 10px;
            transition: all 0.2s;
            background: var(--white);
            color: var(--text-primary);
            font-weight: 500;
        }

        .search-box:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
            background: var(--white);
        }

        .search-box::placeholder {
            color: var(--gray-500);
            font-weight: 400;
        }

        .filter-buttons {
            display: flex;
            gap: 12px;
        }

        .filter-btn {
            padding: 10px 20px;
            border: 2px solid var(--gray-300);
            background: var(--white);
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
            font-size: 0.9375rem;
            font-weight: 600;
            color: var(--text-primary);
        }

        .filter-btn:hover {
            border-color: var(--primary);
            background: var(--gray-100);
        }

        .filter-btn.active {
            background: var(--primary);
            color: var(--white);
            border-color: var(--primary);
            box-shadow: 0 2px 4px rgba(37, 99, 235, 0.2);
        }

        .toc {
            padding: 36px;
            background: var(--gray-100);
            border-bottom: 2px solid var(--border-color);
        }

        .toc-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
        }

        .toc-header h2 {
            font-size: 1.5rem;
            font-weight: 700;
            color: var(--text-primary);
        }

        .toc-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 12px;
        }

        .toc-item {
            background: var(--white);
            padding: 14px 18px;
            border-radius: 8px;
            border: 2px solid var(--gray-200);
            transition: all 0.2s;
            cursor: pointer;
            text-decoration: none;
            color: var(--text-primary);
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-weight: 600;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
        }

        .toc-item:hover {
            background: var(--primary);
            color: var(--white);
            border-color: var(--primary);
            transform: translateX(4px);
            box-shadow: 0 4px 6px rgba(37, 99, 235, 0.2);
        }

        .toc-meta {
            font-size: 0.8125rem;
            opacity: 0.8;
            font-weight: 500;
            background: rgba(0, 0, 0, 0.05);
            padding: 2px 8px;
            border-radius: 4px;
        }

        .toc-item:hover .toc-meta {
            background: rgba(255, 255, 255, 0.2);
        }

        .tables-container {
            padding: 36px;
            background: var(--gray-100);
        }

        .table-wrapper {
            margin-bottom: 36px;
            background: var(--white);
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
            border: 1px solid var(--gray-200);
            transition: all 0.3s;
        }

        .table-wrapper.collapsed .table-content {
            display: none;
        }

        .table-wrapper.collapsed {
            margin-bottom: 16px;
        }

        .table-header {
            background: var(--table-header-bg);
            color: var(--table-header-text);
            padding: 24px;
            display: grid;
            grid-template-columns: minmax(220px, 1fr) auto;
            grid-template-areas:
                "name actions"
                "meta meta";
            align-items: start;
            gap: 14px 24px;
            border-bottom: 3px solid var(--primary);
        }

        .table-name-section {
            grid-area: name;
            min-width: 0;
        }

        .table-name {
            margin: 0;
            font-size: 1.625rem;
            font-weight: 700;
            color: var(--white);
        }

        .table-toggle {
            appearance: none;
            display: inline-flex;
            align-items: center;
            gap: 12px;
            max-width: 100%;
            padding: 3px 5px;
            margin: -3px -5px;
            border: 0;
            border-radius: 6px;
            background: transparent;
            color: inherit;
            font: inherit;
            font-weight: inherit;
            text-align: left;
            cursor: pointer;
            overflow-wrap: anywhere;
        }

        .table-toggle:hover {
            background: rgba(255, 255, 255, 0.1);
        }

        .table-toggle:focus-visible {
            outline: 3px solid var(--warning);
            outline-offset: 3px;
        }

        .table-comment {
            font-size: 0.9375rem;
            opacity: 0.85;
            margin-top: 6px;
            font-style: italic;
            color: var(--gray-300);
        }

        .collapse-indicator {
            font-size: 1.25rem;
            opacity: 0.8;
            transition: transform 0.3s;
        }

        .table-wrapper.collapsed .collapse-indicator {
            transform: rotate(-90deg);
        }

        .table-meta {
            grid-area: meta;
            display: flex;
            flex-wrap: wrap;
            gap: 24px;
            font-size: 0.9375rem;
            font-weight: 600;
            color: var(--gray-300);
        }

        .table-actions {
            grid-area: actions;
            align-self: start;
        }

        .btn-copy-ddl {
            padding: 8px 16px;
            background: var(--primary);
            border: 2px solid transparent;
            border-radius: 6px;
            color: var(--white);
            cursor: pointer;
            font-size: 0.875rem;
            font-weight: 600;
            transition: all 0.2s;
        }

        .btn-copy-ddl:hover {
            background: var(--primary-light);
            transform: translateY(-1px);
            box-shadow: 0 4px 6px rgba(37, 99, 235, 0.3);
        }

        .table-content {
            overflow-x: auto;
            background: var(--white);
        }

        .table-content > table {
            min-width: 900px;
        }

        table {
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            font-size: 0.9375rem;
        }

        th {
            background: var(--gray-100);
            color: var(--text-primary);
            font-weight: 700;
            text-align: left;
            padding: 14px 16px;
            border-bottom: 2px solid var(--gray-300);
            font-size: 0.875rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            position: sticky;
            top: 0;
            z-index: 10;
        }

        td {
            padding: 14px 16px;
            border-bottom: 1px solid var(--gray-200);
            color: var(--text-primary);
            vertical-align: middle;
        }

        tr {
            transition: background 0.2s;
        }

        tr:hover {
            background: var(--hover-bg);
        }

        tr:last-child td {
            border-bottom: none;
        }

        .column-name {
            font-weight: 700;
            color: var(--dark);
            font-family: 'SF Mono', Monaco, 'Courier New', monospace;
            font-size: 0.9375rem;
            letter-spacing: -0.25px;
        }

        .column-comment {
            font-size: 0.875rem;
            color: var(--text-secondary);
            font-style: italic;
            line-height: 1.4;
        }

        .data-type {
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 0.8125rem;
            font-family: 'SF Mono', Monaco, 'Courier New', monospace;
            font-weight: 600;
            display: inline-block;
            text-transform: uppercase;
            letter-spacing: 0.25px;
        }

        .type-int {
            background: #fee2e2;
            color: #991b1b;
            border: 1px solid #fca5a5;
        }
        .type-varchar {
            background: #dcfce7;
            color: #166534;
            border: 1px solid #86efac;
        }
        .type-date {
            background: #fef3c7;
            color: #92400e;
            border: 1px solid #fcd34d;
        }
        .type-decimal {
            background: #e0e7ff;
            color: #3730a3;
            border: 1px solid #a5b4fc;
        }
        .type-text {
            background: #f3e8ff;
            color: #6b21a8;
            border: 1px solid #d8b4fe;
        }
        .type-enum {
            background: #ffe4e6;
            color: #9f1239;
            border: 1px solid #fda4af;
        }
        .type-bool {
            background: #cffafe;
            color: #0e7490;
            border: 1px solid #67e8f9;
        }
        .type-json {
            background: #cffafe;
            color: #0891b2;
            border: 1px solid #67e8f9;
        }
        .type-binary {
            background: #f3f4f6;
            color: #374151;
            border: 1px solid #d1d5db;
        }

        .key-badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 14px;
            font-size: 0.75rem;
            font-weight: 700;
            color: var(--white);
            margin-right: 4px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            box-shadow: 0 1px 2px rgba(0,0,0,0.1);
        }

        .default-value {
            background: var(--gray-100);
            border: 1px solid var(--gray-300);
            padding: 4px 10px;
            border-radius: 6px;
            font-family: 'SF Mono', Monaco, 'Courier New', monospace;
            font-size: 0.8125rem;
            color: var(--text-primary);
            font-weight: 600;
        }

        .relationships-section {
            background: linear-gradient(to right, #ecfdf5, #f0fdf4);
            border-left: 4px solid var(--success);
            padding: 18px;
            margin: 20px;
            border-radius: 8px;
        }

        .relationships-section strong {
            color: var(--success);
            font-size: 1rem;
            font-weight: 700;
            display: block;
            margin-bottom: 12px;
        }

        .relationship-item {
            padding: 10px 0;
            color: var(--text-primary);
            font-family: 'SF Mono', Monaco, 'Courier New', monospace;
            font-size: 0.9375rem;
            border-bottom: 1px solid rgba(5, 150, 105, 0.1);
            font-weight: 600;
        }

        .relationship-item:last-child {
            border-bottom: none;
        }

        .indexes-section {
            background: linear-gradient(to right, #ecfccb, #f0fdf4);
            border-left: 4px solid var(--index-color);
            padding: 18px;
            margin: 20px;
            border-radius: 8px;
        }

        .indexes-section strong {
            color: var(--index-color);
            font-size: 1rem;
            font-weight: 700;
            display: block;
            margin-bottom: 12px;
        }

        .index-item {
            padding: 10px 0;
            color: var(--text-primary);
            font-family: 'SF Mono', Monaco, 'Courier New', monospace;
            font-size: 0.9375rem;
            border-bottom: 1px solid rgba(5, 150, 105, 0.1);
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-weight: 600;
        }

        .index-item:last-child {
            border-bottom: none;
        }

        .index-type {
            font-size: 0.75rem;
            padding: 3px 8px;
            background: var(--index-color);
            color: var(--white);
            border-radius: 4px;
            font-weight: 700;
            text-transform: uppercase;
        }

        .ddl-modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.7);
            z-index: 1000;
            justify-content: center;
            align-items: center;
            backdrop-filter: blur(4px);
        }

        .ddl-modal.show {
            display: flex;
        }

        .ddl-content {
            background: var(--white);
            border-radius: 12px;
            padding: 32px;
            max-width: 900px;
            max-height: 85vh;
            overflow-y: auto;
            position: relative;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
        }

        .ddl-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 2px solid var(--gray-200);
        }

        .ddl-header h3 {
            font-size: 1.5rem;
            font-weight: 700;
            color: var(--text-primary);
        }

        .ddl-code {
            background: var(--gray-900);
            color: #f0f0f0;
            padding: 24px;
            border-radius: 8px;
            font-family: 'SF Mono', Monaco, 'Courier New', monospace;
            font-size: 0.9375rem;
            line-height: 1.6;
            overflow-x: auto;
            white-space: pre-wrap;
            word-wrap: break-word;
            border: 2px solid var(--gray-700);
        }

        .btn-close {
            background: var(--danger);
            color: var(--white);
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            font-size: 0.9375rem;
            transition: all 0.2s;
        }

        .btn-close:hover {
            background: #b91c1c;
            transform: translateY(-1px);
            box-shadow: 0 4px 6px rgba(220, 38, 38, 0.3);
        }

        .toast {
            position: fixed;
            bottom: 30px;
            right: 30px;
            background: var(--success);
            color: var(--white);
            padding: 14px 24px;
            border-radius: 8px;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.2);
            display: none;
            animation: slideIn 0.3s ease;
            font-weight: 600;
            font-size: 0.9375rem;
        }

        .toast.show {
            display: block;
        }

        @keyframes slideIn {
            from {
                transform: translateX(120%);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }

        .back-to-top {
            position: fixed;
            bottom: 30px;
            right: 30px;
            background: var(--primary);
            color: var(--white);
            width: 56px;
            height: 56px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 10px 25px -5px rgba(37, 99, 235, 0.4);
            cursor: pointer;
            opacity: 0;
            visibility: hidden;
            pointer-events: none;
            transform: translateY(10px);
            transition: opacity 0.2s, visibility 0.2s, transform 0.2s,
                        background 0.2s, box-shadow 0.2s;
            text-decoration: none;
            font-size: 1.5rem;
            font-weight: bold;
            z-index: 100;
            border: 2px solid transparent;
        }

        .back-to-top.visible {
            opacity: 1;
            visibility: visible;
            pointer-events: auto;
            transform: translateY(0);
        }

        .back-to-top:hover {
            transform: scale(1.1);
            background: var(--primary-dark);
            box-shadow: 0 14px 28px -5px rgba(37, 99, 235, 0.5);
        }

        .triggers-section {
            background: linear-gradient(to right, #fef3c7, #fed7aa);
            border-left: 4px solid var(--warning);
            padding: 18px;
            margin: 20px;
            border-radius: 8px;
        }

        .triggers-section strong {
            color: var(--warning);
            font-size: 1rem;
            font-weight: 700;
            display: block;
            margin-bottom: 12px;
        }

        .trigger-item {
            padding: 10px 0;
            color: var(--text-primary);
            font-family: 'SF Mono', Monaco, 'Courier New', monospace;
            font-size: 0.9375rem;
            border-bottom: 1px solid rgba(217, 119, 6, 0.1);
            font-weight: 600;
        }

        .trigger-item:last-child {
            border-bottom: none;
        }

        /* Printing state helper */
        body.printing .table-wrapper.collapsed .table-content {
            display: block !important;
        }

        @media (max-width: 900px) {
            body {
                padding: 12px;
            }

            .header {
                padding: 32px 24px;
            }

            .header h1 {
                font-size: 2.25rem;
            }

            .header .meta-info,
            .export-buttons {
                position: static;
                margin-top: 18px;
                text-align: left;
            }

            .export-buttons,
            .filter-buttons,
            .erd-controls,
            .erd-legend,
            .table-meta {
                flex-wrap: wrap;
            }

            .search-container,
            .erd-header {
                align-items: stretch;
                flex-direction: column;
            }

            .table-header {
                grid-template-columns: 1fr;
                grid-template-areas:
                    "name"
                    "meta"
                    "actions";
            }

            .quick-start,
            .erd-container {
                margin-left: 18px;
                margin-right: 18px;
            }

            .legend,
            .toc,
            .tables-container,
            .stats-grid,
            .search-container {
                padding: 24px 18px;
            }

            .table-meta {
                gap: 10px 18px;
            }

            .erd-wrapper {
                padding: 20px;
            }
        }

        @media (max-width: 560px) {
            body {
                padding: 0;
            }

            .container {
                border-radius: 0;
            }

            .header h1 {
                font-size: 1.9rem;
            }

            .export-buttons > *,
            .filter-buttons > * {
                flex: 1 1 100%;
            }

            .stats-grid,
            .legend-grid,
            .toc-grid {
                grid-template-columns: 1fr;
            }

            .table-header {
                padding: 18px;
            }

            .table-name {
                font-size: 1.25rem;
                overflow-wrap: anywhere;
            }
        }

        @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after {
                scroll-behavior: auto !important;
                animation-duration: 0.01ms !important;
                animation-iteration-count: 1 !important;
                transition-duration: 0.01ms !important;
            }
        }

        /* Enhanced Print/PDF Styles */
        @media print {
            /* Page setup */
            @page {
                size: A4 portrait;
                margin: 15mm 10mm;
            }

            * {
                print-color-adjust: exact !important;
                -webkit-print-color-adjust: exact !important;
                color-adjust: exact !important;
            }

            /* Hide interactive elements */
            .search-container,
            .back-to-top,
            .skip-link,
            .export-buttons,
            .filter-buttons,
            .table-actions,
            .collapse-indicator,
            .toc,
            #ddlModal,
            #toast,
            .erd-controls,
            .meta-info {
                display: none !important;
            }

            /* Body reset for print */
            body {
                background: white !important;
                padding: 0 !important;
                margin: 0 !important;
                font-size: 10pt !important;
                line-height: 1.4 !important;
            }

            /* Container adjustments */
            .container {
                box-shadow: none !important;
                border-radius: 0 !important;
                max-width: 100% !important;
                margin: 0 !important;
            }

            /* Header optimization */
            .header {
                background: #2563eb !important;
                color: white !important;
                padding: 15mm !important;
                margin-bottom: 5mm !important;
                page-break-after: avoid !important;
                border-bottom: 3px solid #1e40af !important;
            }

            .header h1 {
                font-size: 20pt !important;
                margin-bottom: 3mm !important;
            }

            .header .subtitle {
                font-size: 12pt !important;
            }

            /* Stats grid */
            .stats-grid {
                page-break-after: avoid !important;
                padding: 5mm !important;
                background: #f3f4f6 !important;
                margin-bottom: 5mm !important;
                border: 2px solid #d1d5db !important;
            }

            .stat-card {
                border: 1px solid #9ca3af !important;
                padding: 3mm !important;
                background: white !important;
            }

            .stat-number {
                font-size: 16pt !important;
            }

            .stat-label {
                font-size: 9pt !important;
            }

            /* Legend */
            .legend {
                break-inside: avoid !important;
                page-break-inside: avoid !important;
                break-after: auto !important;
                page-break-after: auto !important;
                padding: 5mm !important;
                margin-bottom: 5mm !important;
                border: 2px solid #d1d5db !important;
                background: #f9fafb !important;
            }

            .legend h2 {
                font-size: 12pt !important;
                margin-bottom: 3mm !important;
                color: #111827 !important;
            }

            .legend-grid {
                gap: 2mm !important;
                break-inside: avoid !important;
                page-break-inside: avoid !important;
            }

            .legend-badge {
                font-size: 8pt !important;
                padding: 1mm 2mm !important;
            }

            /* ERD for print */
            .erd-container {
                page-break-before: always !important;
                page-break-after: auto !important;
                margin: 0 !important;
                border: 2px solid #000 !important;
            }

            .erd-header {
                background: #e5e7eb !important;
                color: #111827 !important;
                padding: 3mm !important;
                border-bottom: 2px solid #000 !important;
            }

            .erd-header h2 {
                font-size: 14pt !important;
                color: #111827 !important;
            }

            .erd-wrapper {
                max-height: none !important;
                overflow: visible !important;
                padding: 5mm !important;
                background: white !important;
            }

            /* Scale SVG to fit page width */
            #erdDiagram {
                max-width: 100% !important;
                height: auto !important;
                width: 100% !important;
                display: block !important;
            }

            .erd-legend {
                background: #f3f4f6 !important;
                border-top: 2px solid #000 !important;
                padding: 2mm !important;
                font-size: 8pt !important;
            }

            /* Tables container */
            .tables-container {
                break-before: page !important;
                page-break-before: always !important;
                padding: 0 !important;
                background: white !important;
            }

            /* Critical: Table wrapper page break handling */
            .table-wrapper {
                page-break-before: auto !important;
                page-break-after: auto !important;
                page-break-inside: avoid !important;
                margin-bottom: 8mm !important;
                border: 3px solid #000000 !important;
                box-shadow: none !important;
                background: white !important;
                border-radius: 0 !important;
            }

            /* Force expanded state for all tables */
            .table-wrapper.collapsed {
                display: block !important;
            }

            .table-wrapper.collapsed .table-content {
                display: block !important;
            }

            /* Table header - high contrast for print */
            .table-header {
                background: #1f2937 !important;
                color: white !important;
                padding: 4mm !important;
                border-bottom: 3px solid #000000 !important;
                page-break-after: avoid !important;
                cursor: default !important;
            }

            .table-name {
                font-size: 13pt !important;
                font-weight: bold !important;
                color: white !important;
            }

            .table-comment {
                font-size: 9pt !important;
                color: #e5e7eb !important;
            }

            .table-meta {
                font-size: 8pt !important;
                color: #d1d5db !important;
            }

            /* Table content */
            .table-content {
                display: block !important;
                overflow: visible !important;
                background: white !important;
            }

            .table-content > table {
                min-width: 0 !important;
            }

            /* Data tables */
            table {
                width: 100% !important;
                font-size: 8pt !important;
                page-break-inside: auto !important;
                border-collapse: collapse !important;
            }

            thead {
                display: table-header-group !important;
                background: #e5e7eb !important;
            }

            tbody {
                display: table-row-group !important;
            }

            /* Prevent row splits */
            tr {
                page-break-inside: avoid !important;
                page-break-after: auto !important;
            }

            th {
                background: #e5e7eb !important;
                color: #111827 !important;
                font-size: 8pt !important;
                padding: 2mm !important;
                border: 1.5px solid #000000 !important;
                font-weight: bold !important;
                position: static !important;
                text-transform: uppercase !important;
            }

            td {
                padding: 1.5mm !important;
                font-size: 8pt !important;
                border: 1px solid #4b5563 !important;
                color: #111827 !important;
                vertical-align: top !important;
            }

            /* Ensure text doesn't get cut off */
            .column-name {
                font-size: 8pt !important;
                font-weight: bold !important;
                word-break: break-word !important;
            }

            .column-comment {
                font-size: 7pt !important;
                color: #4b5563 !important;
                word-break: break-word !important;
            }

            /* Data types - ensure colors print */
            .data-type {
                font-size: 7pt !important;
                padding: 0.5mm 1mm !important;
                border-width: 1px !important;
                font-weight: bold !important;
            }

            .type-int {
                background: #fee2e2 !important;
                color: #7f1d1d !important;
                border-color: #dc2626 !important;
            }

            .type-varchar {
                background: #dcfce7 !important;
                color: #14532d !important;
                border-color: #16a34a !important;
            }

            .type-date {
                background: #fef3c7 !important;
                color: #713f12 !important;
                border-color: #d97706 !important;
            }

            .type-decimal {
                background: #e0e7ff !important;
                color: #312e81 !important;
                border-color: #6366f1 !important;
            }

            .type-text {
                background: #f3e8ff !important;
                color: #581c87 !important;
                border-color: #9333ea !important;
            }

            .type-enum {
                background: #ffe4e6 !important;
                color: #881337 !important;
                border-color: #f43f5e !important;
            }

            .type-bool {
                background: #cffafe !important;
                color: #164e63 !important;
                border-color: #06b6d4 !important;
            }

            .type-json {
                background: #cffafe !important;
                color: #155e75 !important;
                border-color: #0891b2 !important;
            }

            .type-binary {
                background: #f3f4f6 !important;
                color: #1f2937 !important;
                border-color: #6b7280 !important;
            }

            /* Key badges - high contrast for print */
            .key-badge {
                font-size: 7pt !important;
                padding: 0.5mm 1.5mm !important;
                color: white !important;
                font-weight: bold !important;
                border-radius: 1mm !important;
            }

            .badge-pk {
                background: #dc2626 !important;
                border: 1px solid #7f1d1d !important;
            }

            .badge-fk {
                background: #2563eb !important;
                border: 1px solid #1e3a8a !important;
            }

            .badge-unique {
                background: #7c3aed !important;
                border: 1px solid #5b21b6 !important;
            }

            .badge-index {
                background: #059669 !important;
                border: 1px solid #047857 !important;
            }

            .badge-nn {
                background: #ea580c !important;
                border: 1px solid #9a3412 !important;
            }

            .badge-null {
                background: #6b7280 !important;
                border: 1px solid #374151 !important;
            }

            /* Sections - avoid page breaks */
            .relationships-section,
            .indexes-section,
            .triggers-section {
                margin: 2mm !important;
                padding: 2mm !important;
                page-break-inside: avoid !important;
                border: 2px solid #000 !important;
            }

            .relationships-section {
                background: #f0fdf4 !important;
                border-left: 4px solid #059669 !important;
            }

            .relationships-section strong {
                color: #047857 !important;
                font-size: 10pt !important;
            }

            .indexes-section {
                background: #f0fdf4 !important;
                border-left: 4px solid #14b8a6 !important;
            }

            .indexes-section strong {
                color: #0f766e !important;
                font-size: 10pt !important;
            }

            .triggers-section {
                background: #fef3c7 !important;
                border-left: 4px solid #d97706 !important;
            }

            .triggers-section strong {
                color: #92400e !important;
                font-size: 10pt !important;
            }

            .relationship-item,
            .index-item,
            .trigger-item {
                font-size: 8pt !important;
                padding: 1mm 0 !important;
                color: #111827 !important;
                border-bottom: 1px solid #d1d5db !important;
            }

            .index-type {
                font-size: 7pt !important;
                background: #059669 !important;
                color: white !important;
                padding: 0.5mm 1mm !important;
                border: 1px solid #047857 !important;
            }

            .default-value {
                font-size: 7pt !important;
                background: #f3f4f6 !important;
                border: 1px solid #9ca3af !important;
                padding: 0.5mm 1mm !important;
            }

            /* Ensure nothing is hidden */
            * {
                opacity: 1 !important;
            }
        }
    """ + generate_erd_styles()

    # Build HTML structure
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">
    <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='12' fill='%232563eb'/%3E%3Ctext x='32' y='43' font-size='34' text-anchor='middle' fill='white'%3ED%3C/text%3E%3C/svg%3E">
    <title>Data Dictionary - {escape_html(schema.name)}</title>
    <style>{styles}</style>
</head>
<body>
    <a class="skip-link" href="#main-content">Skip to data dictionary</a>
    <main class="container" id="main-content">
        <div class="header">
            <h1>Data Dictionary</h1>
            <div class="subtitle">{escape_html(schema.name)} Database Schema</div>
            <div class="meta-info">
                <div>Generated: {generation_time}</div>
                <div>Plugin version: 3.7</div>
            </div>
            <div class="export-buttons">
                <button type="button" class="export-btn" onclick="exportToCSV()">Export CSV</button>
                <button type="button" class="export-btn" onclick="exportToJSON()">Export JSON</button>
                <button type="button" class="export-btn" onclick="printToPDF()">Print / Save PDF</button>
            </div>
        </div>

        <div class="stats-grid">
            <div class="stat-card">
                <span class="stat-number">{stats['tables']}</span>
                <div class="stat-label">Tables</div>
            </div>
            <div class="stat-card">
                <span class="stat-number">{stats['columns']}</span>
                <div class="stat-label">Columns</div>
            </div>
            <div class="stat-card">
                <span class="stat-number">{stats['foreign_keys']}</span>
                <div class="stat-label">Foreign Keys</div>
            </div>
            <div class="stat-card">
                <span class="stat-number">{stats['indexes']}</span>
                <div class="stat-label">Indexes</div>
            </div>"""

    if config.get('include_views', True) and stats['views'] > 0:
        html_content += f"""
            <div class="stat-card">
                <span class="stat-number">{stats['views']}</span>
                <div class="stat-label">Views</div>
            </div>"""

    if config.get('include_routines', True) and stats['routines'] > 0:
        html_content += f"""
            <div class="stat-card">
                <span class="stat-number">{stats['routines']}</span>
                <div class="stat-label">Routines</div>
            </div>"""

    if config.get('include_triggers', True) and stats['triggers'] > 0:
        html_content += f"""
            <div class="stat-card">
                <span class="stat-number">{stats['triggers']}</span>
                <div class="stat-label">Triggers</div>
            </div>"""

    html_content += """
        </div>

        <section class="quick-start" aria-labelledby="quick-start-heading">
            <h2 id="quick-start-heading">Start here</h2>
            <ol>
                <li>Confirm the table, column, and foreign-key totals above.</li>
                <li>Use the diagram or table list to understand how tables connect.</li>
                <li>Open one table at a time; required fields, keys, defaults, indexes, and relationships are explained in its detail section.</li>
            </ol>
        </section>
"""

    # Add ERD if configured
    if config.get('show_relationship_diagram', True) and stats['foreign_keys'] > 0:
        html_content += generate_relationship_diagram(schema, config)

    html_content += """
        <div class="legend">
            <h2>Legend</h2>
            <div class="legend-grid">
                <div class="legend-item">
                    <span class="legend-badge badge-pk">PK</span>
                    <span>Primary Key</span>
                </div>
                <div class="legend-item">
                    <span class="legend-badge badge-fk">FK</span>
                    <span>Foreign Key</span>
                </div>
                <div class="legend-item">
                    <span class="legend-badge badge-unique">UQ</span>
                    <span>Unique Constraint</span>
                </div>
                <div class="legend-item">
                    <span class="legend-badge badge-index">IDX</span>
                    <span>Indexed</span>
                </div>
                <div class="legend-item">
                    <span class="legend-badge badge-nn">NOT NULL</span>
                    <span>Required Field</span>
                </div>
                <div class="legend-item">
                    <span class="legend-badge badge-null">NULL</span>
                    <span>Optional Field</span>
                </div>
            </div>
        </div>

        <div class="search-container">
            <label class="sr-only" for="searchBox">Search tables, columns, and comments</label>
            <input type="search" id="searchBox" class="search-box" placeholder="Search tables, columns, and comments" oninput="searchWithDebounce()">
            <div class="filter-buttons">
                <button type="button" class="filter-btn active" aria-pressed="true" data-filter="all" onclick="filterTables('all')">All tables</button>
                <button type="button" class="filter-btn" aria-pressed="false" data-filter="child" onclick="filterTables('child')">Child tables</button>
                <button type="button" class="filter-btn" aria-pressed="false" data-filter="referenced" onclick="filterTables('referenced')">Referenced tables</button>
                <button type="button" class="filter-btn" aria-pressed="false" data-filter="isolated" onclick="filterTables('isolated')">Isolated tables</button>
                <button type="button" class="filter-btn" onclick="toggleAllTables()">Expand / collapse all</button>
            </div>
        </div>

        <div class="toc">
            <div class="toc-header">
                <h2>Database Tables</h2>
                <span style="color: #4b5563; font-size: 0.9375rem;">Choose a table, then expand or collapse its details.</span>
            </div>
            <div class="toc-grid">
"""

    # Add table of contents
    for table in schema.tables:
        col_count = len(table.columns)
        fk_count = len(table.foreignKeys)
        target_id = table_dom_id(table.name)
        html_content += f"""                <a href="#{target_id}" class="toc-item" data-fk-count="{fk_count}">
                    <span>{escape_html(table.name)}</span>
                    <span class="toc-meta">{col_count} cols | {fk_count} FKs</span>
                </a>
"""

    html_content += """            </div>
        </div>

        <div class="tables-container">
"""

    # Generate DDL storage for JavaScript
    ddl_scripts = {}

    # Build the reverse side of every relationship once so each table can show
    # both "references" and "referenced by" information.
    incoming_relationships = {table.name: [] for table in schema.tables}
    for source_table in schema.tables:
        for fk in source_table.foreignKeys:
            incoming_relationships.setdefault(fk.referencedTable.name, []).append(
                (source_table, fk)
            )

    # Generate each table
    for table in schema.tables:
        table_name_escaped = escape_html(table.name)
        table_id = table_dom_id(table.name)
        table_content_id = table_id + '-content'
        col_count = len(table.columns)
        fk_count = len(table.foreignKeys)
        incoming_count = len(incoming_relationships.get(table.name, []))
        idx_count = len(table.indices)

        # Generate DDL for this table
        if config.get('generate_ddl', True):
            ddl = generate_table_ddl(table)
            ddl_scripts[table_id] = ddl

        # Table comment if exists
        table_comment_html = ""
        if table.comment:
            table_comment_html = f'<div class="table-comment">{escape_html(table.comment)}</div>'

        html_content += f"""            <section class="table-wrapper" id="{table_id}" data-fk-count="{fk_count}" data-incoming-fk-count="{incoming_count}" data-table-name="{table_name_escaped}">
                <div class="table-header">
                    <div class="table-name-section">
                        <h3 class="table-name">
                            <button type="button" class="table-toggle" aria-expanded="true" aria-controls="{table_content_id}"
                                    onclick="toggleTable('{table_id}')">
                                <span>{table_name_escaped}</span>
                                <span class="collapse-indicator" aria-hidden="true">▼</span>
                            </button>
                        </h3>
                        {table_comment_html}
                    </div>
                    <div class="table-meta">
                        <span>📋 {col_count} Columns</span>
                        <span>↗ {fk_count} Outgoing FKs</span>
                        <span>↙ {incoming_count} Incoming FKs</span>
                        <span>📍 {idx_count} Indexes</span>
                    </div>"""

        if config.get('generate_ddl', True):
            html_content += f"""
                    <div class="table-actions">
                        <button type="button" class="btn-copy-ddl" onclick="event.stopPropagation(); showDDL('{table_id}')">View reference DDL</button>
                    </div>"""

        html_content += f"""
                </div>
                <div class="table-content" id="{table_content_id}">
                    <table>
                        <caption class="sr-only">Column definitions for {table_name_escaped}</caption>
                        <thead>
                            <tr>
                                <th scope="col" style="width: 3%">#</th>
                                <th scope="col" style="width: 20%">Column name</th>
                                <th scope="col" style="width: 15%">Data type</th>
                                <th scope="col" style="width: 8%">Nullable</th>
                                <th scope="col" style="width: 12%">Keys / indexes</th>
                                <th scope="col" style="width: 12%">Default</th>
                                <th scope="col" style="width: 10%">Extra</th>"""

        if config.get('include_comments', True):
            html_content += """
                                <th scope="col" style="width: 20%">Comment</th>"""

        html_content += """
                            </tr>
                        </thead>
                        <tbody>
"""

        # Add columns
        for idx, column in enumerate(table.columns, 1):
            # Determine data type class
            type_class = get_type_class(column.formattedType)

            # Key badges
            keys = []
            if table.isPrimaryKeyColumn(column):
                keys.append('<span class="key-badge badge-pk">PK</span>')
            if table.isForeignKeyColumn(column):
                keys.append('<span class="key-badge badge-fk">FK</span>')

            # Check for unique constraints. A column in a composite unique key
            # is not unique by itself, so label it as a group member instead of
            # showing the misleading single-column UQ badge.
            for index in table.indices:
                index_name = getattr(index, 'name', '') or ''
                if (getattr(index, 'unique', False) and
                        index_name.upper() != 'PRIMARY' and
                        not table.isPrimaryKeyColumn(column) and
                        index_contains_column(index, column)):
                    member_count = len(index.columns)
                    badge = 'UQ' if member_count == 1 else 'UQ group'
                    explanation = ('Unique by itself' if member_count == 1 else
                                   'Part of a composite unique constraint')
                    keys.append(
                        f'<span class="key-badge badge-unique" '
                        f'title="{explanation}">{badge}</span>'
                    )
                    break

            # Check for regular index
            if config.get('include_indexes', True):
                for index in table.indices:
                    if (not getattr(index, 'unique', False) and
                            index_contains_column(index, column) and
                            not table.isPrimaryKeyColumn(column)):
                        keys.append('<span class="key-badge badge-index">IDX</span>')
                        break

            key_str = ' '.join(keys) if keys else '-'

            # Nullable - clearer display
            if effective_not_null(table, column):
                nullable = '<span class="key-badge badge-nn">NOT NULL</span>'
            else:
                nullable = '<span class="key-badge badge-null">NULL</span>'

            # Default value
            default_value = display_default(table, column)
            if default_value not in (None, ''):
                default = f'<span class="default-value">{escape_html(default_value)}</span>'
            else:
                default = '<span style="color: #9ca3af;">-</span>'

            # Extra
            extras = []
            if column.autoIncrement:
                extras.append('AUTO_INCREMENT')
            if hasattr(column, 'generated') and column.generated:
                storage = getattr(column, 'generatedStorage', '') or ''
                extras.append(('GENERATED ' + storage).strip())
            extra_str = ', '.join(extras) if extras else '<span style="color: #9ca3af;">-</span>'

            html_content += f"""                            <tr>
                                <td style="text-align: center; color: #6b7280; font-weight: 600;">{idx}</td>
                                <td><span class="column-name">{escape_html(column.name)}</span></td>
                                <td><span class="data-type {type_class}">{escape_html(column.formattedType)}</span></td>
                                <td style="text-align: center;">{nullable}</td>
                                <td>{key_str}</td>
                                <td>{default}</td>
                                <td>{extra_str}</td>"""

            if config.get('include_comments', True):
                # Comment
                if column.comment:
                    comment_html = f'<div class="column-comment">{escape_html(column.comment)}</div>'
                else:
                    comment_html = '<span style="color: #9ca3af;">-</span>'
                html_content += f"""
                                <td>{comment_html}</td>"""

            html_content += """
                            </tr>
"""

        html_content += """                        </tbody>
                    </table>
"""

        # Add indexes section if configured
        if config.get('include_indexes', True) and table.indices:
            html_content += """                    <div class="indexes-section">
                        <strong>Index information</strong>
"""
            for index in table.indices:
                index_cols = ', '.join(index_column_name(col) for col in index.columns)
                index_type = "UNIQUE" if getattr(index, 'unique', False) else "INDEX"
                if getattr(index, 'indexType', ''):
                    index_type += f" ({index.indexType})"

                html_content += f"""                        <div class="index-item">
                            <div>
                                <span style="font-weight: 700;">{escape_html(index.name)}</span>
                                <span style="color: #6b7280;"> ({escape_html(index_cols)})</span>
                            </div>
                            <span class="index-type">{escape_html(index_type)}</span>
                        </div>
"""
            html_content += """                    </div>
"""

        # Add outgoing foreign-key relationships with the modeling details that
        # matter in the Week 3 lab: optionality, identifying status, and actions.
        if table.foreignKeys:
            html_content += """                    <div class="relationships-section">
                        <strong>References (outgoing foreign keys)</strong>
"""
            for fk in table.foreignKeys:
                source_cols = ', '.join([col.name for col in fk.columns])
                ref_cols = ', '.join([col.name for col in fk.referencedColumns])
                optionality = ('Required' if all(effective_not_null(table, col)
                                                  for col in fk.columns)
                               else 'Optional')
                identifying = ('Identifying' if any(table.isPrimaryKeyColumn(col)
                                                     for col in fk.columns)
                               else 'Non-identifying')
                delete_rule = getattr(fk, 'deleteRule', '') or 'NO ACTION'
                update_rule = getattr(fk, 'updateRule', '') or 'NO ACTION'
                html_content += f"""                        <div class="relationship-item">
                            <strong>{escape_html(source_cols)}</strong> → {escape_html(fk.referencedTable.name)}.{escape_html(ref_cols)}
                            <span style="color: #4b5563; font-size: 0.8125rem; margin-left: 12px;">
                                {escape_html(fk.name)} · {optionality} · {identifying} ·
                                ON DELETE {escape_html(delete_rule)} · ON UPDATE {escape_html(update_rule)}
                            </span>
                        </div>
"""
            html_content += """                    </div>
"""

        incoming = incoming_relationships.get(table.name, [])
        if incoming:
            html_content += """                    <div class="relationships-section incoming-relationships">
                        <strong>Referenced by (incoming foreign keys)</strong>
"""
            for source_table, fk in incoming:
                source_cols = ', '.join(col.name for col in fk.columns)
                ref_cols = ', '.join(col.name for col in fk.referencedColumns)
                html_content += f"""                        <div class="relationship-item">
                            <strong>{escape_html(source_table.name)}.{escape_html(source_cols)}</strong>
                            → {escape_html(table.name)}.{escape_html(ref_cols)}
                            <span style="color: #4b5563; font-size: 0.8125rem; margin-left: 12px;">
                                {escape_html(fk.name)}
                            </span>
                        </div>
"""
            html_content += """                    </div>
"""

        checks = table_checks(table)
        if checks:
            html_content += """                    <div class="indexes-section">
                        <strong>Check constraints</strong>
"""
            for position, check in enumerate(checks, 1):
                expression = check_expression(check)
                if expression:
                    html_content += f"""                        <div class="index-item">
                            <span style="font-weight: 700;">{escape_html(check_name(check, position))}</span>
                            <code>{escape_html(expression)}</code>
                        </div>
"""
            html_content += """                    </div>
"""

        # Add triggers if configured
        if config.get('include_triggers', True) and hasattr(table, 'triggers') and table.triggers:
            html_content += """                    <div class="triggers-section">
                        <strong>⚡ Triggers</strong>
"""
            for trigger in table.triggers:
                trigger_timing = trigger.timing if hasattr(trigger, 'timing') else 'UNKNOWN'
                trigger_event = trigger.event if hasattr(trigger, 'event') else 'UNKNOWN'
                html_content += f"""                        <div class="trigger-item">
                            {escape_html(trigger.name)} - {escape_html(trigger_timing)} {escape_html(trigger_event)}
                        </div>
"""
            html_content += """                    </div>
"""

        html_content += """                </div>
            </section>
"""

    # Close HTML and add JavaScript with DDL modal if configured
    ddl_modal_html = ""
    if config.get('generate_ddl', True):
        ddl_modal_html = """
    <!-- DDL Modal -->
    <div id="ddlModal" class="ddl-modal" role="dialog" aria-modal="true" aria-labelledby="ddlModalTitle" aria-describedby="ddlModalNote">
        <div class="ddl-content" tabindex="-1">
            <div class="ddl-header">
                <h3 id="ddlModalTitle">Reference DDL</h3>
                <button type="button" class="btn-close" onclick="closeDDL()">Close</button>
            </div>
            <p id="ddlModalNote" style="margin-bottom: 16px; color: #4b5563;">
                Reconstructed from Workbench model metadata. Compare it with
                <code>SHOW CREATE TABLE</code> before executing it.
            </p>
            <pre id="ddlCode" class="ddl-code"></pre>
            <div style="margin-top: 24px; text-align: right;">
                <button type="button" class="export-btn" style="background: var(--primary); color: white; border: none; font-weight: 600;" onclick="copyDDL()">Copy to clipboard</button>
            </div>
        </div>
    </div>"""

    html_content += f"""        </div>
    </main>

    {ddl_modal_html}

    <!-- Toast Notification -->
    <div id="toast" class="toast" role="status" aria-live="polite">Operation successful.</div>

    <a href="#main-content" onclick="scrollToTop();" class="back-to-top" aria-label="Back to top" aria-hidden="true" tabindex="-1">↑</a>

    <script id="ddlData" type="application/json">{safe_json_for_html(ddl_scripts if config.get('generate_ddl', True) else {})}</script>
    <script id="schemaDataJson" type="application/json">{safe_json_for_html({
            'name': schema.name,
            'generated': generation_time,
            'statistics': stats,
            'tables': [
                {
                    'name': table.name,
                    'comment': table.comment if table.comment else None,
                    'engine': getattr(table, 'tableEngine', '') or None,
                    'checks': [
                        {
                            'name': check_name(check, position),
                            'expression': check_expression(check)
                        }
                        for position, check in enumerate(table_checks(table), 1)
                        if check_expression(check)
                    ],
                    'indexes': [
                        {
                            'name': index.name,
                            'columns': [index_column_name(item) for item in index.columns],
                            'unique': bool(getattr(index, 'unique', False)),
                            'primary': bool(getattr(index, 'isPrimary', False))
                                       or getattr(index, 'name', '').upper() == 'PRIMARY',
                            'type': getattr(index, 'indexType', '') or None
                        }
                        for index in table.indices
                    ],
                    'columns': [
                        {
                            'name': col.name,
                            'type': col.formattedType,
                            'nullable': not effective_not_null(table, col),
                            'default': display_default(table, col),
                            'comment': col.comment if col.comment else None,
                            'is_primary_key': table.isPrimaryKeyColumn(col),
                            'is_foreign_key': table.isForeignKeyColumn(col),
                            'auto_increment': col.autoIncrement if hasattr(col, 'autoIncrement') else False,
                            'generated': bool(getattr(col, 'generated', False)),
                            'generated_expression': (
                                getattr(col, 'generatedExpression', '') or
                                getattr(col, 'expression', '') or None
                            ),
                            'generated_storage': getattr(col, 'generatedStorage', '') or None,
                            'unique_groups': [
                                index.name for index in table.indices
                                if getattr(index, 'unique', False)
                                and not getattr(index, 'isPrimary', False)
                                and getattr(index, 'name', '').upper() != 'PRIMARY'
                                and index_contains_column(index, col)
                            ],
                            'foreign_keys': [
                                fk.name for fk in table.foreignKeys
                                if any(member.name == col.name for member in fk.columns)
                            ]
                        } for col in table.columns
                    ],
                    'foreign_keys': [
                        {
                            'name': fk.name,
                            'columns': [col.name for col in fk.columns],
                            'referenced_table': fk.referencedTable.name,
                            'referenced_columns': [col.name for col in fk.referencedColumns],
                            'delete_rule': getattr(fk, 'deleteRule', ''),
                            'update_rule': getattr(fk, 'updateRule', ''),
                            'required': all(effective_not_null(table, col)
                                            for col in fk.columns),
                            'identifying': any(table.isPrimaryKeyColumn(col) for col in fk.columns)
                        } for fk in table.foreignKeys
                    ],
                    'incoming_foreign_keys': [
                        {
                            'name': fk.name,
                            'source_table': source_table.name,
                            'columns': [col.name for col in fk.columns],
                            'referenced_columns': [col.name for col in fk.referencedColumns],
                            'delete_rule': getattr(fk, 'deleteRule', ''),
                            'update_rule': getattr(fk, 'updateRule', ''),
                            'required': all(effective_not_null(source_table, col)
                                            for col in fk.columns),
                            'identifying': any(source_table.isPrimaryKeyColumn(col)
                                               for col in fk.columns)
                        }
                        for source_table, fk in incoming_relationships.get(table.name, [])
                    ]
                } for table in schema.tables
            ]
        })}</script>

    <script>
        const ddlScripts = JSON.parse(document.getElementById('ddlData').textContent);
        const schemaData = JSON.parse(document.getElementById('schemaDataJson').textContent);

        // Debounced search
        let searchTimeout;
        let activeTableFilter = 'all';
        function searchWithDebounce() {{
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(searchTables, 300);
        }}

        function searchTables() {{
            applyTableVisibility();
        }}

        function applyTableVisibility() {{
            const searchTerm = document.getElementById('searchBox').value.toLowerCase();
            const tables = document.querySelectorAll('.table-wrapper');

            tables.forEach(table => {{
                const tableContent = table.textContent.toLowerCase();
                const outgoing = Number.parseInt(table.dataset.fkCount || '0', 10);
                const incoming = Number.parseInt(table.dataset.incomingFkCount || '0', 10);
                const matchesSearch = searchTerm === '' || tableContent.includes(searchTerm);
                const matchesFilter =
                    activeTableFilter === 'all' ||
                    (activeTableFilter === 'child' && outgoing > 0) ||
                    (activeTableFilter === 'referenced' && incoming > 0) ||
                    (activeTableFilter === 'isolated' && outgoing === 0 && incoming === 0);
                table.style.display = matchesSearch && matchesFilter ? 'block' : 'none';
            }});

            // Update TOC items visibility
            const tocItems = document.querySelectorAll('.toc-item');
            tocItems.forEach(item => {{
                const tableName = item.getAttribute('href').substring(1);
                const table = document.getElementById(tableName);
                item.style.display = table.style.display;
            }});
        }}

        function filterTables(filter) {{
            const buttons = document.querySelectorAll('.filter-btn');
            activeTableFilter = filter;

            // Update button states
            buttons.forEach(btn => {{
                btn.classList.remove('active');
                if (btn.dataset.filter) btn.setAttribute('aria-pressed', 'false');
            }});

            const activeButton = document.querySelector(`.filter-btn[data-filter="${{filter}}"]`);
            if (activeButton) {{
                activeButton.classList.add('active');
                activeButton.setAttribute('aria-pressed', 'true');
            }}

            applyTableVisibility();
        }}

        function toggleTable(tableId) {{
            const table = document.getElementById(tableId);
            if (!table) return;
            table.classList.toggle('collapsed');
            const toggle = table.querySelector('.table-toggle');
            if (toggle) toggle.setAttribute('aria-expanded', String(!table.classList.contains('collapsed')));
        }}

        function toggleAllTables() {{
            const tables = document.querySelectorAll('.table-wrapper');
            const allCollapsed = Array.from(tables).every(t => t.classList.contains('collapsed'));

            tables.forEach(table => {{
                if (allCollapsed) {{
                    table.classList.remove('collapsed');
                }} else {{
                    table.classList.add('collapsed');
                }}
                const toggle = table.querySelector('.table-toggle');
                if (toggle) toggle.setAttribute('aria-expanded', String(allCollapsed));
            }});
        }}

        let lastFocusedElement = null;
        function showDDL(tableName) {{
            const modal = document.getElementById('ddlModal');
            const code = document.getElementById('ddlCode');
            if (!modal || !code) return;
            lastFocusedElement = document.activeElement;
            code.textContent = ddlScripts[tableName] || 'DDL not available';
            modal.classList.add('show');
            document.getElementById('main-content')?.setAttribute('inert', '');
            document.querySelector('.back-to-top')?.setAttribute('inert', '');
            modal.querySelector('.btn-close').focus();
        }}

        function closeDDL() {{
            const modal = document.getElementById('ddlModal');
            if (!modal) return;
            modal.classList.remove('show');
            document.getElementById('main-content')?.removeAttribute('inert');
            document.querySelector('.back-to-top')?.removeAttribute('inert');
            if (lastFocusedElement) lastFocusedElement.focus();
        }}

        function trapDDLFocus(event) {{
            const modal = document.getElementById('ddlModal');
            if (!modal?.classList.contains('show') || event.key !== 'Tab') return;
            const focusable = Array.from(modal.querySelectorAll(
                'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), ' +
                'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
            )).filter(element => element.offsetParent !== null);
            if (!focusable.length) return;
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (event.shiftKey && document.activeElement === first) {{
                event.preventDefault();
                last.focus();
            }} else if (!event.shiftKey && document.activeElement === last) {{
                event.preventDefault();
                first.focus();
            }}
        }}

        function copyDDL() {{
            const code = document.getElementById('ddlCode').textContent;
            navigator.clipboard.writeText(code).then(() => {{
                showToast('DDL copied to clipboard!');
            }}).catch(err => {{
                // Fallback for older browsers
                const textArea = document.createElement('textarea');
                textArea.value = code;
                document.body.appendChild(textArea);
                textArea.select();
                document.execCommand('copy');
                document.body.removeChild(textArea);
                showToast('DDL copied to clipboard!');
            }});
        }}

        function showToast(message = 'Operation successful!') {{
            const toast = document.getElementById('toast');
            toast.textContent = '✓ ' + message;
            toast.classList.add('show');
            setTimeout(() => {{
                toast.classList.remove('show');
            }}, 2500);
        }}

        function printToPDF() {{
            document.body.classList.add('printing');
            const collapsedBeforePrint = Array.from(
                document.querySelectorAll('.table-wrapper.collapsed')
            );
            collapsedBeforePrint.forEach(table => table.classList.remove('collapsed'));

            const restorePrintState = () => {{
                collapsedBeforePrint.forEach(table => table.classList.add('collapsed'));
                document.body.classList.remove('printing');
            }};
            window.addEventListener('afterprint', restorePrintState, {{ once: true }});
            window.print();
            showToast('Choose “Save as PDF” in the print dialog.');
        }}

        function csvCell(value) {{
            let text = value === null || value === undefined ? '' : String(value);
            if (/^[\\t\\r\\n ]*[=+\\-@]/.test(text)) text = "'" + text;
            return '"' + text.replace(/"/g, '""') + '"';
        }}

        function safeFilePart(value) {{
            const cleaned = String(value || 'schema')
                .replace(/[^a-zA-Z0-9._-]+/g, '_')
                .replace(/^_+|_+$/g, '');
            return cleaned || 'schema';
        }}

        function downloadBlob(blob, filename) {{
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            link.remove();
            setTimeout(() => URL.revokeObjectURL(url), 0);
        }}

        function exportToCSV() {{
            const rows = [[
                'Table', 'Column', 'Type', 'Nullable', 'Primary Key',
                'Foreign Key', 'Default', 'Auto Increment', 'Generated',
                'Generated Expression', 'Generated Storage', 'Unique Groups',
                'FK Constraints', 'Outgoing FK Details', 'Incoming FK Details',
                'Engine', 'Table Checks', 'Comment'
            ]];
            schemaData.tables.forEach(table => {{
                const tableChecks = (table.checks || [])
                    .map(check => `${{check.name}}: ${{check.expression}}`)
                    .join('; ');
                const outgoingDetails = (table.foreign_keys || []).map(fk =>
                    `${{fk.name}}: (${{fk.columns.join(', ')}}) -> ` +
                    `${{fk.referenced_table}}(${{fk.referenced_columns.join(', ')}}); ` +
                    `${{fk.required ? 'required' : 'optional'}}; ` +
                    `${{fk.identifying ? 'identifying' : 'non-identifying'}}; ` +
                    `ON DELETE ${{fk.delete_rule || 'NO ACTION'}}; ` +
                    `ON UPDATE ${{fk.update_rule || 'NO ACTION'}}`
                ).join(' | ');
                const incomingDetails = (table.incoming_foreign_keys || []).map(fk =>
                    `${{fk.name}}: ${{fk.source_table}}(${{fk.columns.join(', ')}}) -> ` +
                    `${{table.name}}(${{fk.referenced_columns.join(', ')}}); ` +
                    `${{fk.required ? 'required' : 'optional'}}; ` +
                    `${{fk.identifying ? 'identifying' : 'non-identifying'}}; ` +
                    `ON DELETE ${{fk.delete_rule || 'NO ACTION'}}; ` +
                    `ON UPDATE ${{fk.update_rule || 'NO ACTION'}}`
                ).join(' | ');
                table.columns.forEach(col => {{
                    const nullable = col.nullable ? 'YES' : 'NO';
                    const isPK = col.is_primary_key ? 'YES' : 'NO';
                    const isFK = col.is_foreign_key ? 'YES' : 'NO';
                    const autoInc = col.auto_increment ? 'YES' : 'NO';
                    const defaultVal = col.default || '';
                    const comment = col.comment || '';
                    rows.push([
                        table.name, col.name, col.type, nullable, isPK, isFK,
                        defaultVal, autoInc, col.generated ? 'YES' : 'NO',
                        col.generated_expression || '', col.generated_storage || '',
                        (col.unique_groups || []).join('; '),
                        (col.foreign_keys || []).join('; '),
                        outgoingDetails, incomingDetails, table.engine || '',
                        tableChecks, comment
                    ]);
                }});
            }});

            const csv = '\\uFEFF' + rows.map(row => row.map(csvCell).join(',')).join('\\r\\n') + '\\r\\n';
            const blob = new Blob([csv], {{ type: 'text/csv;charset=utf-8' }});
            downloadBlob(blob, `data_dictionary_${{safeFilePart(schemaData.name)}}.csv`);
            showToast('CSV exported successfully!');
        }}

        function exportToJSON() {{
            const blob = new Blob([JSON.stringify(schemaData, null, 2)], {{ type: 'application/json' }});
            downloadBlob(blob, `data_dictionary_${{safeFilePart(schemaData.name)}}.json`);
            showToast('JSON exported successfully!');
        }}

        function scrollToTop() {{
            window.scrollTo({{ top: 0, behavior: 'smooth' }});
            return false;
        }}

        function updateBackToTop() {{
            const button = document.querySelector('.back-to-top');
            if (!button) return;
            const visible = window.scrollY > 600;
            button.classList.toggle('visible', visible);
            button.setAttribute('aria-hidden', String(!visible));
            button.setAttribute('tabindex', visible ? '0' : '-1');
        }}

        window.addEventListener('scroll', updateBackToTop, {{ passive: true }});
        updateBackToTop();

        // Close modal on escape or click outside
        document.addEventListener('keydown', function(e) {{
            trapDDLFocus(e);
            if (e.key === 'Escape') {{
                const wrapper = document.getElementById('erdWrapper');
                if (wrapper && wrapper.classList.contains('fullscreen')) {{
                    toggleERDFullscreen();
                }} else {{
                    closeDDL();
                }}
            }}
        }});

        window.onclick = function(event) {{
            const modal = document.getElementById('ddlModal');
            if (event.target == modal) {{
                closeDDL();
            }}
        }}

        // Smooth scroll for TOC links
        document.querySelectorAll('a[href^="#"]').forEach(anchor => {{
            anchor.addEventListener('click', function (e) {{
                e.preventDefault();
                const target = document.querySelector(this.getAttribute('href'));
                if (target) {{
                    target.scrollIntoView({{
                        behavior: 'smooth',
                        block: 'start'
                    }});
                    // Highlight the table briefly
                    target.style.transition = 'box-shadow 0.3s';
                    target.style.boxShadow = '0 0 20px rgba(37, 99, 235, 0.5)';
                    setTimeout(() => {{
                        target.style.boxShadow = '';
                    }}, 1000);
                }}
            }});
        }});

        {generate_erd_scripts() if config.get('show_relationship_diagram', True) else ''}
    </script>
</body>
</html>
"""

    return html_content

# ==================== MAIN PLUGIN CLASS ====================
@ModuleInfo.plugin("wb.catalog.util.generateDataDictionary",
                   caption="Generate Data Dictionary with ERD",
                   description="Generate high-contrast HTML data dictionary with relationship visualization",
                   input=[wbinputs.currentCatalog()],
                   pluginMenu="Catalog",
                   accessibilityName="Generate Data Dictionary with ERD")
@ModuleInfo.export(grt.INT, grt.classes.db_Catalog)
def generateDataDictionary(catalog):
    """Main plugin function called from menu"""

    if not catalog or not getattr(catalog, 'schemata', None):
        mforms.Utilities.show_warning(
            "No model schema",
            "Open a Workbench model that contains at least one schema, then run the plugin again.",
            "OK", "", ""
        )
        return 0

    # Create dialog for schema selection
    dialog = SchemaSelectionDialog(catalog)

    # Run dialog and check if user cancelled
    if not dialog.run():
        return 0

    selected_schema = dialog.selected_schema
    output_path = dialog.output_path
    config = dialog.config

    if not selected_schema or not output_path:
        mforms.Utilities.show_error("Error", "No schema selected or output path not specified", "OK", "", "")
        return 0

    output_path = os.path.abspath(os.path.expanduser(output_path))
    output_directory = os.path.dirname(output_path)
    if not os.path.isdir(output_directory):
        mforms.Utilities.show_error(
            "Invalid folder",
            f"The output folder does not exist:\n{output_directory}",
            "OK", "", ""
        )
        return 0

    if os.path.exists(output_path):
        replace_result = mforms.Utilities.show_message(
            "Replace existing file?",
            f"A file already exists at:\n{output_path}\n\nReplace it?",
            "Replace", "Cancel", ""
        )
        if replace_result != mforms.ResultOk:
            return 0

    temporary_path = None
    try:
        # Generate HTML content with ERD
        html_content = generate_html_content(selected_schema, config)

        # Write in the destination folder, then atomically replace the target so
        # an interrupted generation cannot leave a half-written report.
        with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8', dir=output_directory,
                prefix='.data_dictionary_', suffix='.tmp', delete=False) as output_file:
            temporary_path = output_file.name
            output_file.write(html_content)
        os.replace(temporary_path, output_path)
        temporary_path = None

        # Show success message with options
        result = mforms.Utilities.show_message("Success",
            f"Data Dictionary with ERD generated successfully!\n\nFile saved to:\n{output_path}\n\nDo you want to open the file now?",
            "Open File", "OK", "")

        if result == mforms.ResultOk:
            import webbrowser
            webbrowser.open(Path(output_path).resolve().as_uri())

        return 1

    except Exception as e:
        mforms.Utilities.show_error("Error", f"Failed to generate data dictionary:\n{str(e)}", "OK", "", "")
        return 0
    finally:
        if temporary_path and os.path.exists(temporary_path):
            try:
                os.remove(temporary_path)
            except OSError:
                pass

class SchemaSelectionDialog:
    """Dialog for selecting schema and output options"""

    def __init__(self, catalog):
        self.catalog = catalog
        self.selected_schema = None
        self.output_path = None
        self.config = DEFAULT_CONFIG.copy()

        # Create form
        self.form = mforms.Form(None, mforms.FormDialogFrame)
        self.form.set_title("Generate Data Dictionary with ERD - Version 3.7")

        # Create main box
        box = mforms.newBox(False)
        box.set_padding(20)
        box.set_spacing(15)

        # Title
        title_label = mforms.newLabel("Data Dictionary Generator v3.7")
        title_label.set_style(mforms.BigBoldStyle)
        box.add(title_label, False, False)

        # Separator
        box.add(mforms.newLabel(""), False, False)

        # Schema selection
        schema_label = mforms.newLabel("Select Database Schema:")
        schema_label.set_style(mforms.BoldStyle)
        box.add(schema_label, False, False)

        self.schema_selector = mforms.newSelector()
        preferred_index = None
        default_schema = getattr(catalog, 'defaultSchema', None)
        default_name = (getattr(default_schema, 'name', '') or
                        (default_schema if isinstance(default_schema, str) else ''))
        for index, schema in enumerate(catalog.schemata):
            self.schema_selector.add_item(
                f"{schema.name} — {len(schema.tables)} table"
                f"{'s' if len(schema.tables) != 1 else ''}"
            )
            if (schema == default_schema or schema.name == default_name) and schema.tables:
                preferred_index = index
            elif preferred_index is None and schema.tables:
                preferred_index = index
        if catalog.schemata:
            self.schema_selector.set_selected(preferred_index if preferred_index is not None else 0)
        self.schema_selector.set_name("Database schema")
        box.add(self.schema_selector, False, False)

        # Add separator
        box.add(mforms.newLabel(""), False, False)

        # Options section
        options_label = mforms.newLabel("Export Options:")
        options_label.set_style(mforms.BoldStyle)
        box.add(options_label, False, False)

        # Create two-column layout for checkboxes
        options_box = mforms.newBox(True)
        options_box.set_spacing(20)

        # Left column
        left_options = mforms.newBox(False)
        left_options.set_spacing(8)

        self.show_erd_cb = mforms.newCheckBox()
        self.show_erd_cb.set_text("Show Relationship Diagram (ERD)")
        self.show_erd_cb.set_active(self.config['show_relationship_diagram'])
        left_options.add(self.show_erd_cb, False, False)

        self.include_indexes_cb = mforms.newCheckBox()
        self.include_indexes_cb.set_text("Include Index Information")
        self.include_indexes_cb.set_active(self.config['include_indexes'])
        left_options.add(self.include_indexes_cb, False, False)

        self.include_comments_cb = mforms.newCheckBox()
        self.include_comments_cb.set_text("Include Column Comments")
        self.include_comments_cb.set_active(self.config['include_comments'])
        left_options.add(self.include_comments_cb, False, False)

        self.generate_ddl_cb = mforms.newCheckBox()
        self.generate_ddl_cb.set_text("Include reconstructed reference DDL")
        self.generate_ddl_cb.set_active(self.config['generate_ddl'])
        left_options.add(self.generate_ddl_cb, False, False)

        options_box.add(left_options, True, True)

        # Right column
        right_options = mforms.newBox(False)
        right_options.set_spacing(8)

        self.include_views_cb = mforms.newCheckBox()
        self.include_views_cb.set_text("Count Views")
        self.include_views_cb.set_active(self.config['include_views'])
        right_options.add(self.include_views_cb, False, False)

        self.include_triggers_cb = mforms.newCheckBox()
        self.include_triggers_cb.set_text("List Triggers")
        self.include_triggers_cb.set_active(self.config['include_triggers'])
        right_options.add(self.include_triggers_cb, False, False)

        self.include_routines_cb = mforms.newCheckBox()
        self.include_routines_cb.set_text("Count Stored Routines")
        self.include_routines_cb.set_active(self.config['include_routines'])
        right_options.add(self.include_routines_cb, False, False)

        # ERD layout option
        layout_label = mforms.newLabel("ERD Layout:")
        right_options.add(layout_label, False, False)

        self.layout_selector = mforms.newSelector()
        self.layout_selector.add_item("Balanced grid (recommended)")
        self.layout_selector.add_item("Parent-to-child hierarchy")
        self.layout_selector.set_selected(0)
        self.layout_selector.set_name("ERD layout")
        right_options.add(self.layout_selector, False, False)

        options_box.add(right_options, True, True)

        box.add(options_box, False, False)

        # Add separator
        box.add(mforms.newLabel(""), False, False)

        # Output file selection
        output_label = mforms.newLabel("Output Location:")
        output_label.set_style(mforms.BoldStyle)
        box.add(output_label, False, False)

        file_box = mforms.newBox(True)
        file_box.set_spacing(10)

        self.output_entry = mforms.newTextEntry()
        self.output_entry.set_value(os.path.join(os.path.expanduser("~"), "data_dictionary.html"))
        self.output_entry.set_name("Output file")
        file_box.add(self.output_entry, True, True)

        browse_button = mforms.newButton()
        browse_button.set_text("Browse...")
        browse_button.add_clicked_callback(self.browse_file)
        file_box.add(browse_button, False, False)

        box.add(file_box, False, False)

        # Add separator
        box.add(mforms.newLabel(""), False, False)

        # Buttons
        button_box = mforms.newBox(True)
        button_box.set_spacing(10)

        # Add spacer
        button_box.add(mforms.newLabel(""), True, True)

        self.cancel_button = mforms.newButton()
        self.cancel_button.set_text("Cancel")
        self.cancel_button.set_name("Cancel")
        self.cancel_button.add_clicked_callback(self.cancel_clicked)
        button_box.add(self.cancel_button, False, False)

        self.ok_button = mforms.newButton()
        self.ok_button.set_text("Generate")
        self.ok_button.set_name("Generate")
        self.ok_button.add_clicked_callback(self.ok_clicked)
        button_box.add(self.ok_button, False, False)

        box.add(button_box, False, False)

        self.form.set_content(box)
        self.form.set_size(600, 650)

    def browse_file(self):
        """Open file browser for output path selection"""
        filechooser = mforms.newFileChooser(self.form, mforms.SaveFile)
        filechooser.set_title("Save Data Dictionary As")
        filechooser.set_extensions("HTML Files (*.html)|*.html", "html")

        if filechooser.run_modal():
            path = filechooser.get_path()
            if not path.lower().endswith('.html'):
                path += '.html'
            self.output_entry.set_value(path)

    def ok_clicked(self):
        """Handle OK button click"""
        selected_index = self.schema_selector.get_selected_index()
        if selected_index < 0:
            mforms.Utilities.show_warning(
                "Select a schema", "Choose a database schema before generating.",
                "OK", "", ""
            )
            return
        if selected_index >= 0:
            self.selected_schema = self.catalog.schemata[selected_index]
            if not self.selected_schema.tables:
                mforms.Utilities.show_warning(
                    "Empty schema",
                    f"{self.selected_schema.name} has no tables. Select a schema "
                    "that contains model tables before generating the report.",
                    "OK", "", ""
                )
                self.selected_schema = None
                return
            self.output_path = self.output_entry.get_string_value()
            if self.output_path and not self.output_path.lower().endswith('.html'):
                self.output_path += '.html'

            # Update configuration
            self.config['show_relationship_diagram'] = self.show_erd_cb.get_active()
            self.config['include_indexes'] = self.include_indexes_cb.get_active()
            self.config['include_comments'] = self.include_comments_cb.get_active()
            self.config['generate_ddl'] = self.generate_ddl_cb.get_active()
            self.config['include_views'] = self.include_views_cb.get_active()
            self.config['include_triggers'] = self.include_triggers_cb.get_active()
            self.config['include_routines'] = self.include_routines_cb.get_active()
            self.config['diagram_layout'] = 'hierarchical' if self.layout_selector.get_selected_index() == 1 else 'force-directed'

            if not self.output_path:
                mforms.Utilities.show_warning("Invalid Path", "Please specify an output file path.", "OK", "", "")
                return

            self.form.close()

    def cancel_clicked(self):
        """Handle Cancel button click"""
        self.selected_schema = None
        self.output_path = None
        self.form.close()

    def run(self):
        """Show dialog and wait for user interaction"""
        self.form.run_modal(self.ok_button, self.cancel_button)
        return self.selected_schema is not None and self.output_path is not None
