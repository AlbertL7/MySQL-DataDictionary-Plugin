"""Regression tests for the standalone Workbench plugin.

The fake GRT objects mirror the attributes used by the plugin.  The fixture is
the canonical Week 3 OnlineStoreDB model: 12 tables, 94 columns, 18 foreign
keys, 5 unique groups, 2 checks, and one stored generated column.
"""

import importlib.util
import json
import re
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FakeModuleInfo:
    def plugin(self, *args, **kwargs):
        return lambda function: function

    def export(self, *args, **kwargs):
        return lambda function: function


def load_plugin():
    wb = types.ModuleType("wb")
    wb.DefineModule = lambda **kwargs: FakeModuleInfo()
    wb.wbinputs = types.SimpleNamespace(currentCatalog=lambda: object())
    sys.modules["wb"] = wb

    grt = types.ModuleType("grt")
    grt.INT = int
    grt.classes = types.SimpleNamespace(db_Catalog=object)
    sys.modules["grt"] = grt

    mforms = types.ModuleType("mforms")
    mforms.FormDialogFrame = 0
    mforms.SaveFile = 0
    mforms.BigBoldStyle = 0
    mforms.BoldStyle = 0
    mforms.ResultOk = 1
    sys.modules["mforms"] = mforms

    spec = importlib.util.spec_from_file_location(
        "data_dictionary_plugin", ROOT / "DataDictionaryDump.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PLUGIN = load_plugin()


class Column:
    def __init__(self, name, formatted_type="INT", required=False, default=None,
                 auto_increment=False, comment="", generated=False,
                 generated_expression="", generated_storage=""):
        self.name = name
        self.formattedType = formatted_type
        self.isNotNull = 1 if required else 0
        self.defaultValue = default
        self.autoIncrement = auto_increment
        self.comment = comment
        self.generated = generated
        self.generatedExpression = generated_expression
        self.generatedStorage = generated_storage
        self.checks = []


class IndexColumn:
    def __init__(self, column):
        self.referencedColumn = column


class Index:
    def __init__(self, name, columns, unique=False, index_type="BTREE"):
        self.name = name
        self.columns = [IndexColumn(column) for column in columns]
        self.unique = unique
        self.indexType = index_type


class ForeignKey:
    def __init__(self, name, columns, referenced_table, referenced_columns,
                 delete_rule, update_rule="CASCADE"):
        self.name = name
        self.columns = columns
        self.referencedTable = referenced_table
        self.referencedColumns = referenced_columns
        self.deleteRule = delete_rule
        self.updateRule = update_rule


class Check:
    def __init__(self, name, expression):
        self.name = name
        self.expression = expression


class WorkbenchCheck:
    """Shape used by MySQL Workbench 8.0.47's db.CheckConstraint."""
    def __init__(self, name, search_condition):
        self.name = name
        self.searchCondition = search_condition


class Table:
    def __init__(self, name, columns, primary_key):
        self.name = name
        self.columns = columns
        self.primary_key = set(primary_key)
        self.foreignKeys = []
        self.indices = [Index("PRIMARY", [self.column(name) for name in primary_key], True)]
        self.checkConstraints = []
        self.tableEngine = "InnoDB"
        self.comment = ""
        self.triggers = []

    def column(self, name):
        return next(column for column in self.columns if column.name == name)

    def isPrimaryKeyColumn(self, column):
        return column.name in self.primary_key

    def isForeignKeyColumn(self, column):
        return any(column in foreign_key.columns for foreign_key in self.foreignKeys)


class Schema:
    def __init__(self, name, tables):
        self.name = name
        self.tables = tables
        self.views = []
        self.routines = []


def columns(specs):
    return [Column(*spec) for spec in specs]


def canonical_schema():
    definitions = {
        "Customers": [
            ("customer_id", "INT", True, None, True),
            ("first_name", "VARCHAR(50)", True), ("last_name", "VARCHAR(50)", True),
            ("email", "VARCHAR(100)", True), ("phone", "VARCHAR(20)"),
            ("date_registered", "DATE", True), ("loyalty_points", "INT", False, "0"),
        ],
        "Addresses": [
            ("address_id", "INT", True, None, True), ("customer_id", "INT", True),
            ("address_type", "ENUM('Billing','Shipping','Both')", False, "'Both'"),
            ("street_address", "VARCHAR(255)", True), ("city", "VARCHAR(100)", True),
            ("state_province", "VARCHAR(50)"), ("postal_code", "VARCHAR(20)"),
            ("country", "VARCHAR(50)", True), ("is_default", "BOOLEAN", False, "FALSE"),
        ],
        "Categories": [
            ("category_id", "INT", True, None, True), ("category_name", "VARCHAR(50)", True),
            ("description", "TEXT"), ("parent_category_id", "INT"),
        ],
        "Suppliers": [
            ("supplier_id", "INT", True, None, True), ("company_name", "VARCHAR(100)", True),
            ("contact_name", "VARCHAR(100)"), ("contact_email", "VARCHAR(100)"),
            ("phone", "VARCHAR(20)"), ("address", "VARCHAR(255)"),
            ("city", "VARCHAR(100)"), ("country", "VARCHAR(50)"),
            ("rating", "DECIMAL(2,1)"),
        ],
        "Products": [
            ("product_id", "INT", True, None, True), ("product_name", "VARCHAR(100)", True),
            ("description", "TEXT"), ("category_id", "INT"), ("supplier_id", "INT"),
            ("unit_price", "DECIMAL(10,2)", True), ("units_in_stock", "INT", False, "0"),
            ("units_on_order", "INT", False, "0"), ("reorder_level", "INT", False, "10"),
            ("discontinued", "BOOLEAN", False, "FALSE"), ("weight_kg", "DECIMAL(8,3)"),
            ("date_added", "DATE", True),
        ],
        "Employees": [
            ("employee_id", "INT", True, None, True), ("first_name", "VARCHAR(50)", True),
            ("last_name", "VARCHAR(50)", True), ("email", "VARCHAR(100)", True),
            ("phone", "VARCHAR(20)"), ("hire_date", "DATE", True),
            ("job_title", "VARCHAR(50)"), ("department", "VARCHAR(50)"),
            ("manager_id", "INT"), ("salary", "DECIMAL(10,2)"),
        ],
        "Orders": [
            ("order_id", "INT", True, None, True), ("customer_id", "INT", True),
            ("employee_id", "INT"), ("order_date", "DATETIME", True, "CURRENT_TIMESTAMP"),
            ("required_date", "DATE"), ("shipped_date", "DATETIME"),
            ("ship_address_id", "INT"),
            ("order_status", "ENUM('Pending','Processing','Shipped','Delivered','Cancelled')", False, "'Pending'"),
            ("payment_method", "VARCHAR(50)"), ("total_amount", "DECIMAL(10,2)"),
            ("notes", "TEXT"),
        ],
        "Order_Items": [
            ("order_item_id", "INT", True, None, True), ("order_id", "INT", True),
            ("product_id", "INT", True), ("quantity", "INT", True),
            ("unit_price", "DECIMAL(10,2)", True),
            ("discount_percent", "DECIMAL(4,2)", False, "0"),
            ("line_total", "DECIMAL(10,2)", False, None, False, "", True,
             "quantity * unit_price * (1 - discount_percent / 100)", "STORED"),
        ],
        "Reviews": [
            ("review_id", "INT", True, None, True), ("product_id", "INT", True),
            ("customer_id", "INT", True), ("rating", "INT", True),
            ("review_text", "TEXT"), ("review_date", "DATETIME", False, "CURRENT_TIMESTAMP"),
            ("is_verified_purchase", "BOOLEAN", False, "FALSE"),
            ("helpful_count", "INT", False, "0"),
        ],
        "Shopping_Cart": [
            ("cart_id", "INT", True, None, True), ("customer_id", "INT", True),
            ("product_id", "INT", True), ("quantity", "INT", True, "1"),
            ("added_date", "DATETIME", False, "CURRENT_TIMESTAMP"),
        ],
        "Wishlists": [
            ("wishlist_id", "INT", True, None, True), ("customer_id", "INT", True),
            ("product_id", "INT", True), ("added_date", "DATE", True),
            ("priority", "INT", False, "5"),
        ],
        "Inventory_Transactions": [
            ("transaction_id", "INT", True, None, True), ("product_id", "INT", True),
            ("transaction_type", "ENUM('Purchase','Sale','Adjustment','Return')", True),
            ("quantity", "INT", True),
            ("transaction_date", "DATETIME", False, "CURRENT_TIMESTAMP"),
            ("reference_order_id", "INT"), ("notes", "TEXT"),
        ],
    }
    tables = {name: Table(name, columns(specs), [specs[0][0]])
              for name, specs in definitions.items()}

    unique_groups = [
        ("Customers", "uq_customers_email", ["email"]),
        ("Employees", "uq_employees_email", ["email"]),
        ("Order_Items", "unique_order_product", ["order_id", "product_id"]),
        ("Shopping_Cart", "unique_customer_product_cart", ["customer_id", "product_id"]),
        ("Wishlists", "unique_customer_product_wish", ["customer_id", "product_id"]),
    ]
    for table_name, index_name, member_names in unique_groups:
        table = tables[table_name]
        table.indices.append(Index(index_name, [table.column(name) for name in member_names], True))

    relationships = [
        ("Addresses", "fk_addresses_customer", ["customer_id"], "Customers", ["customer_id"], "CASCADE"),
        ("Categories", "fk_categories_parent", ["parent_category_id"], "Categories", ["category_id"], "SET NULL"),
        ("Products", "fk_products_category", ["category_id"], "Categories", ["category_id"], "SET NULL"),
        ("Products", "fk_products_supplier", ["supplier_id"], "Suppliers", ["supplier_id"], "SET NULL"),
        ("Employees", "fk_employees_manager", ["manager_id"], "Employees", ["employee_id"], "SET NULL"),
        ("Orders", "fk_orders_customer", ["customer_id"], "Customers", ["customer_id"], "RESTRICT"),
        ("Orders", "fk_orders_employee", ["employee_id"], "Employees", ["employee_id"], "SET NULL"),
        ("Orders", "fk_orders_address", ["ship_address_id"], "Addresses", ["address_id"], "SET NULL"),
        ("Order_Items", "fk_order_items_order", ["order_id"], "Orders", ["order_id"], "CASCADE"),
        ("Order_Items", "fk_order_items_product", ["product_id"], "Products", ["product_id"], "RESTRICT"),
        ("Reviews", "fk_reviews_product", ["product_id"], "Products", ["product_id"], "CASCADE"),
        ("Reviews", "fk_reviews_customer", ["customer_id"], "Customers", ["customer_id"], "CASCADE"),
        ("Shopping_Cart", "fk_cart_customer", ["customer_id"], "Customers", ["customer_id"], "CASCADE"),
        ("Shopping_Cart", "fk_cart_product", ["product_id"], "Products", ["product_id"], "CASCADE"),
        ("Wishlists", "fk_wishlists_customer", ["customer_id"], "Customers", ["customer_id"], "CASCADE"),
        ("Wishlists", "fk_wishlists_product", ["product_id"], "Products", ["product_id"], "CASCADE"),
        ("Inventory_Transactions", "fk_inventory_product", ["product_id"], "Products", ["product_id"], "RESTRICT"),
        ("Inventory_Transactions", "fk_inventory_order", ["reference_order_id"], "Orders", ["order_id"], "SET NULL"),
    ]
    for source_name, fk_name, source_columns, target_name, target_columns, delete_rule in relationships:
        source = tables[source_name]
        target = tables[target_name]
        source.foreignKeys.append(ForeignKey(
            fk_name, [source.column(name) for name in source_columns], target,
            [target.column(name) for name in target_columns], delete_rule
        ))
        source.indices.append(Index(
            "idx_" + fk_name.removeprefix("fk_"),
            [source.column(name) for name in source_columns]
        ))

    tables["Suppliers"].checkConstraints.append(
        Check("chk_suppliers_rating", "rating >= 0 AND rating <= 5")
    )
    tables["Reviews"].checkConstraints.append(
        Check("chk_reviews_rating", "rating >= 1 AND rating <= 5")
    )
    return Schema("onlinestoredb", list(tables.values()))


class DataDictionaryTests(unittest.TestCase):
    def setUp(self):
        self.schema = canonical_schema()
        self.report = PLUGIN.generate_html_content(self.schema, PLUGIN.DEFAULT_CONFIG.copy())

    def test_canonical_acceptance_totals_and_modeling_rules(self):
        tables = self.schema.tables
        foreign_keys = [fk for table in tables for fk in table.foreignKeys]
        unique_groups = [index for table in tables for index in table.indices
                         if index.unique and index.name != "PRIMARY"]
        checks = [check for table in tables for check in table.checkConstraints]
        generated = [column for table in tables for column in table.columns if column.generated]

        self.assertEqual(12, len(tables))
        self.assertEqual(94, sum(len(table.columns) for table in tables))
        self.assertEqual(12, sum(len(table.primary_key) for table in tables))
        self.assertEqual(18, len(foreign_keys))
        self.assertEqual(5, len(unique_groups))
        self.assertEqual(2, len(checks))
        self.assertEqual(1, len(generated))
        self.assertTrue(all(table.tableEngine == "InnoDB" for table in tables))
        self.assertEqual(11, sum(all(column.isNotNull for column in fk.columns)
                                 for fk in foreign_keys))
        self.assertEqual(7, sum(not all(column.isNotNull for column in fk.columns)
                                for fk in foreign_keys))
        self.assertEqual({"CASCADE": 8, "SET NULL": 7, "RESTRICT": 3}, {
            action: sum(fk.deleteRule == action for fk in foreign_keys)
            for action in ("CASCADE", "SET NULL", "RESTRICT")
        })
        self.assertTrue(all(fk.updateRule == "CASCADE" for fk in foreign_keys))
        self.assertTrue(all(not any(table.isPrimaryKeyColumn(column) for column in fk.columns)
                            for table in tables for fk in table.foreignKeys))

    def test_report_contains_complete_export_data_and_readable_sections(self):
        payload = re.search(
            r'<script id="schemaDataJson" type="application/json">(.*?)</script>',
            self.report, re.DOTALL
        ).group(1)
        data = json.loads(payload)
        self.assertEqual("onlinestoredb", data["name"])
        self.assertEqual(12, len(data["tables"]))
        self.assertEqual(94, sum(len(table["columns"]) for table in data["tables"]))
        self.assertEqual(18, sum(len(table["foreign_keys"]) for table in data["tables"]))
        self.assertEqual(12, self.report.count('class="table-wrapper"'))
        self.assertIn("Start here", self.report)
        self.assertIn("References (outgoing foreign keys)", self.report)
        self.assertIn("Referenced by (incoming foreign keys)", self.report)
        self.assertIn("Required · Non-identifying", self.report)
        self.assertIn("Optional · Non-identifying", self.report)
        self.assertEqual(2, self.report.count('title="Unique by itself">UQ</span>'))
        self.assertEqual(
            6,
            self.report.count('title="Part of a composite unique constraint">UQ group</span>')
        )

    def test_reference_ddl_preserves_mysql_84_features(self):
        order_items = next(table for table in self.schema.tables if table.name == "Order_Items")
        ddl = PLUGIN.generate_table_ddl(order_items)
        self.assertIn("GENERATED ALWAYS AS", ddl)
        self.assertIn("STORED", ddl)
        self.assertIn("UNIQUE KEY `unique_order_product`", ddl)
        self.assertIn("ON DELETE CASCADE ON UPDATE CASCADE", ddl)
        self.assertIn("ON DELETE RESTRICT ON UPDATE CASCADE", ddl)
        self.assertIn("ENGINE=InnoDB", ddl)

        suppliers = next(table for table in self.schema.tables if table.name == "Suppliers")
        suppliers.comment = "Supplier's rating"
        supplier_ddl = PLUGIN.generate_table_ddl(suppliers)
        self.assertIn("CHECK (rating >= 0 AND rating <= 5)", supplier_ddl)
        self.assertIn("COMMENT='Supplier''s rating'", supplier_ddl)

    def test_workbench_8047_column_check_shape_is_preserved(self):
        """Workbench 8.0.47 stores db.CheckConstraint objects on columns."""
        schema = canonical_schema()
        suppliers = next(table for table in schema.tables if table.name == "Suppliers")
        reviews = next(table for table in schema.tables if table.name == "Reviews")
        suppliers.checkConstraints = []
        reviews.checkConstraints = []
        suppliers.column("rating").checks.append(
            WorkbenchCheck("chk_suppliers_rating", "rating >= 0 AND rating <= 5")
        )
        reviews.column("rating").checks.append(
            WorkbenchCheck("chk_reviews_rating", "rating >= 1 AND rating <= 5")
        )

        self.assertEqual(1, len(PLUGIN.table_checks(suppliers)))
        self.assertEqual(1, len(PLUGIN.table_checks(reviews)))
        self.assertIn("CHECK (rating >= 0 AND rating <= 5)",
                      PLUGIN.generate_table_ddl(suppliers))
        report = PLUGIN.generate_html_content(schema, PLUGIN.DEFAULT_CONFIG.copy())
        self.assertIn("chk_suppliers_rating", report)
        self.assertIn("rating &gt;= 1 AND rating &lt;= 5", report)

    def test_workbench_imported_primary_key_is_effectively_not_null(self):
        """Workbench may store an AUTO_INCREMENT PK as nullable/DEFAULT NULL."""
        table = Table("Imported", [Column(
            "imported_id", "INT", required=False, default="NULL",
            auto_increment=True
        )], ["imported_id"])
        ddl = PLUGIN.generate_table_ddl(table)
        self.assertIn("`imported_id` INT NOT NULL AUTO_INCREMENT", ddl)
        self.assertNotIn("DEFAULT NULL AUTO_INCREMENT", ddl)

        schema = Schema("imported", [table])
        report = PLUGIN.generate_html_content(schema, PLUGIN.DEFAULT_CONFIG.copy())
        self.assertIn('<span class="key-badge badge-nn">NOT NULL</span>', report)
        payload = re.search(
            r'<script id="schemaDataJson" type="application/json">(.*?)</script>',
            report, re.DOTALL
        ).group(1)
        column = json.loads(payload)["tables"][0]["columns"][0]
        self.assertFalse(column["nullable"])
        self.assertIsNone(column["default"])

    def test_catalog_metadata_cannot_close_json_script_or_break_handlers(self):
        schema = canonical_schema()
        payload = "</script><script>globalThis.pwned=true</script>"
        schema.name = payload
        schema.tables[0].name = "O'Reilly " + payload
        schema.tables[0].comment = payload
        report = PLUGIN.generate_html_content(schema, PLUGIN.DEFAULT_CONFIG.copy())
        self.assertNotIn(payload, report)
        self.assertIn("\\u003c/script\\u003e", report)
        self.assertNotIn("jumpToTable('O'Reilly", report)

    def test_accessibility_and_export_defenses_are_present(self):
        self.assertIn('class="skip-link"', self.report)
        self.assertIn('role="status" aria-live="polite"', self.report)
        self.assertEqual(12, self.report.count('class="sr-only">Column definitions for'))
        self.assertEqual(12, self.report.count('<h3 class="table-name">'))
        self.assertEqual(12, self.report.count('class="table-toggle"'))
        self.assertNotIn('class="table-header" role="button"', self.report)
        self.assertIn('function trapDDLFocus(event)', self.report)
        self.assertIn("setAttribute('inert', '')", self.report)
        self.assertIn('class="back-to-top" aria-label="Back to top" aria-hidden="true" tabindex="-1"', self.report)
        self.assertIn('rel="icon" href="data:image/svg+xml,', self.report)
        self.assertIn('.skip-link,', self.report)
        self.assertRegex(
            self.report,
            r'\.legend \{[^}]*page-break-inside: avoid !important;'
            r'[^}]*page-break-after: auto !important;',
        )
        self.assertRegex(
            self.report,
            r'\.erd-container \{[^}]*page-break-after: auto !important;',
        )
        self.assertRegex(
            self.report,
            r'\.tables-container \{[^}]*page-break-before: always !important;',
        )
        self.assertIn("function csvCell(value)", self.report)
        self.assertIn("text.replace(/\"/g, '\"\"')", self.report)
        self.assertIn("table.name, col.name, col.type", self.report)
        self.assertIn("URL.revokeObjectURL", self.report)


if __name__ == "__main__":
    unittest.main()
