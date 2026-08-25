# MySQL Workbench Data Dictionary Plugin

Generate a self-contained HTML data dictionary from the **catalog in the MySQL
Workbench model that is currently open**. The report is designed for students:
it starts with totals and a short reading guide, then provides an ERD, a table
finder, and one expandable detail section per table.

The plugin does not send schema data to a web service and the generated report
does not load external JavaScript, fonts, or analytics.

## What version 3.7 documents

- Tables, columns, data types, nullability, defaults, comments, and generated columns
- Primary keys, single-column unique keys, composite unique groups, and indexes
- Both sides of each foreign key: **references** and **referenced by**
- Foreign-key optionality, identifying status, and `ON DELETE` / `ON UPDATE` actions
- Check constraints and triggers when Workbench exposes them in the model catalog
- Counts for tables, columns, foreign keys, indexes, views, routines, and triggers
- A searchable table list, foreign-key filters, an interactive SVG ERD, CSV/JSON export, and print/PDF styling
- Reconstructed reference DDL with identifiers, indexes, checks, generated expressions, foreign-key actions, comments, and storage engine

> **Important:** “Reference DDL” is reconstructed from the metadata Workbench
> exposes to plugins. Compare it with `SHOW CREATE TABLE table_name;` before
> executing it. The data dictionary is documentation, not a migration tool.

## Before you install it

- MySQL Workbench 8.0 with Python plugin support
- An EER model/catalog loaded in Workbench
- No `pip` packages or separate API keys

This is a **model-catalog plugin**, not a live-query plugin. If the schema exists
only on a server, use **Database → Reverse Engineer**, select the schema, finish
the wizard, and save the resulting `.mwb` model first. MySQL server 8.4 features
can be documented when they are represented in that loaded catalog; the ability
to connect to or reverse-engineer a particular server version is determined by
the installed MySQL Workbench version, not by this plugin. Oracle notes that
Workbench is developed and tested with Server 8.0; it may connect to Server 8.4
and later, but some Workbench features may not function with those versions.
See the [current Workbench manual](https://dev.mysql.com/doc/workbench/en/).

A live server connection is not required once the model exists: open the `.mwb`
file and make its model tab active. If you have only a MySQL create script, use
**File → Import → Reverse Engineer MySQL Create Script**. Some Workbench releases
can omit table-level `CHECK` constraints during create-script import, so inspect
the resulting model and restore any missing checks before generating the report.
Importing a script into a model does not execute it or create a live database.

## Install

1. Download [`DataDictionaryDump.py`](DataDictionaryDump.py). Do not paste it into the SQL editor.
2. In MySQL Workbench, choose **Scripting → Install Plugin/Module File…** and select the `.py` file.
3. Restart MySQL Workbench.
4. Open the `.mwb` model that contains the schema you want to document.

If the menu wording differs slightly on your operating system, use Workbench’s
plugin/module installer—not the server administration or SQL editor menus.

## Generate a report

1. Open the `.mwb` model, make its **model tab active**, and confirm the desired schema appears in the model catalog.
2. Choose **Tools → Catalog → Generate Data Dictionary with ERD**.
   Some older or platform-specific Workbench builds label the first menu
   **Plugins** instead of **Tools**.
   The command may not appear while the Home screen or a SQL Editor tab is active.
3. Select the schema you want to document.
4. Leave the ERD, indexes, comments, and reference DDL enabled unless the assignment says otherwise.
5. Choose an output file and select **Generate**.
6. If that file already exists, Workbench asks before replacing it.

The default output is `data_dictionary.html` in your home folder—not necessarily
the Desktop. The plugin writes through a temporary file so a failed generation
does not leave a partial report.

## Reading the report

1. Confirm the summary totals.
2. Use the ERD for the big picture.
3. Use **Database tables** or search to open one table.
4. Read **References** for foreign keys owned by that table.
5. Read **Referenced by** for tables that point to it.

Compare the report summary with the active Workbench model. Verify the table,
column, key, relationship, check-constraint, generated-column, and storage-engine
totals, then spot-check foreign-key optionality and referential actions.

## Security and privacy

Version 3.7 treats names, comments, defaults, and other catalog metadata as
untrusted text. It uses inert JSON blocks, safe DOM IDs, context-appropriate
escaping, a restrictive Content Security Policy, and formula-safe CSV cells.
The report remains a local file unless you choose to share it.

Review reports before publishing them: database comments and object names can
contain business-sensitive information even when no row data is included.

## Known limitations

- The plugin documents one selected schema at a time.
- Cross-schema foreign keys appear in textual table details but are omitted from the ERD because the external table has no node in the selected schema.
- Views and stored routines are counted; their definitions are not expanded.
- Workbench catalog objects vary slightly by release. The plugin normalizes both direct and wrapped index-column representations, but an uncommon catalog property may still be absent.
- Large schemas create large SVG diagrams; search and the table list may be easier to use than the ERD.
- Reference DDL can only reproduce metadata exposed through the Workbench plugin API.

## Test locally

The test suite uses a representative fake Workbench catalog; it does not need
MySQL Workbench or a live database.

```bash
python3 -W error::SyntaxWarning -m py_compile DataDictionaryDump.py
python3 -m unittest discover -s tests -v
```

The tests cover the 12/94/18 acceptance totals, key/action semantics, generated
and check constraints, DDL reconstruction, export table names, HTML/script
escaping, CSV defenses, and core accessibility landmarks.

## Contributing

Please keep the plugin dependency-free and compatible with Workbench’s embedded
Python runtime. Add or update a fake-catalog regression test for behavior changes.

## License

This repository does not currently declare a software license. The repository
owner should choose and add one before distributing the plugin under explicit
reuse terms.
