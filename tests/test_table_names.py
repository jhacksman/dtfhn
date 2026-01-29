#!/usr/bin/env python3
"""
Test that _table_names() works correctly for all three tables.

Validates the fix for the list_tables() regression where ListTablesResponse
was not a drop-in replacement for table_names().
"""

import sys
import tempfile
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import lancedb
import pyarrow as pa


def test_list_tables_response_type():
    """Verify what list_tables() actually returns."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = lancedb.connect(tmpdir)
        result = db.list_tables()
        
        # Should be ListTablesResponse, not list
        assert not isinstance(result, list), \
            f"Expected ListTablesResponse, got {type(result)}"
        assert hasattr(result, 'tables'), \
            f"ListTablesResponse missing .tables attribute"
        
        # Empty DB should return empty list
        assert result.tables == [], \
            f"Expected empty list, got {result.tables}"
        
        print("✓ list_tables() returns ListTablesResponse with .tables attribute")


def test_in_operator_fails_on_raw_response():
    """Demonstrate why raw list_tables() breaks 'in' checks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = lancedb.connect(tmpdir)
        schema = pa.schema([pa.field("id", pa.string()), pa.field("vector", pa.list_(pa.float32(), 4))])
        db.create_table("test_table", schema=schema)
        
        result = db.list_tables()
        
        # This is the bug: "in" on ListTablesResponse doesn't check table names
        in_check = "test_table" in result
        assert in_check is False, \
            f"Expected False (the bug), got {in_check}"
        
        # But .tables works correctly
        assert "test_table" in result.tables, \
            "Expected .tables to contain 'test_table'"
        
        print("✓ Confirmed: 'x in db.list_tables()' is ALWAYS False (the bug)")
        print("✓ Confirmed: 'x in db.list_tables().tables' works correctly")


def test_table_names_helper():
    """Test the _table_names() helper from storage.py."""
    from src.storage import _table_names
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db = lancedb.connect(tmpdir)
        
        # Empty DB
        names = _table_names(db)
        assert isinstance(names, list), f"Expected list, got {type(names)}"
        assert names == [], f"Expected [], got {names}"
        
        # Create a table
        schema = pa.schema([pa.field("id", pa.string()), pa.field("vector", pa.list_(pa.float32(), 4))])
        db.create_table("test_table", schema=schema)
        
        names = _table_names(db)
        assert "test_table" in names, f"Expected 'test_table' in {names}"
        
        print("✓ _table_names() helper works correctly")


def test_all_three_tables():
    """Test that stories, episodes, and segments can be created and checked."""
    from src.storage import _table_names, EPISODES_SCHEMA, STORIES_SCHEMA, SEGMENTS_SCHEMA
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db = lancedb.connect(tmpdir)
        
        table_configs = [
            ("episodes", EPISODES_SCHEMA),
            ("stories", STORIES_SCHEMA),
            ("segments", SEGMENTS_SCHEMA),
        ]
        
        for name, schema in table_configs:
            # Table should not exist yet
            names = _table_names(db)
            assert name not in names, f"{name} should not exist yet"
            
            # Create table
            db.create_table(name, schema=schema)
            
            # Table should now exist
            names = _table_names(db)
            assert name in names, f"{name} should exist after creation"
            
            # Opening existing table should work (not crash)
            table = db.open_table(name)
            assert table is not None
            
            print(f"✓ {name}: create → check → open works correctly")
        
        # All three should be present
        names = _table_names(db)
        assert set(["episodes", "stories", "segments"]).issubset(set(names)), \
            f"Missing tables. Got: {names}"
        
        print("✓ All three tables coexist correctly")


def test_create_table_regression():
    """
    Reproduce the exact regression: without _table_names(), create_table 
    would fire on existing tables and crash.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db = lancedb.connect(tmpdir)
        schema = pa.schema([pa.field("id", pa.string()), pa.field("vector", pa.list_(pa.float32(), 4))])
        
        # Create table first time
        db.create_table("stories", schema=schema)
        
        # The bug: raw list_tables() check always returns False
        if "stories" not in db.list_tables():
            try:
                db.create_table("stories", schema=schema)
                assert False, "Should have raised ValueError"
            except (ValueError, OSError) as e:
                print(f"✓ Reproduced regression: create_table on existing table raises: {e}")
        
        # The fix: _table_names() correctly detects existing table
        from src.storage import _table_names
        if "stories" not in _table_names(db):
            assert False, "_table_names should detect existing 'stories' table"
        else:
            table = db.open_table("stories")
            assert table is not None
            print("✓ Fix works: _table_names() correctly detects existing table, opens instead of creating")


def test_deprecated_table_names_still_works():
    """Check if the old table_names() API still functions."""
    import warnings
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db = lancedb.connect(tmpdir)
        schema = pa.schema([pa.field("id", pa.string()), pa.field("vector", pa.list_(pa.float32(), 4))])
        db.create_table("test", schema=schema)
        
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = db.table_names()
            
            assert isinstance(result, list), f"table_names() should return list, got {type(result)}"
            assert "test" in result, f"table_names() should contain 'test'"
            
            deprecation_warnings = [x for x in w if "deprecated" in str(x.message).lower()]
            if deprecation_warnings:
                print(f"✓ table_names() works but warns: {deprecation_warnings[0].message}")
            else:
                print("✓ table_names() works (no deprecation warning in this version)")


if __name__ == "__main__":
    print(f"LanceDB version: {lancedb.__version__}")
    print(f"Python: {sys.version}")
    print("=" * 60)
    
    tests = [
        test_list_tables_response_type,
        test_in_operator_fails_on_raw_response,
        test_table_names_helper,
        test_all_three_tables,
        test_create_table_regression,
        test_deprecated_table_names_still_works,
    ]
    
    passed = 0
    failed = 0
    for test in tests:
        print(f"\n--- {test.__name__} ---")
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"✗ FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
    print("All tests passed! ✓")
