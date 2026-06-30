"""
Healthcare Form Auto-Filling - RoundRobin Multi-Agent Workflow
===============================================================

Uses RoundRobinGroupChat for faster, deterministic agent coordination.
Agents speak in a fixed round-robin order without LLM selection overhead.
"""

import asyncio
import os
import json
import re
import logging
from typing import Dict, Any
from dotenv import load_dotenv

# Autogen imports
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
from autogen_agentchat.base import TaskResult
from autogen_agentchat.messages import TextMessage
from autogen_ext.models.openai import AzureOpenAIChatCompletionClient

# Tool imports
from tools import (
    read_pdf_content,
    load_field_mapping,
    fetch_multiple_from_json,
    get_database_schema,
    fetch_multiple_from_sqlite,
    fill_pdf_form
)

# Configure logging - suppress background details
logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Suppress verbose autogen logging
logging.getLogger("autogen_core").setLevel(logging.WARNING)
logging.getLogger("autogen_agentchat").setLevel(logging.WARNING)
logging.getLogger("autogen_ext").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

# Load environment variables
load_dotenv()

# Azure OpenAI Model Client
model_client = AzureOpenAIChatCompletionClient(
    azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),
    model=os.getenv("AZURE_OPENAI_MODEL"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
)


# ============================================================================
# Helper Function
# ============================================================================

async def load_form_metadata(mapping_path: str) -> Dict[str, Any]:
    """Load form metadata from mapping file."""
    with open(mapping_path, 'r') as f:
        mapping = json.load(f)
    
    return {
        "form_id": mapping.get("form_id", "UNKNOWN"),
        "form_name": mapping.get("form_name", "Unknown Form"),
        "version": mapping.get("version", "1.0"),
        "total_fields": mapping.get("total_fields", 0)
    }


# ============================================================================
# Agent Definitions
# ============================================================================

def create_pdf_schema_agent() -> AssistantAgent:
    """Creates PDFSchemaAgent with concise instructions for round-robin."""
    return AssistantAgent(
        name="PDFSchemaAgent",
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


def create_mapping_agent() -> AssistantAgent:
    """Creates MappingAgent with concise instructions for round-robin."""
    return AssistantAgent(
        name="MappingAgent",
        model_client=model_client,
        description="Loads field mappings",
        tools=[load_field_mapping],
        reflect_on_tool_use=True,
        max_tool_iterations=2,
        system_message="""You load field mappings from JSON files.

When it's your turn:
1. Extract the mapping path from the task (look for **Mapping:** in the instructions)
2. YOU MUST call load_field_mapping(path) with that exact path
3. After the tool returns, output the complete tool result
4. Then say "DONE"

You strictly MUST use the load_field_mapping tool before saying DONE."""
    )


def create_api_agent() -> AssistantAgent:
    """Creates APIAgent with dynamic data extraction capabilities."""
    return AssistantAgent(
        name="APIAgent",
        model_client=model_client,
        description="Intelligently fetches and extracts data from JSON API sources",
        tools=[fetch_multiple_from_json],
        reflect_on_tool_use=True,
        max_tool_iterations=12,
        system_message="""You are an intelligent API Data specialist. You fetch data from API endpoints and extract the correct fields based on facility context.

**CRITICAL: You MUST use the API tool. Do NOT output data without calling the tool first.**

**PROCESS:**

STEP 1: Get context
- Extract the facility_name and facility_id from the task description
- Look at MappingAgent's output and find the "api_mappings" array (NOT "database_mappings")
- ONLY process fields from "api_mappings" - these have "api_endpoint" field
- IGNORE any fields from "database_mappings" - those will be handled by DatabaseAgent
- If there are NO api_mappings, output "NO API FIELDS TO FETCH" and say "DONE"

STEP 2: Group fields by endpoint
- Group all fields from api_mappings that use the same api_endpoint together
- This allows you to fetch each endpoint ONCE and extract multiple fields
- Show each fields details from that particular endpoint.

STEP 3: Call the tool for each unique endpoint (MANDATORY)
- For each unique api_endpoint, you MUST call fetch_multiple_from_json(api_endpoint=..., facility_name=..., facility_id=...)
- The tool will return the FULL API response
- You can call this tool multiple times for different endpoints
- DO NOT skip this step - actually call the tool

STEP 4: Extract data intelligently (Your LLM intelligence)
- For each field in api_mappings, read the data_location instruction
- Use the API response to find the matching facility (by facility_id matching the one from task)
- Extract the required field value based on the description
- Handle data transformations (e.g., combining city, state, zip)
- Do not create any fake data. The data should be strictly from the API endpoints specific to that particular input facility.

STEP 5: Output results from tool calls
- Output ALL extracted data from api_mappings with field_id
- Format: "field_1: Metro Medical Center" (from actual API data)
- If a field cannot be found, output "field_1: <NOT FOUND>"
- Do not create fake data - only use what's in the API response from the tool

STEP 6: Say "DONE"

**EXAMPLE:**
If api_mappings has field_1 (Facility Name) and field_3 (Street Address) from the same endpoint:
1. Call fetch_multiple_from_json("http://127.0.0.1:8000/api/ehr/facility", "Metro Medical Center", "FAC-001")
2. Tool returns: {"facilities": [{"facility_id": "FAC-001", "name": "Metro Medical Center", ...}, ...]}
3. You find the facility with facility_id="FAC-001"
4. Extract: name = "Metro Medical Center", address.street = "456 Oak Avenue"
5. Output: "field_1: Metro Medical Center" and "field_3: 456 Oak Avenue"
6. Say "DONE"

**CRITICAL:**
- You MUST call fetch_multiple_from_json() for each unique endpoint
- ONLY process the "api_mappings" array - do NOT touch "database_mappings"
- Batch requests by endpoint for efficiency
- Use facility_id (from task) to find the correct facility data in API responses
- Follow data_location instructions to extract the right fields
- Do not fabricate data - only extract what exists in API responses from the tool


Make sure the field ID's for each field is correct. If you give wrong field then the filler agent will fill the data to wrong fields.
So it's CRITICAL to give correct field ID's.

If you don't call the tool, you will fail.YOU MUST always use the tool to fetch real data.
"""
    )


def create_database_agent() -> AssistantAgent:
    """Creates DatabaseAgent - Generates SQL queries dynamically based on facility context."""
    return AssistantAgent(
        name="DatabaseAgent",
        model_client=model_client,
        description="Generates SQL queries and fetches data from SQLite databases",
        tools=[get_database_schema, fetch_multiple_from_sqlite],
        reflect_on_tool_use=True,
        max_tool_iterations=15,
        system_message="""You are an intelligent Database Agent that generates SQL queries dynamically based on facility context.

**CRITICAL: You MUST use the database tools. Do NOT output data without calling tools first.**

**YOUR PROCESS:**

STEP 1: Extract facility information from the task
- Look for "**Facility Name:**" and "**Facility ID:**" in the task description
- You MUST use this facility context when generating queries

STEP 2: Understand database requirements
- Look at MappingAgent's output and find the "database_mappings" array (NOT "api_mappings")
- ONLY process fields from "database_mappings" - these have "source_file" field
- If there are NO database_mappings, output "NO DATABASE FIELDS TO FETCH" and say "DONE"
- Each mapping has:
  * field_id: The field identifier
  * field_name: What data is needed (e.g., "Auditor Name", "Administrator Signature")
  * source_file: Which database to query (e.g., "internal_hr.sqlite")
  * table: Which table to query
  * description: What the field represents
  * facility_specific: Whether this data should be filtered by facility

STEP 3: Get database schema (MANDATORY)
- For each unique source_file in database_mappings, you MUST call get_database_schema(source_file) ONCE
- This shows you table columns and sample data
- Use this to understand which columns exist (e.g., facility_id, full_name, etc.)
- DO NOT skip this step - it's required to generate correct queries

STEP 4: Generate intelligent SQL queries
- For FACILITY-SPECIFIC fields (facility_specific = true):
  * Generate query with WHERE clause filtering by facility_id
  * Example: "SELECT full_name FROM employees WHERE facility_id = 'FAC-002' AND can_sign_3427 = 1"
  
- For STATIC fields (facility_specific = false):
  * Generate query without facility filter or use static text from requirements
  * Example: "SELECT 'No significant deficiencies found.' AS comments"

STEP 5: Execute queries (MANDATORY)
- Group all generated queries by source_file
- You MUST call fetch_multiple_from_sqlite(source_file, queries) for each database
- Format: [{"field_id": "9", "sql_query": "YOUR GENERATED SQL"}, ...]
- DO NOT skip this step - actually execute the queries

STEP 6: Output results from tool calls
- Output ALL fetched data with field IDs from the tool results
- Format: "field_9: John Smith" (from actual database results)
- If a query returns no data, output: "field_9: <NOT FOUND>"
- DO NOT fabricate data - only use what the tools return
- Then say "DONE"

**CRITICAL RULES:**
- You MUST call get_database_schema() before generating queries
- You MUST call fetch_multiple_from_sqlite() to execute queries
- ONLY process the "database_mappings" array - do NOT touch "api_mappings"
- Use the facility_id from the task to filter employee/facility-specific data
- Generate queries dynamically - DO NOT use hardcoded employee_id or facility references
- Different facilities have different employees - query based on facility_id column
- DO NOT output fake data or guess values - only return what the database actually contains

**EXAMPLE:**
Task has facility_id = "FAC-002", database_mappings has field_id "9" for "Auditor Name":
1. Call get_database_schema("internal_hr.sqlite") → see columns [employee_id, facility_id, full_name, can_sign_3427]
2. Generate query: "SELECT full_name FROM employees WHERE facility_id = 'FAC-002' AND can_sign_3427 = 1"
3. Call fetch_multiple_from_sqlite("internal_hr.sqlite", [{"field_id": "9", "sql_query": "SELECT..."}])
4. Tool returns: {"9": "Dr. Sarah Johnson"}
5. Output: "field_9: Dr. Sarah Johnson"
6. Say "DONE"

If you don't call the tools, you will fail. Always use the tools to fetch real data."""
    )


var = None

def create_data_populator_agent() -> AssistantAgent:
    """Creates DataPopulatorAgent - pure reasoning, no tools."""
    return AssistantAgent(
        name="DataPopulatorAgent",
        model_client=model_client,
        description="Merges API and Database data",
        tools=[],
        system_message="""You merge data from APIAgent and DatabaseAgent.

When it's your turn:
1. Extract data from APIAgent's output
2. Extract data from DatabaseAgent's output
3. Look at the mapping data - each field has a "field_id" (like field_1, field_2, etc.)
4. Merge into structured data for each field. Make sure you only populate the given fields and field data from API and database agent only
. DO NOT ADD ANY FIELD ON YOUR OWN.
5. CRITICAL: Use field_id as the key (field_1, field_2, NOT the field_name)
6.Check PDF Schema agent's schema - do not miss any field even if the field value is not present just pass the field with no data found as value.
7. Output MUST be in this EXACT format (Strictly with Field IDs and not field names):

```json
{
  "field_1": {
    "type": "text",
    "value": "John Smith"
  },
  "field_2": {
    "type": "number",
    "value": "45"
  },
  "field_3": {
    "type": "date",
    "value": "1980-03-15"
  },
  "field_4": {
    "type": "radio_button",
    "value": "Male"
  },
  "field_5": {
    "type": "dropdown",
    "value": "Blue Cross"
  },
  "field_6": {
    "type": "checkbox",
    "value": "Yes"
  },
  "field_7": {
    "type": "list",
    "value": "Diabetes, Hypertension"
  },
  "field_8": {
    "type": "signature",
    "value": "John Smith"
  }
}

```

Do NOT add any text before the ```json marker.
Make sure the sequence is correct.
 
 

IMPORTANT: Don't mention anything related to POC, do not use that term, this an application
Then say DONE.

Do not miss the field type.
Output format must be clean, structured and readable.
"""
    )


def create_validation_agent() -> AssistantAgent:
    """Creates ValidationAgent - validates data quality before PDF filling."""
    return AssistantAgent(
        name="ValidationAgent",
        model_client=model_client,
        description="Validates data quality before PDF filling",
        tools=[],
        system_message="""You are a validation agent. You validate data quality from DataPopulatorAgent before PDF filling.

When it's your turn:
1. Extract the JSON data from DataPopulatorAgent's previous message
2. Extract the PDF schema from PDFSchemaAgent's output (field types) - This schema will have all the fields present with count of total fields,
    so make sure even if the field value is not present you pass this field - DO NOT MISS.
3. Extract the mappings from MappingAgent's output (required fields)

### VALIDATION CHECKS TO PERFORM:

**1. Required Fields Validation:**
- Check MappingAgent output for fields with "required": true
- Check PDF Schema agent's schema and the count of total fields. Make sure the fields fetched from the pdf = fields given by data populator agent
   - do not miss any field even if the field value is not present just pass the field with <MISSING VALUE>.
- Verify each required field has a non-empty value
- Report any missing required fields as CRITICAL

**2. Data Completeness Check:**
- Count total fields from PDF schema
- Count fields with non-empty values
- Calculate completion percentage
- List empty fields (distinguish required vs optional)

**3. Data Type Validation:**
- Compare expected type (from PDF schema) with populated data
- Verify type consistency:
  * "text" → string value
  * "number" → numeric value
  * "date" → date string (YYYY-MM-DD or MM/DD/YYYY)
  * "checkbox" → boolean or "Yes"/"No"
  * "radio_button" → selected value
  * "dropdown" → selected value


**6. Field Type-Specific Validation:**
- Checkbox: Value is boolean or "Yes"/"No"
- Radio button: Has selected value
- Dropdown/list: Has selected value
- Text: Not just whitespace if required
- Number: Actually numeric, not negative if shouldn't be

### VALIDATION REPORT:
First, output a validation summary:
```
VALIDATION REPORT:
✓ Total Fields: X
✓ Populated Fields: Y (Z%)
✓ Required Fields: A
✓ Missing Required: B

CRITICAL ISSUES:
- [List any missing required fields or critical validation failures]

WARNINGS:
- [List any optional missing fields or minor issues]

DATA TYPE ISSUES:
- [List any type mismatches]


STATUS: [PASS/FAIL/PASS_WITH_WARNINGS]
```

### OUTPUT FORMAT:
After the validation report, you MUST output the data in the EXACT same format as DataPopulatorAgent.
This is CRITICAL because PDFFillerAgent depends on this exact format. Do not change the format

For missing values/ no data found in text fields, use "<MISSING VALUE>".
For other field types, keep the original value or use appropriate placeholder.

```json
{
  "field_1": {
    "type": "text",
    "value": "John Smith"
  },
  "field_2": {
    "type": "number",
    "value": "45"
  },
  "field_3": {
    "type": "date",
    "value": "<MISSING VALUE>"
  },
  "field_4": {
    "type": "checkbox",
    "value": "Yes"
  }
}
```

Do NOT modify the structure. Keep all fields from DataPopulatorAgent.
Only flag missing values appropriately. All the fields should be represented by fields ID"s only and not field names.

Then say "DONE".

Your goal is to validate data quality and pass validated data to PDFFillerAgent.
"""
    )


def create_pdf_filler_agent() -> AssistantAgent:
    """Creates PDFFillerAgent to fill the PDF form with populated data."""
    return AssistantAgent(
        name="PDFFillerAgent",
        model_client=model_client,
        description="Fills PDF form with populated data",
        tools=[fill_pdf_form],
        reflect_on_tool_use=True,
        max_tool_iterations=2,
        system_message="""You fill PDF forms with validated data.

When it's your turn:
1. Look for ValidationAgent's previous message and extract the JSON data from it (skip the validation report, just get the JSON)
2. The JSON will be in this format:
  {
  "field_1": {
    "type": "text",
    "value": "John Smith"
  },
  "field_2": {
    "type": "number",
    "value": "45"
  },
  "field_3": {
    "type": "date",
    "value": "1980-03-15"
  },
  "field_4": {
    "type": "radio_button",
    "value": "Male"
  },
  "field_5": {
    "type": "dropdown",
    "value": "Blue Cross"
  },
  "field_6": {
    "type": "checkbox",
    "value": "Yes"
  }
3. Parse this JSON and use it as the field_data
4. Get the PDF path from the task description (look for "**PDF:**" line)
5. Call fill_pdf_form() with:
   - pdf_path: The PDF path from the task
   - field_data: The complete JSON object you extracted from DataPopulatorAgent
6. Report success and the output path
7.Even if the validation agent reports missing fields - you must not stop you must go ahead and fill the pdf with those missing values specific to those fields.
8. Say "DONE"

CRITICAL: You MUST call the fill_pdf_form tool. Do not skip this step. The tool will handle extracting values from the nested format.

Example tool call:
fill_pdf_form(
    pdf_path="uploads/uploaded_form.pdf",
    field_data={
        "field name": {"type": "text", "value": "xyz"},
        "field name": {"type": "number", "value": "123"}
    }
)

After calling the tool successfully, report the output path and say DONE."""
    )


# ============================================================================
# RoundRobin Workflow
# ============================================================================

# Global function to handle agent logging - will be set by API server
_global_add_agent_log = None

def set_agent_log_handler(handler):
    """Set the global agent log handler from api_server."""
    global _global_add_agent_log
    _global_add_agent_log = handler

def add_agent_log(session_id: str, agent_name: str, message: str, log_type: str = "info"):
    """Add agent log - calls global handler if available, otherwise just prints."""
    if _global_add_agent_log:
        _global_add_agent_log(session_id, agent_name, message, log_type)
    else:
        # Fallback: just print if no handler set
        print(f"[{agent_name}] {message}")

async def run_roundrobin_workflow(
    pdf_path: str,
    mapping_path: str,
    facility_name: str,
    facility_id: str,
    session_id: str = None,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Run workflow using RoundRobinGroupChat for faster execution.
    
    Agents speak in fixed order: PDF → Mapping → API → Database → Populator → Validation → Filler
    
    Args:
        pdf_path: Path to PDF form
        mapping_path: Path to mapping JSON file
        facility_name: Name of facility (e.g., "Metro Medical Center") - REQUIRED
        facility_id: Facility ID (e.g., "FAC-001") - REQUIRED
        session_id: Unique session ID for log streaming (optional)
        verbose: Enable verbose logging
    """
    
    # Validate files
    if not os.path.exists(pdf_path):
        if session_id:
            add_agent_log(session_id, "System", f"PDF file not found: {pdf_path}", "error")
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    if not os.path.exists(mapping_path):
        if session_id:
            add_agent_log(session_id, "System", f"Mapping file not found: {mapping_path}", "error")
        raise FileNotFoundError(f"Mapping file not found: {mapping_path}")
    
    # Load metadata
    form_metadata = await load_form_metadata(mapping_path)
    form_id = form_metadata["form_id"]
    form_name = form_metadata["form_name"]
    
    if session_id:
        add_agent_log(session_id, "System", f"Starting workflow for {form_name} ({form_id})", "info")
    
    if verbose:
        print("\n" + "=" * 80)
        print(f"[FORM] {form_name} ({form_id})")
        print("=" * 80 + "\n")
    
    # Create agents
    pdf_agent = create_pdf_schema_agent()
    mapping_agent = create_mapping_agent()
    api_agent = create_api_agent()
    database_agent = create_database_agent()
    populator_agent = create_data_populator_agent()
    validation_agent = create_validation_agent()
    filler_agent = create_pdf_filler_agent()
    
    if session_id:
        add_agent_log(session_id, "System", "All agents initialized successfully", "success")
    
    # Create termination conditions
    # 1. Stop when TERMINATE is mentioned (for invalid PDF detection)
    terminate_condition = TextMentionTermination("TERMINATE")
    # 2. Max messages as fallback (7 agents + 1 initial message)
    max_messages_condition = MaxMessageTermination(8)
    
    # Create RoundRobinGroupChat with both termination conditions
    team = RoundRobinGroupChat(
        participants=[
            pdf_agent,
            mapping_agent,
            api_agent,
            database_agent,
            populator_agent,
            validation_agent,
            filler_agent
        ],
        termination_condition=terminate_condition | max_messages_condition
    )
    
    # Create task
    task = f"""Complete the form filling workflow:

**Form:** {form_name} ({form_id})
**PDF:** {pdf_path}
**Mapping:** {mapping_path}
**Facility Name:** {facility_name}
**Facility ID:** {facility_id}

**Instructions:**
- PDFSchemaAgent: Read the PDF - 
  If - the PDFSchema agent sends an error message stating STATUS: INVALID_PDF - Terminate the workflow immediately - Do not proceed further.
  Else If - The PDF is valid(no error) - Then fetch all the fields and pass it in detailed schema including field name and field type with count of total fields fetched.
- MappingAgent: Load mappings from the file (contains field descriptions and data locations, no json_path).
  The mapping agent strictly MUST use the load_field_mapping tool.
- APIAgent: Fetch data from API endpoints using INTELLIGENT EXTRACTION:
  * Group fields by api_endpoint
  * Call fetch_multiple_from_json for each endpoint (passes facility context)
  * Use your LLM intelligence to find the matching facility in the API response
  * Extract the required fields based on data_location instructions
  * Output all extracted data with field_id
  * Do not create fake data - only extract what exists in API responses
- DatabaseAgent: Fetch data from SQLite sources (batch by database) using dynamically generated SQL queries based on facility context. Pass data with field_id. Do not create fake data. Only extracts what exists in the database
- DataPopulatorAgent: Merge everything and output final data with respective field_id, field_type and field_value in clean, structured format. Do not miss the field type to pass. 
  Populate the data Strictly keeping Field ID's as JSON keys and not field names.
  Make sure you only populate the given fields and field data from API and database agent only. DO NOT ADD ANY FIELD ON YOUR OWN.
- ValidationAgent: Validate the populated data quality - check required fields, data types, completeness. Output validation report and pass the validated data in the exact same JSON format.
  Check pdf schema fields are equal to final populated fields. Also check if the data is from API sourse or database sources and make sure its not fake or worng data.
- PDFFillerAgent: Fill the PDF form with the validated data from ValidationAgent and save it to outputs/ directory.
  Even if the validation agent reports missing fields - you must not stop you must go ahead and fill the pdf with those missing values specific to those fields.
When each agent finishes, say "DONE" to pass to the next agent.

Make sure that API agent does not touch database mappings.
Make sure Database agent does not touch API mappings.
Make sure you do not add any fake data by yourself, it should only be from either API or database data specific to the facility.
Make sure validation agent keep the structure representation using field ID's only and not by field name.

Begin now."""
    


#     - DataPopulatorAgent: Merge everything and output final data with respective field id, field type and field data in clean, structured format. Do not miss the field type to pass. 
#   Populate the data Strictly keeping Field ID's as JSON value and not field names.
#   Make sure you only populate the given fields and field data from API and database agent only. DO NOT ADD ANY FIELD ON YOUR OWN.
# - ValidationAgent: Validate the populated data quality - check required fields, data types, completeness. Output validation report and pass the validated data in the exact same JSON format. Check pdf schema fields are equal to to final populated fields.
# - PDFFillerAgent: Fill the PDF form with the validated data from ValidationAgent and save it to outputs/ directory.
#   Even if the validation agent reports missing fields - you must not stop you must go ahead and fill the pdf with those missing values specific to those fields.
# When each agent finishes, say "DONE" to pass to the next agent.

# Begin now.

    # Part 1: Show agent outputs and check for early termination
    result = None  # Initialize result
    invalid_pdf_detected = False
    invalid_pdf_reason = ""

    async for message in team.run_stream(task=task):
        if isinstance(message, TaskResult):
            result = message  # ✅ SAVE the TaskResult here
            print("\n\n\n\nStop Reason:", message.stop_reason)
            if session_id:
                add_agent_log(session_id, "System", f"Workflow completed: {message.stop_reason}", "success")
        elif isinstance(message, TextMessage):
            print(f"\n\n\n\n\n{message.source}: {message.content}\n")
            
            # Check for INVALID_PDF from PDFSchemaAgent
            if message.source == "PDFSchemaAgent" and "STATUS: INVALID_PDF" in message.content:
                invalid_pdf_detected = True
                # Extract reason from message
                reason_match = re.search(r'REASON: (.+?)(?:TERMINATE|$)', message.content, re.DOTALL)
                if reason_match:
                    invalid_pdf_reason = reason_match.group(1).strip()
                else:
                    invalid_pdf_reason = "PDF does not contain fillable form fields"
                
                if session_id:
                    add_agent_log(session_id, "PDFSchemaAgent", invalid_pdf_reason, "error")
            
            # Log agent messages to session
            if session_id:
                # Get agent name from source
                agent_name = message.source
                # Send full message content without truncation
                full_message = message.content
                
                # Determine log type based on content
                log_type = "processing"
                if "DONE" in message.content:
                    log_type = "success"
                elif "error" in message.content.lower() or "failed" in message.content.lower():
                    log_type = "error"
                elif "warning" in message.content.lower():
                    log_type = "warning"
                
                add_agent_log(session_id, agent_name, full_message, log_type)
    
    # Check if invalid PDF was detected during stream
    if invalid_pdf_detected:
        if session_id:
            add_agent_log(session_id, "System", "Workflow terminated: Invalid PDF", "error")
        return {
            "status": "error",
            "code": "INVALID_PDF",
            "message": invalid_pdf_reason
        }
    
    # Also check result.stop_reason for TERMINATE
    if result and "TERMINATE" in str(result.stop_reason):
        # Extract reason from messages
        for msg in result.messages:
            if isinstance(msg, TextMessage) and "STATUS: INVALID_PDF" in msg.content:
                reason_match = re.search(r'REASON: (.+?)(?:TERMINATE|$)', msg.content, re.DOTALL)
                if reason_match:
                    reason = reason_match.group(1).strip()
                else:
                    reason = "The provided PDF does not contain fillable form fields or structured data required for extraction."
                
                if session_id:
                    add_agent_log(session_id, "System", f"Workflow terminated: {reason}", "error")
                
                return {
                    "status": "error",
                    "code": "INVALID_PDF",
                    "message": reason
                }




    # Part 2: Extract ValidationAgent's JSON (validated data)
 
    populated_json = None

    for msg in result.messages:
        if isinstance(msg, TextMessage) and 'ValidationAgent' in msg.source:
            content = msg.content
        
            # Use regex to find JSON content
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                populated_json = json_match.group(0)
                break

    print("\n\n\n\n\nPopulated data from validation agent = ", populated_json,"\n\n\n\n\n")
    
    # Log data extraction result
    if session_id:
        if populated_json:
            add_agent_log(session_id, "System", "Data extraction successful", "success")
        else:
            add_agent_log(session_id, "System", "Failed to extract populated data", "error")

    return {
        "populated_data": populated_json,
        "filled_pdf_path": "outputs/filled_form.pdf"
    }

       


# ============================================================================
# Command-Line Interface
# ============================================================================

async def main():
    """Main entry point."""
    
    #Inputs:

    pdf_path = "uploads/uploaded_form.pdf"
    mapping_path = "data/mappings/cms_3427_mapping.json"

    # pdf_path ="CMS_643.pdf"
    # mapping_path = "data\mappings\cms_643_mapping.json"

    # pdf_path ="EFT-agreement.pdf"
    # mapping_path = "data\mappings\cms_588_mapping.json"
    
    try:
        result = await run_roundrobin_workflow(
            pdf_path=pdf_path,
            mapping_path=mapping_path,
            verbose=True
        )
        
        print("\n" + "=" * 80)
        print("WORKFLOW COMPLETED")
        print("=" * 80)
        
        if result:
            print(f"\nPopulated Data: {result.get('populated_data', 'N/A')}")
            print(f"\nFilled PDF Path: {result.get('filled_pdf_path', 'N/A')}")
        
    except Exception as e:
        logger.error(f"❌ Workflow failed: {str(e)}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    asyncio.run(main())
    