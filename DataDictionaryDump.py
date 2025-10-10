# MySQL Workbench Data Dictionary Generator Plugin with Relationship Visualization
# Version: 3.5 - With Interactive ERD
# This version combines the ERD functionality with the complete HTML generation from htmldatadict.py

from wb import *
import grt
import mforms
from datetime import datetime
import os
import html
import json
import math

# Module registration info
ModuleInfo = DefineModule(name="DataDictionary", author="Enhanced Generator", version="3.5", description="Generate comprehensive HTML data dictionary with relationship visualization")

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
    return html.escape(str(text))

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
    """Generate CREATE TABLE statement"""
    ddl = f"CREATE TABLE `{table.name}` (\n"

    # Columns
    column_definitions = []
    for column in table.columns:
        col_def = f"  `{column.name}` {column.formattedType}"
        if column.isNotNull:
            col_def += " NOT NULL"
        if column.defaultValue:
            col_def += f" DEFAULT {column.defaultValue}"
        if column.autoIncrement:
            col_def += " AUTO_INCREMENT"
        if column.comment:
            col_def += f" COMMENT '{escape_html(column.comment)}'"
        column_definitions.append(col_def)

    # Primary key
    pk_columns = [col.name for col in table.columns if table.isPrimaryKeyColumn(col)]
    if pk_columns:
        column_definitions.append(f"  PRIMARY KEY ({', '.join([f'`{c}`' for c in pk_columns])})")

    # Foreign keys
    for fk in table.foreignKeys:
        fk_cols = ', '.join([f'`{col.name}`' for col in fk.columns])
        ref_cols = ', '.join([f'`{col.name}`' for col in fk.referencedColumns])
        column_definitions.append(
            f"  CONSTRAINT `{fk.name}` FOREIGN KEY ({fk_cols}) "
            f"REFERENCES `{fk.referencedTable.name}` ({ref_cols})"
        )

    ddl += ',\n'.join(column_definitions)
    ddl += "\n)"

    if table.comment:
        ddl += f" COMMENT='{escape_html(table.comment)}'"

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
        # Hierarchical layout based on relationship depth
        levels = {}
        processed = set()

        # Find root tables (no incoming foreign keys)
        root_tables = []
        referenced_tables = set()
        for rel in relationships:
            referenced_tables.add(rel['to'])

        for table_name in tables:
            if table_name not in referenced_tables:
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
                if rel['from'] in levels and rel['to'] not in processed:
                    levels[rel['to']] = current_level
                    processed.add(rel['to'])
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

    else:  # force-directed layout - improved grid
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

    for table in schema.tables:
        for fk in table.foreignKeys:
            relationships.append({
                'from': table.name,
                'to': fk.referencedTable.name,
                'name': fk.name,
                'columns': ', '.join([col.name for col in fk.columns]),
                'ref_columns': ', '.join([col.name for col in fk.referencedColumns])
            })
            tables_with_relationships.add(table.name)
            tables_with_relationships.add(fk.referencedTable.name)

    # Get all table names
    all_tables = [table.name for table in schema.tables]

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
            <h2>📊 Entity Relationship Diagram</h2>
            <div class="erd-controls">
                <button onclick="zoomIn()" class="erd-btn">🔍 Zoom In</button>
                <button onclick="zoomOut()" class="erd-btn">🔍 Zoom Out</button>
                <button onclick="resetZoom()" class="erd-btn">↺ Reset</button>
                <button onclick="toggleERDFullscreen()" class="erd-btn">⛶ Fullscreen</button>
            </div>
        </div>
        <div class="erd-wrapper" id="erdWrapper">
            <svg id="erdDiagram" width="{svg_width}" height="{svg_height}" viewBox="0 0 {svg_width} {svg_height}">
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

        # Calculate midpoint
        mid_x = (from_x + to_x) / 2
        mid_y = (from_y + to_y) / 2

        # Calculate distance and angle for better curves
        dx = to_x - from_x
        dy = to_y - from_y
        distance = math.sqrt(dx * dx + dy * dy)

        # Create control point offset based on direction
        # This creates smoother, more natural curves
        if abs(dx) > abs(dy):
            # Horizontal-ish line
            control_x = mid_x
            control_y = mid_y + (distance * 0.15 if dy >= 0 else -distance * 0.15)
        else:
            # Vertical-ish line
            control_x = mid_x + (distance * 0.15 if dx >= 0 else -distance * 0.15)
            control_y = mid_y

        # Relationship label - only show FK name if it's short
        rel_name = rel['name']
        if len(rel_name) > 20:
            rel_name = rel_name[:17] + '...'

        # Position label slightly offset from line
        label_y = mid_y - 8

        svg += f'''
                    <g class="relationship" data-from="{escape_html(rel['from'])}" data-to="{escape_html(rel['to'])}">
                        <path d="M {from_x} {from_y} Q {control_x} {control_y} {to_x} {to_y}"
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

            svg += f'''
                    <g class="table-node {node_class}" data-table="{escape_html(table.name)}"
                       transform="translate({x}, {y})"
                       onclick="jumpToTable('{escape_html(table.name)}')">

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
        }

        .relationship:hover .relationship-label {
            font-weight: bold;
            fill: var(--primary);
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
            svg.style.transform = `scale(${currentZoom})`;
        }

        function toggleERDFullscreen() {
            const wrapper = document.getElementById('erdWrapper');
            wrapper.classList.toggle('fullscreen');

            if (wrapper.classList.contains('fullscreen')) {
                document.body.style.overflow = 'hidden';
            } else {
                document.body.style.overflow = '';
            }
        }

        function jumpToTable(tableName) {
            // Remove fullscreen if active
            const wrapper = document.getElementById('erdWrapper');
            if (wrapper.classList.contains('fullscreen')) {
                toggleERDFullscreen();
            }

            // Scroll to table
            const tableElement = document.getElementById(tableName);
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
                                const targetNode = document.querySelector(`.table-node[data-table="${rel.dataset.to}"]`);
                                if (targetNode) targetNode.classList.add('highlight-target');
                            } else {
                                const sourceNode = document.querySelector(`.table-node[data-table="${rel.dataset.from}"]`);
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
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
            position: relative;
            border-bottom: 3px solid var(--primary);
        }

        .table-header:hover {
            background: var(--gray-900);
        }

        .table-name-section {
            flex: 1;
        }

        .table-name {
            font-size: 1.625rem;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 12px;
            color: var(--white);
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
            display: flex;
            gap: 24px;
            font-size: 0.9375rem;
            font-weight: 600;
            color: var(--gray-300);
        }

        .table-actions {
            position: absolute;
            top: 20px;
            right: 24px;
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
            transition: all 0.3s;
            text-decoration: none;
            font-size: 1.5rem;
            font-weight: bold;
            z-index: 100;
            border: 2px solid transparent;
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
                page-break-after: avoid !important;
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
            }

            .legend-badge {
                font-size: 8pt !important;
                padding: 1mm 2mm !important;
            }

            /* ERD for print */
            .erd-container {
                page-break-before: always !important;
                page-break-after: always !important;
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
    <title>Data Dictionary - {escape_html(schema.name)}</title>
    <style>{styles}</style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 Data Dictionary</h1>
            <div class="subtitle">{escape_html(schema.name)} Database Schema</div>
            <div class="meta-info">
                <div>Generated: {generation_time}</div>
                <div>Version: 3.5 with ERD</div>
            </div>
            <div class="export-buttons">
                <button class="export-btn" onclick="exportToCSV()">📊 Export CSV</button>
                <button class="export-btn" onclick="exportToJSON()">📋 Export JSON</button>
                <button class="export-btn" onclick="printToPDF()">🖨️ Print to PDF</button>
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
            <input type="text" id="searchBox" class="search-box" placeholder="🔍 Search tables, columns, and comments..." onkeyup="searchWithDebounce()">
            <div class="filter-buttons">
                <button class="filter-btn active" onclick="filterTables('all')">All Tables</button>
                <button class="filter-btn" onclick="filterTables('has-fk')">Has FK</button>
                <button class="filter-btn" onclick="filterTables('no-fk')">No FK</button>
                <button class="filter-btn" onclick="toggleAllTables()">Toggle All</button>
            </div>
        </div>

        <div class="toc">
            <div class="toc-header">
                <h2>Database Tables</h2>
                <span style="color: #6b7280; font-size: 0.9375rem;">Click to jump to table • Click header to collapse</span>
            </div>
            <div class="toc-grid">
"""

    # Add table of contents
    for table in schema.tables:
        col_count = len(table.columns)
        fk_count = len(table.foreignKeys)
        html_content += f"""                <a href="#{escape_html(table.name)}" class="toc-item" data-fk-count="{fk_count}">
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

    # Generate each table
    for table in schema.tables:
        table_name_escaped = escape_html(table.name)
        col_count = len(table.columns)
        fk_count = len(table.foreignKeys)
        idx_count = len(table.indices)

        # Generate DDL for this table
        if config.get('generate_ddl', True):
            ddl = generate_table_ddl(table)
            ddl_scripts[table.name] = escape_html(ddl)

        # Table comment if exists
        table_comment_html = ""
        if table.comment:
            table_comment_html = f'<div class="table-comment">{escape_html(table.comment)}</div>'

        html_content += f"""            <div class="table-wrapper" id="{table_name_escaped}" data-fk-count="{fk_count}">
                <div class="table-header" onclick="toggleTable('{table_name_escaped}')">
                    <div class="table-name-section">
                        <div class="table-name">
                            {table_name_escaped}
                            <span class="collapse-indicator">▼</span>
                        </div>
                        {table_comment_html}
                    </div>
                    <div class="table-meta">
                        <span>📋 {col_count} Columns</span>
                        <span>🔗 {fk_count} Foreign Keys</span>
                        <span>📍 {idx_count} Indexes</span>
                    </div>"""

        if config.get('generate_ddl', True):
            html_content += f"""
                    <div class="table-actions">
                        <button class="btn-copy-ddl" onclick="event.stopPropagation(); showDDL('{table_name_escaped}')">📝 View DDL</button>
                    </div>"""

        html_content += f"""
                </div>
                <div class="table-content">
                    <table>
                        <thead>
                            <tr>
                                <th style="width: 3%">#</th>
                                <th style="width: 20%">Column Name</th>
                                <th style="width: 15%">Data Type</th>
                                <th style="width: 8%">Nullable</th>
                                <th style="width: 12%">Constraints</th>
                                <th style="width: 12%">Default</th>
                                <th style="width: 10%">Extra</th>"""

        if config.get('include_comments', True):
            html_content += """
                                <th style="width: 20%">Comment</th>"""

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

            # Check for unique constraint
            for index in table.indices:
                if index.unique and column in index.columns:
                    keys.append('<span class="key-badge badge-unique">UQ</span>')
                    break

            # Check for regular index
            if config.get('include_indexes', True):
                for index in table.indices:
                    if not index.unique and column in index.columns and not table.isPrimaryKeyColumn(column):
                        keys.append('<span class="key-badge badge-index">IDX</span>')
                        break

            key_str = ' '.join(keys) if keys else '-'

            # Nullable - clearer display
            if column.isNotNull == 1:
                nullable = '<span class="key-badge badge-nn">NOT NULL</span>'
            else:
                nullable = '<span class="key-badge badge-null">NULL</span>'

            # Default value
            if column.defaultValue:
                default = f'<span class="default-value">{escape_html(column.defaultValue)}</span>'
            else:
                default = '<span style="color: #9ca3af;">-</span>'

            # Extra
            extras = []
            if column.autoIncrement:
                extras.append('AUTO_INCREMENT')
            if hasattr(column, 'generated') and column.generated:
                extras.append('GENERATED')
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
                        <strong>📍 Index Information</strong>
"""
            for index in table.indices:
                index_cols = ', '.join([col.name for col in index.columns])
                index_type = "UNIQUE" if index.unique else "INDEX"
                if index.indexType:
                    index_type += f" ({index.indexType})"

                html_content += f"""                        <div class="index-item">
                            <div>
                                <span style="font-weight: 700;">{escape_html(index.name)}</span>
                                <span style="color: #6b7280;"> ({escape_html(index_cols)})</span>
                            </div>
                            <span class="index-type">{index_type}</span>
                        </div>
"""
            html_content += """                    </div>
"""

        # Add foreign key relationships if any
        if table.foreignKeys:
            html_content += """                    <div class="relationships-section">
                        <strong>🔗 Foreign Key Relationships</strong>
"""
            for fk in table.foreignKeys:
                source_cols = ', '.join([col.name for col in fk.columns])
                ref_cols = ', '.join([col.name for col in fk.referencedColumns])
                html_content += f"""                        <div class="relationship-item">
                            {escape_html(source_cols)} → {escape_html(fk.referencedTable.name)}.{escape_html(ref_cols)}
                            <span style="color: #6b7280; font-size: 0.8125rem; margin-left: 12px;">({escape_html(fk.name)})</span>
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
            </div>
"""

    # Close HTML and add JavaScript with DDL modal if configured
    ddl_modal_html = ""
    if config.get('generate_ddl', True):
        ddl_modal_html = """
    <!-- DDL Modal -->
    <div id="ddlModal" class="ddl-modal">
        <div class="ddl-content">
            <div class="ddl-header">
                <h3>Table DDL Statement</h3>
                <button class="btn-close" onclick="closeDDL()">✕ Close</button>
            </div>
            <pre id="ddlCode" class="ddl-code"></pre>
            <div style="margin-top: 24px; text-align: right;">
                <button class="export-btn" style="background: var(--primary); color: white; border: none; font-weight: 600;" onclick="copyDDL()">📋 Copy to Clipboard</button>
            </div>
        </div>
    </div>"""

    html_content += f"""        </div>
    </div>

    {ddl_modal_html}

    <!-- Toast Notification -->
    <div id="toast" class="toast">✓ Operation successful!</div>

    <a href="#" onclick="scrollToTop(); return false;" class="back-to-top">↑</a>

    <script>
        // DDL Scripts Storage
        const ddlScripts = {json.dumps(ddl_scripts) if config.get('generate_ddl', True) else '{}'};

        // Schema Data for Export
        const schemaData = {json.dumps({
            'name': schema.name,
            'generated': generation_time,
            'statistics': stats,
            'tables': [
                {
                    
                    
                    'comment': table.comment if table.comment else None,
                    'columns': [
                        {
                            'name': col.name,
                            'type': col.formattedType,
                            'nullable': col.isNotNull == 0,
                            'default': col.defaultValue,
                            'comment': col.comment if col.comment else None,
                            'is_primary_key': table.isPrimaryKeyColumn(col),
                            'is_foreign_key': table.isForeignKeyColumn(col),
                            'auto_increment': col.autoIncrement if hasattr(col, 'autoIncrement') else False
                        } for col in table.columns
                    ],
                    'foreign_keys': [
                        {
                            'name': fk.name,
                            'columns': [col.name for col in fk.columns],
                            'referenced_table': fk.referencedTable.name,
                            'referenced_columns': [col.name for col in fk.referencedColumns]
                        } for fk in table.foreignKeys
                    ]
                } for table in schema.tables
            ]
        }, default=str)};

        // Debounced search
        let searchTimeout;
        function searchWithDebounce() {{
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(searchTables, 300);
        }}

        function searchTables() {{
            const searchTerm = document.getElementById('searchBox').value.toLowerCase();
            const tables = document.querySelectorAll('.table-wrapper');
            let visibleCount = 0;

            tables.forEach(table => {{
                const tableContent = table.textContent.toLowerCase();
                if (searchTerm === '' || tableContent.includes(searchTerm)) {{
                    table.style.display = 'block';
                    visibleCount++;
                }} else {{
                    table.style.display = 'none';
                }}
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
            const tables = document.querySelectorAll('.table-wrapper');
            const buttons = document.querySelectorAll('.filter-btn');

            // Update button states
            buttons.forEach(btn => {{
                btn.classList.remove('active');
            }});

            // Find and activate the right button
            buttons.forEach(btn => {{
                if ((filter === 'all' && btn.textContent === 'All Tables') ||
                    (filter === 'has-fk' && btn.textContent === 'Has FK') ||
                    (filter === 'no-fk' && btn.textContent === 'No FK')) {{
                    btn.classList.add('active');
                }}
            }});

            // Filter tables
            tables.forEach(table => {{
                const fkCount = parseInt(table.dataset.fkCount);
                if (filter === 'all') {{
                    table.style.display = 'block';
                }} else if (filter === 'has-fk' && fkCount > 0) {{
                    table.style.display = 'block';
                }} else if (filter === 'no-fk' && fkCount === 0) {{
                    table.style.display = 'block';
                }} else {{
                    table.style.display = 'none';
                }}
            }});
        }}

        function toggleTable(tableId) {{
            const table = document.getElementById(tableId);
            table.classList.toggle('collapsed');
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
            }});
        }}

        function showDDL(tableName) {{
            const modal = document.getElementById('ddlModal');
            const code = document.getElementById('ddlCode');
            code.textContent = ddlScripts[tableName] || 'DDL not available';
            modal.classList.add('show');
        }}

        function closeDDL() {{
            document.getElementById('ddlModal').classList.remove('show');
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
            // Prepare page for printing
            document.body.classList.add('printing');

            // Expand all collapsed tables before printing
            const tables = document.querySelectorAll('.table-wrapper.collapsed');
            tables.forEach(table => {{
                table.classList.remove('collapsed');
            }});

            // Give browser time to render changes
            setTimeout(() => {{
                window.print();

                // Restore collapsed state after printing
                setTimeout(() => {{
                    document.body.classList.remove('printing');
                }}, 1000);
            }}, 100);

            // Show instructions
            showToast('Print dialog opening. Select "Save as PDF" in the printer options.');
        }}

        function exportToCSV() {{
            let csv = 'Table,Column,Type,Nullable,Primary Key,Foreign Key,Default,Auto Increment,Comment\\n';
            schemaData.tables.forEach(table => {{
                table.columns.forEach(col => {{
                    const nullable = col.nullable ? 'YES' : 'NO';
                    const isPK = col.is_primary_key ? 'YES' : 'NO';
                    const isFK = col.is_foreign_key ? 'YES' : 'NO';
                    const autoInc = col.auto_increment ? 'YES' : 'NO';
                    const defaultVal = col.default || '';
                    const comment = col.comment || '';
                    csv += `"${{table.name}}","${{col.name}}","${{col.type}}","${{nullable}}","${{isPK}}","${{isFK}}","${{defaultVal}}","${{autoInc}}","${{comment}}"\\n`;
                }});
            }});

            const blob = new Blob([csv], {{ type: 'text/csv;charset=utf-8;' }});
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            link.download = `data_dictionary_${{schemaData.name}}_${{Date.now()}}.csv`;
            link.click();
            showToast('CSV exported successfully!');
        }}

        function exportToJSON() {{
            const blob = new Blob([JSON.stringify(schemaData, null, 2)], {{ type: 'application/json' }});
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            link.download = `data_dictionary_${{schemaData.name}}_${{Date.now()}}.json`;
            link.click();
            showToast('JSON exported successfully!');
        }}

        function scrollToTop() {{
            window.scrollTo({{ top: 0, behavior: 'smooth' }});
            return false;
        }}

        // Close modal on escape or click outside
        document.addEventListener('keydown', function(e) {{
            if (e.key === 'Escape') {{
                closeDDL();
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
                   pluginMenu="Catalog")
@ModuleInfo.export(grt.INT, grt.classes.db_Catalog)
def generateDataDictionary(catalog):
    """Main plugin function called from menu"""

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

    try:
        # Generate HTML content with ERD
        html_content = generate_html_content(selected_schema, config)

        # Write to file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        # Show success message with options
        result = mforms.Utilities.show_message("Success",
            f"Data Dictionary with ERD generated successfully!\n\nFile saved to:\n{output_path}\n\nDo you want to open the file now?",
            "Open File", "OK", "")

        if result == mforms.ResultOk:
            # Try to open the file in default browser
            import webbrowser
            webbrowser.open(f"file://{output_path}")

        return 1

    except Exception as e:
        mforms.Utilities.show_error("Error", f"Failed to generate data dictionary:\n{str(e)}", "OK", "", "")
        return 0

class SchemaSelectionDialog:
    """Dialog for selecting schema and output options"""

    def __init__(self, catalog):
        self.catalog = catalog
        self.selected_schema = None
        self.output_path = None
        self.config = DEFAULT_CONFIG.copy()

        # Create form
        self.form = mforms.Form(None, mforms.FormDialogFrame)
        self.form.set_title("Generate Data Dictionary with ERD - Version 3.5")

        # Create main box
        box = mforms.newBox(False)
        box.set_padding(20)
        box.set_spacing(15)

        # Title
        title_label = mforms.newLabel("Data Dictionary Generator v3.5 - With Relationship Visualization")
        title_label.set_style(mforms.BigBoldStyle)
        box.add(title_label, False, False)

        # Separator
        box.add(mforms.newLabel(""), False, False)

        # Schema selection
        schema_label = mforms.newLabel("Select Database Schema:")
        schema_label.set_style(mforms.BoldStyle)
        box.add(schema_label, False, False)

        self.schema_selector = mforms.newSelector()
        for schema in catalog.schemata:
            self.schema_selector.add_item(schema.name)
        if catalog.schemata:
            self.schema_selector.set_selected(0)
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
        self.generate_ddl_cb.set_text("Generate DDL Statements")
        self.generate_ddl_cb.set_active(self.config['generate_ddl'])
        left_options.add(self.generate_ddl_cb, False, False)

        options_box.add(left_options, True, True)

        # Right column
        right_options = mforms.newBox(False)
        right_options.set_spacing(8)

        self.include_views_cb = mforms.newCheckBox()
        self.include_views_cb.set_text("Include Views")
        self.include_views_cb.set_active(self.config['include_views'])
        right_options.add(self.include_views_cb, False, False)

        self.include_triggers_cb = mforms.newCheckBox()
        self.include_triggers_cb.set_text("Include Triggers")
        self.include_triggers_cb.set_active(self.config['include_triggers'])
        right_options.add(self.include_triggers_cb, False, False)

        self.include_routines_cb = mforms.newCheckBox()
        self.include_routines_cb.set_text("Include Stored Routines")
        self.include_routines_cb.set_active(self.config['include_routines'])
        right_options.add(self.include_routines_cb, False, False)

        # ERD layout option
        layout_label = mforms.newLabel("ERD Layout:")
        right_options.add(layout_label, False, False)

        self.layout_selector = mforms.newSelector()
        self.layout_selector.add_item("Force-Directed")
        self.layout_selector.add_item("Hierarchical")
        self.layout_selector.set_selected(0)
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

        cancel_button = mforms.newButton()
        cancel_button.set_text("Cancel")
        cancel_button.add_clicked_callback(self.cancel_clicked)
        button_box.add(cancel_button, False, False)

        ok_button = mforms.newButton()
        ok_button.set_text("Generate")
        ok_button.add_clicked_callback(self.ok_clicked)
        button_box.add(ok_button, False, False)

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
            if not path.endswith('.html'):
                path += '.html'
            self.output_entry.set_value(path)

    def ok_clicked(self):
        """Handle OK button click"""
        selected_index = self.schema_selector.get_selected_index()
        if selected_index >= 0:
            self.selected_schema = self.catalog.schemata[selected_index]
            self.output_path = self.output_entry.get_string_value()

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
        self.form.run_modal(None, None)
        return self.selected_schema is not None and self.output_path is not None
