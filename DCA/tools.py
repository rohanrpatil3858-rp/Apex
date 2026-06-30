"""
Healthcare Form Automation - Tool Functions
============================================

Contains all tool functions used by agents:
- read_pdf_content: Read and extract PDF content
- load_field_mapping: Load mapping configuration from JSON
- fetch_multiple_from_json: Batch fetch from API Endpoints
- fetch_multiple_from_sqlite: Batch fetch from SQLite databases
- fill_pdf_form: Fill PDF form fields with data
"""

import os
import json
import sqlite3
import logging
from typing import Dict, Any
from jsonpath_ng import parse
from datetime import datetime
from pathlib import Path
import httpx

try:
    from PyPDF2 import PdfReader, PdfWriter
    from PyPDF2.generic import NameObject, BooleanObject, TextStringObject
    PYPDF2_AVAILABLE = True
except ImportError:
    PYPDF2_AVAILABLE = False
    PdfReader = None
    PdfWriter = None
    NameObject = None
    BooleanObject = None
    TextStringObject = None

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False
    fitz = None

# Configure logging
logger = logging.getLogger(__name__)


# ============================================================================
# TOOL 1: PDF Reading Tool
# ============================================================================

async def read_pdf_content(pdf_path: str) -> Dict[str, Any]:
    """
    Read PDF file and extract text content for LLM analysis
    Tool called by: PDFSchemaAgent
    
    This tool provides the raw PDF content to the LLM agent, which will then
    use its intelligence to analyze and create a structured schema.
    
    Returns error if PDF has no fillable form fields.
    """
    logger.info(f"Reading PDF content from {pdf_path}")
    
    try:
        from PyPDF2 import PdfReader
        
        if not os.path.exists(pdf_path):
            logger.error(f"PDF file not found: {pdf_path}")
            return {
                "success": False,
                "error": f"File not found: {pdf_path}",
                "content": None
            }
        
        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        
        # Check if PDF has fillable form fields
        has_fields = False
        if "/AcroForm" in reader.trailer["/Root"]:
            acro_form = reader.trailer["/Root"]["/AcroForm"]
            if "/Fields" in acro_form:
                fields = acro_form["/Fields"]
                has_fields = len(fields) > 0
        
        if not has_fields:
            logger.error(f"PDF has no fillable form fields: {pdf_path}")
            return {
                "success": False,
                "error": "This PDF does not contain any fillable form fields. Please upload a valid CMS form with fillable fields.",
                "content": None
            }
        
        # Extract text from all pages
        pages_content = []
        for page_num, page in enumerate(reader.pages, start=1):
            text = page.extract_text()
            pages_content.append({
                "page_number": page_num,
                "text": text,
                "has_content": bool(text.strip())
            })
        
        logger.info(f"PDF read successfully: {total_pages} pages with fillable fields")
        
        return {
            "success": True,
            "pdf_path": pdf_path,
            "total_pages": total_pages,
            "pages": pages_content,
            "file_name": os.path.basename(pdf_path)
        }
        
    except ImportError:
        logger.error("PyPDF2 not installed")
        return {
            "success": False,
            "error": "PyPDF2 library not installed. Install with: pip install PyPDF2",
            "content": None
        }
    except Exception as e:
        logger.error(f"Error reading PDF: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "content": None
        }


# ============================================================================
# TOOL 2: Load Mapping File
# ============================================================================

async def load_field_mapping(path: str) -> Dict[str, Any]:
    """
    Load field mapping configuration from mapping JSON file
    
    Args:
        path: Path to mapping file (e.g., "data/mappings/cms_3427_mapping.json")
    
    Returns:
        Dict containing: form_id, form_name, api_mappings, database_mappings
    """
    logger.info(f"📂 Loading mapping from {path}")
    
    if not os.path.exists(path):
        raise FileNotFoundError(f"Mapping file not found: {path}")
    
    with open(path, "r") as f:
        mapping = json.load(f)
    
    api_count = len(mapping.get("api_mappings", []))
    db_count = len(mapping.get("database_mappings", []))
    
    logger.info(f"✅ Loaded: {mapping['form_name']}")
    logger.info(f"   API fields: {api_count}, DB fields: {db_count}")
    
    return mapping


# ============================================================================
# TOOL 3: Fetch Multiple from JSON (API Agent)
# ============================================================================

count = 0



async def fetch_multiple_from_json(api_endpoint: str, facility_name: str = None, facility_id: str = None) -> Dict[str, Any]:
    """
    Fetch complete API response from endpoint for agent to process.
    Agent will use facility context to extract correct data.
    
    Args:
        api_endpoint: Full API endpoint URL (e.g., "http://127.0.0.1:8000/api/ehr/facility")
        facility_name: Name of facility for context (optional, for logging)
        facility_id: ID of facility for context (optional, for logging)
    
    Returns:
        Complete JSON response from the API endpoint.
        Agent will intelligently extract fields based on facility match.
    
    Example:
        response = await fetch_multiple_from_json(
            api_endpoint="http://127.0.0.1:8000/api/ehr/facility",
            facility_name="Metro Medical Center",
            facility_id="FAC-001"
        )
        # Returns: {"facilities": [{"id": "FAC-001", "name": "Metro Medical Center", ...}, ...]}
        # Agent then finds matching facility and extracts needed fields
    """
    logger.info(f"🌐 Fetching from API: {api_endpoint}")
    if facility_name:
        logger.info(f"   Context: {facility_name} ({facility_id})")
    
    
    headers = {"X-API-Key": "poc-agent-key-12345"}

    try:
        # Fetch data from API endpoint
        async with httpx.AsyncClient() as client:
            response = await client.get(api_endpoint, headers=headers, timeout=30.0)
            response.raise_for_status()  # Raises error for 401, 404, etc.
            data = response.json()
        
        logger.info(f"✅ API response received successfully")
        return data
        
    except httpx.HTTPStatusError as e:
        error_msg = f"API HTTP error {e.response.status_code}: {str(e)}"
        logger.error(error_msg)
        return {
            "success": False,
            "error": error_msg
        }
    except Exception as e:
        error_msg = f"Error fetching from API: {str(e)}"
        logger.error(error_msg)
        return {
            "success": False,
            "error": error_msg
        }



# ============================================================================
# TOOL 4: Get Database Schema (Database Agent)
# ============================================================================

async def get_database_schema(source_file: str) -> Dict[str, Any]:
    """
    Get the schema information for a SQLite database.
    Returns table names, column information, and sample data.
    
    Args:
        source_file: SQLite database filename (e.g., "internal_hr.sqlite")
    
    Returns:
        {
            "success": True/False,
            "database": "internal_hr.sqlite",
            "tables": {
                "employees": {
                    "columns": ["employee_id", "first_name", "facility_id", ...],
                    "sample_row": {...}
                }
            }
        }
    """
    db_path = f"data/database_sources/{source_file}"
    
    logger.info(f"📊 Getting schema for {source_file}")
    
    if not os.path.exists(db_path):
        return {
            "success": False,
            "error": f"Database file not found: {db_path}",
            "database": source_file,
            "tables": {}
        }
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get all table names
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        
        schema_info = {}
        
        for (table_name,) in tables:
            # Get column information
            cursor.execute(f"PRAGMA table_info({table_name});")
            columns_info = cursor.fetchall()
            column_names = [col[1] for col in columns_info]
            
            # Get a sample row
            cursor.execute(f"SELECT * FROM {table_name} LIMIT 1;")
            sample_row = cursor.fetchone()
            
            schema_info[table_name] = {
                "columns": column_names,
                "sample_row": dict(zip(column_names, sample_row)) if sample_row else {}
            }
        
        conn.close()
        
        logger.info(f"✅ Schema retrieved: {len(schema_info)} tables found")
        
        return {
            "success": True,
            "database": source_file,
            "tables": schema_info
        }
        
    except Exception as e:
        logger.error(f"Error getting schema: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "database": source_file,
            "tables": {}
        }


# ============================================================================
# TOOL 5: Fetch Multiple from SQLite (Database Agent)
# ============================================================================

async def fetch_multiple_from_sqlite(source_file: str, queries: list) -> dict:
    """
    Fetch MULTIPLE values from ONE SQLite database in a single connection
    
    Args:
        source_file: SQLite database filename (e.g., "internal_hr.sqlite")
        queries: List of query objects
            [
                {"field_id": "9", "sql_query": "SELECT full_name FROM employees WHERE employee_id = 1"},
                {"field_id": "12", "sql_query": "SELECT 'No significant deficiencies...' AS comments"},
                {"field_id": "13", "sql_query": "SELECT full_name FROM employees WHERE employee_id = 1"}
            ]
    
    Returns:
        Dict of field_id -> value
        {
            "9": "Dr. Sarah Smith",
            "12": "No significant deficiencies found...",
            "13": "Dr. Sarah Smith"
        }
    
    Tool called by: DatabaseAgent
    
    Example:
        result = await fetch_multiple_from_sqlite("internal_hr.sqlite", [
            {"field_id": "9", "sql_query": "SELECT full_name FROM employees WHERE employee_id = 1"},
            {"field_id": "12", "sql_query": "SELECT 'Comments' AS comments"}
        ])
        # Returns: {"9": "Dr. Sarah Smith", "12": "Comments"}
    """
    db_path = f"data/database_sources/{source_file}"
    
    logger.info(f"🗄️  Batch fetching from {source_file}")
    logger.info(f"   Database path: {db_path}")
    logger.info(f"   Queries to execute: {len(queries)}")
    
    # Check database exists
    if not os.path.exists(db_path):
        error_msg = f"Database file not found: {db_path}"
        logger.error(error_msg)
        raise FileNotFoundError(error_msg)
    
    results = {}
    
    try:
        # Open connection ONCE
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Execute all queries in ONE connection
        for query_obj in queries:
            field_id = query_obj.get("field_id")
            sql_query = query_obj.get("sql_query")
            
            logger.info(f"   Executing query for Field {field_id}")
            logger.info(f"   SQL: {sql_query}")
            
            try:
                cursor.execute(sql_query)
                result = cursor.fetchone()
                
                if result is None:
                    logger.warning(f"   ⚠️  Field {field_id}: Query returned no results")
                    results[field_id] = None
                else:
                    # Return first column of first row
                    value = result[0]
                    logger.info(f"   ✅ Field {field_id}: {value}")
                    results[field_id] = value
            
            except sqlite3.Error as e:
                error_msg = f"SQL error for field {field_id}: {str(e)}"
                logger.error(f"   ❌ {error_msg}")
                results[field_id] = None
        
        # Close connection
        conn.close()
        
        success_count = sum(1 for v in results.values() if v is not None)
        logger.info(f"✅ Batch fetch complete: {success_count}/{len(queries)} fields retrieved")
        
        return results
    
    except sqlite3.Error as e:
        error_msg = f"Database connection error: {str(e)}"
        logger.error(error_msg)
        raise
    except Exception as e:
        error_msg = f"Error in batch fetch from {source_file}: {str(e)}"
        logger.error(error_msg)
        raise


# ============================================================================
# TOOL 6: PDF Form Filler Tool
# ============================================================================

async def fill_pdf_form(pdf_path: str, field_data: Dict[str, Any], output_dir: str = "outputs") -> Dict[str, Any]:
    """
    Fill PDF form fields with provided data and save to output directory using PyMuPDF.
    Tool called by: PDFFillerAgent
    
    Args:
        pdf_path: Path to the original PDF form
        field_data: Dictionary with field names and values to fill
                   Format: {"Field Name": {"type": "text", "value": "actual value"}}
                   OR: {"Field Name": "direct value"}
        output_dir: Directory to save filled PDF (default: outputs/)
    
    Returns:
        Dictionary with success status and output file path
    """
    print(f"\n{'='*80}")
    print(f"🔧 PDF FILLER TOOL - Starting")
    print(f"{'='*80}")
    print(f"📄 PDF Path: {pdf_path}")
    print(f"📊 Received {len(field_data)} fields from agent")
    print(f"{'='*80}\n")
    
    # Check if PyMuPDF is available
    if not PYMUPDF_AVAILABLE:
        error_msg = "PyMuPDF library not found. Please install: pip install pymupdf"
        logger.error(error_msg)
        return {
            "success": False,
            "error": error_msg,
            "output_path": None
        }
    
    try:
        # Validate input PDF exists
        if not os.path.exists(pdf_path):
            return {
                "success": False,
                "error": f"PDF file not found: {pdf_path}",
                "output_path": None
            }

        # Create output directory if it doesn't exist
        Path(output_dir).mkdir(exist_ok=True)

        # Delete all existing PDFs in the output directory
        for f in os.listdir(output_dir):
            if f.lower().endswith('.pdf'):
                try:
                    os.remove(os.path.join(output_dir, f))
                    print(f"🗑️  Deleted old PDF: {f}")
                except Exception as e:
                    logger.warning(f"Could not delete {f}: {e}")

        # Generate output filename
        output_filename = "filled_form.pdf"
        output_path = os.path.join(output_dir, output_filename)
        
        # Extract field values and types from nested structure
        print(f"\n{'='*80}")
        print("📋 PROCESSING INCOMING FIELD DATA")
        print(f"{'='*80}")
        
        processed_data = {}
        for field_name, field_info in field_data.items():
            if isinstance(field_info, dict):
                # Nested format: {"type": "text", "value": "..."}
                field_type = field_info.get('type', 'text')
                field_value = field_info.get('value', '')
                processed_data[field_name] = {
                    'value': field_value,
                    'type': field_type
                }
                print(f"  ✓ {field_name}: {field_value} (type: {field_type})")
            else:
                # Direct value format
                processed_data[field_name] = {
                    'value': field_info,
                    'type': 'text'
                }
                print(f"  ✓ {field_name}: {field_info} (type: text - inferred)")
        
        print(f"\n✅ Processed {len(processed_data)} fields\n")
        
        # Open PDF with PyMuPDF
        doc = fitz.open(pdf_path)
        
        # Collect all PDF form fields
        print(f"{'='*80}")
        print("📄 ANALYZING PDF FORM FIELDS")
        print(f"{'='*80}")
        
        pdf_fields = {}
        for page_num, page in enumerate(doc):
            for field in page.widgets():
                if field.field_name:
                    field_type_name = {
                        fitz.PDF_WIDGET_TYPE_TEXT: "text",
                        fitz.PDF_WIDGET_TYPE_CHECKBOX: "checkbox",
                        fitz.PDF_WIDGET_TYPE_RADIOBUTTON: "radio",
                        fitz.PDF_WIDGET_TYPE_COMBOBOX: "combobox",
                        fitz.PDF_WIDGET_TYPE_LISTBOX: "listbox"
                    }.get(field.field_type, "unknown")
                    
                    pdf_fields[field.field_name] = {
                        'page': page_num + 1,
                        'type': field_type_name,
                        'widget': field
                    }
        
        print(f"Found {len(pdf_fields)} form fields in PDF:")
        for i, (fname, finfo) in enumerate(list(pdf_fields.items())[:15], 1):
            print(f"  {i}. '{fname}' (page {finfo['page']}, type: {finfo['type']})")
        if len(pdf_fields) > 15:
            print(f"  ... and {len(pdf_fields) - 15} more fields")
        print()
        
        # Match and fill fields
        print(f"{'='*80}")
        print("🔄 MATCHING AND FILLING FIELDS")
        print(f"{'='*80}")
        
        filled_count = 0
        unmatched_data = []
        unmatched_pdf = []
        
        # Try to fill each field from processed_data
        for data_field_name, data_info in processed_data.items():
            matched = False
            data_value = data_info['value']
            data_type = data_info['type']
            
            # Try exact match first
            if data_field_name in pdf_fields:
                field_info = pdf_fields[data_field_name]
                widget = field_info['widget']
                
                # Fill based on type
                if widget.field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX:
                    if data_type == 'checkbox' or data_type == 'boolean':
                        widget.field_value = data_value if isinstance(data_value, bool) else (str(data_value).lower() in ['true', '1', 'yes', 'compliant', 'checked'])
                    else:
                        widget.field_value = str(data_value).lower() in ['true', '1', 'yes', 'compliant', 'checked']
                else:
                    widget.field_value = str(data_value) if data_value else ""
                
                widget.update()
                filled_count += 1
                matched = True
                print(f"  ✅ Filled: '{data_field_name}' = '{data_value}'")
            else:
                # Try case-insensitive match
                for pdf_field_name, field_info in pdf_fields.items():
                    if pdf_field_name.lower() == data_field_name.lower():
                        widget = field_info['widget']
                        
                        if widget.field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX:
                            widget.field_value = str(data_value).lower() in ['true', '1', 'yes', 'compliant', 'checked']
                        else:
                            widget.field_value = str(data_value) if data_value else ""
                        
                        widget.update()
                        filled_count += 1
                        matched = True
                        print(f"  ✅ Filled (case-insensitive): '{pdf_field_name}' = '{data_value}'")
                        break
            
            if not matched:
                unmatched_data.append(data_field_name)
                print(f"  ❌ No match in PDF: '{data_field_name}'")
        
        # Check for unfilled PDF fields
        for pdf_field_name in pdf_fields.keys():
            found = False
            for data_field_name in processed_data.keys():
                if pdf_field_name.lower() == data_field_name.lower():
                    found = True
                    break
            if not found:
                unmatched_pdf.append(pdf_field_name)
        
        # Save the filled PDF
        doc.save(output_path)
        doc.close()
        
        # Summary
        print(f"\n{'='*80}")
        print("📊 FILL SUMMARY")
        print(f"{'='*80}")
        print(f"✅ Successfully filled: {filled_count} fields")
        print(f"📄 Total PDF fields: {len(pdf_fields)}")
        print(f"📊 Total data fields: {len(processed_data)}")
        
        if unmatched_data:
            print(f"\n⚠️  Data fields not matched to PDF ({len(unmatched_data)}):")
            for field in unmatched_data[:10]:
                print(f"    - {field}")
            if len(unmatched_data) > 10:
                print(f"    ... and {len(unmatched_data) - 10} more")
        
        if unmatched_pdf:
            print(f"\n⚠️  PDF fields not filled ({len(unmatched_pdf)}):")
            for field in unmatched_pdf[:10]:
                print(f"    - {field}")
            if len(unmatched_pdf) > 10:
                print(f"    ... and {len(unmatched_pdf) - 10} more")
        
        print(f"\n✅ Filled PDF saved to: {output_path}")
        print(f"{'='*80}\n")
        
        return {
            "success": True,
            "output_path": output_path,
            "filled_fields": filled_count,
            "total_pdf_fields": len(pdf_fields),
            "total_data_fields": len(processed_data),
            "unmatched_data_fields": unmatched_data,
            "unmatched_pdf_fields": unmatched_pdf,
            "message": f"Successfully filled {filled_count}/{len(pdf_fields)} PDF fields. Saved to {output_path}"
        }
        
    except Exception as e:
        error_msg = f"Error filling PDF form: {str(e)}"
        logger.error(error_msg)
        import traceback
        logger.error(traceback.format_exc())
        print(f"\n❌ ERROR: {error_msg}\n")
        return {
            "success": False,
            "error": error_msg,
            "output_path": None
        }
