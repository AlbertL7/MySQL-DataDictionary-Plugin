# MySQL-DataDictionary-Plugin
MySQL Workbench plugin that generates interactive HTML data dictionaries with searchable tables, columns, and visual ERD diagrams

[![MySQL](https://img.shields.io/badge/MySQL-4479A1?logo=mysql&logoColor=white)](https://www.mysql.com/)
[![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A powerful MySQL Workbench plugin that automatically generates beautiful, interactive HTML data dictionaries with intelligent Entity Relationship Diagrams (ERD). Perfect for database documentation, team collaboration, and project presentations.

## ✨ Features

### 📊 Interactive ERD Diagram
- **Visual relationship mapping** with curved connector lines
- **Intelligent label positioning** with collision detection and avoidance
- **Hierarchical or force-directed layouts** for optimal table placement
- **Zoom, pan, and fullscreen** controls for easy navigation
- **Click-to-navigate** from diagram to table details

### 🔍 Advanced Search & Filtering
- **Real-time search** with debouncing across tables, columns, and comments
- **Highlighted search results** with yellow background for easy visibility
- **Filter by foreign keys** - View tables with or without FKs
- **Table of Contents** with live filtering and quick navigation

### 📝 Comprehensive Documentation
- **Complete schema overview** with statistics (tables, columns, PKs, FKs)
- **Detailed table information** including:
  - Column definitions with data types, constraints, and defaults
  - Primary and Foreign Key relationships
  - Indexes and constraints
  - Table comments and column descriptions
- **Export functionality** - Download as CSV for offline analysis
- **Print-optimized styling** for professional documentation

### 🎨 Modern UI/UX
- Clean, responsive design with smooth animations
- Color-coded elements (PKs in red, FKs in blue)
- Expandable/collapsible sections
- Dark mode compatible table headers
- Mobile-friendly layout

## 📸 Screenshots

*Add your screenshots here showing:*
- ERD diagram example
- Search functionality
- Table detail view
- Filter options

## 🚀 Installation

### Prerequisites
- MySQL Workbench 8.0 or higher
- Python support enabled in MySQL Workbench

### Steps

1. **Download the plugin**
   ```bash
   git clone https://github.com/yourusername/mysql-data-dictionary-erd.git
   ```

2. **Locate MySQL Workbench plugins folder**
   - **Windows**: `%AppData%\MySQL\Workbench\scripts\`
   - **macOS**: `~/Library/Application Support/MySQL/Workbench/scripts/`
   - **Linux**: `~/.mysql/workbench/scripts/`

3. **Copy the plugin file**
   ```bash
   cp DataDictionarydump_COMPLETE.py [MySQL Workbench scripts folder]
   ```

4. **Restart MySQL Workbench**

5. **Access the plugin**
   - Open a database model or connection
   - Go to: **Tools** → **Utilities** → **Generate Data Dictionary with ERD**

## 📖 Usage

### Basic Usage

1. Open your database in MySQL Workbench
2. Navigate to **Tools** → **Utilities** → **Generate Data Dictionary with ERD**
3. Configure your preferences:
   - Enable/disable ERD diagram
   - Choose layout type (Hierarchical or Force-Directed)
   - Select output location
4. Click **Generate** and wait for completion
5. The HTML file will open automatically in your default browser

### Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| **Show Relationship Diagram** | Display interactive ERD | Enabled |
| **ERD Layout** | Choose between Hierarchical or Force-Directed | Force-Directed |
| **Output Path** | Location to save the HTML file | Desktop |

### Search Tips

- **Search by table name**: Type the table name
- **Search by column**: Enter column name to find all tables containing it
- **Search by data type**: Search for "VARCHAR", "INT", etc.
- **Search by comment**: Find tables/columns by their descriptions
- **Clear search**: Delete search text to show all tables

### Filter Options

- **All Tables**: Show all tables in the schema
- **Has FK**: Show only tables with foreign key relationships
- **No FK**: Show only tables without foreign keys

## 🛠️ Technical Details

### Technology Stack
- **Backend**: Python (for MySQL Workbench integration)
- **Frontend**: Pure HTML5, CSS3, JavaScript (no dependencies)
- **Graphics**: SVG for ERD rendering
- **Data Source**: MySQL Workbench GRT (Generic Runtime Type) API

### Key Features Implementation

#### Collision Detection Algorithm
The plugin uses a sophisticated multi-pass algorithm to prevent FK label overlaps:
1. **Pass 1**: Calculate all relationship data and initial positions
2. **Pass 2**: Try 14+ different positions for each label to find collision-free placement
3. **Pass 3**: Render all relationships with optimized label positions

#### Search Highlighting
- TreeWalker API for efficient DOM traversal
- Regex-free text matching for better performance
- Dynamic span injection for highlighted terms
- Automatic cleanup on new searches

#### Layout Algorithms
- **Hierarchical**: Tables organized by dependency depth
- **Force-Directed**: Grid-based layout with optimized spacing

## 🤝 Contributing

Contributions are welcome! Here's how you can help:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

### Development Guidelines
- Follow PEP 8 style guide for Python code
- Add comments for complex logic
- Test with multiple database schemas
- Update documentation for new features

## 🐛 Known Issues & Limitations

- Cross-schema foreign keys are not displayed in the ERD (by design)
- Very large schemas (500+ tables) may have performance considerations
- SVG rendering may vary slightly between browsers

## 📋 Roadmap

- [ ] Add table grouping/clustering in ERD
- [ ] Support for multiple schema export
- [ ] Dark mode toggle
- [ ] Export ERD as PNG/PDF
- [ ] Custom color themes
- [ ] Stored procedures and views documentation
- [ ] Version comparison feature

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built for MySQL Workbench using the GRT API
- Inspired by the need for better database documentation tools
- Thanks to the open-source community for continuous inspiration

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/mysql-data-dictionary-erd/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/mysql-data-dictionary-erd/discussions)
- **Email**: your.email@example.com

## 🌟 Show Your Support

If this plugin helped you, please consider:
- ⭐ Starring the repository
- 🐛 Reporting bugs
- 💡 Suggesting new features
- 📢 Sharing with others

---

**Made with ❤️ for the database community**
