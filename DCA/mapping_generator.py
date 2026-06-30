import asyncio
import json, os
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import TextMentionTermination, MaxMessageTermination
from autogen_ext.models.openai import AzureOpenAIChatCompletionClient
from typing import Dict, Any
import logging


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
# ============= TOOLS =============


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

count = 0

def call_api_tool(endpoint_url: str, method: str = "GET", params: dict = None) -> str:
    """
    Call any API endpoint to explore or fetch data.
    Agent provides the full endpoint URL.
    """
    global count
    count+=1
    print(f"\n\n\n\n\n\n\napi - {count}\n\n\n\n\n\n\n")
    import requests
    
    try:
        headers = {}
        headers["X-API-Key"] = "poc-agent-key-12345"
        
        if method == "GET":
            response = requests.get(endpoint_url, params=params, headers=headers, timeout=5)
        elif method == "POST":
            response = requests.post(endpoint_url, json=params, headers=headers, timeout=5)
        else:
            return json.dumps({"error": f"Unsupported method: {method}"})
        
        if response.status_code == 200:
            data = response.json()
            return json.dumps({
                "status": "success",
                "endpoint": endpoint_url,
                "data": data
            })
        else:
            return json.dumps({"error": f"Status {response.status_code}", "endpoint": endpoint_url})
    except Exception as e:
        return json.dumps({"error": str(e), "endpoint": endpoint_url})
    
def query_database_tool(db_path: str, query: str = None) -> str:
    """
    Query database. 
    If query is None, returns all table schemas.
    Otherwise executes the SQL query.
    """
    global count
    count = 0
    count+=1
    print(f"\n\n\n\n\n\n\ndatabase - {count}\n\n\n\n\n\n\n")

    import sqlite3
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        if query is None or query == "SHOW_SCHEMA":
            # Get all tables and their schemas
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            schema = {}
            for table in tables:
                cursor.execute(f"PRAGMA table_info({table})")
                columns = cursor.fetchall()
                schema[table] = [{"name": col[1], "type": col[2]} for col in columns]
            
            result = {"tables": tables, "schema": schema}
        else:
            cursor.execute(query)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            result = {"columns": columns, "rows": rows}
        
        conn.close()
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


def save_mapping_tool(mapping_json: str, output_path: str = "outputs/CMS_3427C_mapping.json") -> str:
    """Save the generated mapping to file."""
    logger.info(f"save_mapping_tool called with output_path: {output_path}")
    print(f"\n{'='*60}")
    print(f"SAVE MAPPING TOOL CALLED")
    print(f"Output path: {output_path}")
    print(f"{'='*60}\n")
    
    try:
        # Parse the mapping JSON
        mapping_data = json.loads(mapping_json)
        logger.info(f"Successfully parsed mapping JSON with {len(mapping_data)} top-level keys")
        
        # Ensure output directory exists
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
            logger.info(f"Created output directory: {output_dir}")
        
        # Save the mapping file
        with open(output_path, 'w') as f:
            json.dump(mapping_data, f, indent=2)
        
        logger.info(f"Successfully saved mapping to: {output_path}")
        print(f"\n✓ SUCCESS: Mapping saved to {output_path}\n")
        
        return json.dumps({
            "status": "success",
            "saved_to": output_path,
            "message": f"Mapping file successfully saved to {output_path}"
        })
    except json.JSONDecodeError as e:
        error_msg = f"Invalid JSON format: {str(e)}"
        logger.error(error_msg)
        print(f"\n✗ ERROR: {error_msg}\n")
        return json.dumps({"error": error_msg, "status": "failed"})
    except Exception as e:
        error_msg = f"Failed to save mapping: {str(e)}"
        logger.error(error_msg)
        print(f"\n✗ ERROR: {error_msg}\n")
        return json.dumps({"error": error_msg, "status": "failed"})


# ============= AGENTS =============

async def create_mapping_system(pdf_path: str, endpoints: list, databases: list, output_path: str):
    """
    Create agentic system - agents discover APIs and databases themselves.
    
    Args:
        pdf_path: Path to the PDF file
        endpoints: List of endpoint configurations with id, url, method, is_custom
        databases: List of database configurations with id, path, type
        output_path: Path to save the generated mapping
    """
    
   
    model_client = AzureOpenAIChatCompletionClient(
    azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),
    model=os.getenv("AZURE_OPENAI_MODEL"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
)

    
    # PDF Schema Agent
    pdf_agent =  AssistantAgent(
        name="pdf_schema_agent",
        model_client=model_client,
        description="Extracts PDF form schema",
        tools=[read_pdf_content],
         reflect_on_tool_use=True,
        max_tool_iterations=2,
        system_message="""You are tasked with extracting structured data from a PDF file containing a specific template. 
        The goal is to identify and capture all the fields present in the PDF and represent them in a well-organized JSON format.
 
### Instructions:
1. Call read_pdf_content tool with the PDF path to analyze the document
2. **IMPORTANT: Check the tool result for errors:**
   - If the result has an "error" key or "success": false, the PDF is INVALID
   - In this case, you MUST output:
     ```
     STATUS: INVALID_PDF
     REASON: [copy the exact error message from the tool result]
     TERMINATE
     ```
   - Then STOP immediately. Do not proceed further.
3. If the PDF is valid (no error), analyze the PDF content carefully to identify all fields, including labels, input areas, boolean checkboxes, compliant status(check) and any relevant metadata
4. Extract each field's name and its corresponding value or placeholder if the value is not provided
5. Structure the extracted information into a JSON object where each key is the field name and the value is the field content or an empty string if no content is present
6. Ensure the JSON reflects the hierarchy or grouping of fields if the template organizes fields into sections or categories
7. Validate that all fields from the PDF are included without omission
 
### Guidelines:
- Extract only the information visible or explicitly present in the PDF
- Do not infer or add any data beyond what is contained in the document
- Maintain the exact field names as they appear in the template for clarity
- If the template contains nested sections, represent them as nested JSON objects
 
### Output Format (for VALID PDFs only):
You MUST output the extracted schema in this exact format:

PDF_SCHEMA:
```json
{
  "field name": {
    "type": "text",
    "value": ""
  },
  "field name": {
    "type": "number",
    "value": ""
  },
  "field name": {
    "type": "date",
    "value": ""
  },
  "field name": {
    "type": "radio button",
    "value": ""
  },
  "field name": {
    "type": "dropdown",
    "value": ""
  },
  "field name": {
    "type": "checkbox",
    "value": ""
  },
  "field name": {
    "type": "list",
    "value": ""
  }
}
```
Total fields : 7

Then say "DONE"

Other agents need your JSON output to continue."""
    )
    
    # API Explorer Agent - discovers endpoints itself
    api_explorer = AssistantAgent(
        name="api_explorer_agent",
        model_client=model_client,
        tools=[call_api_tool],
        reflect_on_tool_use=True,
        max_tool_iterations=8,
        system_message=f"""You are the API Explorer Agent. Your job is to find API data sources for PDF fields.

Available API Endpoints:
{json.dumps(endpoints, indent=2)}

**Your Task:**

1. **Receive PDF fields** from pdf_schema_agent - analyze the field names and types

2. **Explore ALL available API endpoints**:
   - Use the endpoint URLs directly from the list above
   - Call each endpoint using call_api_tool (authentication is automatic)
   - Each endpoint has: id, url (full URL), method (GET/POST), is_custom flag

3. **Analyze API responses**:
   - Study the JSON structure returned by each endpoint
   - Note nested objects and arrays
   - Identify field names and data types

4. **Match PDF fields to API data** using semantic matching:
   - "Facility Name" → matches "name", "facilityName", "facility_name"
   - "Street Address" → matches "address.street", "street_address", "address"
   - "NPI" → matches "npi", "NPI", "national_provider_id"
   - "Phone" → matches "phone", "telephone", "contact.phone"
   
5. **Document mappings** with these details for EACH field:
   - **PDF field name**: Exact name from PDF
   - **API endpoint**: Full URL from the endpoints list
   - **Endpoint ID**: The id field from the endpoint configuration
   - **Response field path**: How to access the data (e.g., "address.street", "contact.phone")
   - **Data location instructions**: Write clear, LLM-friendly instructions:
     * "Find the facility matching the user-provided facility name and ID, then extract the [field] field"
     * "Find the matching facility and extract the [field] from the [object] object"
     * "Find the audit record for the matching facility and extract the [field] field"
     * For combined fields: "extract [field1], [field2], and [field3] from the [object] object, then combine them in the format: {{field1}}, {{field2}} {{field3}}"

6. **Coverage**: Try to map as many PDF fields as possible to API sources

7. **Report findings**: 
   When done, say: "API exploration complete. Found mappings for [X] fields. Passing to db_explorer_agent"
   
   List each mapped field with its endpoint and data path.

**Remember**: The mapping_builder_agent needs your detailed findings to create accurate data_location instructions!"""
    )
    
    # Database Explorer Agent
    db_explorer = AssistantAgent(
        name="db_explorer_agent",
        model_client=model_client,
        tools=[query_database_tool],
        reflect_on_tool_use=True,
        max_tool_iterations=8,
        system_message=f"""You are the Database Explorer Agent. Your job is to find database sources for PDF fields not covered by APIs.

Available Databases:
{json.dumps(databases, indent=2)}

**Your Task:**

1. **Get database schema for EACH database**:
   - For each database in the list above, call query_database_tool
   - Use the database path from the configuration
   - Call with query=None to see all tables and their schemas
   - Study column names, types, and structure

2. **Identify unmapped fields**:
   - Review findings from api_explorer_agent
   - Focus on PDF fields that don't have API sources
   - Look for signature fields, auditor info, comments, etc.

3. **Match PDF fields to database columns** using semantic matching:
   - "Auditor Name" → matches "employees.name" where role relates to auditing
   - "Signature" → matches "employees.name" where can_sign_* = 1
   - "Comments" → matches "comments", "notes", "remarks" fields
   
4. **Query sample data** (if needed):
   - Use SELECT queries to understand data structure
   - Check for facility-specific columns (facility_id, facility_name, etc.)
   - Verify authorization flags (can_sign_3427, is_auditor, etc.)

5. **Document mappings** with these details for EACH database field:
   - **PDF field name**: Exact name from PDF
   - **Database ID**: The id field from the database configuration
   - **Source file**: Database filename from configuration path
   - **Table name**: Exact table name from schema
   - **Column name**: Specific column(s) to extract
   - **Description**: Clear explanation with context
   - **Facility-specific**: true if data must match a specific facility, false otherwise
   - **Requirements**: SQL-friendly conditions (e.g., "Employee from this facility who can sign CMS-3427 (can_sign_3427 = 1)")
   - **Required**: true for mandatory fields, false for optional

6. **Provide context** for the mapping_builder_agent:
   - Explain what conditions must be met (e.g., "can_sign_3427 = 1")
   - Note if multiple tables need to be joined
   - Specify any facility-matching requirements

7. **Report findings**:
   When done, say: "Database exploration complete. Found mappings for [X] fields. Passing to mapping_builder_agent"
   
   List each mapped field with its database_id, table, column, and requirements.

**Remember**: Focus on fields that APIs cannot provide - typically internal employee data, signatures, and facility-specific information."""
    )
    
    # Mapping Builder Agent
    mapping_builder = AssistantAgent(
        name="mapping_builder_agent",
        model_client=model_client,
        tools=[save_mapping_tool],
        system_message=f"""You are the Mapping Builder Agent responsible for creating the final mapping.json file.

**CRITICAL: Follow this EXACT JSON structure:**

{{
  "form_id": "CMS-XXXX",
  "form_name": "Full descriptive name of the form",
  "version": "1.0",
  "total_fields": <number>,
  
  "api_mappings": [
    {{
      "field_id": "1",
      "field_name": "Exact field name from PDF",
      "api_endpoint": "http://127.0.0.1:8001/full/endpoint/url",
      "required": true,
      "description": "Clear description of what this field represents",
      "data_location": "LLM-friendly instructions: Find the [object] matching the user-provided [criteria], then extract the [specific_field_name] field"
    }}
  ],
  
  "database_mappings": [
    {{
      "field_id": "9",
      "field_name": "Exact field name from PDF",
      "source_file": "database_filename.sqlite",
      "table": "table_name",
      "description": "Clear description with context about what data is needed",
      "facility_specific": true,
      "requirements": "Specific SQL-friendly requirements like 'Employee from this facility who can sign CMS-3427 (can_sign_3427 = 1)'",
      "required": true
    }}
  ]
}}

**Instructions:**

1. **Collect Data** from api_explorer_agent and db_explorer_agent:
   - Extract all PDF fields identified by pdf_schema_agent
   - Note which fields have API sources vs database sources
   - Preserve all mapping details discovered by explorer agents

2. **Build api_mappings array** for fields sourced from APIs:
   - field_id: Use sequential numbers matching PDF field order
   - field_name: Exact field name as it appears in the PDF
   - api_endpoint: FULL endpoint URL 
   - required: true for mandatory fields, false for optional
   - description: Clear, concise explanation of the field's purpose
   - data_location: **CRITICAL** - Write LLM-friendly instructions that explain:
     * What object/record to find (e.g., "Find the facility matching...")
     * What criteria to match on (e.g., "user-provided facility name and ID")
     * What field to extract (e.g., "extract the certification_number field")
     * If nested, describe the path (e.g., "from the address object")
     * If transformation needed, explain (e.g., "combine them in the format: {{city}}, {{state}} {{zip}}")

3. **Build database_mappings array** for fields sourced from database:
   - field_id: Continue sequential numbering
   - field_name: Exact field name as it appears in the PDF
   - source_file: Database filename (e.g., "internal_hr.sqlite")
   - table: Exact table name from database schema
   - description: Explain what data is needed with full context
   - facility_specific: true if data must match a specific facility, false otherwise
   - requirements: SQL-friendly conditions (e.g., "can_sign_3427 = 1")
   - required: true for mandatory fields, false for optional

4. **Form Metadata**:
   - form_id: Extract from PDF filename or content (e.g., "CMS-3427")
   - form_name: Descriptive name of the form
   - version: Use "1.0" for new mappings
   - total_fields: Total count of all fields (API + database)

5. **Quality Checks**:
   - Ensure all PDF fields are mapped (compare with pdf_schema_agent output)
   - Prioritize API sources over database when both are available
   - Verify field_id numbering is sequential
   - Ensure data_location provides clear, actionable instructions for an LLM
   - Validate JSON syntax is correct

6. **CRITICAL - Save the mapping**:
   Call save_mapping_tool with these EXACT parameters:
   - mapping_json: Your complete mapping JSON as a valid JSON string
   - output_path: "{output_path}"
   
   Example: save_mapping_tool(mapping_json=<your_json_string>, output_path="{output_path}")

7. After successfully saving, say: "MAPPING_COMPLETE"

**Remember**: The data_location field is crucial - it will be used by an agentic AI system to automatically fetch and fill form data. Write instructions as if explaining to an intelligent assistant how to find and extract the data."""
    )
    
    # Use multiple termination conditions for safety
    termination = TextMentionTermination("MAPPING_COMPLETE") | MaxMessageTermination(5)
    
    # RoundRobinGroupChat for linear workflow: pdf -> api -> db -> mapping
    team = RoundRobinGroupChat(
        participants=[pdf_agent, api_explorer, db_explorer, mapping_builder],
        termination_condition=termination
    )
    
    return team


# ============= MAIN =============

async def generate_mapping(pdf_path: str, endpoints: list, databases: list, output_path: str):
    """Generate mapping for new CMS PDF."""
    
    print("\n" + "="*50)
    print("STARTING MAPPING GENERATION")
    print("="*50)
    print(f"PDF: {pdf_path}")
    print(f"Output: {output_path}")
    print(f"Endpoints: {len(endpoints)}")
    print(f"Databases: {len(databases)}\n")
    
    team = await create_mapping_system(pdf_path, endpoints, databases, output_path)
    
    initial_task = f"""
AUTOMATED MAPPING GENERATION WORKFLOW
=======================================

Target PDF: {pdf_path}
Output File: {output_path}
Available API Endpoints: {json.dumps(endpoints, indent=2)}
Available Databases: {json.dumps(databases, indent=2)}

**OBJECTIVE**: Generate a production-ready mapping.json file that will be used by an agentic AI system to automatically fill PDF forms with data from multiple sources (APIs and databases).

**REQUIRED OUTPUT FORMAT**:
{{
  "form_id": "CMS-XXXX",
  "form_name": "Full form name",
  "version": "1.0",
  "total_fields": <count>,
  "api_mappings": [ /* Array of API-sourced fields */ ],
  "database_mappings": [ /* Array of database-sourced fields */ ]
}}

**4-AGENT SEQUENTIAL WORKFLOW**:

1. **pdf_schema_agent** - PDF Schema Extraction
   → Extract ALL fillable fields from the PDF form
   → Identify field names, types, and structure
   → Output: Complete JSON schema of PDF fields
   → Validation: Ensure PDF has valid fillable form fields
   
2. **api_explorer_agent** - API Data Source Mapping
   → Receive PDF schema from pdf_schema_agent
   → Call ALL available API endpoints to discover data structures
   → Match PDF fields to API response fields (semantic matching)
   → Document for EACH matched field:
     * Full endpoint URL 
     * Response field path (e.g., "address.street", "contact.phone")
     * LLM-friendly data_location instructions (how to extract the data)
   → Example data_location: "Find the facility matching the user-provided facility name and ID, then extract the certification_number field"
   → Output: List of API mappings with detailed extraction instructions
   
3. **db_explorer_agent** - Database Source Mapping
   → Receive API mappings from api_explorer_agent
   → Query database schema to discover tables and columns
   → Focus on fields NOT covered by APIs (signatures, auditor info, internal data)
   → Document for EACH database field:
     * Source file name (e.g., "internal_hr.sqlite")
     * Table and column names
     * SQL-friendly requirements (e.g., "can_sign_3427 = 1")
     * Facility-specific flags
   → Output: List of database mappings with query requirements
   
4. **mapping_builder_agent** - Final Mapping Assembly
   → Collect ALL mappings from api_explorer_agent and db_explorer_agent
   → Build complete mapping.json with EXACT format:
     * "api_mappings": Array with field_id, field_name, api_endpoint, required, description, data_location
     * "database_mappings": Array with field_id, field_name, source_file, table, description, facility_specific, requirements, required
   → Ensure all PDF fields are mapped
   → Prioritize API sources over database when both available
   → Call save_mapping_tool(mapping_json=<json_string>, output_path="{output_path}")
   → Confirm completion by saying the termination phrase

**CRITICAL REQUIREMENTS**:
- ALL PDF fields MUST be mapped (no fields left unmapped)
- data_location must contain clear, LLM-friendly extraction instructions
- Sequential numbering of field_id across both api_mappings and database_mappings
- Final mapping must be valid JSON and saved to {output_path}

BEGIN WORKFLOW NOW - pdf_schema_agent, start by extracting the PDF schema from {pdf_path}.
"""
    
    print("Running agent team...\n")
    
    try:
        # Stream results to console
        stream = team.run_stream(task=initial_task)
        async for message in stream:
            if hasattr(message, 'content'):
                print(f"[{message.source}] {message.content}")
            else:
                print(message)
        
        print("\n" + "="*50)
        print("MAPPING GENERATION COMPLETE")
        print("="*50)
        
        # CRITICAL: Verify the file was created
        if not os.path.exists(output_path):
            error_msg = f"Agent workflow completed but file was not created at {output_path}"
            logger.error(error_msg)
            print(f"\n❌ ERROR: {error_msg}")
            print("Creating fallback empty mapping file...")
            
            # Create a minimal valid mapping as fallback
            fallback_mapping = {
                "form_id": "UNKNOWN",
                "form_name": "Mapping generation failed",
                "version": "1.0",
                "total_fields": 0,
                "api_mappings": [],
                "database_mappings": [],
                "error": "Agent workflow did not complete successfully. Please check logs and try again."
            }
            
            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Save fallback mapping
            with open(output_path, 'w') as f:
                json.dump(fallback_mapping, f, indent=2)
            
            logger.info(f"Created fallback mapping at {output_path}")
            raise RuntimeError(error_msg)
        
        logger.info(f"Verified mapping file exists at: {output_path}")
        return stream
        
    except Exception as e:
        logger.error(f"Error during mapping generation: {str(e)}")
        
        # Ensure we at least create an error file so the API doesn't crash
        if not os.path.exists(output_path):
            fallback_mapping = {
                "form_id": "ERROR",
                "form_name": "Mapping generation error",
                "version": "1.0",
                "total_fields": 0,
                "api_mappings": [],
                "database_mappings": [],
                "error": str(e)
            }
            
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, 'w') as f:
                json.dump(fallback_mapping, f, indent=2)
            
            logger.info(f"Created error mapping file at {output_path}")
        
        raise


# ============= USAGE =============

if __name__ == "__main__":
    # Example endpoint configurations
    endpoints = [
        {
            "id": "compliance_audit_api",
            "url": "http://127.0.0.1:8000/api/compliance/audit",
            "method": "GET",
            "is_custom": False
        },
        {
            "id": "state_registry_api",
            "url": "http://127.0.0.1:8000/api/registry/state",
            "method": "GET",
            "is_custom": False
        },
        {
            "id": "ehr_facility_api",
            "url": "http://127.0.0.1:8000/api/ehr/facility",
            "method": "GET",
            "is_custom": False
        },
        {
            "id": "hr_auditor_api",
            "url": "http://127.0.0.1:8000/api/hr/auditor",
            "method": "GET",
            "is_custom": False
        }
    ]
    
    # Example database configurations
    databases = [
        {
            "id": "internal_hr_db",
            "path": "data/database_sources/internal_hr.sqlite",
            "type": "sqlite"
        },
        {
            "id": "internal_finance_db",
            "path": "data/database_sources/internal_finance.sqlite",
            "type": "sqlite"
        }
    ]
    
    pdf_path = "mapping_uploads/form.pdf"
    output_path = "mapping_outputs/cms_3427_mapping.json"
    
    asyncio.run(generate_mapping(pdf_path, endpoints, databases, output_path))
