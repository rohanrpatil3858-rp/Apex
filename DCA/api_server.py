from fastapi import FastAPI, HTTPException, Security, Depends, Form, BackgroundTasks, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse
from dotenv import load_dotenv
import json
import os
import uvicorn
import asyncio
import logging
import traceback
import uuid
from pathlib import Path
from datetime import datetime
from typing import Dict, List

# Load environment variables BEFORE importing workflow module
load_dotenv()

import roundrobin_workflowv4
from roundrobin_workflowv4 import run_roundrobin_workflow

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Form Data API",
    description="REST APIs for form automation data sources",
    version="1.0.0"
)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_PATH = "data/api_sources"
UPLOAD_DIR = "uploads"
OUTPUT_DIR = "outputs"
MAPPING_DIR = "data/mappings"

# Create directories if they don't exist
Path(UPLOAD_DIR).mkdir(exist_ok=True)
Path(OUTPUT_DIR).mkdir(exist_ok=True)

# ============================================================================
# Session-based Log Storage for Real-time Streaming
# ============================================================================

# Global dictionary to store logs per session
session_logs: Dict[str, List[Dict]] = {}

# Global dictionary to store workflow results per session
workflow_results: Dict[str, Dict] = {}

def add_agent_log(session_id: str, agent_name: str, message: str, log_type: str = "info"):
    """
    Add a log entry for a session and print to terminal.
    
    Args:
        session_id: Unique session identifier
        agent_name: Name of the agent or component
        message: Log message content
        log_type: Type of log (info, success, error, warning, processing)
    """
    timestamp = datetime.now().isoformat()
    log_entry = {
        "timestamp": timestamp,
        "agent_name": agent_name,
        "message": message,
        "type": log_type
    }
    
    # Initialize session logs if not exists
    if session_id not in session_logs:
        session_logs[session_id] = []
    
    # Add to session logs
    session_logs[session_id].append(log_entry)
    
    # Also print to terminal (preserve existing behavior)
    log_prefix = {
        "info": "ℹ️",
        "success": "✅",
        "error": "❌",
        "warning": "⚠️",
        "processing": "🔄"
    }.get(log_type, "📝")
    
    print(f"{log_prefix} [{agent_name}] {message}")
    logger.info(f"[{session_id}] [{agent_name}] {message}")

# Set the workflow's logging handler to use our add_agent_log function
roundrobin_workflowv4.set_agent_log_handler(add_agent_log)


async def run_workflow_background(session_id: str, pdf_path: str, mapping_path: str, facility_name: str, facility_id: str):
    """Run workflow in background and store result."""
    try:
        add_agent_log(session_id, "System", "Workflow execution started", "info")
        
        workflow_result = await run_roundrobin_workflow(
            pdf_path=pdf_path,
            mapping_path=mapping_path,
            facility_name=facility_name,
            facility_id=facility_id,
            session_id=session_id,
            verbose=True
        )
        
        # Check if workflow returned an error (e.g., invalid PDF)
        if isinstance(workflow_result, dict) and workflow_result.get("status") == "error":
            workflow_results[session_id] = {
                "status": "error",
                "code": workflow_result.get("code", "UNKNOWN_ERROR"),
                "error": workflow_result.get("message", "Workflow failed")
            }
            add_agent_log(session_id, "System", f"❌ Workflow failed: {workflow_result.get('message')}", "error")
        else:
            # Store result for later retrieval
            workflow_results[session_id] = {
                "status": "success",
                "data": workflow_result
            }
            add_agent_log(session_id, "System", "✨ Workflow completed successfully!", "success")
        
    except Exception as e:
        logger.error(f"Workflow error for session {session_id}: {str(e)}")
        logger.error(traceback.format_exc())
        workflow_results[session_id] = {
            "status": "error",
            "error": str(e)
        }
        add_agent_log(session_id, "System", f"❌ Workflow failed: {str(e)}", "error")


API_KEY_NAME = "X-API-Key"

api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

VALID_API_KEYS = {
    "poc-agent-key-12345"  # Single key for all agents and demos
}

async def verify_api_key(api_key: str = Security(api_key_header)):
    if not api_key or api_key not in VALID_API_KEYS:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API Key. Please provide X-API-Key header."
        )
    return api_key

# Helper function to load JSON files
def load_json_file(filename: str):
    try:
        file_path = os.path.join(DATA_PATH, filename)
        with open(file_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File {filename} not found")
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail=f"Invalid JSON in {filename}")

# Protected Endpoints (require API key)
@app.get("/api/ehr/facility", dependencies=[Depends(verify_api_key)])
async def get_ehr_facility():
    """Get EHR facility data for all 3 facilities"""
    return load_json_file("ehr_facility.json")

@app.get("/api/hr/auditor", dependencies=[Depends(verify_api_key)])
async def get_hr_auditor():
    """Get HR auditor information"""
    return load_json_file("hr_auditor.json")

@app.get("/api/compliance/audit", dependencies=[Depends(verify_api_key)])
async def get_compliance_audit():
    """Get compliance audit data"""
    return load_json_file("compliance_audit.json")

@app.get("/api/registry/state", dependencies=[Depends(verify_api_key)])
async def get_state_registry():
    """Get state registry certification data"""
    return load_json_file("state_registry.json")

# Public endpoint (no authentication needed)
@app.get("/")
async def root():
    return {
        "message": "Form Data API Server",
        "version": "1.0.0",
        "endpoints": [
            "/api/ehr/facility",
            "/api/hr/auditor",
            "/api/compliance/audit",
            "/api/registry/state"
        ],
        "authentication": "Required - Use X-API-Key header"
    }

# Demo endpoint
@app.get("/helloworld")
async def demo():
    return {"message": "hello world"}

@app.get("/health")
async def health_check():
    """Public health check endpoint"""
    files = ["ehr_facility.json", "hr_auditor.json", 
             "compliance_audit.json", "state_registry.json"]
    status = {}
    
    for file in files:
        file_path = os.path.join(DATA_PATH, file)
        status[file] = "OK" if os.path.exists(file_path) else "MISSING"
    
    return {"status": "healthy", "data_files": status}


# ============================================================================
# SSE Log Streaming Endpoint
# ============================================================================

@app.get("/stream-logs/{session_id}")
async def stream_logs(session_id: str):
    """
    Stream agent logs in real-time using Server-Sent Events (SSE).
    
    Args:
        session_id: Unique session identifier from /api/process-form
        
    Returns:
        EventSourceResponse streaming log events
    """
    async def event_generator():
        """Generate SSE events from session logs."""
        sent_count = 0
        
        try:
            # Wait for session to be created (up to 30 seconds)
            wait_time = 0
            while session_id not in session_logs and wait_time < 30:
                await asyncio.sleep(0.5)
                wait_time += 0.5
            
            if session_id not in session_logs:
                yield {
                    "event": "error",
                    "data": json.dumps({"error": f"Session {session_id} not found"})
                }
                return
            
            # Stream logs as they are added
            while True:
                current_logs = session_logs.get(session_id, [])
                
                # Send any new logs
                if len(current_logs) > sent_count:
                    new_logs = current_logs[sent_count:]
                    for log in new_logs:
                        yield {
                            "event": "log",
                            "data": json.dumps(log)
                        }
                        logger.debug(f"SSE sent log: {log['agent_name']}: {log['message'][:50]}")
                    sent_count = len(current_logs)
                
                # Check if workflow is complete (check workflow_results instead of log messages)
                if session_id in workflow_results:
                    await asyncio.sleep(0.5)  # Give time for final logs
                    
                    # Send any remaining logs
                    current_logs = session_logs.get(session_id, [])
                    if len(current_logs) > sent_count:
                        new_logs = current_logs[sent_count:]
                        for log in new_logs:
                            yield {
                                "event": "log",
                                "data": json.dumps(log)
                            }
                        sent_count = len(current_logs)
                    
                    # Send complete event
                    result = workflow_results[session_id]
                    
                    if result["status"] == "success":
                        complete_data = {
                            "status": "complete",
                            "message": "Workflow finished successfully",
                            "session_id": session_id
                        }
                    else:
                        # Error case - include error code if available
                        complete_data = {
                            "status": "error",
                            "code": result.get("code", "UNKNOWN_ERROR"),
                            "message": result.get("error", "Unknown error"),
                            "session_id": session_id
                        }
                    
                    yield {
                        "event": "complete",
                        "data": json.dumps(complete_data)
                    }
                    logger.info(f"SSE sent complete event for session {session_id}")
                    break
                
                # Wait before checking for new logs
                await asyncio.sleep(0.3)
                
        except asyncio.CancelledError:
            # Client disconnected
            logger.info(f"Client disconnected from session {session_id}")
        except Exception as e:
            logger.error(f"Error streaming logs: {str(e)}")
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)})
            }
    
    return EventSourceResponse(event_generator())


# ============================================================================
# Get Workflow Result Endpoint
# ============================================================================

@app.get("/api/workflow-result/{session_id}")
async def get_workflow_result(session_id: str):
    """
    Get the result of a completed workflow.
    
    Args:
        session_id: Unique session identifier from /api/process-form
        
    Returns:
        JSON object with workflow result (populated data and PDF path)
    """
    if session_id not in workflow_results:
        raise HTTPException(
            status_code=404,
            detail=f"No workflow result found for session {session_id}. Workflow may still be running."
        )
    
    result = workflow_results[session_id]
    
    if result["status"] == "error":
        raise HTTPException(
            status_code=500,
            detail=f"Workflow failed: {result['error']}"
        )
    
    # Extract workflow data
    workflow_data = result["data"]
    populated_data_str = workflow_data.get("populated_data")
    filled_pdf_path = workflow_data.get("filled_pdf_path")
    
    if not populated_data_str:
        raise HTTPException(
            status_code=500,
            detail="Workflow completed but no data was generated"
        )
    
    # Parse the JSON string
    populated_data_str = populated_data_str.replace("DONE", "").strip()
    
    try:
        populated_data = json.loads(populated_data_str)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse workflow output: {str(e)}"
        )
    
    # Build download URL
    download_url = None
    if filled_pdf_path and os.path.exists(filled_pdf_path):
        download_url = "/download/filled_form.pdf"
    
    return {
        "status": "success",
        "session_id": session_id,
        "data": populated_data,
        "filled_pdf_path": filled_pdf_path,
        "download_url": download_url
    }


# ============================================================================
# PDF Form Processing Endpoint
# ============================================================================

@app.post("/api/process-form")
async def process_form(
    background_tasks: BackgroundTasks,
    form_type: str = Form(..., description="Form type: cms_3427, cms_3427b, cms_588, or cms_643"),
    facility_name: str = Form(..., description="Facility name (e.g., 'Metro Medical Center') - REQUIRED"),
    facility_id: str = Form(..., description="Facility ID (e.g., 'FAC-001') - REQUIRED"),
    api_key: str = Security(api_key_header)
):
    """
    Process CMS form and populate it with data from various sources.
    Uses default form templates internally - no PDF upload needed, just select the form type.
    
    Args:
        background_tasks: FastAPI background tasks
        form_type: Type of form (cms_3427, cms_3427b, cms_588, or cms_643)
        facility_name: Name of the facility (REQUIRED for dynamic facility selection)
        facility_id: Facility ID (REQUIRED for dynamic facility selection)
        
    Returns:
        JSON object with session_id for log streaming (workflow runs in background)
    """
    # Generate unique session ID
    session_id = str(uuid.uuid4())
    
    # Verify API key
    await verify_api_key(api_key)
    
    # Validate form type and get mapping path
    form_mappings = {
        "cms_3427": "cms_3427_mapping.json",
        "cms_3427b": "cms_3427B_mapping.json",
        "cms_588": "cms_588_mapping.json",
        "cms_643": "cms_643_mapping.json"
    }
    
    if form_type not in form_mappings:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid form_type. Must be one of: {', '.join(form_mappings.keys())}"
        )
    
    mapping_path = os.path.join(MAPPING_DIR, form_mappings[form_type])
    
    # Use default PDF for selected form type
    pdf_path = os.path.join(UPLOAD_DIR, f"default_{form_type}_form.pdf")
    
    # Check if default PDF exists
    if not os.path.exists(pdf_path):
        raise HTTPException(
            status_code=500, 
            detail=f"Default {form_type.upper()} form template not found at: {pdf_path}. Please ensure the default form is available in the uploads directory."
        )
    
    # Check if mapping file exists
    if not os.path.exists(mapping_path):
        raise HTTPException(
            status_code=500, 
            detail=f"Mapping file not found: {mapping_path}"
        )
    
    try:
        logger.info(f"Using default {form_type.upper()} form template: {pdf_path}")
        logger.info(f"Using mapping: {mapping_path}")
        logger.info(f"Facility: {facility_name} (ID: {facility_id})")
        
        # Initialize session logs
        add_agent_log(session_id, "System", f"Starting workflow for {form_type.upper()} - Facility: {facility_name} ({facility_id})", "info")
        
        # Start the workflow in background
        logger.info("Starting workflow execution in background...")
        background_tasks.add_task(
            run_workflow_background, 
            session_id, 
            pdf_path, 
            mapping_path,
            facility_name,
            facility_id
        )
        
        logger.info(f"Workflow task queued for session {session_id}")
        
        # Return immediately with session_id
        # Frontend will stream logs via /stream-logs/{session_id}
        return {
            "status": "processing",
            "session_id": session_id,
            "form_type": form_type,
            "message": "Workflow started. Connect to /stream-logs/{session_id} for real-time updates."
        }
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse workflow output: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error processing form: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error processing form: {str(e)}"
        )
    finally:
        # Optional: Clean up uploaded file after processing
        # Uncomment the line below if you want to delete the PDF after processing
        # if os.path.exists(pdf_path):
        #     os.remove(pdf_path)
        pass


# ============================================================================
# PDF Download Endpoint
# ============================================================================

@app.get("/download/{filename}")
async def download_filled_pdf(filename: str):
    """
    Download a filled PDF file from the outputs directory.
    
    Args:
        filename: Name of the PDF file to download
        
    Returns:
        FileResponse with the PDF file
    """
    file_path = os.path.join(OUTPUT_DIR, filename)
    
    # Validate file exists
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=404,
            detail=f"File not found: {filename}"
        )
    
    # Validate it's a PDF file
    if not filename.lower().endswith('.pdf'):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files can be downloaded"
        )
    
    # Return the file
    return FileResponse(
        path=file_path,
        media_type='application/pdf',
        filename=filename,
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ============================================================================
# Mapping Generation Endpoints
# ============================================================================

from mapping_generator import generate_mapping
from pydantic import BaseModel

class MappingHealthResponse(BaseModel):
    status: str
    message: str

@app.get("/api/mapping/health", response_model=MappingHealthResponse)
async def mapping_health_check():
    """Health check endpoint for mapping generation"""
    return {
        "status": "healthy",
        "message": "Mapping Generator API is running"
    }

@app.post("/api/mapping/generate")
async def generate_pdf_mapping(
    pdf: UploadFile = File(...),
    endpoints_config: str = Form(None),
):
    """
    Generate field mappings from uploaded PDF form
    
    Args:
        pdf: PDF file uploaded from React frontend
        endpoints_config: JSON string array of API endpoint configurations
    
    Returns:
        FileResponse with generated mapping JSON file
    """
    try:
        logger.info(f"Received file: {pdf.filename}, content_type: {pdf.content_type}")
        logger.info(f"Endpoints config: {endpoints_config}")
        
        # Validate file type
        if not pdf.filename.endswith('.pdf'):
            raise HTTPException(
                status_code=400,
                detail="Only PDF files are allowed"
            )

        # 1. Create temp folders
        os.makedirs("mapping_uploads", exist_ok=True)
        os.makedirs("mapping_outputs", exist_ok=True)

        # 2. Clean up old PDFs in uploads folder
        if os.path.exists("mapping_uploads"):
            for file in os.listdir("mapping_uploads"):
                file_path = os.path.join("mapping_uploads", file)
                if os.path.isfile(file_path):
                    try:
                        os.remove(file_path)
                        logger.info(f"Deleted old PDF: {file_path}")
                    except Exception as e:
                        logger.warning(f"Could not delete {file_path}: {e}")

        # 3. Clean up old mappings in outputs folder BEFORE generating new one
        if os.path.exists("mapping_outputs"):
            for file in os.listdir("mapping_outputs"):
                file_path = os.path.join("mapping_outputs", file)
                if os.path.isfile(file_path):
                    try:
                        os.remove(file_path)
                        logger.info(f"Deleted old mapping: {file_path}")
                    except Exception as e:
                        logger.warning(f"Could not delete {file_path}: {e}")

        # 4. Save uploaded PDF (keep only one file)
        pdf_path = "mapping_uploads/form.pdf"

        logger.info(f"Processing PDF: {pdf.filename}")

        # Parse dynamic configurations
        endpoints_list = []
        databases_list = []
        
        if endpoints_config:
            try:
                endpoints_list = json.loads(endpoints_config)
                logger.info(f"Received {len(endpoints_list)} endpoint configurations from UI")
            except json.JSONDecodeError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid endpoints_config JSON: {str(e)}"
                )
        else:
            # Fallback: No config from UI, use backend defaults
            logger.warning("No endpoints_config provided, using backend default API configs")
            endpoints_list = [
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
        
        databases_list = [
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

        with open(pdf_path, "wb") as f:
            f.write(await pdf.read())

        logger.info(f"PDF saved to: {pdf_path}")

        # 5. Define paths
        output_path = "mapping_outputs/mapping.json"

        # 6. Call mapping generation logic with dynamic configs
        logger.info("Starting mapping generation with dynamic configurations...")
        await generate_mapping(
            pdf_path=pdf_path,
            endpoints=endpoints_list,
            databases=databases_list,
            output_path=output_path
        )

        logger.info(f"Mapping generated successfully: {output_path}")

        # 7. Verify file exists before returning
        if not os.path.exists(output_path):
            logger.error(f"Mapping file was not created: {output_path}")
            raise HTTPException(
                status_code=500,
                detail="Mapping generation completed but output file was not created. Check server logs for details."
            )

        # 8. Return mapping file
        return FileResponse(
            output_path,
            media_type="application/json",
            filename="mapping.json"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing form: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error processing form: {str(e)}"
        )

@app.get("/api/mapping/download")
async def download_mapping():
    """Get the current mapping file"""
    try:
        mapping_path = "mapping_outputs/mapping.json"
        
        if not os.path.exists(mapping_path):
            return {"status": "no mapping available"}
        
        return FileResponse(
            mapping_path,
            media_type="application/json",
            filename="mapping.json"
        )
    except Exception as e:
        logger.error(f"Error retrieving mapping: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving mapping: {str(e)}"
        )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)